import os
import json
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
# API キー（環境変数から読む）
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
IMAGE_PROBABILITY = 0.25   # 画像付きにする確率（25%くらい）
USE_RELEASE_LINK = False   # リリース後に True にするとリンク付きツイートになる
RELEASE_LINK_URL = "https://example.com"  # 後で正式な配信リンクに差し替え
MEMBERS = ["ポキヌ", "チョビア", "ラムヌ", "ボーロコ", "グミナ"]

# 「毎日時間をずらしたい」ための投稿時間ウィンドウ（24h）
# 例：18〜20時、22〜24時のどこかにランダムで投稿
TIME_WINDOWS = [
    (18, 20),  # 18:00〜19:59
    (22, 24),  # 22:00〜23:59
]

# ==========================
# 自動エンゲージメント設定
# ==========================
ENABLE_LIKE_BACK = True          # いいね返し
ENABLE_DISCOVERY_LIKES = True    # 関連ユーザーへのいいね撒き
ENABLE_SMART_REPLIES = True      # 自然リプ（ごく少なめ）

LIKE_BACK_LIMIT_PER_RUN = 10         # 1回の実行で返す「いいね」の最大数
DISCOVERY_LIKE_LIMIT_PER_RUN = 10    # 関連ツイートへ押す「いいね」の最大数
REPLY_LIMIT_PER_RUN = 2              # 1回の実行で送るリプの最大数

# 画像保存先（すでにある BOTimg フォルダを利用）
BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "BOTimg"
IMG_DIR.mkdir(exist_ok=True)

# 前回使った手動画像を保存するファイル
LAST_IMAGE_FILE = BASE_DIR / "last_image.json"

# OpenAI クライアント（APIキーは環境変数 OPENAI_API_KEY から自動で読む）
oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()

# ==========================
# X クライアント（v2）＆ 画像アップロード用API（v1.1）
# ==========================
def create_client_v2() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
    )


def create_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(
        API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET
    )
    return tweepy.API(auth)


def get_my_user_id(client: tweepy.Client) -> str:
    """自分のユーザーIDを取得"""
    me = client.get_me()
    return str(me.data.id)


# ==========================
# テキスト + 画像投稿
# ==========================
def post_text(text: str, image_path: Optional[str] = None) -> Optional[str]:
    client = create_client_v2()

    media_ids = None
    if image_path is not None:
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
        print("URL: https://x.com/i/web/status/" + tweet_id)
        return tweet_id
    except Exception as e:
        print("テキスト投稿でエラー:", e)
        return None


# ==========================
# 前回使った手動画像の保存・読み込み
# ==========================
def load_last_manual_image() -> Optional[str]:
    if not LAST_IMAGE_FILE.exists():
        return None
    try:
        with LAST_IMAGE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("last_manual_image")
    except Exception:
        return None


def save_last_manual_image(path: str) -> None:
    try:
        with LAST_IMAGE_FILE.open("w", encoding="utf-8") as f:
            json.dump({"last_manual_image": path}, f)
    except Exception:
        pass


# ==========================
# BOTimg から「前回と違う」画像を選ぶ
# ==========================
def choose_manual_image() -> Optional[str]:
    """
    BOTimg フォルダから png 画像を取得。
    直前に使った画像はなるべく避ける。
    """
    images = list(IMG_DIR.glob("*.png"))
    if not images:
        return None

    last_path = load_last_manual_image()

    # 2枚以上あれば、前回と違うものを優先
    candidates = [p for p in images if str(p) != last_path]
    if not candidates:
        candidates = images

    chosen = random.choice(candidates)
    save_last_manual_image(str(chosen))
    print(f"手動画像を選択: {chosen}")
    return str(chosen)


# ==========================
# 画像をざっくり解析して「雰囲気メモ」をもらう
# ==========================
def describe_image_for_tweet(image_path: str) -> Optional[str]:
    """
    画像をざっくり解析して、
    ・何人くらい写っているか
    ・場所（街/スタジオ/部屋 など）
    ・雰囲気（元気/のんびり/しっとり など）
    を 50文字以内の日本語でまとめてもらう。
    """
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        resp = oa_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "あなたは画像の雰囲気を短く要約するアシスタントです。",
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "この画像に写っている人数・場所・空気感を、"
                                "女子大学生バンドのSNS担当向けに、50文字以内の日本語でまとめてください。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/png;base64," + image_b64
                            },
                        },
                    ],
                },
            ],
            max_tokens=120,
        )
        desc = resp.choices[0].message.content.strip()
        print("画像の説明:", desc)
        return desc
    except Exception as e:
        print("画像解析でエラー:", e)
        return None


# ================================
# AIでツイート文を生成（画像コンテキスト対応）
# ================================
def generate_ai_tweet(mode: str, image_context: Optional[str] = None) -> str:
    """
    mode:
        "daily" -> 普段の日常ツイート
        "band"  -> 音楽のスタジオ・バンド練習ツイート

    image_context:
        一緒に貼る写真の説明（人柄・場所・雰囲気・状況 などの説明）※なくてもOK
    """

    # それ以外が来たらとりあえず daily に直す
    if mode not in ("daily", "band"):
        mode = "daily"

    # -----------------------------
    # ベース文言
    # -----------------------------
    if mode == "band":
        base_instruction = """
あなたは日本の大学生バンド「パンダうさギーズ」のSNS担当です。
全国の友だちに、これからスタジオ練習/録音/本番のあったバンド活動あゆりの
一言ツイートを作ってください。
"""
    else:
        base_instruction = """
あなたは日本の大学生バンド「パンダうさギーズ」のSNS担当です。
メンバーの日常が、 自分のアカウントからつぶやいているような
自然な一言ツイートを書いてください。
"""

    # -----------------------------
    # 共通ルール
    # -----------------------------
    common_rule = """
【絶対守るルール】
- 文章は大学生が話している感じの日本語で書く。
- 大学生っぽいワード（「モチベ爆上げ」「〇ちカワ」「バブみ」など）は使わない。
- SNSの文っぽさが出る言い回しはOK（「エモい」「すき」「わかりみ」など）。
- ですが、あまりにもふざけすぎてしまう言い回し（「おはよう」「朝から」「今夜は」など）は使わない。
- 長文にしない。1〜2文で。
- 絵文字は1〜2個まで。量は多くなくていい。
- 読む人が嫌な気持ちにならないこと。

【内容のルール】
- 「新しいフレーズが浮かんだ」「フレーズ思いついた瞬間」など、
  作曲の話ばかりにならないようにする。
- 作曲ネタは “ときどき出すスペシャル話” くらいの頻度のつもりで書く。
- それ以外にも、次のような話題を自由に使ってよい。
  例）スタジオ練習の様子 / ライブへのワクワク / メンバー同士の会話 /
      学校・バイト帰りの気持ち / 好きなバンド・音楽の話 /
      楽器や機材の話 / 移動中の景色や天気のこと など。
- 画像があるときは、まず「画像に写っていそうな雰囲気や気持ち」を
  1番大事にして、それに合う一言を考える。
- 音楽の話や日常の一言ツイートをメインにする。
- たまにで良いので、「フォローしてくれたらうれしい」など、
  軽くフォローをお願いする一文を入れてもよい。ただし毎回は書かない。
"""

    # -----------------------------
    # 画像情報を付け足す場合
    # -----------------------------
    if image_context:
        img_part = (
            "\n【画像付き情報】\n"
            "このツイートには、次のような雰囲気の写真が一緒に投稿されます:\n"
            f"{image_context}\n"
            "この写真の人物や空気感を想像しながら書いてください。\n"
        )
    else:
        img_part = ""

    # -----------------------------
    # プロンプト生成
    # -----------------------------
    system_prompt = base_instruction + common_rule + img_part
    user_prompt = "上の条件を守って、今日のテーマに合ったツイートを1つだけ書いてください。"

    # -----------------------------
    # ChatGPT API 呼び出し
    # -----------------------------
    response = oa_client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=120,
        temperature=0.9,
    )

    text = response.choices[0].message.content.strip()

    # 文字数が長すぎたら切る（270文字まで）
    if len(text) > 270:
        text = text[:270]

    return text


def add_signature(text: str) -> str:
    member = random.choice(MEMBERS)
    return f"{text}\n- {member}"


# ==========================
# 画像生成（平日=手動 / 金曜=AI）＋ コンテキスト返却
# ==========================
def maybe_generate_image(mode: str, now: datetime) -> Tuple[Optional[str], Optional[str]]:
    """
    画像パスと、その画像に基づく「雰囲気説明」文字列を返す。
    return: (image_path, image_context)

    - 金曜 (weekday == 4) は AI 画像のみ
    - それ以外の曜日は BOTimg 内の手動画像のみ
    - 全体として IMAGE_PROBABILITY の確率で画像付き
    """
    if random.random() > IMAGE_PROBABILITY:
        return None, None

    # 金曜日は AI 画像だけ
    if now.weekday() == 4:
        # スタジオ or 猫/犬 をランダム
        theme = random.choice(["studio", "pet"])

        if theme == "studio":
            img_prompt = (
                "polaroid-style instant film photo, "
                "small Japanese rehearsal studio, cables and amps on the floor, "
                "guitars and bass leaning on the wall, "
                "slightly messy but cozy, real photo, soft flash, grainy film texture"
            )
            image_context = "スタジオでの練習風景をポラロイドで撮った写真"
        else:
            animal = random.choice(["street cat", "friend's dog"])
            img_prompt = (
                f"polaroid-style instant film photo of a {animal}, "
                "shot in Japan, candid everyday moment, "
                "slightly faded colors, soft flash, grainy film, real snapshot"
            )
            image_context = "道でばったり会った猫や友だちの犬をポラロイドで撮ったみたいな写真"

        try:
            img_response = oa_client.images.generate(
                model="gpt-image-1",
                prompt=img_prompt,
                n=1,
                size="1024x1024",
                quality="high",
            )

            image_b64 = img_response.data[0].b64_json
            image_bytes = base64.b64decode(image_b64)

            filename = f"pandausagies_band_{now.strftime('%Y%m%d_%H%M%S')}.png"
            image_path = IMG_DIR / filename

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            print(f"AI画像生成成功(金曜): {image_path} / theme={theme}")
            return str(image_path), image_context

        except Exception as e:
            print("AI画像生成でエラー:", e)
            return None, None

    # 金曜以外は BOTimg からランダムに選ぶ
    manual_path = choose_manual_image()
    if manual_path is None:
        return None, None

    # 画像の内容に合わせて説明文を作る
    image_context = describe_image_for_tweet(manual_path)
    return manual_path, image_context


# ==========================
# 今日の「投稿時刻」をウィンドウからランダムに決める
# ==========================
def choose_today_target_time(now: datetime) -> datetime:
    """
    TIME_WINDOWS のどれか1つを選び、その中でランダムな時刻を返す。
    すでにその時間を過ぎていたら翌日扱い。
    """
    window = random.choice(TIME_WINDOWS)
    start_hour, end_hour = window

    hour = random.randint(start_hour, end_hour - 1)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)

    target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    return target


# ==========================
# いいね返し機能
# ==========================
def like_back_recent_likers() -> None:
    """自分のツイートにいいねしてくれた人の最新ツイートに、いいね返しをする。"""
    if not ENABLE_LIKE_BACK:
        return

    client = create_client_v2()
    my_id = get_my_user_id(client)
    liked_count = 0

    try:
        tweets_resp = client.get_users_tweets(
            id=my_id,
            max_results=5,
            tweet_fields=["id"],
        )
    except Exception as e:
        print("いいね返し: 自分のツイート取得でエラー:", e)
        return

    if not tweets_resp.data:
        return

    for my_tweet in tweets_resp.data:
        try:
            likers_resp = client.get_liking_users(
                id=my_tweet.id,
                max_results=20,
            )
        except Exception as e:
            print("いいね返し: liker取得でエラー:", e)
            continue

        if not likers_resp.data:
            continue

        for user in likers_resp.data:
            if liked_count >= LIKE_BACK_LIMIT_PER_RUN:
                return

            try:
                user_tweets = client.get_users_tweets(
                    id=user.id,
                    max_results=5,
                    exclude=["retweets", "replies"],
                    tweet_fields=["id"],
                )
            except Exception as e:
                print("いいね返し: 相手ツイート取得でエラー:", e)
                continue

            if not user_tweets.data:
                continue

            target_tweet_id = user_tweets.data[0].id

            try:
                client.like(target_tweet_id)
                liked_count += 1
                print(f"いいね返し: user={user.id} tweet={target_tweet_id}")
            except Exception as e:
                print("いいね返し: likeでエラー:", e)
                continue


# ==========================
# 関連ユーザーへの「いいね撒き」
# ==========================
def like_discovery_tweets() -> None:
    """関連ワードでツイート検索して、自然な範囲でいいねを押す。"""
    if not ENABLE_DISCOVERY_LIKES:
        return

    client = create_client_v2()
    query = (
        "バンド 女子 OR ガールズバンド OR 学生バンド OR ライブハウス "
        "-is:retweet lang:ja"
    )

    try:
        search_resp = client.search_recent_tweets(
            query=query,
            max_results=DISCOVERY_LIKE_LIMIT_PER_RUN * 2,
            tweet_fields=["id", "author_id"],
        )
    except Exception as e:
        print("ディスカバリーいいね: searchでエラー:", e)
        return

    if not search_resp.data:
        return

    liked = 0
    for tweet in search_resp.data:
        if liked >= DISCOVERY_LIKE_LIMIT_PER_RUN:
            break

        try:
            client.like(tweet.id)
            liked += 1
            print(f"ディスカバリーいいね: tweet={tweet.id}")
        except Exception as e:
            print("ディスカバリーいいね: likeでエラー:", e)
            continue


# ==========================
# 自然な短文リプライ生成
# ==========================
def generate_short_reply(original_text: str) -> str:
    """
    相手のツイートに対する、50文字以内の短いリプを作る。
    失礼にならず、宣伝もしない。軽い感想だけ。
    """
    system_prompt = """
あなたはバンド「パンダうさギーズ」のSNS担当です。
相手のツイートに、感じの良い一言だけ日本語で返信してください。

【絶対守るルール】
- 50文字以内。
- 1文だけ。顔文字は1つまで。
- 相手をほめたり、共感したりする内容にする。
- 自分の宣伝（フォローしてね、配信中です 等）は書かない。
- 上から目線や説教っぽい言い方はしない。
"""

    user_prompt = f"元のツイート:「{original_text}」\n\nこれに対する短い返信文を1つだけ書いてください。"

    resp = oa_client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=80,
        temperature=0.8,
    )

    text = resp.choices[0].message.content.strip()
    if len(text) > 60:
        text = text[:60]
    return text


# ==========================
# 自然リプ（控えめ）
# ==========================
def smart_replies() -> None:
    """関連ツイートの一部にだけ、短い自然リプを送る。"""
    if not ENABLE_SMART_REPLIES:
        return

    client = create_client_v2()
    query = (
        "バンド 女子 OR ガールズバンド OR 学生バンド "
        "-is:retweet lang:ja"
    )

    try:
        search_resp = client.search_recent_tweets(
            query=query,
            max_results=20,
            tweet_fields=["id", "text", "author_id"],
        )
    except Exception as e:
        print("スマートリプ: searchでエラー:", e)
        return

    if not search_resp.data:
        return

    replied = 0
    for tweet in search_resp.data:
        if replied >= REPLY_LIMIT_PER_RUN:
            break

        original_text = tweet.text

        # URLだけのツイートなどは避ける
        if "http://" in original_text or "https://" in original_text:
            continue

        try:
            reply_text = generate_short_reply(original_text)
            if not reply_text:
                continue

            client.create_tweet(
                text=reply_text,
                reply={"in_reply_to_tweet_id": tweet.id},
            )
            replied += 1
            print(f"スマートリプ: reply to tweet={tweet.id}")
        except Exception as e:
            print("スマートリプ: リプ送信でエラー:", e)
            continue


# ==========================
# メイン処理
# ==========================
def run_once() -> None:
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()  # 月曜=0, 金曜=4
    mode = "band" if weekday == 4 else "daily"

    # まず画像（必要なら）を決めて、その情報を使ってツイート文を作る
    image_path, image_context = maybe_generate_image(mode, now)

    # ベースのツイート文をAIで生成
    base_text = generate_ai_tweet(mode, image_context=image_context)

    # メンバーの誰かの署名を付ける
    signed_text = add_signature(base_text)

    # リリース後はリンクを足す（リンクは署名の下につける）
    if USE_RELEASE_LINK and RELEASE_LINK_URL:
        tweet_text = f"{signed_text}\n{RELEASE_LINK_URL}"
    else:
        tweet_text = signed_text

    print("生成されたツイート文:", tweet_text)
    print("画像:", image_path)

    # ツイート投稿
    post_text(tweet_text, image_path=image_path)


if __name__ == "__main__":
    now = datetime.now(ZoneInfo(TIMEZONE))

    # 環境変数 RANDOM_DELAY=true にすると、毎回ランダムな時間まで待ってから投稿
    use_random_delay = os.getenv("RANDOM_DELAY", "false").lower() == "true"

    if use_random_delay:
        target = choose_today_target_time(now)
        delay = (target - now).total_seconds()
        print(f"今日の投稿予定時刻: {target} (あと {int(delay)} 秒)")

        if delay > 0:
            time.sleep(delay)

    # ① 通常ツイート
    run_once()

    # ② エンゲージメント系（控えめ）
    like_back_recent_likers()
    like_discovery_tweets()
    smart_replies()
