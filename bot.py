# bot.py
# Panda Usa G's / ポキヌ運用Bot（Render Cron想定：起動→1回投稿→終了）
#
# ▼この版の思想（“変”を作るための物理制約）
# - GPTに「作文」させない：最大2行・短文・接続詞/状態説明/詩っぽい回収を禁止
# - 投稿は「断片」：名詞+動作、またはツッコミ。意味をまとめない
# - 禁止語・禁止構文をコード側で強制（違反したら捨てて作り直す）
# - URLは絶対にこの1つだけ。貼る頻度も落とす（1日1回まで）
# - 地名/ライブハウスは原則出さない（パラレル地名事故を避ける）
# - “ライブ告知”はしない（設定：ポキヌ1人プロジェクトでライブ未定）
#
# 必要環境変数（RenderのEnvironmentへ）
#   API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET
#   OPENAI_API_KEY (任意。無くても動く=ローカル断片生成だけで回る)
#   TIMEZONE (任意, default Asia/Tokyo)
#   DRY_RUN=1 で投稿せずログ出力
#   FORCE_SLOT=practice/night/day/auto (任意)
#   FORCE_PROMO=1 で今回だけURL付ける（ただし1日1回制限は維持）
#
# 依存:
#   tweepy, python-dotenv, openai
#
# 注意:
# - Renderの「Exited with status 1」を避けるため、例外は握りつぶして exit 0 で終える（通知を減らす）
# - それでも投稿失敗が続くなら、ログで原因を見て直す

import os
import re
import json
import base64
import random
import hashlib
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from zoneinfo import ZoneInfo

import tweepy
from dotenv import load_dotenv

# OpenAIは任意（無くても回す）
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

# ==========================
# .env（ローカル用。RenderではEnvironment推奨）
# ==========================
load_dotenv()

# ==========================
# 環境変数
# ==========================
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

TIMEZONE = os.getenv("TIMEZONE", "Asia/Tokyo")
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
FORCE_SLOT = os.getenv("FORCE_SLOT", "auto").strip().lower()  # practice/night/day/auto
FORCE_PROMO = os.getenv("FORCE_PROMO", "0") == "1"

MODEL_TEXT = os.getenv("OPENAI_MODEL_TEXT", "gpt-4o-mini")

# ==========================
# パス
# ==========================
BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "BOTimg"
MEDIA_DIR.mkdir(exist_ok=True)

STATE_PATH = BASE_DIR / "state.json"

# ==========================
# URL（これ以外は禁止）
# ==========================
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"

# ==========================
# 行事（「今日は」禁止だが行事語はOK）
# ==========================
def jp_event_label(d: date) -> Optional[str]:
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
# Render通知抑制のためのState
# ==========================
def _load_state() -> Dict:
    if not STATE_PATH.exists():
        return {
            "last_promo_date": None,   # "YYYY-MM-DD"
            "recent_hashes": [],       # list[str]
        }
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "last_promo_date": None,
            "recent_hashes": [],
        }

def _save_state(st: Dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _hash_text(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

# ==========================
# スロット（時間帯）判定
# ==========================
def detect_slot(now: datetime) -> str:
    if FORCE_SLOT in ("practice", "night", "day"):
        return FORCE_SLOT
    h = now.hour
    if 18 <= h <= 21:
        return "practice"
    if 22 <= h or h <= 1:
        return "night"
    return "day"

# ==========================
# 画像/動画 選択（正月専用 botimg51.png）
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

    # 正月用：botimg51.png
    if now.month == 1 and now.day == 1:
        for p in all_media:
            if p.name.lower() == "botimg51.png":
                return p

    videos = [p for p in all_media if p.suffix.lower() in (".mp4", ".mov")]
    images = [p for p in all_media if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]

    # 動画は控えめ
    video_rate = 0.10 if slot in ("practice", "night") else 0.15
    if videos and random.random() < video_rate:
        return random.choice(videos)
    if images:
        return random.choice(images)
    return random.choice(all_media)

# ==========================
# “変”のための素材（断片）
# - ここを増やすほど、バリエが増える（GPTに頼らず増える）
# ==========================

# 接続詞・説明・まとめを誘発しがちな語彙は最初から入れない

PRACTICE_BITS = [
    "ピック見つからない",
    "弦張り替えた",
    "正しいのはチューナー",
    "アンプの電源入れた",
    "音出た",
    "メトロノーム鳴ってる",
    "メトロノーム止めない",
    "メトロノーム止めたくない",
    "指先痛い",
    "リフ出た",
    "リフ忘れた",
    "リフもう一発来い！",
    "弦切れなかった",
    "チューニング合った！",
    "ギターケース閉める",
    "ギターケース開けた",
    "ピック三枚あるぞ！",
    "あいつ全部違う…",
    "音量上げた",
    "音量下げた",
    "安心した",
    "リズム合わない…",
    "ギター重い…",
    "ギター下ろさない",
    "アンプ熱っ！！",
    "音出した",
    "ピック落とした…",
    "チューニング終わった",
]

# “笑わせに行く・生活”断片（あなたの方向性に寄せた）
LIFE_BITS = [
    "おい！パジャマ裏返しじゃねーか！！",
    "パジャマのまま外出…やってしまった…",
    "太るケーキ買った",
    "フォークもらい忘れたので手で食った",
    "冷蔵庫開けた…チーズ1個しかない",
    "居酒屋IN 先に飲んだ",
    "家飲みハイボール作った 9：1",
    "デカジョッキ 氷一個",
    "風呂入った…ぬるかった…",
    "シャンプー切れてた",
    "外寒！眼鏡曇った",
    "コインランドリー来た",
    "小銭なくて帰宅",
    "準特急乗った",
    "各駅乗ってるじゃ無ーかよ！",
]

# “設定”断片（ソロ化・ライブ未定・2/1録り）
# ※重くしすぎると鬱日記になるので、出現率は低めにする
LORE_BITS = [
    "メンバーいない",
    "一人プロジェクト",
    "ライブ未定",
    "2/1 録り",
]

# 行事断片（言う時はぶっきらぼう）
EVENT_BITS = {
    "大晦日": ["大晦日", "年末"],
    "元日": ["元日", "正月"],
    "三が日": ["三が日"],
    "正月": ["正月"],
}

# URLを貼る時の“短い宣伝”断片（お願いはしない）
PROMO_BITS = [
    "入口だけ置く",
    "ダウンロード置いとく",
    "聴くならここ",
    "これだけ出す",
]

# ==========================
# 禁止（“作文AI”を殺す）
# ==========================
# 「だけ」禁止：単語として出たら落とす/失敗扱い
FORBIDDEN_SUBSTRINGS = [
    "だけ",
    "感じる", "思う", "気づく", "気がする",
    "心", "集中", "疲れ", "眠", "リフレッシュ", "瞬間",
    "まるで", "みたい", "ように",
    "それだけ", "音だけ",
    "危険だ", "最高", "最強", "充電満タン",
    "みんな", "応援", "感想", "待ってます",
    "#", "♪", "✨", "🐼", "👍", "😊", "🎸", "🥁",  # 絵文字/記号寄りも一括で嫌う
]

# 接続詞（作文を誘発）
FORBIDDEN_CONNECTORS = [
    "だから", "でも", "そして", "けど", "なので", "それで", "さらに",
]

# 「今日は/昨日」禁止（行事語だけOK）
FORBIDDEN_DATE_WORDS = [
    "今日は", "今日", "昨日は", "昨日", "きょう", "きのう",
]

# 疑問符禁止（問いかけ地獄防止）
QUESTION_MARKS = ["？", "?"]

# ==========================
# 200ルール（“ある”状態は維持）
# 使い方：GPTに渡すためではなく、後で「規律として残す」ために同梱
# ※この版は主に“禁止表”で制御するので、200ルールは参照しなくても回る
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

PERSONA_RULES = [ln.strip() for ln in PERSONA_RULES_TEXT.splitlines() if ln.strip()]
if len(PERSONA_RULES) != 200:
    # ここで落ちるとRenderがstatus1になるので、例外を投げない
    # ただしログで気づけるようにする
    print(f"[WARN] PERSONA_RULES length expected 200, got {len(PERSONA_RULES)}")

# ==========================
# 投稿テキスト生成（基本：断片を組む。たまにGPTで“短い変換”）
# ==========================
@dataclass
class GenConfig:
    max_lines: int = 2
    max_chars: int = 120  # 2行断片の上限
    retry: int = 12       # 作り直し回数
    gpt_spice_rate: float = 0.18  # GPTで短い言い回し変換を試す確率（無くても回る）
    lore_rate: float = 0.10       # 設定断片の出現率
    event_rate: float = 0.25      # 行事語の出現率（行事日のみ）
    promo_rate: float = 0.32      # URLを貼る“候補”確率（ただし1日1回制限）

CFG = GenConfig()

def _strip_punct_line(s: str) -> str:
    # 句点・読点を減らす（「。」は要らない方針）
    s = s.replace("。", "")
    s = s.strip()
    return s

def build_candidate_lines(now: datetime, slot: str) -> List[str]:
    lines: List[str] = []

    # 行事（行事日のみ）
    ev = jp_event_label(now.date())
    if ev and random.random() < CFG.event_rate:
        lines.append(random.choice(EVENT_BITS.get(ev, [ev])))

    # スロット素材
    if slot == "practice":
        a = random.choice(PRACTICE_BITS)
        b_pool = PRACTICE_BITS + LIFE_BITS[:5]
    elif slot == "night":
        a = random.choice(LIFE_BITS)
        b_pool = LIFE_BITS + PRACTICE_BITS[:6]
    else:
        # dayは生活寄り＋練習少し
        a = random.choice(LIFE_BITS + PRACTICE_BITS[:8])
        b_pool = LIFE_BITS + PRACTICE_BITS

    # 2行構成を基本にする（同じ型固定を避けるため、1行にする日も混ぜる）
    lines.append(a)

    if random.random() < 0.70:
        b = random.choice(b_pool)
        # 同じの連発回避
        if b == a:
            b = random.choice(b_pool)
        lines.append(b)

    # 設定断片（たまにだけ）
    if random.random() < CFG.lore_rate:
        lines.append(random.choice(LORE_BITS))

    # 最後に最大2行へ圧縮（余計なのは落とす）
    # “雑に切る”ほうが変になる
    random.shuffle(lines)
    out = lines[:CFG.max_lines]
    return [_strip_punct_line(x) for x in out if x.strip()]

def violates_rules(text: str) -> bool:
    # 2行以内
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not (1 <= len(lines) <= CFG.max_lines):
        return True

    if len(text) > CFG.max_chars:
        return True

    # 疑問符禁止
    for q in QUESTION_MARKS:
        if q in text:
            return True

    # 日付語禁止（行事語はOK）
    ev = jp_event_label(datetime.now(ZoneInfo(TIMEZONE)).date())
    for w in FORBIDDEN_DATE_WORDS:
        if w in text:
            # 行事語で相殺しない
            if ev and any(e in text for e in EVENT_BITS.get(ev, [ev])):
                continue
            return True

    # 接続詞禁止
    for c in FORBIDDEN_CONNECTORS:
        if c in text:
            return True

    # 禁止語
    for bad in FORBIDDEN_SUBSTRINGS:
        if bad in text:
            return True

    # URL混入禁止（貼るなら最後に正しいURLだけを別途付ける）
    if "http://" in text or "https://" in text:
        return True
    if "big-up.style" in text:
        return True

    return False

def normalize_text(lines: List[str]) -> str:
    # 「。」無し方針：必要なら「！」や「…」は許す（ただし絵文字は上で落ちる）
    cleaned = []
    for ln in lines:
        s = ln.strip()
        s = s.replace("。", "")
        s = re.sub(r"\s+", " ", s)
        s = s.strip()
        if not s:
            continue
        cleaned.append(s)

    # 2行上限
    cleaned = cleaned[:CFG.max_lines]
    return "\n".join(cleaned)[:CFG.max_chars].strip()

def try_gpt_spice(base_text: str, slot: str) -> Optional[str]:
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    if random.random() > CFG.gpt_spice_rate:
        return None

    # GPTには「短く変な言い換え」だけさせる。作文禁止。説明禁止。
    client = OpenAI(api_key=OPENAI_API_KEY)

    sys = (
        "あなたは日本語の短文加工機。"
        "入力文を『もっと変に』するが、作文にしない。説明・まとめ・感情描写は禁止。"
        "最大2行、合計120文字以内。句点「。」は使わない。接続詞（だから/でも/そして/けど）禁止。"
        "疑問符禁止。『だけ』禁止。URLや固有のリンク文字列は禁止。"
        "出力は短い断片。"
    )
    usr = f"slot={slot}\n入力:\n{base_text}\n\n短く変に加工して出力:"
    try:
        resp = client.chat.completions.create(
            model=MODEL_TEXT,
            messages=[
                {"role": "system", "content": sys},
                {"role": "user", "content": usr},
            ],
            temperature=1.0,
            max_tokens=80,
        )
        out = (resp.choices[0].message.content or "").strip()
        out = out.replace("。", "")
        # 余計な空行整理
        out_lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        out2 = normalize_text(out_lines)
        if out2 and not violates_rules(out2):
            return out2
        return None
    except Exception:
        return None

def should_attach_promo(now: datetime, st: Dict) -> bool:
    if FORCE_PROMO:
        # ただし1日1回制限
        last = st.get("last_promo_date")
        if last == now.date().isoformat():
            return False
        return True

    # 候補確率
    if random.random() > CFG.promo_rate:
        return False

    # 1日1回
    last = st.get("last_promo_date")
    if last == now.date().isoformat():
        return False

    return True

def build_promo_tail() -> str:
    # URLを貼る時も“お願い”はしない。短い断片 + URL
    head = random.choice(PROMO_BITS)
    head = head.replace("。", "").strip()
    return f"{head}\n{RELEASE_LINK_URL}"

def generate_text(now: datetime, slot: str, st: Dict) -> Tuple[str, bool]:
    """
    return: (text, promo_attached)
    """
    promo = should_attach_promo(now, st)

    # 既出回避（完全一致に近いのは弾く）
    recent_hashes: List[str] = st.get("recent_hashes", [])[-40:]

    for _ in range(CFG.retry):
        lines = build_candidate_lines(now, slot)
        base = normalize_text(lines)
        if not base:
            continue

        # ルール違反なら捨てる
        if violates_rules(base):
            continue

        # たまにGPTで“短い変換”を試す
        sp = try_gpt_spice(base, slot)
        text = sp if sp else base

        # URL付けるなら最後に付ける
        if promo:
            # URLを付けても規則が壊れないよう、本文は2行以内のまま。URLは別枠で2行追加され得るので、
            # この版では “URL付ける投稿” も最大2行にする：本文1行 + (URL行) の2行を基本にする
            # なので、本文は1行に圧縮し、URLを2行目へ。
            t_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if len(t_lines) > 1:
                t_lines = [random.choice(t_lines)]
            promo_text = f"{t_lines[0]}\n{RELEASE_LINK_URL}"
            # URL以外のリンク文字列混入は事前に落としてるのでOK
            text = promo_text

        # 既出っぽいのを弾く
        h = _hash_text(text)
        if h in recent_hashes:
            continue

        recent_hashes.append(h)
        st["recent_hashes"] = recent_hashes[-40:]
        if promo:
            st["last_promo_date"] = now.date().isoformat()
        return text[:280].strip(), promo

    # 最後の逃げ道：とにかく短く、禁止語を避ける
    fallback = "ピック見つからない"
    if should_attach_promo(now, st):
        fallback = f"{fallback}\n{RELEASE_LINK_URL}"
        st["last_promo_date"] = now.date().isoformat()
    h = _hash_text(fallback)
    recent_hashes.append(h)
    st["recent_hashes"] = recent_hashes[-40:]
    return fallback[:280].strip(), "\n" in fallback

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
            media = api_v1.media_upload(filename=str(media_path), media_category="tweet_video")
            return [media.media_id]
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

    # 認証が無いなら落とさず終了（Render通知を増やさない）
    if not (API_KEY and API_SECRET and ACCESS_TOKEN and ACCESS_TOKEN_SECRET):
        print("[WARN] X credentials missing. Set API_KEY/API_SECRET/ACCESS_TOKEN/ACCESS_TOKEN_SECRET")
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
        # status1で落とさずログに出して終える
        print(f"[X POST ERROR] {e}")

# ==========================
# メイン
# ==========================
def run_once() -> None:
    now = datetime.now(ZoneInfo(TIMEZONE))
    slot = detect_slot(now)

    st = _load_state()

    print(f"[BOOT] now={now.isoformat()} slot={slot}")
    print(f"[STATE] last_promo_date={st.get('last_promo_date')} recent_hashes={len(st.get('recent_hashes', []))}")
    print(f"[RULES] persona_rules_count={len(PERSONA_RULES)}")
    print(f"[LINK] {RELEASE_LINK_URL}")

    media_path = choose_media(now=now, slot=slot)

    text, promo = generate_text(now=now, slot=slot, st=st)

    print(f"[GEN] promo={promo}")
    print("[TEXT]")
    print(text)

    post_to_x(text=text, media_path=media_path)

    _save_state(st)

if __name__ == "__main__":
    try:
        run_once()
    except Exception as e:
        # Renderの「Exited with status 1」回避：落とさず終える
        print(f"[FATAL] {e}")
        # exit 0