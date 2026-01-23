# bot.py
# GPT提案・実験運用版
# 目的：破綻せず、嘘を吐かず、短文が出やすい状態を作る

import os
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import tweepy
from openai import OpenAI
from dotenv import load_dotenv

# =========================
# 環境変数
# =========================
load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TIMEZONE = "Asia/Tokyo"
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"

# =========================
# 固定URL（これ以外は出さない）
# =========================
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"

# =========================
# OpenAI
# =========================
client = OpenAI(api_key=OPENAI_API_KEY)

MODEL = "gpt-4o-mini"

# =========================
# スロット判定（超ざっくり）
# =========================
def detect_slot(now: datetime) -> str:
    h = now.hour
    if 18 <= h <= 21:
        return "practice"
    if h >= 22 or h <= 1:
        return "night"
    return "day"

# =========================
# 投稿モード
# =========================
def pick_mode() -> str:
    # 宣伝は少なめ
    r = random.random()
    if r < 0.15:
        return "promo"
    return "normal"

# =========================
# GPTプロンプト
# =========================
def build_prompt(slot: str, mode: str) -> str:
    base = f"""
あなたはXに短文を投稿する。
説明しない。盛らない。嘘を作らない。

条件：
- 日本語
- 1〜2行
- 25〜90文字
- 絵文字、ハッシュタグ禁止
- 地名・日付・ライブ告知は禁止
- 「だけ」「それだけ」「音だけ残る」などの詩的逃げは禁止
- 普通すぎる近況報告は禁止
- 意味のわからない比喩は禁止
"""

    if slot == "practice":
        base += "\n話題は手元、音、準備、集中のズレ。"
    elif slot == "night":
        base += "\n話題は疲れ、甘いもの、風呂、眠気。"
    else:
        base += "\n話題は生活の一瞬。"

    if mode == "promo":
        base += f"""
最後の行にURLを置いていい。
主張は「ダウンロード」だけ。
URL：
{RELEASE_LINK_URL}
"""
    else:
        base += "\nURLは出さない。"

    return base.strip()

# =========================
# テキスト生成
# =========================
def generate_text(slot: str, mode: str) -> str:
    prompt = build_prompt(slot, mode)

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "投稿文を書いて"}
            ],
            temperature=0.8,
            max_tokens=120,
        )
        text = resp.choices[0].message.content.strip()
    except Exception:
        return "今日は何も書けなかった。"

    # 念のため暴走防止
    text = text.replace("？", "")
    text = text[:200]

    return text

# =========================
# X 投稿
# =========================
def post_to_x(text: str):
    if DRY_RUN:
        print("[DRY_RUN]")
        print(text)
        return

    client_v2 = tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
    )

    client_v2.create_tweet(text=text)

# =========================
# メイン
# =========================
def main():
    now = datetime.now(ZoneInfo(TIMEZONE))
    slot = detect_slot(now)
    mode = pick_mode()

    print(f"[BOOT] {now.isoformat()} slot={slot} mode={mode}")

    text = generate_text(slot, mode)
    post_to_x(text)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Renderでstatus 1連発を避ける
        print("[ERROR]", e)
