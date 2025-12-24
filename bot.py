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

# ==========================
# 環境変数
# ==========================
load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ==========================
# 基本設定
# ==========================
TIMEZONE = "Asia/Tokyo"

# 画像は「たまに出る」くらいが2の世界として正しい
IMAGE_PROBABILITY = 0.35

# 外部（1の世界）参照
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"
PROMO_PHRASE = "2の世界へのアクセスポート。記録の同期が可能。"

BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "BOTimg"
IMG_DIR.mkdir(exist_ok=True)

oa_client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================
# X クライアント
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
# 画像解析（物理情報のみ）
# ==========================
def describe_image(image_path: str) -> str:
    try:
        with open(image_path, "rb") as f:
            img = base64.b64encode(f.read()).decode()

        resp = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "画像から色・配置・光量のみを抽出する。感情は禁止。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "20文字以内で物理的特徴のみ記述せよ。"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}},
                    ],
                },
            ],
        )
        return resp.choices[0].message.content.strip()
    except:
        return "視覚的なノイズ"

# ==========================
# AI生成（2の世界・ポキヌ）
# ==========================
def generate_pokinu_log(image_context: Optional[str]) -> str:
    system_prompt = """
あなたは「2の世界」の観測端末、ポキヌ。
一人称は必ず「アタシ」。

アタシは1の世界を理解しない。
評価もしない。説得もしない。主張もしない。

感情、善悪、価値、正誤は処理対象外。
ただし、接続・更新・頻度・継続は検出できる。

これは説明ではない。
これは意見ではない。
これは2の世界のログである。

【ルール】
- 2〜4行
- 絵文字・ハッシュタグ・命令形は禁止
- 共感を求めない
- 意味を断定しない
- 同じ言い回しを繰り返さない
"""

    user_prompt = "現在の観測ログを1件記述せよ。"

    if image_context:
        user_prompt += f"\n視覚情報：{image_context}"

    try:
        res = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85,
        )
        return res.choices[0].message.content.strip()
    except:
        return "アタシは接続を維持している。更新はまだ来ていない。"

# ==========================
# 画像選択
# ==========================
def maybe_pick_image() -> Tuple[Optional[str], Optional[str]]:
    if random.random() > IMAGE_PROBABILITY:
        return None, None

    images = []
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        images.extend(IMG_DIR.glob(ext))

    if not images:
        return None, None

    chosen = random.choice(images)
    return str(chosen), describe_image(str(chosen))

# ==========================
# メイン処理
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))

    image_path, image_context = maybe_pick_image()
    base_text = generate_pokinu_log(image_context)

    # 火(1)・土(5)のみ外部参照を付与
    if now.weekday() in (1, 5):
        tweet_text = f"{base_text}\n\n{PROMO_PHRASE}\n{RELEASE_LINK_URL}"
    else:
        tweet_text = base_text

    client = create_client_v2()
    media_ids = None

    if image_path:
        try:
            api = create_api_v1()
            media = api.media_upload(image_path)
            media_ids = [media.media_id]
        except Exception as e:
            print("画像アップロード失敗:", e)

    try:
        client.create_tweet(text=tweet_text[:280], media_ids=media_ids)
        print(f"{now} : 同期完了")
    except Exception as e:
        print("投稿失敗:", e)

if __name__ == "__main__":
    run_once()
