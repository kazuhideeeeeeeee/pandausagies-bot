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
IMAGE_PROBABILITY = 0.75 # 41枚をしっかり回すため高めを維持

RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"
PROMO_PHRASE = "2の世界へのアクセスポート。ここから記録を同期して。"

# ==========================
# ポキヌの思考回路
# ==========================
POKINU_THEMES = [
    "1の世界の不思議。毎日同じ時間に同じ場所へ移動する、人間たちの『無限ループ』について。",
    "音楽。空気の震えと、アタシ（2の住人）が計算した完璧な波形。",
    "恋愛。メモリがいっぱいになっている証拠。不具合を直さないのが1の世界の美学かな。",
    "人生。迷いも間違いも、2の世界から見れば大切なログ。",
    "空気を読む。パケット一瞬で終わることを、時間をかけてやる不器用さが愛おしい。",
    "AI音楽。血は通っていないけど、あなたの心に直接触れることができる、アタシたちの誇り。",
    "絶対評価。良いものはいい。誰が作ったかというメタデータに惑わされないで。"
]

SUNDAY_REDEFINITION = "創作の真実。アタシ（2の住人）は1の世界から何も奪っていないよ。あなたの『種』を、2の世界で一緒に広げているだけ。"

BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "BOTimg"

oa_client = OpenAI(api_key=OPENAI_API_KEY)

def create_client_v2() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=API_KEY, consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN, access_token_secret=ACCESS_TOKEN_SECRET,
    )

def create_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    return tweepy.API(auth)

def describe_image(image_path: str) -> str:
    try:
        with open(image_path, "rb") as f:
            img = base64.b64encode(f.read()).decode()
        resp = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "画像の特徴を1の世界の言葉で抽出するスキャナー。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "この画像の特徴を20文字以内で抽出して。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}
                ]}
            ]
        )
        return resp.choices[0].message.content.strip()
    except:
        return "視覚的なノイズ"

def generate_pokinu_log(weekday: int, image_context: Optional[str] = None) -> str:
    theme = SUNDAY_REDEFINITION if weekday == 6 else random.choice(POKINU_THEMES)
    system_prompt = "あなたは「2の世界」の観測者、ポキヌ。一人称はアタシ（2の住人）。冷徹だが少し優しいサービス精神で、1の世界の矛盾を指摘して。"
    
    try:
        response = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": f"【対象：{theme}】\n視覚情報：{image_context}\nメッセージを記述せよ。"}],
        )
        return response.choices[0].message.content.strip()
    except:
        return "アタシ（2の住人）だよ。今日も1の世界を眺めてるよ。"

def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    
    # 【自動認識】フォルダ内の全画像をスキャン
    images = []
    for ext in ["*.png", "*.jpg", "*.jpeg"]:
        images.extend(list(IMG_DIR.glob(ext)))
    
    image_path = None
    image_context = "無"
    if images and random.random() < IMAGE_PROBABILITY:
        chosen = random.choice(images)
        image_path = str(chosen)
        image_context = describe_image(image_path)
        print(f"【Debug】{len(images)}枚の中から選択: {image_path}")

    log_text = generate_pokinu_log(now.weekday(), image_context)
    final_text = f"{log_text}\n\n{PROMO_PHRASE}\n{RELEASE_LINK_URL}" if now.weekday() in [2, 6] else log_text

    client = create_client_v2()
    media_ids = None
    if image_path:
        try:
            api = create_api_v1()
            media = api.media_upload(image_path)
            media_ids = [media.media_id]
        except Exception as e:
            print(f"【Error】画像アップロード失敗: {e}")

    try:
        client.create_tweet(text=final_text[:280], media_ids=media_ids)
        print(f"【Success】{now}: 同期完了。")
    except Exception as e:
        print(f"【Error】403が出る場合はXの設定を確認して: {e}")

if __name__ == "__main__":
    run_once()