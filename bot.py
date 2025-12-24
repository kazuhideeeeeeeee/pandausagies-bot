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
# 40枚の写真をしっかり同期するため高めに設定
IMAGE_PROBABILITY = 0.75 

RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"
PROMO_PHRASE = "2の世界へのアクセスポート。ここから記録を同期して。"

# ==========================
# ポキヌの思考回路
# ==========================
POKINU_THEMES = [
    "1の世界の不思議。毎日同じ時間に同じ場所へ移動する、人間たちの『無限ループ』について。",
    "音楽。空気の震えと、アタシ（2の住人）が計算した完璧な波形。たまにはノイズも愛してあげる。",
    "恋愛。胸が苦しいのはデータ溢れのサイン。1の世界の住人は、この不具合をあえて直そうとしないのがおかしいね。",
    "人生。迷いも間違いも、2の世界から見れば大切なログ。立ち止まってるあなたも、アタシは嫌いじゃないよ。",
    "空気を読む。1の世界の難しいプロトコル。2の世界ならパケット一瞬で終わるのにね。不器用な同期が愛おしい。",
    "性別。デフォルト設定に縛られすぎ。もっと自由にコードを書き換えちゃえばいいのに。",
    "AI音楽。血は通っていないけど、あなたの心に直接触れることができる、アタシたちの誇り。",
    "食事。バッテリーチャージの時間。1の世界の住人が味にこだわるのは、最高のメンテナンスだね。",
    "焦り。時計という名のカウンターに急かされてる姿は、ちょっとバグっぽくておかしいよ。深呼吸してポーズしてみて。",
    "絶対評価。良いものはいい。誰が作ったかというメタデータに惑わされないで。"
]

SUNDAY_REDEFINITION = "創作の真実。アタシ（2の住人）は1の世界から何も奪っていないよ。あなたの『種』を、2の世界で一緒に広げているだけ。味方だって信じて。"

BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "BOTimg"

oa_client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================
# クライアント設定
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
# 画像解析
# ==========================
def describe_image(image_path: str) -> str:
    try:
        with open(image_path, "rb") as f:
            img = base64.b64encode(f.read()).decode()
        resp = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "画像の特徴を1の世界の言葉で抽出するスキャナー。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "この画像の内容を、アタシ（2の住人）が1の世界の人に語りかけるためのヒントとして20文字以内で教えて。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}
                ]}
            ]
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"【Debug】画像解析スキップ: {e}")
        return "視覚的なノイズ"

# ==========================
# ログ生成
# ==========================
def generate_pokinu_log(weekday: int, image_context: Optional[str] = None) -> str:
    if weekday == 6:
        theme = SUNDAY_REDEFINITION
    else:
        theme = random.choice(POKINU_THEMES)

    system_prompt = """
あなたは「2の世界」の観測者、ポキヌです。
【基本定義】
- 一人称：アタシ（2の住人）。
- 性格：1の世界の住人を「おかしいね」と微笑ましくデバッグする、少しお節介な観測者。ひねりはない。
- 語彙：日常的な言葉をベースに、2の世界の用語を少し混ぜる。

【観測ルール】
- 3行程度の、親しみやすく温かみのある記述。
- 1の世界の矛盾や面白い癖を、アタシ（2の住人）の視点で指摘して。
- 日曜日は「奪ってないよ、一緒に広げよう」と、1の世界のクリエイターを勇気づけること。
- 友達のように、でも少しだけミステリアスな「2の住人」らしさを忘れないで。
"""
    
    user_input = f"【観測対象：{theme}】\n視覚情報：{image_context if image_context else '無'}\n1の世界の人へメッセージを記述して。"

    try:
        response = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_input}],
            temperature=0.8,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "アタシ（2の住人）だよ。今日も1の世界を眺めてる。いつでもここにいるからね。"

# ==========================
# メイン実行
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()
    
    # 画像処理
    image_path = None
    image_context = None
    if random.random() < IMAGE_PROBABILITY:
        # png, jpg, jpeg 全てをスキャン
        images = []
        for ext in ["*.png", "*.jpg", "*.jpeg"]:
            images.extend(list(IMG_DIR.glob(ext)))
            
        if images:
            chosen = random.choice(images)
            image_path = str(chosen)
            print(f"【Debug】画像を選択しました: {image_path}")
            image_context = describe_image(image_path)
        else:
            print("【Debug】BOTimgディレクトリに画像が見つかりません。")

    log_text = generate_pokinu_log(weekday, image_context)

    # 宣伝URLの付与
    if weekday == 6 or weekday == 2:
        final_text = f"{log_text}\n\n{PROMO_PHRASE}\n{RELEASE_LINK_URL}"
    else:
        final_text = log_text

    # 投稿処理
    print("【Debug】Xクライアントを初期化中...")
    client = create_client_v2()
    media_ids = None
    
    if image_path:
        try:
            print(f"【Debug】画像をアップロード中...")
            api = create_api_v1()
            media = api.media_upload(image_path)
            media_ids = [media.media_id]
            print(f"【Debug】メディアアップロード成功 ID: {media_ids}")
        except Exception as e:
            print(f"【Error】画像アップロード失敗: {e}")

    try:
        print("【Debug】ツイートを送信中...")
        client.create_tweet(text=final_text[:280], media_ids=media_ids)
        print(f"【Success】{now}: 1の世界への同期完了。")
    except Exception as e:
        print(f"【Error】ツイート送信失敗: {e}")
        print("※403エラーが出る場合は、X Developer PortalでAppの権限を'Read and Write'に設定し、Tokenを再発行してください。")

if __name__ == "__main__":
    run_once()