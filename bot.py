import os
import random
import time
import logging
from datetime import datetime
from typing import List, Optional

import tweepy

# ==========================
# ログ設定
# ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)

# ==========================
# 環境変数
# ==========================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
logger.info(f"DEBUG API_KEY is None? -> {API_KEY is None}")

if not API_KEY or not API_SECRET or not ACCESS_TOKEN or not ACCESS_TOKEN_SECRET:
    logger.error("Twitter API の環境変数が足りません。")
    raise SystemExit("Twitter API の環境変数が足りません。")

# ==========================
# Twitter クライアント
# ==========================
auth = tweepy.OAuth1UserHandler(
    API_KEY,
    API_SECRET,
    ACCESS_TOKEN,
    ACCESS_TOKEN_SECRET,
)

api = tweepy.API(auth)

client = tweepy.Client(
    consumer_key=API_KEY,
    consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_TOKEN_SECRET,
)

# ==========================
# 定数
# ==========================
RELEASE_LINK_URL = "https://linkco.re/XXXXXXXX"  # 実際のURLに差し替え

IMAGE_BASE_DIR = "images"
PANDA_DIR = os.path.join(IMAGE_BASE_DIR, "panda")
USA_DIR = os.path.join(IMAGE_BASE_DIR, "usa")
GEESE_DIR = os.path.join(IMAGE_BASE_DIR, "geese")
STAFF_DIR = os.path.join(IMAGE_BASE_DIR, "staff")

STAFF_POST_PER_DAY = 1
POKINU_POST_INTERVAL_DAYS = 2

# ==========================
# ユーティリティ
# ==========================
def choose_random_image(directory: str) -> Optional[str]:
    if not os.path.isdir(directory):
        logger.warning(f"画像ディレクトリが見つかりません: {directory}")
        return None

    files = [
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))
    ]

    if not files:
        logger.warning(f"画像ファイルが見つかりません: {directory}")
        return None

    return random.choice(files)


def upload_media(image_path: str) -> Optional[str]:
    try:
        media = api.media_upload(image_path)
        return media.media_id_string
    except Exception as e:
        logger.exception(f"画像アップロードに失敗しました: {e}")
        return None


def post_tweet(text: str, image_path: Optional[str] = None) -> Optional[int]:
    if DEBUG:
        logger.info("=== DEBUG モードのためツイートしません ===")
        logger.info(f"ツイート内容:\n{text}")
        if image_path:
            logger.info(f"添付画像: {image_path}")
        return None

    media_ids = None
    if image_path:
        media_id = upload_media(image_path)
        if media_id:
            media_ids = [media_id]

    try:
        if media_ids:
            tweet = client.create_tweet(text=text, media_ids=media_ids)
        else:
            tweet = client.create_tweet(text=text)

        tweet_id = tweet.data["id"]
        logger.info(f"投稿成功: https://twitter.com/user/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        logger.exception(f"投稿に失敗しました: {e}")
        return None

# ==========================
# ポキヌ文章
# ==========================
POKINU_TWEETS: List[str] = [
    "ホームで立ってたら突然ランドセルの子に話しかけられて靴ひも踏んでた。",
    "自販機で小銭落として、おじさんが一緒に探してくれた。",
    "ガリガリ君当たり出たけど交換しそびれて財布の守り神になった。",
    "駅で傘忘れてたらサラリーマンが押し付けるように渡して去った。",
    "ラーメン3分待つ間にSNS見てたら12分になった。",
    "エレベーターで挨拶されただけで昇進した気分になった。",
    "スーパーのBGMでおばあちゃんがステップ踏んでた。",
    "メモに『こうなる未来は嫌だ』とだけ書いてあった。",
    "自転車で向かい風に勝てなくて見えない敵と戦ってる気分に。",
    "洗濯してたら隣のおばさんに『今日も戦ってますね』と言われた。",
]

def build_pokinu_tweet() -> str:
    return random.choice(POKINU_TWEETS) + "\n\n#パンダうさギーズ #ポキヌ"

# ==========================
# スタッフ文章（修正版）
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
def describe_image_for_tweet(image_path: str) -> Optional[str]:
    if not image_path:
        return None

    filename = os.path.basename(image_path)

    if "panda" in filename.lower():
        return "今日はパンダが主役。"
    if "usa" in filename.lower():
        return "今日はうさぎが主役。"
    if "geese" in filename.lower():
        return "今日はガチョウーズが登場。"

    return None


def build_image_text(base_text: str, image_path: Optional[str]) -> str:
    comment = describe_image_for_tweet(image_path)
    if comment:
        return f"{base_text}\n\n{comment}"
    return base_text

# ==========================
# 投稿の種類
# ==========================
class PostType:
    STAFF = "staff"
    POKINU = "pokinu"

def should_post_pokinu(today: datetime) -> bool:
    return today.toordinal() % POKINU_POST_INTERVAL_DAYS == 0

def decide_today_post_types(today: Optional[datetime] = None) -> List[str]:
    if today is None:
        today = datetime.now()

    types = [PostType.STAFF]
    if should_post_pokinu(today):
        types.append(PostType.POKINU)

    return types

# ==========================
# メイン実行
# ==========================
def run_once():
    today = datetime.now()
    post_types = decide_today_post_types(today)

    # スタッフ投稿
    if PostType.STAFF in post_types:
        staff_text = build_staff_tweet()
        staff_img = choose_random_image(STAFF_DIR) or choose_random_image(PANDA_DIR)
        tweet_text = build_image_text(staff_text, staff_img)
        logger.info("スタッフ投稿します。")
        post_tweet(tweet_text, staff_img)

    # ポキヌ投稿
    if PostType.POKINU in post_types:
        txt = build_pokinu_tweet()
        img = choose_random_image(random.choice([PANDA_DIR, USA_DIR, GEESE_DIR]))
        tweet_text = build_image_text(txt, img)
        logger.info("ポキヌ投稿します。")
        post_tweet(tweet_text, img)

def main():
    logger.info("===== pandausagies-bot start =====")
    try:
        run_once()
    except Exception as e:
        logger.exception(f"致命的エラー: {e}")
    logger.info("===== pandausagies-bot end =====")

if __name__ == "__main__":
    main()
