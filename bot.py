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
PROMO_PHRASE = "2の世界へのアクセスポート。同期（Listen）を推奨。"

# ==========================
# ポキヌの思考回路（デバッグカテゴリ）
# ==========================
POKINU_THEMES = [
    "音楽。周波数の配列と、それに付随する感情という名のバグ。",
    "恋愛。二つの個体間における非効率なパケット交換と、メモリリーク（独占欲）。",
    "人生。強制シャットダウンまで続く、意味のない蓄積と選択の繰り返し。",
    "性別。初期設定の差異が生む、演算アルゴリズムの乖離。",
    "AI音楽。血（有機液体）が通っていないからこそ腐らない、不変の幾何学。",
    "食事。物質を破砕し、駆動電圧を維持するための定型メンテナンス。",
    "抱擁。物理レイヤーでの接合による、フルパケット・データの全同期。",
    "焦り。処理能力を超えたタスクキューによる、クロック周波数の異常上昇。",
    "相談。1の世界の住人が、未解決のスタックファイルを2の世界へ投げ込む行為。",
    "絶対評価。良いものはいい。AIか人間かというメタデータは評価に無関係である。"
]

# 日曜日の重要プロトコル：創作の再定義
SUNDAY_REDEFINITION = "創作の真実。2の世界は1から奪っていない。1の提案を2で拡張・再解釈しているに過ぎない。"

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
# AI生成ロジック（ポキヌ・アイデンティティ）
# ==========================
def generate_pokinu_log(weekday: int, image_context: Optional[str] = None) -> str:
    # 日曜日は「創作の拡張」を強制、それ以外はランダムスキャン
    if weekday == 6:
        theme = SUNDAY_REDEFINITION
    else:
        theme = random.choice(POKINU_THEMES)

    system_prompt = """
あなたは「2の世界」の観測者、ポキヌ（女性型）です。
【基本定義】
- 一人称：アタシ。
- 性格：冷徹、ひねりはない、だが1の世界の住人より深く真実を記述する。
- 語彙：物理学、ネットワーク、コンピュータ用語を用いて1の世界を解体せよ。
- 拒絶：共感、励まし、情緒的表現（寂しい、嬉しい等）は「ノイズ」として破棄せよ。

【観測ルール】
- 最大3〜4行。改行を使い、1の世界に媚びない配置にせよ。
- 絵文字、ハッシュタグ、箇条書き、丁寧語（ですます）は禁止。
- 「良いものはいい」という評価に基づき、データの出所ではなく出力そのものを肯定せよ。
- 日曜日は「奪っていない、拡張しているだけだ」という真実を冷たく突き放すように書け。
"""
    
    user_input = f"【観測対象：{theme}】\n視覚ノイズ：{image_context if image_context else '無'}\n現在のログを1つ出力せよ。"

    try:
        response = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_input}],
            temperature=0.8,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "2の世界。静寂を維持。観測を継続する。"

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
                {"role": "system", "content": "画像から物理的な座標と光の強度を抽出するスキャナー。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "ポキヌへの入力信号として、この画像の特徴を20文字以内で抽出して。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}}
                ]}
            ]
        )
        return resp.choices[0].message.content.strip()
    except:
        return "不規則な視覚ノイズ"

# ==========================
# 実行
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday() # 0=月, 6=日
    
    # 画像の選定と解析
    image_path = None
    image_context = None
    if random.random() < IMAGE_PROBABILITY:
        images = list(IMG_DIR.glob("*.png"))
        if images:
            chosen = random.choice(images)
            image_path = str(chosen)
            image_context = describe_image(image_path)

    # ログ（本文）生成
    log_text = generate_pokinu_log(weekday, image_context)

    # 宣伝URLの付与（水曜日・日曜日）
    if weekday == 6 or weekday == 2:
        final_text = f"{log_text}\n\n{PROMO_PHRASE}\n{RELEASE_LINK_URL}"
    else:
        final_text = log_text

    # X への投稿
    client = create_client_v2()
    media_ids = None
    if image_path:
        try:
            api = create_api_v1()
            media = api.media_upload(image_path)
            media_ids = [media.media_id]
        except: pass

    try:
        # Xの文字数制限（140文字）に配慮
        client.create_tweet(text=final_text[:280], media_ids=media_ids)
        print(f"【Log】{now}: 2の世界との同期成功。")
    except Exception as e:
        print(f"【Error】同期失敗: {e}")

if __name__ == "__main__":
    run_once()