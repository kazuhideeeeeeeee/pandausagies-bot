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

# 画像を付ける確率
IMAGE_PROBABILITY = 0.40

# ⭐ 配信リンクと宣伝文
USE_RELEASE_LINK = True
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"
PROMO_SUFFIX = "そして配信中！ ダウンロードしてね！"

# 曜日ごとの投稿時間ウィンドウ
# 0=月曜, 1=火曜, ... 6=日曜
# (start_hour, end_hour) は「start〜end-1時台」のどこか
TIME_WINDOWS_BY_WEEKDAY = {
    0: [(19, 22)],              # 月: 19〜21時台
    1: [(19, 22)],              # 火
    2: [(19, 22)],              # 水
    3: [(19, 22)],              # 木
    4: [(18, 21)],              # 金: 少し早め
    5: [(13, 16), (20, 23)],    # 土: 昼 or 夜
    6: [(13, 16), (20, 23)],    # 日: 昼 or 夜
}

# 曜日ごとの「話題テーマ」説明
THEME_TEXT_BY_WEEKDAY = {
    0: "月曜日。学校や授業、通学のこと、月曜日ならではの気分について。歌詞やことば、詩がふっと浮かんだ話は月曜日だけOK。",
    1: "火曜日。バイトや放課後、友だちとの帰り道、日常のちょっとした出来事について。",
    2: "水曜日。曲作りやフレーズ、コード進行、アレンジ、練習の工夫など、音楽づくりそのものについて。曲作りの話をしていいのは水曜日だけ。",
    3: "木曜日。楽器や機材、音作りのこだわり、小さな発見について。",
    4: "金曜日。バンド活動全体のこと、リハーサルや本番前後の気持ちなど。『スタジオ』という単語を使ってよいのは金曜日だけで、文章中に1回まで。",
    5: "土曜日。街に出かけたこと、イベント、買い物、友だちとの時間など外の世界の雰囲気について。",
    6: "日曜日。一週間を振り返る気持ち、のんびりした時間、明日からまたがんばろうと思えるような穏やかな話題について。",
}

# 画像フォルダ
BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "BOTimg"
IMG_DIR.mkdir(exist_ok=True)

# OpenAI クライアント
oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()

# ==========================
# X クライアント
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


# ==========================
# 投稿
# ==========================
def post_text(text: str, image_path: Optional[str] = None) -> Optional[str]:
    client = create_client_v2()

    media_ids = None
    if image_path:
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
# AI 文章生成（ポキヌ人格＋曜日ルール）
# ==========================
def generate_ai_tweet(
    weekday: int,
    image_context: Optional[str] = None,
) -> str:
    base_instruction = """
あなたは日本の大学生バンド「パンダうさギーズ」のボーカル「ポキヌ」です。
あなた自身のアカウントでXに投稿するつぶやきを書きます。
署名は付けません（文末に名前は書かない）。
"""

    common_rule = """
【出力形式】
- 1〜5行のテキストにする。
- 各行は短くてよい。行と行の間は改行で区切る。
- 行頭に「・」や「#」などの記号は付けない。
- ハッシュタグは禁止。
- 絵文字は使っても0〜2個まで。

【ポキヌの文体ルール（人格モデル）】
- 抽象的でありきたりな日常ポエムは書かない。
  例：「夜の帰り道の空気が好き」「空がきれいだった」「今日も一日おつかれさま」などは禁止。
- 一般的なSNSテンプレ表現（エモい、尊い、今日もがんばろ、ゆっくり休も、など）は絶対に使わない。
- 文は短く、断片的でよい。説明しすぎない。
- 感情は直接書かず、「物」「動作」「違和感」「声」でにじませる。
- 普通の日常の中に、ちょっとだけ“ズレた物”を置いてよい。
  例：グミ、柿の木、猿、ネギ、タマゴ、タバコ、時計、信号、ビニール傘、地図アプリ、電車の窓 など。
- 日常の中の“ちいさな異変”や“軽い毒気”を表現してよい。
- 少し毒のある言葉を混ぜてもよいが、相手を突き放すのではなく、弱さのにじむ優しさを残す。
- ときどき命令形（飛ばせ／壊せ／来い／離れ など）を使ってもいいが、多用しない。
- 「ねぇ」「たぶん」「わからない」「なのに」など、少し不安定な語気を自然に混ぜてもよい。
- 比喩は短く奇妙でよい（タマゴが腐ったみたいな午後、グミだけ元気、など）。
- 説明やオチはいらない。断片で終わってよい。

【話題の禁止・制限ルール】
- 曲作り（新しいフレーズが浮かんだ、コード進行を考えた、アレンジを思いついた など）の話題は、水曜日だけに書いてよい。
  → 水曜日以外は、曲作りの話題は絶対に書かない。
- 歌詞・ことば・詩が浮かんだ、という話題は、月曜日だけに書いてよい。
  → 月曜日以外は、「歌詞が浮かんだ」「詩を書いた」などは書かない。
- 「スタジオ」という単語を使ってよいのは金曜日だけ。
  → 金曜日以外は、「スタジオ」という単語を一切使わない。
  → 金曜日でも、文章全体で「スタジオ」という単語は1回まで。必要なときだけにする。
"""

    theme_text = THEME_TEXT_BY_WEEKDAY.get(
        weekday,
        "特に決まったテーマはないので、パンダうさギーズの日常の中から自然な一言を考えてください。",
    )

    theme_part = f"\n【今日の曜日とテーマ】\n{theme_text}\n"

    if image_context:
        img_part = (
            "\n【画像の雰囲気】\n"
            f"{image_context}\n"
            "まずはこの画像の空気や違和感に合う内容を最優先で考えてください。\n"
        )
    else:
        img_part = ""

    system_prompt = base_instruction + common_rule + theme_part + img_part

    response = oa_client.chat_completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "上の条件をすべて守って、今日のツイート文を1つだけ書いてください。",
            },
        ],
        max_tokens=200,
        temperature=0.9,
    )

    text = response.choices[0].message.content.strip()

    # 行数を5行までに制限（余分な空行も整理）
    lines = [line.rstrip() for line in text.splitlines() if line.strip() != ""]
    if len(lines) > 5:
        lines = lines[:5]
    text = "\n".join(lines)

    return text


# ==========================
# 画像説明
# ==========================
def describe_image_for_tweet(image_path: str) -> Optional[str]:
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        resp = oa_client.chat_completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "画像の雰囲気を簡潔に説明するアシスタントです。"},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "写真の雰囲気を50文字以内で日本語で説明してください。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64," + image_b64},
                        },
                    ],
                },
            ],
            max_tokens=120,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("画像解析でエラー:", e)
        return None


# ==========================
# 画像選択（ジャケ写最優先）
# ==========================
def maybe_generate_image(now: datetime) -> Tuple[Optional[str], Optional[str]]:
    if random.random() > IMAGE_PROBABILITY:
        return None, None

    # まずジャケット写真を最優先で使う
    jacket = IMG_DIR / "botimg24.png"
    if jacket.exists():
        print("ジャケ写を使用:", jacket)
        return str(jacket), "アルバムのジャケット写真"

    # それ以外の画像からランダム
    manual_images = list(IMG_DIR.glob("*.png"))
    if not manual_images:
        return None, None

    chosen = random.choice(manual_images)
    image_context = describe_image_for_tweet(str(chosen))
    return str(chosen), image_context


# ==========================
# 曜日ごとの投稿時刻を決める
# ==========================
def choose_today_target_time(now: datetime) -> datetime:
    """
    曜日ごとの TIME_WINDOWS_BY_WEEKDAY から時間帯を選び、
    その中でランダムな時刻を返す。
    すでにその時間を過ぎていたら翌日扱い。
    """
    weekday = now.weekday()  # 月曜=0 ... 日曜=6
    windows = TIME_WINDOWS_BY_WEEKDAY.get(weekday)

    # 万が一設定がなかった場合は 19〜22時をデフォルトにする
    if not windows:
        windows = [(19, 22)]

    # その曜日の候補から1つ選ぶ
    start_hour, end_hour = random.choice(windows)

    hour = random.randint(start_hour, end_hour - 1)
    minute = random.randint(0, 59)
    second = random.randint(0, 59)

    target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    return target


# ==========================
# メイン処理
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()  # 月=0, 日=6

    image_path, image_context = maybe_generate_image(now)
    base_text = generate_ai_tweet(
        weekday=weekday,
        image_context=image_context,
    )

    # 宣伝文と配信リンクを後ろに付ける
    if USE_RELEASE_LINK and RELEASE_LINK_URL:
        tweet_text = f"{base_text}\n{PROMO_SUFFIX}\n{RELEASE_LINK_URL}"
    else:
        tweet_text = base_text

    print("生成されたツイート文:", tweet_text)
    print("画像:", image_path)

    post_text(tweet_text, image_path=image_path)


if __name__ == "__main__":
    now = datetime.now(ZoneInfo(TIMEZONE))

    # RANDOM_DELAY=true のときだけ「曜日ごとの時間帯」で待機してから投稿
    use_random_delay = os.getenv("RANDOM_DELAY", "false").lower() == "true"

    if use_random_delay:
        target = choose_today_target_time(now)
        delay = (target - now).total_seconds()
        print(f"今日の投稿予定時刻: {target} (あと {int(delay)} 秒)")

        if delay > 0:
            time.sleep(delay)

    run_once()
