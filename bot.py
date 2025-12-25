# bot.py
# Panda Usa G's / ポキヌ運用Bot（Render Cron想定：起動→1回投稿→終了）
#
# 重要：
# - バンド名/地名を「200個」入れるなら、コードにベタ書きせず外部ファイルで読み込むのが安全
#   - music_refs.txt（1行1件）… 例: Blur|Parklife|End of a Century
#   - places_micro.txt / places_city.txt / places_venue.txt（1行1件）
# - 入れた数はログで必ず表示する（端折り確認用）

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

# ==========================
# 運用ルール（曜日）
# ==========================
# 0=Mon ... 6=Sun
# 火曜：~100文字
# 水曜：固定プロモ（写真つけたいなら水曜も可だが、ここでは「水曜は必ずプロモ」）
# 木曜：~20文字
# 金曜/日曜：写真 or 動画を添付する日（できれば）
# 土曜：レコーディング（何してるか知らないニュアンスOK）
WEEKDAY_RULES = {
    0: {"label": "mon", "max_chars": 120, "mode": "normal", "attach_media": False},
    1: {"label": "tue", "max_chars": 100, "mode": "normal", "attach_media": False},
    2: {"label": "wed", "max_chars": 180, "mode": "promo_fixed", "attach_media": True},  # 写真添付したい派ならTrue
    3: {"label": "thu", "max_chars": 20,  "mode": "normal", "attach_media": False},
    4: {"label": "fri", "max_chars": 140, "mode": "normal", "attach_media": True},
    5: {"label": "sat", "max_chars": 140, "mode": "recording", "attach_media": False},
    6: {"label": "sun", "max_chars": 180, "mode": "normal", "attach_media": True},
}

# ==========================
# プロモ（URL）
# ==========================
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"

# 水曜固定（ユーザー指定）
WED_PROMO_TEXT = (
    "1の世界の民よ！\n"
    "パンダうさギーズ絶対聴いてね！\n"
    f"{RELEASE_LINK_URL}"
)

# 日曜：感謝＋URL（ユーザー確定）
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
# 外部リスト読み込み（端折り防止）
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
    music_refs.txt 形式（1行1件）:
      Artist|Album|Track
    AlbumやTrackは空でもOK:
      Blur||
      Beirut|Gulag Orkestar|
    """
    path = BASE_DIR / "music_refs.txt"
    raw = _read_lines(path)
    refs = []
    for row in raw:
        parts = row.split("|")
        # 3要素に揃える
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
recent_artists = deque(maxlen=20)  # 直近20回は同じartist避け
recent_places = deque(maxlen=20)   # 直近20回は同じplace避け

def pick_non_recent(items: List[str], recent: deque) -> Optional[str]:
    if not items:
        return None
    # まず recent に入ってない候補
    candidates = [x for x in items if x not in recent]
    if not candidates:
        # 全部 recent なら、仕方なく全体から
        choice = random.choice(items)
        recent.append(choice)
        return choice
    choice = random.choice(candidates)
    recent.append(choice)
    return choice

def pick_music_ref(music_refs: List[Dict[str, str]], weekday: int) -> Optional[Dict[str, str]]:
    if not music_refs:
        return None

    # 粒度制御：曲名は週1〜2回に抑えたいので、金/日だけtrack許可
    allow_track = weekday in (4, 6)
    allow_album = weekday in (1, 4, 6)  # 火/金/日

    # recent artist 避け
    candidates = [r for r in music_refs if r["artist"] and r["artist"] not in recent_artists]
    if not candidates:
        candidates = music_refs[:]

    ref = random.choice(candidates)
    recent_artists.append(ref["artist"])

    # track/albumを曜日ルールに従って落とす
    if not allow_album:
        ref = {**ref, "album": "", "track": ""}
    elif not allow_track:
        ref = {**ref, "track": ""}
    return ref

def pick_place(places: Dict[str, List[str]], weekday: int) -> Optional[str]:
    # 曜日ごとの粒度
    if weekday in (0, 3, 6):          # 月・木・日
        pool = places.get("micro", [])
    elif weekday in (4, 2):           # 金・水
        pool = (places.get("venue", []) + places.get("city", []))
    elif weekday in (5,):             # 土
        pool = places.get("city", [])
    else:                              # 火
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
    """
    金/日/水（設定上 attach_media True の日）だけ添付を狙う。
    mp4があれば一定確率で動画優先。
    """
    rule = WEEKDAY_RULES[weekday]
    if not rule.get("attach_media", False):
        return None

    all_media = list_media_files()
    if not all_media:
        return None

    videos = [p for p in all_media if p.suffix.lower() in (".mp4", ".mov")]
    images = [p for p in all_media if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]

    # 動画はまだ2本とのことなので、出し過ぎない
    if videos and random.random() < 0.25:
        return random.choice(videos)

    if images:
        return random.choice(images)

    return random.choice(all_media)

# ==========================
# 画像説明（必要なら）
# ==========================
def describe_image_for_prompt(image_path: Path) -> str:
    """
    画像をそのままポスト内容に直結させない（AI臭くなるので）
    ただし「具体名詞」を増やすための補助として短く抽出する。
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
                {"role": "system", "content": "画像の特徴を短く日本語で抽出する。抽象語を避け、物体/場所/構図を優先。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "画像の中で『名詞』だけを中心に、20〜35文字で抽出して。"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]},
            ],
            max_tokens=80,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return ""

# ==========================
# テキスト生成（ポキヌ）
# ==========================
def build_system_prompt(weekday: int, max_chars: int, mode: str) -> str:
    """
    ポキヌ：感情はある。ありがとうも言う。具体名詞（地名・バンド名・物の名）優先。
    NG：今日は/昨日は、天気、曖昧語（そこ/あの場所/この距離 多用）、説教、営業テンプレ。
    """
    # 曖昧語の完全禁止は不自然なので「多用禁止＋具体名詞優先」で縛る
    return f"""
あなたは大学生バンド「パンダうさギーズ」のボーカル、ポキヌ（女性）。
一人称は必ず「アタシ」。
ミュージシャンなので感情は強い。照れもある。ありがとうも言う。

【出力】
- 日本語
- 1〜4行（曜日で短くなる日がある）
- 句読点や改行は自由だが、箇条書き記号・ハッシュタグ・絵文字は禁止
- 「今日は」「昨日は」などの日付語は禁止
- 天気の話は禁止
- 「そこ」「あの場所」「この距離」など曖昧語の連発は禁止（使うなら1回まで）。代わりに具体名詞を置く
- 説明しすぎない。ポエムに寄せすぎない。人が読んで意味が拾える

【会話の形】
- 「アタシは今こうしてる。あなたは？」の並走スタイルを優先
- ただし、毎回質問だらけにしない（質問は1つまで）

【固有名詞】
- バンド名/アルバム名/曲名、地名、場所名、物の名を積極的に使ってよい
- 固有名詞は自慢や解説にしない。「状況の一部」として置く

【曜日モード】
- mode={mode}
- 最大文字数の目安：{max_chars}（超えないように短く）
""".strip()

def compose_user_payload(
    weekday: int,
    mode: str,
    max_chars: int,
    music_ref: Optional[Dict[str, str]],
    place: Optional[str],
    image_hint: str
) -> str:
    """
    生成の“材料”を渡す。材料は具体、文は短く。
    """
    # 音楽参照の表記を曜日制限後の状態で
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

    # 土曜は“レコーディング”の空気を必ず混ぜる
    extra = ""
    if mode == "recording":
        extra = "土曜：アタシは『レコーディング中』の体で書く。ただし何をしてるかは断定しない。\n"

    # 火曜は100字目安で少し情報量、木曜は超短く
    return f"""
材料：
- 場所（具体名詞）：{place_str}
- 音楽参照（具体名詞）：{music_str}
- 画像ヒント（名詞）：{hint_str}

{extra}
条件を守って、1本だけ投稿文を書いて。
質問は最大1つ。
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

    # 日曜は「感謝＋URL」固定（ユーザー確定）
    if weekday == 6:
        # ただし長すぎるのを防ぐ
        return SUN_THANKS_TEXT[:280]

    # 木曜は極短：材料を渡しても短くまとめる
    music_ref = pick_music_ref(music_refs, weekday)
    place = pick_place(places, weekday)

    image_hint = ""
    if media_path and media_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        # 画像がある日だけヒントを抽出（AI臭くなるので短く）
        image_hint = describe_image_for_prompt(media_path)

    system_prompt = build_system_prompt(weekday, max_chars=max_chars, mode=mode)
    user_payload = compose_user_payload(
        weekday=weekday,
        mode=mode,
        max_chars=max_chars,
        music_ref=music_ref,
        place=place,
        image_hint=image_hint,
    )

    try:
        resp = oa_client.chat.completions.create(
            model=MODEL_TEXT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.9,
            max_tokens=220,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[OpenAI ERROR] {e}")
        # 最低限のフォールバック（NG避け）
        text = "アタシは黙ってる。\nあなたは？"

    # 後処理：行数・空行整理、文字数カット
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > 4:
        lines = lines[:4]
    text = "\n".join(lines)

    # 曜日ごとの最大長に寄せる（木曜は20字相当）
    # ※完全一致は難しいので、上限で切る
    if max_chars and len(text) > max_chars:
        text = text[:max_chars].rstrip()

    return text[:280]

# ==========================
# 投稿（画像/動画対応）
# ==========================
def upload_media(api_v1: tweepy.API, media_path: Path) -> Optional[List[int]]:
    """
    画像：api.media_upload
    動画：media_category を tweet_video にして upload（tweepyが内側で分割アップロード対応する場合あり）
    """
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

    # 外部リスト読み込み（ここで“端折り”検出できる）
    music_refs = load_music_refs()
    places = load_places()

    # 端折り疑い防止：数を必ず出す
    total_places = sum(len(v) for v in places.values())
    print(f"[LIST COUNT] music_refs={len(music_refs)} / places_total={total_places} "
          f"(micro={len(places['micro'])}, city={len(places['city'])}, venue={len(places['venue'])})")

    if len(music_refs) < 50:
        print("[WARN] music_refs が少ない（200入れるなら music_refs.txt を増やす）")
    if total_places < 50:
        print("[WARN] places が少ない（200入れるなら places_*.txt を増やす）")

    rule = WEEKDAY_RULES[weekday]
    media_path = choose_media(weekday) if rule.get("attach_media") else None

    text = generate_text(
        weekday=weekday,
        music_refs=music_refs,
        places=places,
        media_path=media_path
    )

    # 水曜固定プロモはURL込みなので、余計な追記はしない
    # 日曜固定感謝も同様
    post_to_x(text=text, media_path=media_path)

if __name__ == "__main__":
    run_once()
