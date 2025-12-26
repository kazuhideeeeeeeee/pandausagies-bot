# bot.py
# Panda Usa G's / ポキヌ運用Bot（Render Cron想定：起動→1回投稿→終了）

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

# ==========================
# 曜日ルール
# ==========================
WEEKDAY_RULES = {
    0: {"label": "mon", "max_chars": 120, "mode": "normal", "attach_media": False},
    1: {"label": "tue", "max_chars": 100, "mode": "normal", "attach_media": False},
    2: {"label": "wed", "max_chars": 180, "mode": "promo_fixed", "attach_media": True},
    3: {"label": "thu", "max_chars": 20,  "mode": "normal", "attach_media": False},
    4: {"label": "fri", "max_chars": 140, "mode": "normal", "attach_media": True},
    5: {"label": "sat", "max_chars": 140, "mode": "recording", "attach_media": False},
    6: {"label": "sun", "max_chars": 180, "mode": "normal", "attach_media": True},
}

# ==========================
# プロモ文
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
# パス
# ==========================
BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "BOTimg"
MEDIA_DIR.mkdir(exist_ok=True)

# ==========================
# OpenAI
# ==========================
oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()
MODEL_TEXT = os.getenv("OPENAI_MODEL_TEXT", "gpt-4o-mini")
MODEL_VISION = os.getenv("OPENAI_MODEL_VISION", "gpt-4o-mini")

# ==========================
# X API
# ==========================
def create_client_v2() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
    )

def create_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(
        API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET
    )
    return tweepy.API(auth)

# ==========================
# 外部ファイル読込
# ==========================
def _read_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]

def load_music_refs() -> List[Dict[str, str]]:
    rows = _read_lines(BASE_DIR / "music_refs.txt")
    refs = []
    for r in rows:
        parts = r.split("|")
        while len(parts) < 3:
            parts.append("")
        artist, album, track = [p.strip() for p in parts[:3]]
        if artist:
            refs.append({"artist": artist, "album": album, "track": track})
    return refs

def load_places() -> Dict[str, List[str]]:
    return {
        "micro": _read_lines(BASE_DIR / "places_micro.txt"),
        "city":  _read_lines(BASE_DIR / "places_city.txt"),
        "venue": _read_lines(BASE_DIR / "places_venue.txt"),
    }

# ==========================
# 被り防止
# ==========================
recent_artists = deque(maxlen=20)
recent_places = deque(maxlen=20)

def pick_non_recent(items: List[str], recent: deque) -> Optional[str]:
    if not items:
        return None
    candidates = [x for x in items if x not in recent]
    choice = random.choice(candidates or items)
    recent.append(choice)
    return choice

def pick_music_ref(music_refs: List[Dict[str, str]], weekday: int) -> Optional[Dict[str, str]]:
    if not music_refs:
        return None
    allow_track = weekday in (4, 6)
    allow_album = weekday in (1, 4, 6)

    candidates = [r for r in music_refs if r["artist"] not in recent_artists]
    ref = random.choice(candidates or music_refs)
    recent_artists.append(ref["artist"])

    if not allow_album:
        ref = {**ref, "album": "", "track": ""}
    elif not allow_track:
        ref = {**ref, "track": ""}

    return ref

def pick_place(places: Dict[str, List[str]], weekday: int) -> Optional[str]:
    pool = places["city"] + places["venue"] + places["micro"]
    return pick_non_recent(pool, recent_places)

# ==========================
# メディア
# ==========================
def list_media_files() -> List[Path]:
    files = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.mp4", "*.mov"):
        files.extend(MEDIA_DIR.glob(ext))
    return files

def choose_media(weekday: int) -> Optional[Path]:
    if not WEEKDAY_RULES[weekday]["attach_media"]:
        return None
    files = list_media_files()
    if not files:
        return None
    videos = [f for f in files if f.suffix.lower() in (".mp4", ".mov")]
    if videos and random.random() < 0.25:
        return random.choice(videos)
    return random.choice(files)

# ==========================
# テキスト生成
# ==========================
def build_system_prompt(weekday: int, max_chars: int, mode: str) -> str:
    return f"""
あなたはパンダうさギーズのボーカル、ポキヌ。
一人称は「アタシ」。
感情はある。ありがとうも言う。
具体名詞（バンド名・地名）を優先。

禁止：
- 今日は／昨日は
- 天気
- 曖昧語の連発
- 説明口調

最大文字数目安：{max_chars}
mode={mode}
""".strip()

def compose_user_payload(music_ref, place) -> str:
    bits = []
    if music_ref:
        bits.append(music_ref["artist"])
        if music_ref["album"]:
            bits.append(f"『{music_ref['album']}』")
        if music_ref["track"]:
            bits.append(f"「{music_ref['track']}」")
    music = " / ".join(bits)
    return f"場所：{place}\n音楽：{music}\n短く1本書いて。"

def generate_text(weekday, music_refs, places):
    rule = WEEKDAY_RULES[weekday]
    mode = rule["mode"]
    max_chars = rule["max_chars"]

    if mode == "promo_fixed":
        return WED_PROMO_TEXT[:280]
    if weekday == 6:
        return SUN_THANKS_TEXT[:280]

    music_ref = pick_music_ref(music_refs, weekday)
    place = pick_place(places, weekday)

    resp = oa_client.chat.completions.create(
        model=MODEL_TEXT,
        messages=[
            {"role": "system", "content": build_system_prompt(weekday, max_chars, mode)},
            {"role": "user", "content": compose_user_payload(music_ref, place)},
        ],
        temperature=0.9,
        max_tokens=220,
    )

    text = resp.choices[0].message.content.strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    text = "\n".join(lines[:4])

    # 🔧 ★修正ポイント（単語途中で切らない）
    if max_chars and len(text) > max_chars:
        cut = text[:max_chars]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        text = cut.rstrip()

    return text[:280]

# ==========================
# 投稿
# ==========================
def post_to_x(text: str, media_path: Optional[Path]):
    client = create_client_v2()
    media_ids = None

    if media_path:
        api = create_api_v1()
        media = api.media_upload(str(media_path))
        media_ids = [media.media_id]

    client.create_tweet(text=text[:280], media_ids=media_ids)

# ==========================
# Main
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()

    music_refs = load_music_refs()
    places = load_places()

    print(f"[COUNT] music={len(music_refs)} places={sum(len(v) for v in places.values())}")

    media = choose_media(weekday)
    text = generate_text(weekday, music_refs, places)
    post_to_x(text, media)

if __name__ == "__main__":
    run_once()
