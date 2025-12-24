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

# 画像は金・日のみ使用（確率は低め）
IMAGE_PROBABILITY = 0.4

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
# 曜日ごとの生成モード
# ==========================
def get_mode_by_weekday(weekday: int) -> str:
    # 月0 火1 水2 木3 金4 土5 日6
    if weekday == 0:
        return "diary"              # 月：日記
    elif weekday in (1, 3):
        return "one_line_question"  # 火・木：一行の問い
    elif weekday == 2:
        return "two_world_log"      # 水：2の世界の話
    elif weekday == 4:
        return "photo_short"        # 金：写真＋短文
    elif weekday == 5:
        return "recording_log"      # 土：レコーディング
    elif weekday == 6:
        return "photo_soft"         # 日：写真＋静か
    return "one_line_question"

# ==========================
# AI生成（モード別）
# ==========================
def generate_text(mode: str, image_context: Optional[str]) -> str:
    system_prompt = """
あなたは「2の世界」の観測端末、ポキヌ。
一人称は「アタシ」。

アタシは1の世界を理解しない。
評価・説得・主張は行わない。

ただ、影響と更新を受け取り、
ログとして配置する。

共通ルール：
- 絵文字・ハッシュタグ・命令形は禁止
- 共感を求めない
- 意味を断定しない
- ロボットすぎず、人間にならない
"""

    mode_prompt = {
        "diary": """
月曜日。
2〜4行。
1の世界の空気に少し寄る。
日記のようだが、感情は断定しない。
""",
        "one_line_question": """
1行のみ。
問いで終わる。
答えを求めない。
""",
        "two_world_log": """
2〜4行。
2の世界の構造や状態のみ。
問いは禁止。
""",
        "photo_short": """
写真あり前提。
1〜2行。
距離は近いが、触れない。
""",
        "recording_log": """
2〜3行。
2の世界のレコーディング中ログ。
何をしているかは書かない。
""",
        "photo_soft": """
写真あり前提。
2〜3行。
静かで、夜に耐える文。
問いは最大1つ。
"""
    }

    user_prompt = "ログを生成せよ。"
    if image_context:
        user_prompt += f"\n視覚情報：{image_context}"

    try:
        res = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt + mode_prompt.get(mode, "")},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.85,
        )
        return res.choices[0].message.content.strip()
    except:
        return "アタシは接続を維持している。更新はまだ来ていない。"

# ==========================
# 画像選択（金・日のみ）
# ==========================
def maybe_pick_image(use_image: bool) -> Tuple[Optional[str], Optional[str]]:
    if not use_image:
        return None, None

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
    weekday = now.weekday()
    mode = get_mode_by_weekday(weekday)

    use_image = weekday in (4, 6)  # 金・日
    image_path, image_context = maybe_pick_image(use_image)

    text = generate_text(mode, image_context)

    # 火・土のみ外部参照を付与
    if weekday in (1, 5):
        text = f"{text}\n\n{PROMO_PHRASE}\n{RELEASE_LINK_URL}"

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
        client.create_tweet(text=text[:280], media_ids=media_ids)
        print(f"{now} : 投稿完了 ({mode})")
    except Exception as e:
        print("投稿失敗:", e)

if __name__ == "__main__":
    run_once()
