import os
import random
import time
import logging
from datetime import datetime, timedelta
from typing import List, Optional

import tweepy
from PIL import Image

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
BEARER_TOKEN = os.getenv("BEARER_TOKEN")

# デバッグフラグ（Render の環境変数で制御）
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

logger.info(f"DEBUG: {DEBUG}")

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

# v2 用クライアント（画像アップロードなどは v1.1 を使用）
client = tweepy.Client(
    consumer_key=API_KEY,
    consumer_secret=API_SECRET,
    access_token=ACCESS_TOKEN,
    access_token_secret=ACCESS_TOKEN_SECRET,
)

# ==========================
# 定数
# ==========================

# リリース URL（固定）
RELEASE_LINK_URL = "https://linkco.re/XXXXXXXX"  # 実際のURLに差し替え

# 画像ディレクトリ
IMAGE_BASE_DIR = "images"
PANDA_DIR = os.path.join(IMAGE_BASE_DIR, "panda")
USA_DIR = os.path.join(IMAGE_BASE_DIR, "usa")
GEESE_DIR = os.path.join(IMAGE_BASE_DIR, "geese")
STAFF_DIR = os.path.join(IMAGE_BASE_DIR, "staff")

# ポスト頻度
STAFF_POST_PER_DAY = 1           # スタッフ投稿：毎日1回
POKINU_POST_INTERVAL_DAYS = 2    # ポキヌ：2日に1回

# ==========================
# ユーティリティ
# ==========================
def choose_random_image(directory: str) -> Optional[str]:
    """指定ディレクトリからランダムに画像パスを1つ返す"""
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
    """画像を Twitter にアップロードして media_id を返す"""
    try:
        media = api.media_upload(image_path)
        return media.media_id_string
    except Exception as e:
        logger.exception(f"画像アップロードに失敗しました: {e}")
        return None


def post_tweet(text: str, media_path: Optional[str] = None) -> Optional[int]:
    """テキスト（と任意で画像）をツイートする"""

    if DEBUG:
        logger.info("=== DEBUG モードのためツイートしません ===")
        logger.info(f"ツイート内容:\n{text}")
        if media_path:
            logger.info(f"添付画像: {media_path}")
        return None

    media_ids = None
    if media_path:
        media_id = upload_media(media_path)
        if media_id:
            media_ids = [media_id]

    try:
        if media_ids:
            tweet = client.create_tweet(text=text, media_ids=media_ids)
        else:
            tweet = client.create_tweet(text=text)

        tweet_id = tweet.data["id"]
        logger.info(f"ツイート投稿成功: https://twitter.com/user/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        logger.exception(f"ツイート投稿に失敗しました: {e}")
        return None


# ==========================
# テキスト生成（ポキヌ）
# ==========================
POKINU_TWEETS: List[str] = [
    # ここに 10 個のポキヌ用ツイートを入れておく
    "ホームで立ってたら突然ランドセルの子に「その…」って話しかけられて、なんだろうと思ったら靴ひも踏んづけてた。",
    "自販機の前で小銭を落として、拾おうとしたら知らないおじさんも一緒にしゃがんで探してくれた。あの一瞬の共同作業なんだったんだろう。",
    "コンビニでガリガリ君買ったら当たりが出た。でもなんとなく交換しそびれて、財布の中で神様みたいに祀ってある。",
    "傘を忘れて駅で立ち尽くしてたら、後ろのサラリーマンが「どうせタクシーなんで」と言って傘を押し付けるように渡して去っていった。",
    "カップラーメンにお湯入れて3分待つ間にSNS開いたら、気づいたら12分たってて、麺の方が人生経験積んだ顔してた。",
    "エレベーターで二人きりになった人が降り際に「よい一日を」と言ってくれた。行き先ボタン押しただけなのに、ちょっと昇進した気分になった。",
    "スーパーで流れてるBGMに合わせて、野菜コーナーのおばあちゃんが小さくステップ踏んでた。キャベツがディスコボールに見えてきた。",
    "スマホのメモに『こうなる未来は嫌だ』って書いてあって、何のことかわからないけど、とりあえず今日は早く寝ることにした。",
    "自転車こいでたら向かい風が強すぎて、「これもう見えない敵と腕相撲してるだろ」と思いながら必死で帰った。",
    "洗濯物を干してたら、となりのベランダから「今日も戦ってますねえ」とおばさんに声かけられた。靴下一足ずつが敵兵みたいに見えてきた。",
]

def build_pokinu_tweet() -> str:
    """ポキヌ用ツイートをランダムに1つ返す"""
    base_text = random.choice(POKINU_TWEETS)
    hashtag = "\n\n#パンダうさギーズ #ポキヌ"
    return base_text + hashtag


# ==========================
# テキスト生成（スタッフ）
# ==========================
def build_staff_tweet() -> str:
    """
    スタッフによる定番の宣伝テキスト。
    事実だけを書くようにして、勝手な脚色はしない。
    """
    text = (
        "ミニアルバム『Pandaluggies』が各配信サービスで配信中です。\n"
        "パンダうさギーズの今をぎゅっと詰め込んだミニアルバムです。ぜひチェックしてみてください。\n"
        f"{RELEASE_LINK_URL}\n"
        "【スタッフ】"
    )
    return text


# ==========================
# 画像説明
# ==========================
def describe_image_for_tweet(image_path: str) -> Optional[str]:
    """
    画像を見て一言コメントを返す（将来拡張用。今はファイル名ベース）
    """
    if not image_path:
        return None

    filename = os.path.basename(image_path)

    if "panda" in filename.lower():
        return "今日はパンダが主役。"
    if "usa" in filename.lower():
        return "今日はうさぎが主役。"
    if "geese" in filename.lower():
        return "今日はガチョウーズが集結。"

    return None


def build_image_tweet_text(base_text: str, image_path: Optional[str]) -> str:
    """
    ベースのテキストに、画像からの一言コメントを足す
    """
    comment = describe_image_for_tweet(image_path) if image_path else None
    if comment:
        return f"{base_text}\n\n{comment}"
    return base_text


# ==========================
# ポスト種別の管理
# ==========================
class PostType:
    STAFF = "staff"
    POKINU = "pokinu"


def should_post_pokinu(today: datetime) -> bool:
    """
    ポキヌを投稿する日かどうか。
    2日に1回、偶数日をポキヌの日とする簡易ロジック。
    """
    return today.toordinal() % POKINU_POST_INTERVAL_DAYS == 0


def decide_today_post_types(today: Optional[datetime] = None) -> List[str]:
    """
    今日投稿すべき投稿種別のリストを返す。
    - スタッフ投稿：毎日1本
    - ポキヌ：2日に1本
    """
    if today is None:
        today = datetime.now()

    post_types: List[str] = [PostType.STAFF]

    if should_post_pokinu(today):
        post_types.append(PostType.POKINU)

    logger.info(f"本日の投稿種別: {post_types}")
    return post_types


# ==========================
# メイン処理
# ==========================
def run_once():
    """
    1回分の実行。
    - 今日投稿すべき投稿の種類を決定
    - スタッフ投稿（テキスト＋画像）
    - ポキヌ（テキスト＋画像）※必要な日のみ
    """

    today = datetime.now()
    post_types = decide_today_post_types(today)

    # スタッフ投稿
    if PostType.STAFF in post_types:
        staff_text = build_staff_tweet()
        staff_image = choose_random_image(STAFF_DIR) or choose_random_image(PANDA_DIR)
        tweet_text = build_image_tweet_text(staff_text, staff_image)
        logger.info("スタッフ投稿を行います。")
        post_tweet(tweet_text, staff_image)

    # ポキヌ投稿（ある日のみ）
    if PostType.POKINU in post_types:
        pokinu_text = build_pokinu_tweet()
        # パンダ / うさ / ガチョウ からランダムで1枚
        pokinu_image_dirs = [PANDA_DIR, USA_DIR, GEESE_DIR]
        random_dir = random.choice(pokinu_image_dirs)
        pokinu_image = choose_random_image(random_dir)
        tweet_text = build_image_tweet_text(pokinu_text, pokinu_image)
        logger.info("ポキヌ投稿を行います。")
        post_tweet(tweet_text, pokinu_image)


def main():
    """
    Render の cron から叩かれる想定のメイン関数。
    1回実行したら終了。
    """
    logger.info("===== pandausagies-bot 実行開始 =====")
    try:
        run_once()
    except Exception as e:
        logger.exception(f"致命的なエラーが発生しました: {e}")
    finally:
        logger.info("===== pandausagies-bot 実行終了 =====")


if __name__ == "__main__":
    main()
