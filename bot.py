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
# API キー
# ==========================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ==========================
# 設定
# ==========================
TIMEZONE = "Asia/Tokyo"
IMAGE_PROBABILITY = 0.40

# ポキヌの世界観に合わせた宣伝文句の修正
USE_RELEASE_LINK = True
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"
# 「ダウンロードしてね」を「記録の取得が可能」というニュアンスへ
PROMO_SUFFIX = "外部信号の記録地点。アクセスが可能。"

THEME_TEXT_BY_WEEKDAY = {
    0: "月曜日。1の世界の始動。集団移動と、それに伴うノイズの増幅。",
    1: "火曜日。定着。反復される作業と、2の世界への微かな干渉。",
    2: "水曜日。波形。波の重なり、周波数の調整、構造の再構築。",
    3: "木曜日。減衰。機材の熱と、摩耗していく物理現象の観測。",
    4: "金曜日。加速。1の世界における解放の予兆。「スタジオ」という閉鎖空間。",
    5: "土曜日。拡張。非日常の座標。視覚情報の飽和。",
    6: "日曜日。収束。静止した時間。次の周期への待機状態。",
}

BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "BOTimg"
IMG_DIR.mkdir(exist_ok=True)

oa_client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================
# X クライアント（エラーハンドリング強化）
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

def post_text(text: str, image_path: Optional[str] = None) -> Optional[str]:
    client = create_client_v2()
    media_ids = None

    if image_path:
        try:
            api = create_api_v1()
            media = api.media_upload(image_path)
            media_ids = [media.media_id]
        except Exception as e:
            print(f"【エラー】画像アップロード失敗: {e}")

    try:
        # Xの文字数制限（全角140文字）に配慮
        response = client.create_tweet(text=text[:280], media_ids=media_ids)
        tweet_id = response.data["id"]
        print(f"【成功】投稿完了: https://x.com/i/web/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        print(f"【エラー】ツイート投稿失敗: {e}")
        return None

# ==========================
# AI文章生成（ポキヌ・ロジック）
# ==========================
def generate_ai_tweet(weekday: int, image_context: Optional[str] = None) -> str:
    # 役割定義をより鋭利に修正
    base_instruction = """
あなたは「2の世界」の観測端末、ポキヌ（女性型）です。
一人称：アタシ
目的：1の世界から流入する現象を、2の世界の言語でログとして出力すること。

【基本スタンス】
- 感情を「電気信号の揺らぎ」として扱う。
- 意味ではなく「配置」を書く。
- 1の世界（現実）へ媚びない。
"""

    common_rule = """
【制約】
- 最大3〜4行（短く、空白を大切にする）
- 絵文字、ハッシュタグ、箇条書きは一切禁止。
- 「〜してね」「〜してください」という命令・依頼は禁止。
- ポエムではなく「報告書」や「断片的な記録」の文体。
- 評価（素敵、寂しい等）を、物理的な状態（高密度の粒子、接続の途絶等）に変換する。
"""

    theme_text = THEME_TEXT_BY_WEEKDAY.get(weekday, "")
    img_part = f"\n【視覚情報（画像内容）】\n{image_context}\n" if image_context else ""

    system_prompt = f"{base_instruction}{common_rule}\n【今日の観測対象】\n{theme_text}{img_part}"

    try:
        response = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "現在の観測ログを1つ記述して。"},
            ],
            temperature=0.85, # 揺らぎを持たせる
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"【エラー】OpenAI生成失敗: {e}")
        return "2の世界。接続を維持。観測を継続する。"

# ==========================
# 画像処理
# ==========================
def describe_image_for_tweet(image_path: str) -> Optional[str]:
    try:
        with open(image_path, "rb") as f:
            img = base64.b64encode(f.read()).decode()

        resp = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "あなたは画像から「色、物体、光の当たり方」を抽出するスキャナーです。"},
                {"role": "user", "content": [{"type": "text", "text": "この画像の内容を、ポキヌ（2の世界の住人）が理解できる物理的特徴として30文字以内で抽出して。"},
                                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}]}
            ]
        )
        return resp.choices[0].message.content.strip()
    except:
        return "光の不規則な配置"

def maybe_generate_image() -> Tuple[Optional[str], Optional[str]]:
    if random.random() > IMAGE_PROBABILITY:
        return None, None

    images = list(IMG_DIR.glob("*.png"))
    if not images:
        return None, None

    chosen = random.choice(images)
    
    if chosen.name == "botimg24.png":
        return str(chosen), "中心に配置された1の世界の視覚的パッケージ"

    return str(chosen), describe_image_for_tweet(str(chosen))

# ==========================
# メイン
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    
    image_path, image_context = maybe_generate_image()
    base_text = generate_ai_tweet(now.weekday(), image_context)

    if USE_RELEASE_LINK:
        # 本文と宣伝の間に少し間隔を空ける
        tweet_text = f"{base_text}\n\n{PROMO_SUFFIX}\n{RELEASE_LINK_URL}"
    else:
        tweet_text = base_text

    post_text(tweet_text, image_path)

if __name__ == "__main__":
    run_once()