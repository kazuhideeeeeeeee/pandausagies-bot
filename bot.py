# bot.py
# Panda Usa G's / ポキヌ運用Bot
# Render Cron 想定：起動→1回投稿→終了

import os
import base64
import random
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from zoneinfo import ZoneInfo
import tweepy
from openai import OpenAI
from dotenv import load_dotenv

# ==========================
# 環境変数
# ==========================
load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TIMEZONE = "Asia/Tokyo"

# ==========================
# OpenAI
# ==========================
oa_client = OpenAI(api_key=OPENAI_API_KEY)
MODEL_TEXT = "gpt-4o-mini"
MODEL_VISION = "gpt-4o-mini"

# ==========================
# X (Twitter)
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
        API_KEY, API_SECRET,
        ACCESS_TOKEN, ACCESS_TOKEN_SECRET
    )
    return tweepy.API(auth)

# ==========================
# パス
# ==========================
BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "BOTimg"
MEDIA_DIR.mkdir(exist_ok=True)

# ==========================
# 曜日ルール
# ==========================
WEEKDAY_RULES = {
    0: {"max_chars": 120, "attach_media": False},
    1: {"max_chars": 100, "attach_media": False},
    2: {"max_chars": 180, "attach_media": True},   # 水曜：宣伝日
    3: {"max_chars": 20,  "attach_media": False},
    4: {"max_chars": 140, "attach_media": True},
    5: {"max_chars": 140, "attach_media": False},
    6: {"max_chars": 180, "attach_media": True},
}

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
# メディア選択
# ==========================
def list_media_files() -> List[Path]:
    files = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.mp4", "*.mov"):
        files.extend(MEDIA_DIR.glob(ext))
    return files

def choose_media(weekday: int) -> Optional[Path]:
    rule = WEEKDAY_RULES[weekday]
    if not rule["attach_media"]:
        return None
    files = list_media_files()
    if not files:
        return None
    return random.choice(files)

# ==========================
# 行事判定（★ここが今回の核心）
# ==========================
def detect_event(media_path: Optional[Path]) -> Optional[str]:
    if not media_path:
        return None

    name = media_path.name.lower()

    # 正月用画像
    if name == "botimg51.png":
        return "newyear"

    return None

# ==========================
# システムプロンプト
# ==========================
def build_system_prompt(event: Optional[str], max_chars: int) -> str:
    event_rule = ""
    if event == "newyear":
        event_rule = """
【行事ルール：正月】
- 「正月」という単語は1回まで使用可
- 「今日は」「昨日」「今年」「来年」「あけまして」禁止
- 抱負・振り返り・まとめ禁止
- 問いかけ禁止
- 結果・結論を言わない
"""

    return f"""
あなたは大学生バンド「パンダうさギーズ」のボーカル、ポキヌ。
一人称は必ず「アタシ」。

【文体】
- 感情はあるが、説明しない
- 笑わせようとしないが、ズレは残す
- 自虐は禁止（下げるのはOK）
- 問いかけは基本しない
- 結果・教訓を言わない

【禁止】
- 「今日は」「昨日」
- 天気
- SNSテンプレ
- 連続した同型構文

{event_rule}

最大文字数目安：{max_chars}
""".strip()

# ==========================
# テキスト生成
# ==========================
def generate_text(
    weekday: int,
    media_path: Optional[Path],
) -> str:

    # 固定日
    if weekday == 2:
        return WED_PROMO_TEXT[:280]
    if weekday == 6:
        return SUN_THANKS_TEXT[:280]

    rule = WEEKDAY_RULES[weekday]
    max_chars = rule["max_chars"]

    event = detect_event(media_path)
    system_prompt = build_system_prompt(event, max_chars)

    user_prompt = """
短文で1本だけ書く。
説明しない。
情景は置く。
結論は言わない。
""".strip()

    try:
        resp = oa_client.chat.completions.create(
            model=MODEL_TEXT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.95,
            max_tokens=200,
        )
        text = resp.choices[0].message.content.strip()
    except Exception:
        text = "アタシは黙ってる。"

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    text = "\n".join(lines)

    if len(text) > max_chars:
        text = text[:max_chars].rstrip()

    return text[:280]

# ==========================
# 投稿
# ==========================
def upload_media(api: tweepy.API, path: Path) -> Optional[List[int]]:
    try:
        media = api.media_upload(str(path))
        return [media.media_id]
    except Exception as e:
        print("[MEDIA ERROR]", e)
        return None

def post_to_x(text: str, media_path: Optional[Path]):
    client = create_client_v2()
    media_ids = None

    if media_path:
        api = create_api_v1()
        media_ids = upload_media(api, media_path)

    client.create_tweet(text=text, media_ids=media_ids)

# ==========================
# メイン
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()

    media_path = choose_media(weekday)
    text = generate_text(weekday, media_path)

    print("[DEBUG] media:", media_path.name if media_path else "none")
    print("[DEBUG] text:\n", text)

    post_to_x(text, media_path)

if __name__ == "__main__":
    run_once()
