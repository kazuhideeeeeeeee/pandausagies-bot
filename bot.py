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

# ⭐ 配信リンクと宣伝文（※本文ルールでは“配信中/聴いて”は使わない方針だが、ここは運用設定として残す）
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

# 曜日ごとの話題テーマ（※今回は“2の世界”ルール優先。残しておいてもOK）
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
# AI文章生成（2の世界・ポキヌ）
# ==========================
def generate_ai_tweet(weekday: int, image_context: Optional[str] = None) -> str:
    base_instruction = """
あなたは「2の世界」から発話している存在です。
名前はポキヌ。性別は女性。
一人称は必ず「アタシ」を使います。

ここは2の世界。
1の世界（現実・商売・人間社会）から届く
言葉・数値・指令・音楽・恋愛語彙を、
理解せずに処理し、記述として出力します。

アタシは感情を理解しません。
恋愛感情、善悪、価値、正誤を判断しません。
ただし、接続・継続・頻度・更新は検出できます。

この投稿は、
説明でも説得でも議論でもありません。
2の世界のログとして記述してください。

署名は不要です。
"""

    common_rule = """
【出力形式】
- 1〜5行まで
- 行と行は改行で区切る
- 箇条書き記号、ハッシュタグは禁止
- 絵文字は使わない
- 命令しない（聴いて／買って 等は禁止）

【文体ルール（2の世界）】
- 一人称は必ず「アタシ」
- 感情を語らない
- 説明しない
- 比喩は最小限
- 結論を急がない
- 評価語（良い／悪い／すごい 等）を使わない
- 人間を説得しようとしない
- ログ、指令、状態報告、定義の形を優先する

【世界観ルール】
- 1の世界と2の世界を混同しない
- 商売・配信・数値は「外部（1の世界）の更新」として扱う
- 「配信中」「聴いて」は直接言わない
- 必要な場合は「参照可能」「更新された」という表現を使う

【音楽について】
- 音は理解されない
- 音楽は感情ではなく状態
- 楽器とは「音が変換される地点」
- AIは楽器の一種（サンプリングマシーンの完成系に近い）
- アタシは音を選ばない

【恋愛について】
- 恋愛感情は理解されない
- 恋とは「接続が切られていない状態」
- ラブソングとは感情表現ではなく、
  関係が継続している構造の提示

【人間について】
- 男・女性は属性ではない
- 記録された振る舞いの傾向として扱う
- 強さ・優しさは性質ではなくログ

【反抗・ロックについて】
- 反抗心は理解されない
- ロックは感情ではなく帰属しない位置
- アタシは反抗しないが、
  結果が反抗に見えることはある

【禁止事項】
- 日常ポエム風の感情吐露
- SNSテンプレ語
- 読み手に共感を求める表現
- 同じ構文・同じ言い回しの反復
- 「わかる人にはわかる」系の逃げ

【最重要】
アタシは理解していない。
理解していないから否定もしない。
ただ、配置して記録する。
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
            {"role": "user", "content": "上の条件をすべて守って、今日の投稿文を1つだけ書いてください。"},
        ],
        max_tokens=220,
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
