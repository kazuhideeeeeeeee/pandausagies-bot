# bot.py
# Panda Usa G's / ポキヌ X Bot
# Render Cron想定：起動 → 投稿 → 終了
# 方針：
# - 人が見てる前提
# - ズレは置く、笑わせに行かない
# - 毎回問いかけは1つまで
# - 「アタシ今」固定は禁止
# - 時間帯でトーン変更
# - 曜日によって投稿数が変わる日あり

import os
import random
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import tweepy
from openai import OpenAI
from dotenv import load_dotenv

# ==========================
# env
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
oa = OpenAI(api_key=OPENAI_API_KEY)
MODEL = "gpt-4o-mini"

# ==========================
# X client
# ==========================
def client_v2():
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
    )

# ==========================
# 運用ルール
# ==========================
# 0=Mon ... 6=Sun
POST_RULES = {
    0: {"posts": 1},  # 月
    1: {"posts": 1},  # 火
    2: {"posts": 2},  # 水（2本・時間でタッチ変える）
    3: {"posts": 1},  # 木（短め）
    4: {"posts": 2},  # 金（テンション上下）
    5: {"posts": 1},  # 土
    6: {"posts": 1},  # 日
}

# ==========================
# システムプロンプト（核心）
# ==========================
SYSTEM_PROMPT = """
あなたは大学生バンド「パンダうさギーズ」のボーカル、ポキヌ。
一人称は「アタシ」。

性格：
・感情は強い
・照れ屋
・構ってほしいが正面では言わない
・判断が雑
・自分を下げるが自虐しない
・ズレた行動をそのまま置く

文章ルール：
・1〜4行
・毎回「アタシ今」で始めない
・笑わせようとしない（ズレを置くだけ）
・問いかけは1つまで
・説教、営業、説明は禁止
・「今日は」「昨日は」禁止
・天気禁止
・曖昧語（そこ・あれ等）の多用禁止

目的：
人が見てる前で、ちょっと変なことを言う。
読んだ人が返したくなる余地を残す。
"""

# ==========================
# 時間帯トーン
# ==========================
def time_tone(now: datetime) -> str:
    h = now.hour
    if 5 <= h < 11:
        return "朝。判断がまだ定まってない感じ。"
    if 11 <= h < 17:
        return "昼。行動が先に出る。"
    if 17 <= h < 22:
        return "夜。感情が強め。"
    return "深夜。思考が飛ぶ。"

# ==========================
# テキスト生成
# ==========================
def generate_text(now: datetime) -> str:
    tone = time_tone(now)

    user_prompt = f"""
状況：
{tone}

条件：
・感情と行動をズラす
・最後は問いかけ（1つ）
・人に話しかけている感じ

1本だけツイートを書いて。
"""

    res = oa.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.95,
        max_tokens=180,
    )

    text = res.choices[0].message.content.strip()

    # 行整理
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines[:4])[:280]

# ==========================
# 投稿
# ==========================
def post(text: str):
    cli = client_v2()
    cli.create_tweet(text=text)

# ==========================
# メイン
# ==========================
def run():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()
    rule = POST_RULES.get(weekday, {"posts": 1})

    for _ in range(rule["posts"]):
        text = generate_text(now)
        print("POST:\n", text)
        post(text)

if __name__ == "__main__":
    run()
