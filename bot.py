import os
import base64
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from zoneinfo import ZoneInfo
import tweepy
from openai import OpenAI
from dotenv import load_dotenv

# .env 用（ローカルでだけ使われる。Render では無視されてもOK）
load_dotenv()

# ==========================
# API キー
# ==========================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

print("DEBUG API_KEY is None? ->", API_KEY is None)

# ==========================
# 設定
# ==========================
TIMEZONE = "Asia/Tokyo"

IMAGE_PROBABILITY = 0.40  # 40%

USE_RELEASE_LINK = True
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"
PROMO_SUFFIX = "そして配信中！ ダウンロードしてね！"

# 曜日ごとの投稿時間帯
TIME_WINDOWS_BY_WEEKDAY = {
    0: [(19, 22)],
    1: [(19, 22)],
    2: [(19, 22)],
    3: [(19, 22)],
    4: [(18, 21)],
    5: [(13, 16), (20, 23)],
    6: [(13, 16), (20, 23)],
}

# 曜日テーマ
THEME_TEXT_BY_WEEKDAY = {
    0: "月曜日。学校や授業、通学の気分など。詩が浮かぶのは月曜だけOK。",
    1: "火曜日。バイト、放課後、友だちとの帰り道など。",
    2: "水曜日。曲作り・アレンジ・フレーズの話をしていい日。",
    3: "木曜日。楽器・機材・音作りなどの話題。",
    4: "金曜日。バンド活動全体の話。『スタジオ』という単語を使えるのは金曜だけ（1回のみ）。",
    5: "土曜日。出かけた話、街の雰囲気、イベントなど。",
    6: "日曜日。一週間の振り返りやゆっくりした話題。",
}

BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "BOTimg"
IMG_DIR.mkdir(exist_ok=True)

oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()

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
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    return tweepy.API(auth)

# ==========================
# 投稿
# ==========================
def post_text(text: str, image_path: Optional[str] = None) -> Optional[str]:
    client = create_client_v2()

    media_ids = None
    if image_path:
        try:
            api = create_api_v1()
            media = api.media_upload(image_path)
            media_ids = [media.media_id]
            print(f"画像アップロード成功: {image_path}")
        except Exception as e:
            print("画像アップロードでエラー:", e)

    try:
        response = client.create_tweet(text=text, media_ids=media_ids)
        tweet_id = response.data["id"]
        print("投稿成功:", text)
        print(f"URL: https://x.com/i/web/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        print("テキスト投稿でエラー:", e)
        return None


# ==========================
# 生理ポスト（月1）
# ==========================
PERIOD_STATE_FILE = BASE_DIR / "period_state.json"

def load_period_state():
    if not PERIOD_STATE_FILE.exists():
        return {"last_post": None}
    try:
        import json
        with open(PERIOD_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"last_post": None}

def save_period_state(date_str: str):
    import json
    with open(PERIOD_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_post": date_str}, f)

def needs_period_post(now: datetime) -> bool:
    state = load_period_state()
    last = state.get("last_post")
    if last is None:
        return True
    last_date = datetime.fromisoformat(last)
    return not (last_date.year == now.year and last_date.month == now.month)

def generate_period_post() -> str:
    texts = [
        "生理きてお腹の中で誰か暴れてるみたい。今日は静かにいく日。",
        "朝からお腹が重い。毎回慣れないけど、ゆっくりしたい日だな。",
        "生理でお腹ぐーっと痛くて、授業中ほぼ前かがみだった。ホットカイロ偉すぎ。",
    ]
    return random.choice(texts)

# ==========================
# ポキヌ（二日に一回）
# ==========================
POKINU_STATE_FILE = BASE_DIR / "pokinu_state.json"

def load_pokinu_state():
    if not POKINU_STATE_FILE.exists():
        return {"last_post": None}
    try:
        import json
        with open(POKINU_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"last_post": None}

def save_pokinu_state(date_str: str):
    import json
    with open(POKINU_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_post": date_str}, f)

def needs_pokinu_post(now: datetime) -> bool:
    state = load_pokinu_state()
    last = state.get("last_post")
    if last is None:
        return True
    last_date = datetime.fromisoformat(last)
    return (now - last_date).total_seconds() >= 48 * 3600


# ==========================
# スタッフ（毎日）
# ==========================
def generate_staff_post() -> str:
    return (
        "ミニアルバムは現在各ストアで配信中です。\n"
        "短い期間で仕上げた作品ですが、メンバーのこだわりが詰まっています。\n"
        "よろしければチェックしてみてください。\n"
        f"{RELEASE_LINK_URL}\n"
        "【スタッフ】"
    )


# ==========================
# AI 文章生成（ポキヌ）
# ==========================
def generate_ai_tweet(weekday: int, image_context: Optional[str] = None) -> str:

    base_instruction = """
あなたは大学生バンド「パンダうさギーズ」のボーカル「ポキヌ」です。
あなた自身のアカウントで自然な日常のつぶやきを書きます。
署名は付けません。
"""

    common_rule = """
【形式】
- 1〜5行で書く。
- 絵文字は0〜2個まで。
- テンプレSNS語は禁止（エモい/尊い/おつかれ〜等）。

【ポキヌの文体】
- 日常の中の小さな出来事を具体的に入れる。
- 少しズレた視点や比喩はOKだが意味不明はNG。
- 夕焼け/空/天気の話は禁止。
- 唐突に詩にならない。

【話題の制限】
- 曲作りの話は水曜日だけ。
- 歌詞・詩が浮かんだ話は月曜日だけ。
- 「スタジオ」という単語を使えるのは金曜だけ（最大1回）。
"""

    theme_text = THEME_TEXT_BY_WEEKDAY.get(weekday, "")
    theme_part = f"\n【今日のテーマ】\n{theme_text}\n"

    img_part = ""
    if image_context:
        img_part = (
            "\n【写真の雰囲気】\n"
            f"{image_context}\n"
            "写真の気配を優先して書いてください。\n"
        )

    system_prompt = base_instruction + common_rule + theme_part + img_part

    resp = oa_client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "条件を守ってポキヌのつぶやきを1つ書いてください。"},
        ],
        max_tokens=200,
        temperature=0.9,
    )

    text = resp.choices[0].message.content.strip()
    lines = [l for l in text.split("\n") if l.strip()]
    return "\n".join(lines[:5])


# ==========================
# 画像処理
# ==========================
def describe_image_for_tweet(image_path: str) -> Optional[str]:
    try:
        with open(image_path, "rb") as f:
            image_b = f.read()
        image_b64 = base64.b64encode(image_b).decode()

        resp = oa_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "写真の雰囲気を短く説明します。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "写真の雰囲気を50文字以内で説明してください。"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64}},
                    ],
                },
            ],
        )
        return resp.choices[0].message.content.strip()
    except:
        return None


def maybe_generate_image(now: datetime) -> Tuple[Optional[str], Optional[str]]:
    if random.random() > IMAGE_PROBABILITY:
        return None, None

    jacket = IMG_DIR / "botimg24.png"
    if jacket.exists():
        return str(jacket), "アルバムのジャケット写真"

    imgs = list(IMG_DIR.glob("*.png"))
    if not imgs:
        return None, None

    chosen = random.choice(imgs)
    return str(chosen), describe_image_for_tweet(str(chosen))


# ==========================
# 時間帯決定
# ==========================
def choose_today_target_time(now: datetime) -> datetime:
    weekday = now.weekday()
    windows = TIME_WINDOWS_BY_WEEKDAY.get(weekday, [(19, 22)])
    start, end = random.choice(windows)

    hour = random.randint(start, end - 1)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)

    target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


# ==========================
# メイン
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()

    # --------------------------
    # ① スタッフ投稿（毎日）
    # --------------------------
    staff_text = generate_staff_post()
    print("スタッフ投稿:", staff_text)
    post_text(staff_text)

    # --------------------------
    # ② ポキヌ投稿（二日に一回）
    # -
