# bot.py
# Panda Usa G's / ポキヌ運用Bot
# Render Cron 想定：1日1〜2回起動（時間帯別）

import os
import random
import base64
from datetime import datetime
from pathlib import Path
from typing import Optional, List
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

TIMEZONE = "Asia/Tokyo"

# ==========================
# OpenAI
# ==========================
oa_client = OpenAI(api_key=OPENAI_API_KEY)
MODEL = "gpt-4o-mini"

# ==========================
# X
# ==========================
def create_client_v2():
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
    )

def create_api_v1():
    auth = tweepy.OAuth1UserHandler(
        API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET
    )
    return tweepy.API(auth)

# ==========================
# パス
# ==========================
BASE_DIR = Path(__file__).resolve().parent
MEDIA_DIR = BASE_DIR / "BOTimg"
MEDIA_DIR.mkdir(exist_ok=True)

# ==========================
# 宣伝
# ==========================
RELEASE_URL = "https://big-up.style/uviwifz2tO"

PROMO_VARIANTS = [
    "ダウンロードしてくれた人、ありがとう。\nこれからの人も、たぶん好き。\n" + RELEASE_URL,
    "アタシは続けてる。\n見つけた人は、持って帰って。\n" + RELEASE_URL,
    "気に入ったらでいい。\n記録はここにある。\n" + RELEASE_URL,
]

# ==========================
# メディア選択
# ==========================
def choose_image() -> Optional[Path]:
    images = list(MEDIA_DIR.glob("*.png")) + list(MEDIA_DIR.glob("*.jpg")) + list(MEDIA_DIR.glob("*.jpeg"))
    if not images:
        return None
    return random.choice(images)

# ==========================
# 時間帯判定
# ==========================
def time_band(now: datetime) -> str:
    hour = now.hour
    if 18 <= hour < 21:
        return "evening"   # 練習・外
    if 22 <= hour or hour < 1:
        return "late"      # パジャマ・甘い物
    return "other"

# ==========================
# 投稿回数判定
# ==========================
def should_post_twice(weekday: int) -> bool:
    # 金・土のみ2ポスト
    return weekday in (4, 5)

# ==========================
# システムプロンプト（人格OS）
# ==========================
def system_prompt(weekday: int, band: str) -> str:
    return f"""
あなたは大学生バンド「パンダうさギーズ」のボーカル、ポキヌ。
一人称は必ず「アタシ」。

【人格】
- 感情は強い
- 少し構ってほしい
- でも要求しない
- 判断が雑
- 行動と感情がズレる
- 自分を少し下げる（自虐は禁止）
- 笑わせに行かない。ズレを置くだけ

【禁止】
- 「今日は」「昨日は」
- 天気の話
- 説教
- 営業口調
- 毎回同じ型（アタシ今〜の連発禁止）

【問いかけ】
- 0〜1個まで
- 「アタシはこう。あなたは？」型が望ましい

【時間帯】
- evening：練習、移動、外、楽器
- late：パジャマ、甘い物、風呂、洗濯、電車、寝落ち前

【文字数】
- 20〜120字目安
"""

# ==========================
# テキスト生成
# ==========================
def generate_text(weekday: int, band: str) -> str:
    user_prompt = "Xに投稿する短文を1つだけ書いて。"

    resp = oa_client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt(weekday, band)},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.95,
        max_tokens=200,
    )

    text = resp.choices[0].message.content.strip()
    lines = [l for l in text.splitlines() if l.strip()]
    return "\n".join(lines[:4])[:280]

# ==========================
# 投稿
# ==========================
def post(text: str, image: Optional[Path]):
    client = create_client_v2()
    media_ids = None

    if image:
        api = create_api_v1()
        media = api.media_upload(str(image))
        media_ids = [media.media_id]

    client.create_tweet(text=text, media_ids=media_ids)

# ==========================
# 実行
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()
    band = time_band(now)

    # 水曜：宣伝のみ
    if weekday == 2:
        post(random.choice(PROMO_VARIANTS), choose_image())
        return

    text = generate_text(weekday, band)

    # 日曜：感謝寄り
    if weekday == 6:
        text += "\n\n" + random.choice(PROMO_VARIANTS)

    image = None
    if weekday in (4, 6):  # 金・日
        image = choose_image()

    post(text, image)

# ==========================
if __name__ == "__main__":
    run_once()
