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
# 認証情報
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

# ⭐ 配信リンクと宣伝文（使うのはスタッフ投稿だけ）
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"
PROMO_SUFFIX = "ダウンロードしてね！してくれたら泣いちゃう！"

# スタッフデー判定（簡易：月の1,8,15,22,29日をスタッフデー）
def is_staff_day(now: datetime) -> bool:
    return now.day % 7 == 1

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
    # 画像アップロード用の v1.1 API
    auth = tweepy.OAuth1UserHandler(
        API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET
    )
    return tweepy.API(auth)


# ==========================
# 共通ユーティリティ
# ==========================
def post_text(text: str, image_path: Optional[str] = None) -> Optional[str]:
    """テキスト＋任意で画像をポストする（v2）"""
    debug = os.getenv("DEBUG", "false").lower() == "true"

    if debug:
        print("=== DEBUG モード: 実際にはポストしません ===")
        print("テキスト:", text)
        print("画像パス:", image_path)
        return None

    try:
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

        response = client.create_tweet(text=text, media_ids=media_ids)
        tweet_id = response.data["id"]
        print("投稿成功:", text)
        print(f"URL: https://x.com/i/web/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        print("テキスト投稿でエラー:", e)
        return None


def load_image_as_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode("utf-8")


# ==========================
# ポキヌ文生成（帰り道＆音楽ワード禁止＋ポエム弱め＋1行OK）
# ==========================
def generate_pokinu_tweet(
    weekday: int,
    image_context: Optional[str] = None,
) -> str:
    """
    ポキヌ用のテキストを生成する。
    weekday: 0=月曜, 6=日曜
    image_context: 画像がある場合、その説明文などを渡すと味付けに使う
    """
    weekday_label = ["月曜", "火曜", "水曜", "木曜", "金曜", "土曜", "日曜"][weekday]

    base_instruction = f"""
あなたは「パンダうさギーズ」の謎の人格「ポキヌ」として、X に投稿するテキストを1本だけ書きます。

【ポストの基本】
- 日本語で書く。
- 140文字以内。
- 一人称は「ぼく」「私」「おれ」などを自由に使ってよい。
- 日常の小さな出来事や感情を、すこしズレた視点で書く。
- 読み終わったときに、静かな余韻や、にやっとする感じが残るようにする。
- 行頭に「・」や「#」などの記号は付けない。
- ハッシュタグは禁止。
- 絵文字は0〜2個まで。なくてもいい。

【禁止・制限】
- 「帰り道」「帰り」「家に帰る」「帰宅」など、「帰り」にまつわる言葉は使わない。
- 「音楽」「歌」「曲」「ライブ」「ギター」「ベース」「ドラム」「バンド」「フェス」など、
  音楽やバンドを直接連想させる単語は使わない。
- 「フォローして」「拡散して」など、SNSっぽい呼びかけは禁止。
- 作品やアルバムの宣伝は禁止。ポキヌはただの一個人としてつぶやく。

【文体のイメージ】
- 長さはバラバラでよい。
  - 1行だけの短いぼやき（例:「出かけたくない」「曲できなかった」）でもよい。
  - 2〜3文の少し長めのものもあってよい。
- 具体的なモノや場面を必ず1つ以上入れる
  例: コンビニの照明、スーパーのかご、エレベーター、信号待ち、冷蔵庫の中、教室の匂い、洗濯もの、靴、机の上 など。
- 詩的になりすぎないこと。
  - ふわっとした比喩は全体で1つまで。
  - 意味がぼやけすぎないようにする。
- 「出かけたくない」「曲できなかった」「歌詞はいつ来る？」「プロデューサーは何？親か？」のような、
  ストレートなぼやきやおねだりを混ぜてもよい。
- 大きなドラマではなく、「どうでもいいけど、ちょっと刺さる」程度の出来事。
- オチをつけようとし過ぎない。淡く終わってよい。

【曜日の味付け】
- 今日は {weekday_label} です。
- 曜日を直接書かなくてもいいが、
  その曜日らしい空気感（だるさ／中だるみ／折り返し／金曜の解放感／週末の空虚さなど）を少しだけ混ぜてください。
"""

    if image_context:
        base_instruction += f"""

【画像からのヒント】
- 画像の雰囲気から連想されるキーワード: {image_context}
- 画像を説明するのではなく、「なんとなく今日の空気はこうだった」のレベルで使ってください。
"""

    base_instruction += """

【出力形式】
- テキスト本文のみを出力。
- 1行だけの短文でも、2〜3行でもよい。
- 余計な前置きや説明、番号は一切書かない。
"""

    system_prompt = (
        "あなたは、日常の一瞬を静かに切り取る日本語テキストを作るライターです。"
        "ポエムではなく、普通の文章として読めることを大事にしてください。"
    )

    try:
        response = oa_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": base_instruction.strip(),
                },
            ],
            max_tokens=200,
            temperature=0.9,
        )

        text = response.choices[0].message.content.strip()

        # 行数を3行までに制限（余分な空行も整理）
        lines = [line.rstrip() for line in text.splitlines() if line.strip() != ""]
        if len(lines) > 3:
            lines = lines[:3]
        text = "\n".join(lines)

        return text
    except Exception as e:
        print("ポキヌ生成でエラー:", e)
        return "今日は、特に何もなかったはずなのに、靴ひもだけやたらとよく結べた。"


# ==========================
# 【スタッフ】宣伝ポスト（軽めの文体）
# ==========================
def build_staff_tweet() -> str:
    """
    スタッフが書く、あっさりめの宣伝テキスト。
    """
    base = (
        "ミニアルバム『Pandaluggies』が配信中です。\n"
        "ダウンロードしてね！してくれたら泣いちゃう！\n"
        f"{RELEASE_LINK_URL}\n"
        "【スタッフ】"
    )
    return base


# ==========================
# 画像の雰囲気説明（AI）
# ==========================
def describe_image_for_tweet(image_path: str) -> Optional[str]:
    """
    画像を見て「雰囲気の説明文」を短く生成する。
    ポキヌのテキスト生成やスタッフ文のオマケに使う。
    """
    if not os.path.exists(image_path):
        return None

    try:
        image_b64 = load_image_as_base64(image_path)

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
# 画像選択（ジャケ写最優先）
# ==========================
def maybe_generate_image(now: datetime) -> Tuple[Optional[str], Optional[str]]:
    """
    画像を使うかどうかを IMAGE_PROBABILITY で決め、
    使う場合は BOTimg フォルダから1枚選ぶ。
    戻り値: (image_path, image_context)
    """
    if random.random() > IMAGE_PROBABILITY:
        return None, None

    # まずジャケ写（botimg24.png）があればそれを最優先
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
    今日の投稿予定時刻をランダムに決める。
    """
    weekday = now.weekday()
    windows = TIME_WINDOWS_BY_WEEKDAY.get(weekday, [(19, 22)])
    start_hour, end_hour = random.choice(windows)

    start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    delta_seconds = random.randint(0, (end_hour - start_hour) * 3600)
    target = start + timedelta(seconds=delta_seconds)

    if target < now:
        target += timedelta(days=1)

    return target


# ==========================
# メイン処理（1日1ポスト）
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    weekday = now.weekday()  # 月=0, 日=6

    # まずスタッフデーかどうかを判定
    if is_staff_day(now):
        print("今日は【スタッフ宣伝デー】です")
        image_path, image_context = maybe_generate_image(now)
        tweet_text = build_staff_tweet()
        print("スタッフ投稿テキスト:", tweet_text)
        print("画像(スタッフ):", image_path)
        post_text(tweet_text, image_path=image_path)
    else:
        print("今日は【ポキヌ投稿デー】です")
        image_path, image_context = maybe_generate_image(now)
        tweet_text = generate_pokinu_tweet(
            weekday=weekday,
            image_context=image_context,
        )
        print("ポキヌ投稿テキスト:", tweet_text)
        print("画像(ポキヌ):", image_path)
        post_text(tweet_text, image_path=image_path)


if __name__ == "__main__":
    now = datetime.now(ZoneInfo(TIMEZONE))
    use_random_delay = os.getenv("RANDOM_DELAY", "false").lower() == "true"
    print("RANDOM_DELAY =", use_random_delay)

    if use_random_delay:
        target = choose_today_target_time(now)
        delay = (target - now).total_seconds()
        print(f"今日の投稿予定時刻: {target} (あと {int(delay)} 秒)")

        if delay > 0:
            time.sleep(delay)

    print("run_once を実行します")
    run_once()
    print("run_once 終了")
