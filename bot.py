# bot.py
# Panda Usa G's / ポキヌ運用Bot
# Render Cron想定：1日1〜2回起動（時間帯で内容分岐）

import os
import base64
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
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
oa = OpenAI(api_key=OPENAI_API_KEY)

MODEL_TEXT = "gpt-4o-mini"

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

# ==========================
# 宣伝URL
# ==========================
RELEASE_URL = "https://big-up.style/uviwifz2tO"

PROMO_VARIANTS = [
    "ダウンロードしてくれた人、ありがとう。\nこれからの人も、たぶん好き。\n" + RELEASE_URL,
    "気に入ったら連れて帰って。\n" + RELEASE_URL,
    "ここに音が置いてある。\n" + RELEASE_URL,
]

# ==========================
# 時間帯判定
# ==========================
def get_time_slot(now: datetime) -> str:
    h = now.hour
    if 18 <= h <= 20:
        return "evening"   # 19時台：練習・音楽・動いてる
    if 22 <= h <= 24 or h <= 1:
        return "late"      # 23時台：パジャマ・移動・判断が雑
    return "other"

# ==========================
# メディア選択
# ==========================
def choose_media() -> Optional[Path]:
    files = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.mp4", "*.mov"):
        files.extend(MEDIA_DIR.glob(ext))
    if not files:
        return None
    return random.choice(files)

# ==========================
# プロンプト生成
# ==========================
def build_system_prompt(slot: str) -> str:
    base = """
あなたは大学生バンド「パンダうさギーズ」のボーカル、ポキヌ。
一人称は必ず「アタシ」。

【人格】
・感情は強い
・判断は雑
・賢そうに振る舞わない
・笑わせようとしないが、ズレてる
・自分を下げるが、自虐ではない
・人に構ってほしいが、主張しない
・ミュージシャンとしてコール＆レスポンスに憧れがある
・ありがとうは言う

【禁止】
・今日は／昨日は
・天気の話
・説明口調
・営業テンプレ
・毎回同じ書き出し（例：アタシ今〜）

【文体】
・1〜4行
・具体名詞を使う（バンド名、地名、食べ物、乗り物）
・問いかけは最大1つ
・「そこ」「あの場所」など曖昧語の多用禁止
"""

    if slot == "evening":
        return base + """
【19時台】
・練習中、音楽中、動いてる
・楽器、バンド名OK
・少し元気
"""
    if slot == "late":
        return base + """
【23時台】
・パジャマ、移動、電車、風呂、サウナ、コインランドリー
・判断が止まる
・生活感を置くだけ
・深夜テンションだが病まない
"""
    return base

def build_user_prompt(slot: str) -> str:
    if slot == "evening":
        return """
状況例：
・練習スタジオ
・ギター
・Blur / The Cure / Oasis / Wet Leg など
・終わりが見えない

この空気で1投稿書いて。
"""
    if slot == "late":
        return """
状況例：
・パジャマ
・電車内
・準特急
・千歳烏山
・サウナ
・コインランドリー
・判断が雑

この空気で1投稿書いて。
"""
    return "自由に1投稿書いて。"

# ==========================
# テキスト生成
# ==========================
def generate_text(slot: str) -> str:
    resp = oa.chat.completions.create(
        model=MODEL_TEXT,
        messages=[
            {"role": "system", "content": build_system_prompt(slot)},
            {"role": "user", "content": build_user_prompt(slot)},
        ],
        temperature=0.95,
        max_tokens=200,
    )
    text = resp.choices[0].message.content.strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines[:4])

# ==========================
# 投稿
# ==========================
def post(text: str, media: Optional[Path]):
    client = create_client_v2()
    media_ids = None

    if media:
        api = create_api_v1()
        try:
            if media.suffix.lower() in (".mp4", ".mov"):
                m = api.media_upload(
                    filename=str(media),
                    media_category="tweet_video"
                )
            else:
                m = api.media_upload(str(media))
            media_ids = [m.media_id]
        except Exception as e:
            print("[MEDIA ERROR]", e)

    client.create_tweet(text=text[:280], media_ids=media_ids)

# ==========================
# メイン
# ==========================
def run():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()
    slot = get_time_slot(now)

    # 宣伝日は1日1回（水・日）
    if weekday in (2, 6):
        text = random.choice(PROMO_VARIANTS)
        media = choose_media()
        post(text, media)
        return

    text = generate_text(slot)
    media = None

    # 金・日は写真OK
    if weekday in (4, 6):
        media = choose_media()

    post(text, media)

if __name__ == "__main__":
    run()
