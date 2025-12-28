# bot.py
# Panda Usa G's / ポキヌ運用Bot（Render Cron想定：起動→1回投稿→終了）
#
# 変更点（今回の目的）
# - 「型が固定されない」「似た投稿を物理的に出しづらい」は維持
# - ただし “笑いに寄せる”：毎回「ズレ」要素を最低1個強制
# - 主張はDLのみ：URLを出す回を明確に制御（出しすぎない）
# - 文字数カットで「途中でブツ切れ」を防止：句点/改行で綺麗に落とす
# - 1日2投稿対応：CRON_SLOT=morning/evening で文体テンション変える（Cronを2本にする）

import os
import base64
import random
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Dict

from zoneinfo import ZoneInfo
import tweepy
from openai import OpenAI
from dotenv import load_dotenv

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

# 1日2投稿にしたい場合：Render Cronを2本作って
# 朝のCronに CRON_SLOT=morning
# 夜のCronに CRON_SLOT=evening
CRON_SLOT = os.getenv("CRON_SLOT", "any")  # any / morning / evening

# ==========================
# 運用ルール（曜日）
# ==========================
# 0=Mon ... 6=Sun
WEEKDAY_RULES = {
    0: {"label": "mon", "max_chars": 140, "mode": "normal",      "attach_media": False},
    1: {"label": "tue", "max_chars": 100, "mode": "normal",      "attach_media": False},
    2: {"label": "wed", "max_chars": 180, "mode": "promo_fixed", "attach_media": True},
    3: {"label": "thu", "max_chars": 40,  "mode": "short",       "attach_media": False},  # 20は短すぎて事故るので40に
    4: {"label": "fri", "max_chars": 160, "mode": "normal",      "attach_media": True},
    5: {"label": "sat", "max_chars": 160, "mode": "recording",   "attach_media": False},
    6: {"label": "sun", "max_chars": 180, "mode": "thanks_fixed","attach_media": True},
}

# ==========================
# プロモ（URL）
# ==========================
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"

WED_PROMO_TEXT = (
    "1の世界の民よ！\n"
    "パンダうさギーズ絶対聴いてね！\n"
    f"{RELEASE_LINK_URL}"
)

SUN_THANKS_TEXT = (
    "ダウンロードしてくれた人、ありがとう。\n"
    "これからの人も、たぶん好き。\n"
    f"{RELEASE_LINK_URL}"
)

# ==========================
# パス・メディア
# ==========================
BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "BOTimg"   # 画像も動画もここでOK
MEDIA_DIR.mkdir(exist_ok=True)

# ==========================
# OpenAI
# ==========================
oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()
MODEL_TEXT = os.getenv("OPENAI_MODEL_TEXT", "gpt-4o-mini")
MODEL_VISION = os.getenv("OPENAI_MODEL_VISION", "gpt-4o-mini")

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

# ==========================
# 外部リスト読み込み
# ==========================
def _read_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    lines = []
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
    music_refs.txt（1行1件）:
      Artist|Album|Track
    """
    path = BASE_DIR / "music_refs.txt"
    raw = _read_lines(path)
    refs = []
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
    return {
        "micro": _read_lines(BASE_DIR / "places_micro.txt"),
        "city":  _read_lines(BASE_DIR / "places_city.txt"),
        "venue": _read_lines(BASE_DIR / "places_venue.txt"),
    }

# ==========================
# 直近被り防止
# ==========================
recent_artists = deque(maxlen=30)
recent_places  = deque(maxlen=30)
recent_openers = deque(maxlen=12)

def pick_non_recent(items: List[str], recent: deque) -> Optional[str]:
    if not items:
        return None
    candidates = [x for x in items if x not in recent]
    choice = random.choice(candidates) if candidates else random.choice(items)
    recent.append(choice)
    return choice

def pick_music_ref(music_refs: List[Dict[str, str]], weekday: int) -> Optional[Dict[str, str]]:
    if not music_refs:
        return None

    # 曲名は金/日だけ（情報が強すぎて型が出やすいので）
    allow_track = weekday in (4, 6)
    allow_album = weekday in (1, 4, 6)

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

def pick_place(places: Dict[str, List[str]], weekday: int) -> Optional[str]:
    if weekday in (0, 3, 6):
        pool = places.get("micro", [])
    elif weekday in (4, 2):
        pool = (places.get("venue", []) + places.get("city", []))
    elif weekday in (5,):
        pool = places.get("city", [])
    else:
        pool = (places.get("micro", []) + places.get("city", []))

    return pick_non_recent(pool, recent_places)

# ==========================
# 画像/動画 選択
# ==========================
def list_media_files() -> List[Path]:
    files: List[Path] = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.mp4", "*.mov"):
        files.extend(MEDIA_DIR.glob(ext))
    return sorted(files)

def choose_media(weekday: int) -> Optional[Path]:
    rule = WEEKDAY_RULES[weekday]
    if not rule.get("attach_media", False):
        return None

    all_media = list_media_files()
    if not all_media:
        return None

    videos = [p for p in all_media if p.suffix.lower() in (".mp4", ".mov")]
    images = [p for p in all_media if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]

    # 動画は出し過ぎない（2本しかない想定）
    if videos and random.random() < 0.20:
        return random.choice(videos)

    if images:
        return random.choice(images)

    return random.choice(all_media)

# ==========================
# 画像ヒント（名詞だけ）
# ==========================
def describe_image_for_prompt(image_path: Path) -> str:
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
                {"role": "system", "content": "画像の特徴を名詞中心で短く。抽象語と感情語は禁止。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "名詞だけで20〜40文字。例：ピンク髪、ギター、マイク、逆光"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]},
            ],
            max_tokens=90,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""

# ==========================
# 文章のブツ切れ防止（安全トリム）
# ==========================
def smart_trim(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text

    # まず上限内で「自然に終われる位置」を探す
    candidates = []
    window = text[:max_chars]
    for sep in ["。", "！", "？", "\n"]:
        idx = window.rfind(sep)
        if idx != -1 and idx >= max_chars * 0.55:  # 途中で短くなり過ぎない
            candidates.append(idx + 1)

    if candidates:
        cut = max(candidates)
        return window[:cut].rstrip()

    # 最後の手段：単純カット（ただし末尾を整える）
    return window.rstrip(" 　、,").rstrip()

# ==========================
# “笑いスイッチ” = ズレ装置
# ==========================
# 毎回どれか1つ必須（ギャグじゃなく「変な判断」「矛盾」「急な具体」で笑いに寄せる）
COMEDY_DEVICES = [
    "判断が雑（勢いで結論出す）",
    "感情と行動がズレる（切ないのに飯の話など）",
    "因果が変（理由が隣の家任せ等）",
    "急に逆ギレ（対象は物やアプリや概念）",
    "セルフツッコミを1回だけ入れる",
    "妙に具体（店名/駅名/曲名/機材名を状況の一部として置く）",
    "矛盾を自覚してない（でも最後に一言だけ刺す）",
]

OPENERS = [
    "アタシ、",
    "いまさらだけど、",
    "急に思い出した。",
    "耳が勝手に、",
    "手が勝手に、",
    "頭の中が、",
    "口が勝手に、",
    "なんかさ、",
    "この感じ、",
]

def pick_opener() -> str:
    candidates = [o for o in OPENERS if o not in recent_openers]
    choice = random.choice(candidates) if candidates else random.choice(OPENERS)
    recent_openers.append(choice)
    return choice

# ==========================
# DL主張の制御（出しすぎない）
# ==========================
def should_include_download_link(weekday: int) -> bool:
    # 水曜固定・日曜固定は別処理
    if weekday in (2, 6):
        return True
    # それ以外：週の中で「たまに」だけ
    # 金曜は少し高め、木曜は低め
    if weekday == 4:
        return random.random() < 0.35
    if weekday == 3:
        return random.random() < 0.10
    return random.random() < 0.20

# ==========================
# テキスト生成
# ==========================
def build_system_prompt(weekday: int, max_chars: int, mode: str) -> str:
    # スロットでテンションを変える（朝=淡い毒、夜=感情強め）
    slot_note = ""
    if CRON_SLOT == "morning":
        slot_note = "朝スロット：短め、乾いたノリ、言い切り多め。"
    elif CRON_SLOT == "evening":
        slot_note = "夜スロット：感情強め、でも説明はしない。"

    return f"""
あなたは大学生バンド「パンダうさギーズ」のボーカル、ポキヌ（女性）。
一人称は必ず「アタシ」。
ミュージシャンなので感情は強い。照れもある。ありがとうも言う。

【絶対NG】
- 「今日は」「昨日は」など日付語
- 天気の話
- ハッシュタグ、絵文字、箇条書き記号
- 説教、営業テンプレ、説明過多
- 「そこ」「あの場所」「この距離」など曖昧語の連発（使うなら1回まで）

【大事】
- 毎回「笑いに寄せる」：ギャグを書かない。代わりに“ズレ”を最低1個入れる
- 投稿の型を固定しない（毎回似た構造にしない）
- 質問は最大1つ。構ってほしさは“滲ませる”が、依存はしない

【固有名詞】
- バンド名/アルバム名/曲名、地名、場所名を状況の一部として置く（自慢/解説にしない）

【曜日モード】
mode={mode}
最大文字数の目安：{max_chars}（超えない）
{slot_note}
""".strip()

def compose_user_payload(
    weekday: int,
    mode: str,
    max_chars: int,
    music_ref: Optional[Dict[str, str]],
    place: Optional[str],
    image_hint: str,
    include_link: bool,
) -> str:
    music_bits = []
    if music_ref:
        if music_ref.get("artist"):
            music_bits.append(music_ref["artist"])
        if music_ref.get("album"):
            music_bits.append(f"『{music_ref['album']}』")
        if music_ref.get("track"):
            music_bits.append(f"「{music_ref['track']}」")
    music_str = " / ".join(music_bits) if music_bits else "（指定なし）"
    place_str = place or "（指定なし）"
    hint_str = image_hint or "（なし）"

    device = random.choice(COMEDY_DEVICES)
    opener = pick_opener()

    # 土曜：録音の空気（断定しない）
    extra = ""
    if mode == "recording":
        extra = "土曜：レコーディング中“っぽい”空気。断定しない。機材名やスタジオ名を置いてもいい。\n"

    link_rule = ""
    if include_link:
        link_rule = f"最後の行にURLを単独で置く（他の主張は入れない）：{RELEASE_LINK_URL}\n"
    else:
        link_rule = "URLは出さない。\n"

    # 「アタシ今」固定を避けるため、オープナーを材料として渡す
    return f"""
材料：
- オープナー候補：{opener}
- 場所（具体名詞）：{place_str}
- 音楽参照（具体名詞）：{music_str}
- 画像ヒント（名詞）：{hint_str}

必須の“ズレ装置”：{device}
{extra}
{link_rule}

条件を守って、投稿文を1本だけ。
- 1〜4行
- 質問は最大1つ
- 文の途中で切れそうなら、短く作って自然に終わる
""".strip()

def generate_text(
    weekday: int,
    music_refs: List[Dict[str, str]],
    places: Dict[str, List[str]],
    media_path: Optional[Path]
) -> str:
    rule = WEEKDAY_RULES[weekday]
    mode = rule["mode"]
    max_chars = rule["max_chars"]

    # 水曜固定
    if mode == "promo_fixed":
        return WED_PROMO_TEXT[:280]

    # 日曜固定
    if mode == "thanks_fixed":
        return SUN_THANKS_TEXT[:280]

    music_ref = pick_music_ref(music_refs, weekday)
    place = pick_place(places, weekday)

    image_hint = ""
    if media_path and media_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        image_hint = describe_image_for_prompt(media_path)

    include_link = should_include_download_link(weekday)

    system_prompt = build_system_prompt(weekday, max_chars=max_chars, mode=mode)
    user_payload = compose_user_payload(
        weekday=weekday,
        mode=mode,
        max_chars=max_chars,
        music_ref=music_ref,
        place=place,
        image_hint=image_hint,
        include_link=include_link,
    )

    try:
        resp = oa_client.chat.completions.create(
            model=MODEL_TEXT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.95,
            max_tokens=260,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[OpenAI ERROR] {e}")
        text = "アタシ、うるさい。\nあなたは？"

    # 整形
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 4:
        lines = lines[:4]
    text = "\n".join(lines)

    # 上限に収める（ブツ切れ防止）
    text = smart_trim(text, max_chars)
    text = smart_trim(text, 280)

    return text

# ==========================
# 投稿（画像/動画対応）
# ==========================
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
    weekday = now.weekday()

    music_refs = load_music_refs()
    places = load_places()

    total_places = sum(len(v) for v in places.values())
    print(f"[LIST COUNT] music_refs={len(music_refs)} / places_total={total_places} "
          f"(micro={len(places['micro'])}, city={len(places['city'])}, venue={len(places['venue'])})")
    print(f"[SLOT] CRON_SLOT={CRON_SLOT} / weekday={weekday} ({WEEKDAY_RULES[weekday]['label']})")

    rule = WEEKDAY_RULES[weekday]
    media_path = choose_media(weekday) if rule.get("attach_media") else None

    text = generate_text(
        weekday=weekday,
        music_refs=music_refs,
        places=places,
        media_path=media_path
    )

    post_to_x(text=text, media_path=media_path)

if __name__ == "__main__":
    run_once()
