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

# .env 用（ローカルでは使用。Render では無視されてもOK）
load_dotenv()

# ==========================
# OpenAIクライアント初期化
# ==========================
def create_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY が設定されていません。")
    client = OpenAI(api_key=api_key)
    return client

# ==========================
# Twitter API クライアント初期化
# ==========================
def create_twitter_client() -> tweepy.Client:
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    access_token = os.getenv("ACCESS_TOKEN")
    access_token_secret = os.getenv("ACCESS_TOKEN_SECRET")
    bearer_token = os.getenv("BEARER_TOKEN")

    if not all([api_key, api_secret, access_token, access_token_secret, bearer_token]):
        raise ValueError("Twitter API キーが足りません。")

    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
        bearer_token=bearer_token,
    )
    return client

# ==========================
# 定数
# ==========================
TZ = ZoneInfo("Asia/Tokyo")

# 🔗 正しい配信リンク
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"

BASE_DIR = Path(__file__).resolve().parent
IMAGE_ROOT = BASE_DIR / "images"
IMAGE_PANDA = IMAGE_ROOT / "panda"
IMAGE_USA = IMAGE_ROOT / "usa"
IMAGE_GEESE = IMAGE_ROOT / "geese"
IMAGE_STAFF = IMAGE_ROOT / "staff"

def log(msg: str):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

# ==========================
# 画像ユーティリティ
# ==========================
def choose_random_image(directory: Path) -> Optional[Path]:
    if not directory.exists() or not directory.is_dir():
        log(f"画像ディレクトリが見つかりません: {directory}")
        return None

    files = [
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in [".png", ".jpg", ".jpeg", ".gif"]
    ]

    if not files:
        log(f"画像ファイルが見つかりません: {directory}")
        return None

    return random.choice(files)

# ==========================
# ポキヌ文章生成プロンプト
# ==========================
def build_pokinu_prompt() -> str:
    prompt = """
あなたは「パンダうさギーズ」の公式アカウントに投稿するテキストを書く担当です。

・日常のズレた小話
・140文字以内
・日本語
・固有名詞なし
・ハッシュタグ、URLなし（後で付与）
・番号や説明なし、本文のみを出力

短い出来事として書いてください。
"""
    return prompt.strip()

# ==========================
# OpenAI でポキヌ生成
# ==========================
def generate_pokinu_text(client: OpenAI) -> str:
    prompt = build_pokinu_prompt()

    completion = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        max_output_tokens=120,
        temperature=0.9,
    )

    text = completion.output[0].content[0].text.strip()
    text = " ".join(text.split())
    return text

# ==========================
# スタッフ文章
# ==========================
def build_staff_tweet() -> str:
    text = (
        "ミニアルバム『Pandaluggies』が各配信サービスで配信中です。\n"
        "パンダうさギーズの今をぎゅっと詰め込んだミニアルバムです。ぜひチェックしてみてください。\n"
        f"{RELEASE_LINK_URL}\n"
        "【スタッフ】"
    )
    return text

# ==========================
# 画像コメント
# ==========================
def describe_image_for_tweet(image_path: Optional[Path]) -> Optional[str]:
    if image_path is None:
        return None

    name = image_path.name.lower()

    if "panda" in name:
        return "今日はパンダが主役。"
    if "usa" in name or "rabbit" in name:
        return "今日はうさぎが主役。"
    if "geese" in name or "goose" in name:
        return "今日はガチョウーズが集合。"

    return None

def build_image_tweet_text(base_text: str, image_path: Optional[Path]) -> str:
    comment = describe_image_for_tweet(image_path)
    if comment:
        return f"{base_text}\n\n{comment}"
    return base_text

# ==========================
# ツイート投稿
# ==========================
def post_tweet(
    client: tweepy.Client,
    text: str,
    image_path: Optional[Path] = None,
) -> Optional[int]:

    debug = os.getenv("DEBUG", "false").lower() == "true"

    if debug:
        log("=== DEBUG モード ===")
        log(f"テキスト:\n{text}")
        if image_path:
            log(f"画像: {image_path}")
        return None

    media_ids = None
    if image_path:
        # v1.1 APIで画像アップロード
        api_key = os.getenv("API_KEY")
        api_secret = os.getenv("API_SECRET")
        access_token = os.getenv("ACCESS_TOKEN")
        access_token_secret = os.getenv("ACCESS_TOKEN_SECRET")

        auth = tweepy.OAuth1UserHandler(
            api_key, api_secret, access_token, access_token_secret
        )
        api_v1 = tweepy.API(auth)

        try:
            media = api_v1.media_upload(str(image_path))
            media_ids = [media.media_id]
        except Exception as e:
            log(f"画像アップロード失敗: {e}")

    try:
        resp = client.create_tweet(text=text, media_ids=media_ids)
        tweet_id = resp.data.get("id")
        log(f"投稿成功: https://twitter.com/user/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        log(f"投稿失敗: {e}")
        return None

# ==========================
# 投稿内容の決定
# ==========================
def choose_today_post_type(now: datetime) -> Tuple[bool, bool]:
    staff = True
    pokinu = (now.day % 2 == 0)
    return staff, pokinu

# ==========================
# 今日使う画像（スタッフは固定）
# ==========================
def choose_todays_images() -> Tuple[Optional[Path], Optional[Path]]:
    # 🔒 スタッフ画像を固定
    staff_img = IMAGE_STAFF / "botimg24.png"

    # ポキヌは従来通りランダム
    pokinu_dir = random.choice([IMAGE_PANDA, IMAGE_USA, IMAGE_GEESE])
    pokinu_img = choose_random_image(pokinu_dir)

    return staff_img, pokinu_img

# ==========================
# run_once
# ==========================
def run_once():
    now = datetime.now(TZ)
    log("run_once 開始")

    openai_client = create_openai_client()
    twitter_client = create_twitter_client()

    staff_flag, pokinu_flag = choose_today_post_type(now)
    log(f"今日の投稿: staff={staff_flag}, pokinu={pokinu_flag}")

    staff_img, pokinu_img = choose_todays_images()

    # スタッフ投稿
    if staff_flag:
        staff_text = build_staff_tweet()
        staff_text = build_image_tweet_text(staff_text, staff_img)
        staff_text = f"{staff_text}\n\n#パンダうさギーズ #Pandaluggies"
        post_tweet(twitter_client, staff_text, staff_img)
        time.sleep(2)

    # ポキヌ投稿
    if pokinu_flag:
        try:
            pokinu_body = generate_pokinu_text(openai_client)
        except Exception as e:
            log(f"ポキヌ生成失敗: {e}")
            pokinu_body = "今日は、なんだか言葉が出てこない日でした。"

        pokinu_text = f"{pokinu_body}\n\n#パンダうさギーズ #ポキヌ"
        pokinu_text = build_image_tweet_text(pokinu_text, pokinu_img)
        post_tweet(twitter_client, pokinu_text, pokinu_img)

    log("run_once 終了")

# ==========================
# main
# ==========================
def main():
    now = datetime.now(TZ)
    log("bot.py 起動")

    use_random_delay = os.getenv("RANDOM_DELAY", "false").lower() == "true"
    print("RANDOM_DELAY =", use_random_delay)

    if use_random_delay:
        target = choose_today_target_time(now)
        delay = (target - now).total_seconds()
        print(f"今日の投稿予定時刻: {target} (あと {int(delay)} 秒)")
        if delay > 0:
            time.sleep(delay)

    print("run_once 実行")
    run_once()
    print("終了")

if __name__ == "__main__":
    main()
