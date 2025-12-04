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

# ポキヌ投稿に画像を付ける確率
IMAGE_PROBABILITY = 0.40

# ⭐ 配信リンク
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"

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

# 曜日ごとの「話題テーマ」説明（ポキヌ用）
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

# ジャケット画像
JACKET_PATH = IMG_DIR / "botimg24.png"

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
        print(f"URL: https://x.com/i/web/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        print("テキスト投稿でエラー:", e)
        return None


# ==========================
# AI 文章生成（ポキヌ人格＋曜日ルール）
# ==========================
def generate_pokinu_tweet(
    weekday: int,
    image_context: Optional[str] = None,
) -> str:
    base_instruction = """
あなたは日本の大学生バンド「パンダうさギーズ」のボーカル「ポキヌ」です。
あなた自身のアカウントでXに投稿するつぶやきを書きます。
署名は付けません（文末に名前は書かない）。
配信リンクやURLは絶対に書かないでください。
"""

    common_rule = """
【出力形式】
- 1〜5行のテキストにする。
- 各行は短くてよい。行と行の間は改行で区切る。
- 行頭に「・」や「#」などの記号は付けない。
- ハッシュタグは禁止。
- 絵文字は使っても0〜2個まで。

【ポキヌの文体ルール（人格モデル）】
- 文は短めでよいが、あまり意味不明にはしない。
  → 日常の出来事や状況が一言わかる程度には具体的にする。
- 断片的な表現は残すが、“ズレた詩”は1〜2か所にとどめる。
- 感情は直接書き過ぎず、「物」「動作」「小さな違和感」で伝える。
- 普通の日常のひと言（今日は授業が長かった／バイト帰りがしんどい 等）を混ぜていい。
  → ただしテンプレSNS語（エモい、尊い、おつかれ〜など）は禁止。
- 少し毒のある比喩はOKだが、意味がつながるように。
- 命令形（飛ばせ／来い／壊せなど）は使ってもよいが、全体の1回まで。
- 文章に最低1つは “今日あったこと” がわかる具体要素を入れる。
  例：電車／コンビニ／自転車／雨／昼ごはん／授業／帰り道／駅前 など。
- 比喩は短く奇妙でもよいが「唐突すぎる不可解さ」は避ける。

【話題の禁止・制限ルール】
- 曲作り（新しいフレーズが浮かんだ、コード進行を考えた、アレンジを思いついた など）の話題は、水曜日だけに書いてよい。
  → 水曜日以外は、曲作りの話題は絶対に書かない。
- 歌詞・ことば・詩が浮かんだ、という話題は、月曜日だけに書いてよい。
  → 月曜日以外は、「歌詞が浮かんだ」「詩を書いた」などは書かない。
- 「スタジオ」という単語を使ってよいのは金曜日だけ。
  → 金曜日以外は、「スタジオ」という単語を一切使わない。
  → 金曜日でも、文章全体で「スタジオ」という単語は1回まで。必要なときだけにする。
- 天気や空そのものの感想（夕焼けきれい／空が青い 等）だけで終わる文章は禁止。
  → 天気を使う場合は、必ず具体的な出来事や行動とセットにする。
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

    response = oa_client.chat.completions.create(
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
# スタッフ用宣伝ツイート
# ==========================
STAFF_MESSAGES = [
    "ミニアルバム『Pandaluggies』が各配信サービスで聴けるようになりました。2週間詰め込みで録った8曲、ぜひ一度チェックしてみてください。",
    "パンダうさギーズのミニアルバムが配信中です。通学や通勤のお供に、ゆるっと流してもらえたらうれしいです。",
    "少しずつ再生数や感想も届きはじめています。まだ聴いていない方は、この機会にぜひ試しに再生してみてください。",
    "録音からミックスまでドタバタで駆け抜けたミニアルバム、ようやく皆さんのところに届きました。気に入った1曲が見つかれば幸いです。",
]


def generate_staff_tweet() -> str:
    body = random.choice(STAFF_MESSAGES)
    # 「本日」などの日付感は入れない
    text = f"{body}\n{RELEASE_LINK_URL}\n【スタッフ】"
    return text


# ==========================
# 画像説明（ポキヌ用のコンテキスト）
# ==========================
def describe_image_for_tweet(image_path: str) -> Optional[str]:
    try:
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        resp = oa_client.chat.completions.create(
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
# 画像選択（ポキヌ用）ジャケ写最優先
# ==========================
def maybe_generate_image(now: datetime) -> Tuple[Optional[str], Optional[str]]:
    if random.random() > IMAGE_PROBABILITY:
        return None, None

    # まずジャケット写真を最優先で使う
    if JACKET_PATH.exists():
        print("ジャケ写を使用:", JACKET_PATH)
        return str(JACKET_PATH), "アルバムのジャケット写真"

    # それ以外の画像からランダム
    manual_images = list(IMG_DIR.glob("*.png"))
    if not manual_images:
        return None, None

    chosen = random.choice(manual_images)
    image_context = describe_image_for_tweet(str(chosen))
    return str(chosen), image_context


# ==========================
# 曜日ごとの投稿時刻を決める（長時間 sleep しない版）
# ==========================
def choose_today_target_time(now: datetime) -> datetime:
    """
    曜日ごとの TIME_WINDOWS_BY_WEEKDAY から時間帯を選び、
    その中でランダムな時刻を返す。
    すでにその時間を過ぎていたら「明日」にはせず、
    5〜15分後くらいのランダムな時間にずらす。
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
        # もう今日のウィンドウは過ぎているので、
        # 明日まで待つのではなく、5〜15分後くらいにずらす
        extra_sec = random.randint(5 * 60, 15 * 60)
        target = now + timedelta(seconds=extra_sec)

    return target


# ==========================
# メイン処理
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()  # 月=0, 日=6

    # 1) スタッフの宣伝ポスト（毎回）
    staff_text = generate_staff_tweet()
    staff_image = str(JACKET_PATH) if JACKET_PATH.exists() else None
    print("スタッフ投稿:", staff_text)
    post_text(staff_text, image_path=staff_image)

    # 2) ポキヌのポスト：だいたい2日に1回（偶数日だけ）
    if now.day % 2 == 0:
        image_path, image_context = maybe_generate_image(now)
        pokinu_text = generate_pokinu_tweet(
            weekday=weekday,
            image_context=image_context,
        )
        print("ポキヌ投稿:", pokinu_text)
        print("画像(ポキヌ):", image_path)
        post_text(pokinu_text, image_path=image_path)
    else:
        print("今日はポキヌのツイートはお休み（日付が奇数のため）")


# ==========================
# エントリーポイント
# ==========================
if __name__ == "__main__":
    now = datetime.now(ZoneInfo(TIMEZONE))
    use_random_delay = os.getenv("RANDOM_DELAY", "false").lower() == "true"
    print(f"RANDOM_DELAY = {use_random_delay}")

    try:
        if use_random_delay:
            target = choose_today_target_time(now)
            delay = (target - now).total_seconds()
            print(f"投稿予定: {target}（あと {int(delay)} 秒）")
            if delay > 0:
                time.sleep(delay)
        else:
            print("ディレイなしで run_once を実行します")

        print("run_once を呼びます")
        run_once()
        print("run_once 終了")

    except Exception as e:
        import traceback
        print("===== bot.py で予期しないエラー発生 =====")
        print(repr(e))
        traceback.print_exc()
        print("======================================")
