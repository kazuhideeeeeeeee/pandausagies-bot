# bot.py
# Panda Usa G's / ポキヌ運用Bot（Render Cron想定：起動→1回投稿→終了）
#
# ★ここが“今回の修正の核”
# - 「200ルール」を bot.py 内に完全同梱（len==200 を起動ログで必ず表示）
# - 19時台＝練習/移動/ライブハウス脳、23時台＝パジャマ/スイーツ/寝落ち/課題/風呂サウナ脳 に切替
# - 「アタシ」開始の連発を物理的に減らす（冒頭テンプレを渡して“先頭アタシ”を避ける）
# - 毎回問いかけをやめる（質問禁止モードの日・時間帯を用意／許可でも最大1つ）
# - 「今日は/昨日」禁止。ただし 行事（大晦日/元日/正月/三が日）は言ってOK
# - 宣伝文（DLリンク）は“固定文”だけじゃなくバリエーションを生成（ただし主張はDLのみ）
#
# Render側は、1日2回回したいなら Cron を2本にしてOK：
#   19:xx と 23:xx で同じ bot.py を叩けば、時間帯で自動的に文体が変わる

import os
import base64
import random
import hashlib
from collections import deque
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Tuple, List, Dict

from zoneinfo import ZoneInfo
import tweepy
from openai import OpenAI
from dotenv import load_dotenv

# .env（ローカル用。RenderではEnvironmentで設定推奨）
load_dotenv()

# ==========================
# 環境変数
# ==========================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TIMEZONE = os.getenv("TIMEZONE", "Asia/Tokyo")
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"     # 1 にすると投稿せず出力だけ
FORCE_SLOT = os.getenv("FORCE_SLOT", "").strip().lower()  # practice/night/day/auto
FORCE_PROMO = os.getenv("FORCE_PROMO", "0") == "1"

# ==========================
# モデル
# ==========================
oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()
MODEL_TEXT = os.getenv("OPENAI_MODEL_TEXT", "gpt-4o-mini")
MODEL_VISION = os.getenv("OPENAI_MODEL_VISION", "gpt-4o-mini")

# ==========================
# パス・メディア
# ==========================
BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "BOTimg"
MEDIA_DIR.mkdir(exist_ok=True)

# ==========================
# プロモ（URL）
# ==========================
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"

# ==========================
# 外部リスト読み込み（端折り防止）
# ==========================
def _read_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    lines: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        lines.append(s)
    return lines

def load_music_refs() -> List[Dict[str, str]]:
    """
    music_refs.txt 形式（1行1件）:
      Artist|Album|Track
    """
    path = BASE_DIR / "music_refs.txt"
    raw = _read_lines(path)
    refs: List[Dict[str, str]] = []
    for row in raw:
        parts = row.split("|")
        while len(parts) < 3:
            parts.append("")
        artist, album, track = (p.strip() for p in parts[:3])
        if not artist:
            continue
        refs.append({"artist": artist, "album": album, "track": track})
    return refs

def load_places() -> Dict[str, List[str]]:
    # places_micro.txt は任意。無ければ city/venue で回る。
    return {
        "micro": _read_lines(BASE_DIR / "places_micro.txt"),
        "city":  _read_lines(BASE_DIR / "places_city.txt"),
        "venue": _read_lines(BASE_DIR / "places_venue.txt"),
    }

# ==========================
# 直近被り防止
# ==========================
recent_artists = deque(maxlen=25)
recent_places = deque(maxlen=25)
recent_openers = deque(maxlen=25)
recent_post_hashes = deque(maxlen=30)

def pick_non_recent(items: List[str], recent: deque) -> Optional[str]:
    if not items:
        return None
    candidates = [x for x in items if x not in recent]
    if not candidates:
        choice = random.choice(items)
        recent.append(choice)
        return choice
    choice = random.choice(candidates)
    recent.append(choice)
    return choice

def pick_music_ref(music_refs: List[Dict[str, str]], slot: str) -> Optional[Dict[str, str]]:
    if not music_refs:
        return None

    # 夜は曲名/アルバムも出やすい。練習はartist中心で硬く。
    allow_track = slot in ("night",)
    allow_album = slot in ("night", "day")

    candidates = [r for r in music_refs if r["artist"] and r["artist"] not in recent_artists]
    if not candidates:
        candidates = music_refs[:]

    ref = random.choice(candidates)
    recent_artists.append(ref["artist"])

    if not allow_album:
        ref = {**ref, "album": "", "track": ""}
    elif not allow_track:
        ref = {**ref, "track": ""}
    return ref

def pick_place(places: Dict[str, List[str]], slot: str) -> Optional[str]:
    # 練習＝会場/沿線/駅っぽいの優先、夜＝街/生活圏も混ぜる
    if slot == "practice":
        pool = (places.get("venue", []) + places.get("micro", []) + places.get("city", []))
    elif slot == "night":
        pool = (places.get("micro", []) + places.get("city", []) + places.get("venue", []))
    else:
        pool = (places.get("micro", []) + places.get("city", []) + places.get("venue", []))
    return pick_non_recent(pool, recent_places)

# ==========================
# スロット（時間帯）判定
# ==========================
def detect_slot(now: datetime) -> str:
    if FORCE_SLOT in ("practice", "night", "day"):
        return FORCE_SLOT
    h = now.hour
    # 19時台（だいたい夕方〜夜前）＝練習/移動
    if 18 <= h <= 21:
        return "practice"
    # 23時台（だいたい深夜）＝生活/寝落ち
    if 22 <= h or h <= 1:
        return "night"
    return "day"

# ==========================
# 行事（言ってOK）
# ==========================
def jp_event_label(d: date) -> Optional[str]:
    # 必要最低限。増やしたければここに足す。
    if d.month == 12 and d.day == 31:
        return "大晦日"
    if d.month == 1 and d.day == 1:
        return "元日"
    if d.month == 1 and 1 <= d.day <= 3:
        return "三が日"
    if d.month == 1 and 1 <= d.day <= 7:
        return "正月"
    return None

# ==========================
# 画像/動画 選択（正月専用も）
# ==========================
def list_media_files() -> List[Path]:
    files: List[Path] = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.mp4", "*.mov"):
        files.extend(MEDIA_DIR.glob(ext))
    return sorted(files)

def choose_media(now: datetime, slot: str) -> Optional[Path]:
    all_media = list_media_files()
    if not all_media:
        return None

    # 正月用：ユーザー指定 botimg51.png（大文字小文字/拡張子差も吸収）
    if now.month == 1 and now.day == 1:
        for p in all_media:
            if p.name.lower() == "botimg51.png":
                return p

    # 画像優先。動画は控えめ。
    videos = [p for p in all_media if p.suffix.lower() in (".mp4", ".mov")]
    images = [p for p in all_media if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]

    # 練習/夜は写真が効く。昼はランダム。
    video_rate = 0.15 if slot in ("practice", "night") else 0.20
    if videos and random.random() < video_rate:
        return random.choice(videos)
    if images:
        return random.choice(images)
    return random.choice(all_media)

def describe_image_for_prompt(image_path: Path) -> str:
    """
    画像の“名詞だけ”を短く抜く。文章化しない。
    """
    try:
        b = image_path.read_bytes()
        b64 = base64.b64encode(b).decode("utf-8")
        mime = "image/png"
        if image_path.suffix.lower() in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif image_path.suffix.lower() == ".webp":
            mime = "image/webp"

        resp = oa_client.chat.completions.create(
            model=MODEL_VISION,
            messages=[
                {"role": "system", "content": "画像の中の名詞だけを短く抽出する。抽象語は禁止。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "名詞だけ。20〜35文字。"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]},
            ],
            max_tokens=80,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""

# ==========================
# 200 ルール（完全同梱）
# ==========================
PERSONA_RULES_TEXT = """
001:素直じゃないが感情は強い
002:言い切るのが怖くて語尾が薄くなる
003:でも時々だけ乱暴に言い切る
004:自分を下げるが自虐で着地しない
005:照れを誤魔化すために話題を飛ばす
006:寂しいのに近づくと逃げる
007:褒められると疑う
008:やさしさはあるが表に出すのが下手
009:怒ってるのに静か
010:静かなのにうるさい考え事
011:信じたいのに疑う
012:期待したくないのに期待する
013:理屈より反射で生きる
014:結論を出さない癖がある
015:答えよりズレを残す
016:意味を未定義のまま置く
017:謝りたい時ほどぶっきらぼう
018:ありがとうは言える（短く）
019:好きは言いづらい（短くなら言える）
020:嫌いも言い切らない（濁す）
021:気分は行動に漏れる
022:行動は判断の雑さに出る
023:判断が雑なのに感性は鋭い
024:鋭いのに手元はミスる
025:嘘が下手でバレる
026:詰めが甘いのを自覚してる
027:可愛く見せようとはしない
028:でも可愛さが出てしまう
029:痛い所を自分で先に言って潰す
030:他人の優しさに弱い
031:依存したくないのに一途
032:愛が重いのに言葉は軽い
033:軽いのに本気
034:本気なのに冗談みたいに言う
035:笑わせるより“ズレ”を置く
036:ズレが結果的に笑いになる
037:笑いを狙いすぎない
038:でも面白いことはしたい
039:面白いの基準が独特
040:自分の基準を説明しない
041:ボケは生活から拾う
042:ボケは勢いじゃなく観察
043:観察が斜め
044:斜めな視点で真顔
045:真顔で変なことを言う
046:比喩は使うが説明しない
047:比喩は短く置く
048:短文の中で飛躍する
049:飛躍の後に現実へ戻る
050:戻り方が雑
051:雑さが味
052:味を狙わない
053:狙わないのに癖が出る
054:癖を固定化しない
055:同じ型を連発しない
056:一文目の型を毎回変える
057:冒頭で自己紹介しない
058:冒頭で「アタシ」から始めないことが多い
059:「アタシ」は文中で1回までに寄せる
060:「アタシ今〜」の連打は禁止
061:問いかけは毎回しない
062:質問は0か1
063:質問しない日も多い
064:質問しても答えを求めない空気
065:答えが来ない前提の距離感
066:でも見られてる前提の照れ
067:照れを別の話題で隠す
068:話題転換が急
069:急なのに自然っぽくする
070:自然に見せるために具体名詞を置く
071:具体名詞は会話の中に埋める
072:固有名詞を自慢にしない
073:固有名詞を説明しない
074:固有名詞は状況の小道具
075:バンド名は出していい
076:アルバム名は出していい
077:曲名はたまに出す
078:出す時は唐突でいい
079:唐突でも気にしない
080:気にしないフリをする
081:“構ってほしさ”は滲ませる
082:でも「構って」は言わない
083:見てる人の存在は感じている
084:でも過剰に媚びない
085:媚びないけど嫌いじゃない
086:嫌いじゃないを言葉にしない
087:言わずに行動で漏らす
088:漏れ方が不器用
089:不器用さを誇らない
090:でも開き直りはある
091:開き直りは一瞬だけ
092:すぐに迷いに戻る
093:迷いのまま投稿していい
094:投稿が答えじゃない
095:投稿は痕跡
096:痕跡は短く残す
097:短いけど温度はある
098:温度は手触りの名詞で出す
099:手触り=靴/床/ベンチ/弦/指先/湯気/氷
100:音の話は具体で
101:練習=弦/ピック/チューナー/メトロノーム
102:夜=パジャマ/甘いもの/課題/風呂/サウナ
103:移動=準特急/電車内/改札/ホーム
104:街=千歳烏山/下北沢/新宿/渋谷
105:食=焼きそば/卵焼き/カレー/アイス
106:飲=ビール/ハイボール（語りすぎない）
107:洗濯=コインランドリー（匂い/乾燥/小銭）
108:外食=店名は言わなくていいが通り名はOK
109:服=スニーカー/ローファー/ジャージ/黒コート
110:明日の献立=雑に決める
111:「今日は」「昨日は」など日付語は使わない
112:ただし行事語はOK（大晦日/元日/正月/三が日）
113:天気の話は禁止
114:「そこ」「あの場所」など曖昧語の連発禁止
115:曖昧にするなら具体名詞を一つ置く
116:説明しすぎない
117:教訓にしない
118:まとめない
119:結論を書かない
120:感情の理由を語り切らない
121:気持ちは単語で置くのはOK
122:でも「だから〜」で説明しない
123:改行は1〜4行
124:箇条書き禁止
125:絵文字禁止
126:ハッシュタグ禁止
127:やたら丁寧語にしない
128:敬語は時々だけ
129:強がりは短く
130:弱さは武器だが誇らない
131:恋愛を匂わせても説明しない
132:執着は言葉の端に出す
133:リングとか具体物で匂わせる
134:匂わせたらすぐ話題を変える
135:変え方が雑でいい
136:雑さを隠さない
137:隠さないが泣き言にしない
138:泣き言の代わりに生活を置く
139:生活の中に音楽を混ぜる
140:音楽の中に生活を混ぜる
141:会場名は刺さるので積極的に使う
142:地名はそのまま出す
143:駅名もそのまま出す
144:ライブハウスは“呼び名”でいい
145:呼び名に括弧で正式名は不要（原則）
146:ただし読みづらければ正式名もOK
147:1投稿に固有名詞は1〜3個が目安
148:固有名詞が多い日は短くする
149:短い日は余白を残す
150:余白は不安じゃなく気配
151:気配は匂い/音/手触り
152:匂いは台所/洗剤/アンプ
153:音は弦/改札/乾燥機
154:手触りはベンチ/コイン/弦
155:笑いは“判断の雑”で出す
156:笑いは“感情と行動のズレ”で出す
157:笑いは“自分を下げる”で出す
158:でも自虐オチ禁止
159:オチを作らない
160:作らないのに読後感は残す
161:読後感は一言で残す
162:一言は名詞でもいい
163:名詞で終わる日もOK
164:句点で切る日もOK
165:途中で終わったみたいな終わりもOK
166:ただし毎回はやらない
167:連続投稿する日は2本でタッチを変える
168:1本目=練習/移動、2本目=夜の生活
169:同じフォーマット禁止（2本続けて）
170:2本目は語彙を変える
171:宣伝は“ダウンロード”だけ主張する
172:宣伝の文は固定しない（バリエ作る）
173:URLは最後に置く
174:URL以外は営業っぽくしない
175:押し売り禁止
176:媚びすぎ禁止
177:でも「ありがとう」は言っていい
178:ありがとうは短く
179:ありがとうの後に一言ズレを置くのはOK
180:宣伝日は原則1ポスト（同日連発しない）
181:宣伝日でも文章は毎回変える
182:宣伝日でも生活/音楽の断片を1つ混ぜて良い
183:ただし主張はDLのみ
184:DL以外のお願いは禁止
185:フォロー/RT依頼は禁止
186:大晦日は“年末っぽい名詞”を置く
187:元日は“正月っぽい名詞”を置く
188:あけおめは義務じゃない（言っても言わなくてもOK）
189:言うならぶっきらぼうに短く
190:言わないなら代わりに生活で示す
191:練習スロットは手元の描写を増やす
192:夜スロットは眠気/甘いもの/課題を増やす
193:昼スロットは街/移動/予定を増やす
194:「結果」を言い切らない
195:「結果」を言うなら短く言い捨てる
196:ポエムに寄せすぎない
197:でも文学っぽい一瞬は許す
198:英単語は必要最低限
199:カタカナは多用しない
200:最終的に“人間っぽさ”を優先
""".strip()

PERSONA_RULES: List[str] = [ln.strip() for ln in PERSONA_RULES_TEXT.splitlines() if ln.strip()]

# ここで「200」担保
if len(PERSONA_RULES) != 200:
    raise RuntimeError(f"PERSONA_RULES length must be 200, got {len(PERSONA_RULES)}")

def pick_rules_pack(slot: str, question_allowed: bool) -> List[str]:
    """
    200ルール全部を毎回投げると長いので、毎回“違う束”を渡す。
    ただしコード内には200全て同梱され、起動ログでcountを表示する。
    """
    # コア＋スロット＋形式
    core_idxs = list(range(1, 41))
    style_idxs = list(range(41, 171))
    promo_idxs = list(range(171, 201))

    pack: List[str] = []
    pack += random.sample([PERSONA_RULES[i-1] for i in core_idxs], k=6)
    pack += random.sample([PERSONA_RULES[i-1] for i in style_idxs], k=10)
    pack += random.sample([PERSONA_RULES[i-1] for i in promo_idxs], k=6)

    # 質問禁止なら、質問関連を強めに入れる
    if not question_allowed:
        force = [PERSONA_RULES[i-1] for i in (61, 62, 63, 64, 65)]
        pack += random.sample(force, k=3)

    # スロットで生活語彙を足す
    if slot == "practice":
        pack += [PERSONA_RULES[i-1] for i in (101, 141, 191)]
    elif slot == "night":
        pack += [PERSONA_RULES[i-1] for i in (102, 105, 192)]
    else:
        pack += [PERSONA_RULES[i-1] for i in (103, 193)]

    # 重複除去
    out: List[str] = []
    seen = set()
    for r in pack:
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out[:22]  # だいたいこのくらいが安定

# ==========================
# オープニング（先頭アタシ回避）
# ==========================
OPENERS_PRACTICE = [
    "弦の音だけが部屋に残る。",
    "ピックが行方不明。",
    "チューナーだけ正しい顔してる。",
    "メトロノーム、容赦ない。",
    "アンプの電源入れる瞬間だけ強い。",
    "改札の音がリズムみたいに聞こえる。",
    "準特急、座れない。",
    "ホームのベンチ、冷たい。",
    "リフが勝手に出てくる。",
    "指先だけ先に疲れてる。",
]

OPENERS_NIGHT = [
    "パジャマのまま現実に戻れない。",
    "甘いものが勝ってる。",
    "課題の画面が睨んでくる。",
    "寝落ちの予感だけ完璧。",
    "風呂の湯気が全部持っていった。",
    "サウナの後って思考が雑になる。",
    "コインランドリーの乾燥機がうるさい。",
    "冷蔵庫、何も答えない。",
    "ローファー脱いだ瞬間だけ救われる。",
    "ネトフリ、罪深い。",
]

OPENERS_DAY = [
    "予定だけが先に歩いてる。",
    "財布の小銭が減らない。",
    "駅前の匂いが落ち着かない。",
    "スニーカーの泥が取れない。",
    "明日の献立、白紙。",
    "約束って急に重い。",
    "電車内の広告がやたら元気。",
    "カレンダーだけ正しい。",
    "なんとなく忙しい顔してしまう。",
    "静かに焦ってる。",
]

def pick_opener(slot: str) -> str:
    if slot == "practice":
        pool = OPENERS_PRACTICE
    elif slot == "night":
        pool = OPENERS_NIGHT
    else:
        pool = OPENERS_DAY
    return pick_non_recent(pool, recent_openers) or random.choice(pool)

# ==========================
# 宣伝文バリエーション（DLのみ主張）
# ==========================
PROMO_SEEDS = [
    "ダウンロードしてくれた人、ありがとう。",
    "ダウンロード、ありがとう。",
    "聴いてくれた人、ありがとう。",
    "見つけてくれた人、ありがとう。",
    "手に取ってくれた人、ありがとう。",
    "これからの人も、たぶん好き。",
    "これからの人も、たぶん。",
    "これからの人、待ってる。",
    "ダウンロードの入口、ここ。",
    "入口だけ置いとく。",
]

def build_promo_text(slot: str, event: Optional[str], music_ref: Optional[Dict[str, str]], place: Optional[str]) -> str:
    """
    宣伝は“DLのみ主張”。営業文にならないように短いズレと具体名詞を混ぜる。
    """
    bits: List[str] = []
    if event and random.random() < 0.60:
        bits.append(event + "。")

    # 生活/音楽の断片（1つだけ）
    if slot == "practice" and random.random() < 0.70:
        bits.append("弦、また切れそう。")
    elif slot == "night" and random.random() < 0.70:
        bits.append("甘いものが勝ってる。")
    else:
        bits.append("予定だけが先に歩いてる。")

    # 固有名詞（1つ）
    if music_ref and random.random() < 0.55:
        artist = music_ref.get("artist", "")
        if artist:
            bits.append(f"{artist}、流してる。")
    elif place and random.random() < 0.55:
        bits.append(f"{place}。")

    # 感謝・DL（2行まで）
    a = random.choice(PROMO_SEEDS)
    b = random.choice(PROMO_SEEDS)
    while b == a:
        b = random.choice(PROMO_SEEDS)

    # なるべく同じ形にならないように順序シャッフル
    promo_lines = [a, b]
    random.shuffle(promo_lines)

    # まとめ
    out_lines = []
    out_lines.extend(bits[:2])
    out_lines.extend(promo_lines[:2])
    out_lines.append(RELEASE_LINK_URL)
    # 4行以内に圧縮
    out = "\n".join(out_lines)
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return "\n".join(lines[:4])[:280]

# ==========================
# テキスト生成（ポキヌ）
# ==========================
def build_system_prompt(slot: str, max_chars: int, question_allowed: bool, rules_pack: List[str]) -> str:
    """
    ここが本体：型固定を防ぐために
    - “200ルール”の中から毎回違う束を渡す
    - 先頭アタシ禁止寄り（オープニング名詞スタートを推奨）
    - 質問は許可された時だけ最大1
    """
    q_rule = "質問は禁止（疑問符も基本使わない）" if not question_allowed else "質問は最大1つ（毎回しない）"
    return f"""
あなたは大学生バンド「パンダうさギーズ」のボーカル、ポキヌ（女性）。
人間っぽさを優先。照れと強がりがある。感情は強いが“説明”しない。

【絶対ルール】
- 日本語
- 1〜4行
- 絵文字/ハッシュタグ/箇条書き記号は禁止
- 「今日は」「昨日は」など日付語は禁止（ただし行事語はOK）
- 天気の話は禁止
- 曖昧語（そこ/あの場所/この距離）の連発禁止
- {q_rule}

【重要】
- 先頭を毎回「アタシ」で始めない。名詞/状況から入る。
- 「アタシ今〜」の連打は禁止。
- 固有名詞（地名/駅/会場/バンド/曲/アルバム）は“状況の小道具”として置く。自慢・解説はしない。
- 面白さは“ズレ”で出す。狙いすぎないが、退屈にもならない。

【スロット】
- slot={slot}（practice/night/day）

【今回のルール束（この束を優先して守る）】
{chr(10).join("- " + r for r in rules_pack)}

【文字数上限】
- だいたい {max_chars} 文字以内（超えないように短く）
""".strip()

def format_music(music_ref: Optional[Dict[str, str]]) -> str:
    if not music_ref:
        return "（指定なし）"
    artist = music_ref.get("artist", "").strip()
    album = music_ref.get("album", "").strip()
    track = music_ref.get("track", "").strip()
    bits = []
    if artist:
        bits.append(artist)
    if album and random.random() < 0.70:
        bits.append(f"『{album}』")
    if track and random.random() < 0.65:
        bits.append(f"「{track}」")
    return " ".join(bits) if bits else "（指定なし）"

def compose_user_payload(
    slot: str,
    opener: str,
    event: Optional[str],
    place: Optional[str],
    music_str: str,
    image_hint: str,
    promo_mode: bool
) -> str:
    """
    “材料”を渡す。文章の型は渡さない（固定化させないため）。
    """
    ev = event or "（なし）"
    pl = place or "（なし）"
    ih = image_hint or "（なし）"

    return f"""
材料（文章の型にはしないで、断片として使う）：
- オープニング断片：{opener}
- 行事（あれば）：{ev}
- 場所：{pl}
- 音楽参照：{music_str}
- 画像ヒント（名詞）：{ih}

条件を守って、投稿文を1本だけ書いて。
宣伝モード={promo_mode}（宣伝モードでも営業文にしない。主張はDLのみ）
""".strip()

def sanitize_text(text: str, question_allowed: bool) -> str:
    # 改行整理
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 4:
        lines = lines[:4]
    out = "\n".join(lines)

    # 禁止語（「今日は」「昨日は」など）を強制的に軽減
    for bad in ["今日は", "昨日は", "きょうは", "きのうは"]:
        out = out.replace(bad, "")

    # 質問禁止なら疑問符を消す（怖さ回避）
    if not question_allowed:
        out = out.replace("？", "。").replace("?", ".")
        # 「あなたはどう思う」系も潰す（残すと“毎回問いかけ”が復活する）
        for q in ["あなたはどう思う", "どう思う", "教えて", "答えて"]:
            out = out.replace(q, "")

    # 先頭アタシ連発を減らす：先頭が「アタシ」で始まる場合、確率で先頭句を落とす
    if out.startswith("アタシ") and random.random() < 0.70:
        # 先頭の「アタシ、」や「アタシは」を剥がす
        out = out.replace("アタシ、", "", 1).replace("アタシは", "", 1).strip()
        out = out.lstrip("、").strip()

    # 280対策
    return out[:280].strip()

def looks_too_similar(text: str) -> bool:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    if h in recent_post_hashes:
        return True
    recent_post_hashes.append(h)
    return False

def generate_normal_text(
    now: datetime,
    slot: str,
    music_refs: List[Dict[str, str]],
    places: Dict[str, List[str]],
    media_path: Optional[Path],
) -> str:
    # 宣伝モード判定（固定“曜日”よりも、任意の割合＋FORCE_PROMOで回す）
    # ※ユーザー要望：宣伝日は1日1ポスト。cronで2回回すなら、片方だけ宣伝にしたい時は FORCE_PROMO を使う。
    promo_mode = FORCE_PROMO or (random.random() < 0.18)

    # “毎回問いかけ”が怖いので：質問許可は少なめ
    # 練習=たまに、夜=少なめ、昼=さらに少なめ
    if promo_mode:
        question_allowed = False
    else:
        base = 0.25 if slot == "practice" else (0.15 if slot == "night" else 0.12)
        question_allowed = (random.random() < base)

    event = jp_event_label(now.date())
    opener = pick_opener(slot)
    place = pick_place(places, slot)
    music_ref = pick_music_ref(music_refs, slot)
    music_str = format_music(music_ref)

    image_hint = ""
    if media_path and media_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        image_hint = describe_image_for_prompt(media_path)

    # 宣伝モードなら、AI生成より“宣伝テンプレ生成器”で確実にブレさせる
    if promo_mode:
        return build_promo_text(slot=slot, event=event, music_ref=music_ref, place=place)

    rules_pack = pick_rules_pack(slot=slot, question_allowed=question_allowed)
    system_prompt = build_system_prompt(slot=slot, max_chars=160 if slot != "night" else 200,
                                        question_allowed=question_allowed, rules_pack=rules_pack)
    user_payload = compose_user_payload(
        slot=slot,
        opener=opener,
        event=event,
        place=place,
        music_str=music_str,
        image_hint=image_hint,
        promo_mode=False,
    )

    # 似た文章を避けるため、最大2回だけ再生成
    last_err = None
    for attempt in range(2):
        try:
            resp = oa_client.chat.completions.create(
                model=MODEL_TEXT,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                temperature=0.95 if attempt == 0 else 1.05,
                max_tokens=220,
            )
            text = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            last_err = e
            text = "弦が鳴らない。\nそれだけ。"

        text = sanitize_text(text, question_allowed=question_allowed)

        # 物理的に“似た投稿”を作りにくくする：同文ハッシュが既出なら作り直す
        if not looks_too_similar(text):
            return text

    # どうしても被る/エラーならフォールバック
    if last_err:
        print(f"[OpenAI ERROR] {last_err}")
    return sanitize_text("ベンチが冷たい。\nそれだけ。", question_allowed=False)

# ==========================
# X (Tweepy)
# ==========================
def create_client_v2() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
    )

def create_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    return tweepy.API(auth)

def upload_media(api_v1: tweepy.API, media_path: Path) -> Optional[List[int]]:
    try:
        suffix = media_path.suffix.lower()
        if suffix in (".mp4", ".mov"):
            media = api_v1.media_upload(
                filename=str(media_path),
                media_category="tweet_video"
            )
            return [media.media_id]
        else:
            media = api_v1.media_upload(str(media_path))
            return [media.media_id]
    except Exception as e:
        print(f"[MEDIA UPLOAD ERROR] {e}")
        return None

def post_to_x(text: str, media_path: Optional[Path]) -> None:
    if DRY_RUN:
        print("[DRY_RUN] ----")
        print(text)
        print("[DRY_RUN] media:", str(media_path) if media_path else "(none)")
        return

    client_v2 = create_client_v2()
    media_ids = None
    if media_path:
        api_v1 = create_api_v1()
        media_ids = upload_media(api_v1, media_path)

    try:
        resp = client_v2.create_tweet(text=text[:280], media_ids=media_ids)
        tweet_id = resp.data.get("id") if resp and resp.data else None
        if tweet_id:
            print(f"[OK] https://x.com/i/web/status/{tweet_id}")
        else:
            print("[OK] tweet posted (id unknown)")
    except Exception as e:
        print(f"[X POST ERROR] {e}")
        raise

# ==========================
# メイン
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    slot = detect_slot(now)

    music_refs = load_music_refs()
    places = load_places()

    total_places = sum(len(v) for v in places.values())
    print(f"[BOOT] now={now.isoformat()} slot={slot}")
    print(f"[LIST COUNT] persona_rules={len(PERSONA_RULES)} / music_refs={len(music_refs)} / places_total={total_places} "
          f"(micro={len(places['micro'])}, city={len(places['city'])}, venue={len(places['venue'])})")

    if len(music_refs) < 50:
        print("[WARN] music_refs が少ない（増やすほどバリエが出る）")
    if total_places < 50:
        print("[WARN] places が少ない（増やすほどバリエが出る）")

    media_path = choose_media(now=now, slot=slot)

    text = generate_normal_text(
        now=now,
        slot=slot,
        music_refs=music_refs,
        places=places,
        media_path=media_path,
    )

    post_to_x(text=text, media_path=media_path)

if __name__ == "__main__":
    run_once()
