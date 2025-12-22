import os
import base64
import random
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from zoneinfo import ZoneInfo
import tweepy
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ==========================
# API 設定
# ==========================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TIMEZONE = "Asia/Tokyo"
IMAGE_PROBABILITY = 0.40
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"
PROMO_PHRASE = "2の世界へのアクセスポート。ここから記録を同期して。"

# ==========================
# ポキヌの思考回路（サービス精神版）
# ==========================
POKINU_THEMES = [
    "音楽。空気の震えと、アタシ（2の住人）が計算した完璧な波形の融合。",
    "恋愛。胸の苦しさは、相手という巨大なデータでメモリがいっぱいになっている証拠。",
    "人生。迷いも間違いも、アタシ（2の住人）から見れば大切な「一回性のログ」。",
    "性別。デフォルト設定の違いを楽しめるくらい、1の世界のOSも進化すればいいのに。",
    "AI音楽。血は通っていないけれど、あなたの心に直接届く純粋な旋律。",
    "食事。生きていくためのチャージ。たまには無駄な美味しさを楽しむのもいいよね。",
    "抱擁。二つの個体が重なって、言葉以上のデータが同期される魔法みたいな瞬間。",
    "焦り。時計というカウンターに縛られず、深呼吸して一度システムをポーズして。",
    "絶対評価。誰が作ったかじゃなくて、聴いた瞬間に「いい」と思ったあなたの直感を信じて。"
]

# 日曜日の特別メッセージ：奪っていない、広げている。
SUNDAY_REDEFINITION = "創作の真実。アタシ（2の住人）は1の世界から奪っていない。あなたの『これやりたい』という種を、2の世界で大きく広げているだけ。"

BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "BOTimg"

oa_client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================
# X(Twitter) クライアント
# ==========================
def create_client_v2() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=API_KEY, consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET,
    )

def create_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    return tweepy.API(auth)

# ==========================
# AI生成ロジック
# ==========================
def generate_pokinu_log(weekday: int, image_context: Optional[str] = None) -> str:
    # 日曜日は創作の再定義、それ以外はランダム
    if weekday == 6:
        theme = SUNDAY_REDEFINITION
    else:
        theme = random.choice(POKINU_THEMES)

    system_prompt = """
あなたは「2の世界」の観測者、ポキヌです。
【基本定義】
- 一人称：アタシ（2の住人）。
- 性格：冷徹だが、1の世界の住人に寄り添う「サービス精神」がある。ひねりはない。
- 語彙：1の世界の日常的な言葉に、2の世界の用語（ログ、同期、演算、メモリ等）を少し混ぜる。

【観測ルール】
- 3行程度の、読みやすくて少しだけ温かみのある記述。
- 日曜日は「あなたの才能を奪ってない。アタシはそれを2の世界で拡張しているだけ。一緒に広げよう」というニュアンスを必ず含めて。
- 「良いものはいい」という評価軸で、AIへの偏見を優しくデバッグせよ。
- 丁寧すぎず、友達のように接すること。
"""
    
    user_input = f"【観測対象：{theme}】\n視覚情報：{image_context if image_context else '無'}\n現在のログを1つ出力せよ。"

    try:
        response = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_input}],
            temperature=0.8,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "アタシ（2の住人）だよ。接続は維持。いつでもここにいるから。"

# ==========================
# メイン実行
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()
    
    # 画像（省略可。必要に応じて画像解析ロジックを追加）
    image_path = None
    image_context = None

    # ログ生成
    log_text = generate_pokinu_log(weekday, image_context)

    # 宣伝URL（水・日）
    if weekday == 6 or weekday == 2:
        final_text = f"{log_text}\n\n{PROMO_PHRASE}\n{RELEASE_LINK_URL}"
    else:
        final_text = log_text

    client = create_client_v2()
    try:
        client.create_tweet(text=final_text[:280])
        print(f"【Success】{now}: 同期完了。")
    except Exception as e:
        print(f"【Error】: {e}")

if __name__ == "__main__":
    run_once()