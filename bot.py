import os
import base64
import random
import time
from datetime import datetime
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

# 曜日ごとの投稿時間ウィンドウ（今は「テーマ用途」にのみ使用）
TIME_WINDOWS_BY_WEEKDAY = {
    0: [(19, 22)],              # 月
    1: [(19, 22)],              # 火
    2: [(19, 22)],              # 水
    3: [(19, 22)],              # 木
    4: [(18, 21)],              # 金
    5: [(13, 16), (20, 23)],    # 土
    6: [(13, 16), (20, 23)],    # 日
}

# 曜日ごとの話題テーマ
THEME_TEXT_BY_WEEKDAY = {
    0: "月曜日。学校や授業、通学、月曜ならではの気分について。",
    1: "火曜日。バイト、放課後、友だちとの帰り道、日常の出来事。",
    2: "水曜日。曲作りやフレーズ、アレンジなど音楽制作そのもの。",
    3: "木曜日。楽器や機材、音作り、小さな発見について。",
    4: "金曜日。バンド活動、リハや本番の気持ち。「スタジオ」は1回だけ許可。",
    5: "土曜日。街、イベント、買い物、外に出た時の出来事。",
    6: "日曜日。一週間の振り返り、のんびりした気分、明日への気持ち。",
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
# 投稿処理
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
        print(f"URL: https://x.com/i/web/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        print("テキスト投稿でエラー:", e)
        return None


# ==========================
# AI文章生成（ポキヌ人格）
# ==========================
def generate_ai_tweet(weekday: int, image_context: Optional[str] = None) -> str:
    base_instruction = """
あなたは日本の大学生バンド「パンダうさギーズ」のボーカル「ポキヌ」です。
あなた自身のアカウントでXに投稿するつぶやきを書きます。
署名は付けません。
"""

    # 【修正】インデントを修正しました（左に詰めました）
    common_rule = """
【出力形式】
- 1〜5行のテキストにする。
- 短くてよい。行と行の間は改行。
- 記号での箇条書きは禁止。
- ハッシュタグ禁止。
- 絵文字は0〜2個。

【ポキヌの文体ルール（壁打ち寄り・自然系）】
- 文は短めでよいが、意味不明すぎない。
- 今日あったこと・思ったことを素直に書いてよい。
- 不要な詩的表現はつくらなくてよい。自然に出るときだけ。
- 日常の中のちょっとしたズレや違和感は「1ヶ所だけ」混ぜる程度にする。
- 無理に比喩を作らない。直球の言葉も使ってよい。
- 感情は少し曖昧な語尾（〜かも／〜気がする）でにじませる。
- 友人へ軽くぼやくように、壁打ちするように呟いてよい。
- 重すぎる暗喩（世界が溶ける 等）は控える。
- テンプレSNS語（エモい・尊い 等）は禁止。
- 説明しすぎず、不可解になりすぎない中間を保つ。

【話題の禁止・制限ルール】
- 曲作りの話題（水曜のみ許可）。それ以外の曜日は禁止。
- 歌詞・詩が浮かんだという話（月曜のみ許可）。他曜日は禁止。
- 「スタジオ」と書けるのは金曜のみ。金曜でも1回まで。

【禁止フレーズ・禁止パターン】
- 次の表現やほぼ同じ意味の言い換えは使わない：
  - 「月曜日の学校って、なんだかいつも重い気がする」
  - 「月曜日の朝は重い気がする」
  - 「でも、みんなと会うとちょっと楽になるかも」
  - 「次の休みが待ち遠しい」「次の休みが遠い」
- 上のような、「月曜は重い → でもみんなと会うと楽 → 休みが遠い」
  という三段構成の文章は作らない。
- 同じテーマ（学校／月曜日／休み）を書く場合も、
  毎回違う具体的な出来事や物（教室、電車、コンビニ、雨、ノートなど）を選ぶ。
"""

    theme_text = THEME_TEXT_BY_WEEKDAY.get(weekday, "")
    theme_part = f"\n【今日の曜日とテーマ】\n{theme_text}\n"

    if image_context:
        img_part = f"""
【画像の雰囲気】
{image_context}
まずはこの画像の空気に合う内容を考えてください。
"""
    else:
        img_part = ""

    system_prompt = base_instruction + common_rule + theme_part + img_part

    response = oa_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "今日のツイート文を1つだけ書いてください。"},
        ],
        max_tokens=200,
        temperature=0.9,
    )

    text = response.choices[0].message.content.strip()
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if len(lines) > 5:
        lines = lines[:5]

    return "\n".join(lines)


# ==========================
# 画像説明
# ==========================
def describe_image_for_tweet(image_path: str) -> Optional[str]:
    try:
        with open(image_path, "rb") as f:
            img = base64.b64encode(f.read()).decode()

        resp = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "画像の雰囲気を簡潔に説明するアシスタントです。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "写真の雰囲気を50文字以内で説明してください。"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img}},
                    ],
                },
            ],
            max_tokens=100,
        )
        return resp.choices[0].message.content.strip()

    except Exception as e:
        print("画像解析でエラー:", e)
        return None


# ==========================
# 画像選択（ランダム＋ジャケ写だけ特別扱い）
# ==========================
def maybe_generate_image(now: datetime) -> Tuple[Optional[str], Optional[str]]:
    # 画像を付けるかどうかを確率で決定
    if random.random() > IMAGE_PROBABILITY:
        return None, None

    # BOTimg 内の png を全部取得
    images = list(IMG_DIR.glob("*.png"))

    if not images:
        return None, None

    # ランダムに 1 枚選ぶ
    chosen = random.choice(images)

    # ジャケットなら説明文を固定
    if chosen.name == "botimg24.png":
        print("ジャケット画像を使用:", chosen)
        return str(chosen), "アルバムのジャケット写真"

    # それ以外は画像説明を生成
    image_context = describe_image_for_tweet(str(chosen))
    return str(chosen), image_context


# ==========================
# メイン処理
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()

    image_path, image_context = maybe_generate_image(now)
    base_text = generate_ai_tweet(weekday, image_context)

    if USE_RELEASE_LINK and RELEASE_LINK_URL:
        tweet_text = f"{base_text}\n{PROMO_SUFFIX}\n{RELEASE_LINK_URL}"
    else:
        tweet_text = base_text

    print("生成されたツイート文:", tweet_text)
    print("画像:", image_path)

    post_text(tweet_text, image_path=image_path)


if __name__ == "__main__":
    # ⚠ Render の Cron 想定：起動したら即1回だけ投稿して終了
    now = datetime.now(ZoneInfo(TIMEZONE))
    run_once()