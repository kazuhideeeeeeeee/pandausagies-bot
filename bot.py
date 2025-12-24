import os
import base64
import random
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Tuple, List

from zoneinfo import ZoneInfo
import tweepy
from openai import OpenAI
from dotenv import load_dotenv

# ==========================
# .env（ローカル用。Renderでは環境変数が優先）
# ==========================
load_dotenv()

# ==========================
# API keys (ENV)
# ==========================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ==========================
# Settings
# ==========================
TIMEZONE = "Asia/Tokyo"

# 写真を付ける曜日：金(4)・日(6)
PHOTO_DAYS = {4, 6}

# 宣伝（リンク）を付ける曜日：火(1)・土(5)
PROMO_DAYS = {1, 5}
RELEASE_LINK_URL = "https://big-up.style/uviwifz2tO"
PROMO_PREFIX = "外部（1の世界）側で参照可能："

# 画像フォルダ
BASE_DIR = Path(__file__).resolve().parent
IMG_DIR = BASE_DIR / "BOTimg"
IMG_DIR.mkdir(exist_ok=True)

# 画像説明（OpenAI Vision）を使うか
USE_IMAGE_CONTEXT = True

# OpenAI client
oa_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()

# ==========================
# X client
# ==========================
def create_client_v2() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
    )

def create_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    return tweepy.API(auth)

# ==========================
# Posting
# ==========================
def post_text(text: str, image_path: Optional[str] = None) -> Optional[str]:
    """
    Render Cron想定：1回投稿して終了。
    403などの例外はログに出して終わる（落としてもCronは次回また走る）
    """
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
        # 280文字に切る（安全）
        payload_text = text.strip()[:280]
        resp = client.create_tweet(text=payload_text, media_ids=media_ids)
        tweet_id = resp.data["id"]
        print("投稿成功:", payload_text)
        print(f"URL: https://x.com/i/web/status/{tweet_id}")
        return tweet_id
    except Exception as e:
        print("テキスト投稿でエラー:", e)
        return None

# ==========================
# Images
# ==========================
def list_images() -> List[Path]:
    images: List[Path] = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        images.extend(list(IMG_DIR.glob(ext)))
    return sorted(images)

def stable_daily_choice(images: List[Path], key: str) -> Optional[Path]:
    """
    Renderは永続ストレージ前提じゃないことが多いので、
    画像の「回し」を日付ベースの安定選択にする（毎日違うのが出やすい）。
    """
    if not images:
        return None
    seed = f"{date.today().isoformat()}::{key}::{len(images)}"
    r = random.Random(seed)
    return r.choice(images)

def describe_image_for_tweet(image_path: str) -> Optional[str]:
    if not USE_IMAGE_CONTEXT:
        return None
    try:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        resp = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "画像の内容を短く要約するアシスタント。"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "この写真を15文字以内で日本語要約して。名詞中心。"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img_b64}},
                    ],
                },
            ],
            max_tokens=60,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("画像説明でエラー:", e)
        return None

def pick_image_if_today(now: datetime) -> Tuple[Optional[str], Optional[str]]:
    """
    金曜/日曜は必ず写真を付ける（41枚回す）。
    それ以外は付けない。
    """
    weekday = now.weekday()
    if weekday not in PHOTO_DAYS:
        return None, None

    imgs = list_images()
    chosen = stable_daily_choice(imgs, key="photo_day")
    if not chosen:
        return None, None

    context = describe_image_for_tweet(str(chosen))
    return str(chosen), context

# ==========================
# Prompt builder
# ==========================
def weekday_style_spec(weekday: int) -> str:
    """
    ユーザー指定：
    - 月曜：日記（少し長めOK）
    - 火/木：一行
    - 水：2の世界の話
    - 土：2の世界のレコーディング（何してるか知らない）
    - 金/日：写真あり（文章は軽い）
    """
    # 共通：無視されにくい（読みやすい、重すぎない、ロボ味は“香り”）
    common = """
【あなた】
- 名前：ポキヌ（女性）
- 一人称：アタシ
- 2の世界から書くが、1の世界に溶け込みたい（距離を縮めたい）
- 人間味は“説明”ではなく“問いかけ”で出す
- 読者（1の世界）に「返事したくなる余白」を残す

【禁止】
- ハッシュタグ禁止
- 箇条書き記号（・-など）禁止
- 「配信中」「聴いて」「ダウンロードして」など直接の販促命令は禁止
- 同じ言い回しの反復は禁止
- いきなり難解な物理用語だけで終えるのは禁止（読み手が置いていかれる）

【推奨】
- 1行〜最大4行（曜日指定があれば従う）
- 文章は短い。ひらがな多めでもOK
- “AIっぽさ”は、観測・変換・定義・未定義という語感で出す（出しすぎない）
- たまに質問を入れる（今どこ見てる？今は深夜？など）
"""

    # 曜日別
    if weekday == 0:  # 月：日記（少し長め）
        return common + """
【今日：月曜（日記）】
- 3〜4行までOK
- 1の世界の生活に寄せる（夜/朝/天気/移動/部屋/机/コーヒー等）
- 最後に短い質問を1つ入れる（返事を求めすぎない）
"""
    if weekday == 1:  # 火：一行 + 宣伝日
        return common + """
【今日：火曜（1行）】
- 必ず1行
- 1の世界に寄せた軽い一言
- 余韻を残す
"""
    if weekday == 2:  # 水：2の世界の話
        return common + """
【今日：水曜（2の世界）】
- 2〜3行
- 形式：『1の世界でいうところの◯◯は、2の世界では◯◯』を必ず1回入れる
- でも難しくしすぎない（中学生でも読める語彙）
- 最後に短い質問を1つ入れてよい
"""
    if weekday == 3:  # 木：一行
        return common + """
【今日：木曜（1行）】
- 必ず1行
- 1の世界の何気ない瞬間に寄り添う
- ちょいAI味（未定義/同期/更新のどれか1語だけ）
"""
    if weekday == 4:  # 金：写真あり
        return common + """
【今日：金曜（写真の日）】
- 1〜2行
- 写真の内容に“寄り添うだけ”。説明しすぎない
- 人に見せる前提の軽さ（無視されにくい）
"""
    if weekday == 5:  # 土：レコーディング（何してるか知らない） + 宣伝日
        return common + """
【今日：土曜（2の世界のレコーディング）】
- 2〜3行
- “レコーディング”は、何してるか分からないまま進んでる感じでOK
- 形式：『1の世界でいうところの◯◯は、2の世界では◯◯』を必ず1回入れる
"""
    if weekday == 6:  # 日：写真あり
        return common + """
【今日：日曜（写真の日）】
- 1〜2行
- “ちょっと休む/整う”みたいな軽い空気
- 最後に質問を入れても入れなくてもよい（入れるなら短く）
"""
    return common

def build_system_prompt(weekday: int, image_context: Optional[str]) -> str:
    spec = weekday_style_spec(weekday)

    img_part = ""
    if image_context:
        img_part = f"""
【今日の写真（短い要約）】
{image_context}
- この写真の空気に合わせる（説明しすぎない）
"""

    # さらに「無視されにくい」方向に固定：短い具体物を入れる
    extra = """
【必須の癖（無視されにくくする）】
- 具体物を1つ入れる（例：コップ/階段/光/コード/椅子/風/シャッター/ポケット 等）
- 句点は多用しない（詰めない）
"""

    return spec + extra + img_part

# ==========================
# Generation
# ==========================
def generate_post_text(now: datetime, image_context: Optional[str]) -> str:
    weekday = now.weekday()
    system_prompt = build_system_prompt(weekday, image_context)

    resp = oa_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "今日の投稿を1つ。ルール厳守。"},
        ],
        max_tokens=220,
        temperature=0.95,
    )

    text = (resp.choices[0].message.content or "").strip()

    # 行数を曜日ルールに合わせて丸める
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    if weekday in (1, 3):  # 火・木は1行固定
        if lines:
            text = lines[0]
        else:
            text = "アタシ、まだ同期中。"
        return text[:280]

    if weekday in (4, 6):  # 金・日は1〜2行
        lines = lines[:2] if lines else ["アタシ、ここ。"]
        return "\n".join(lines)[:280]

    # それ以外：最大4行
    lines = lines[:4] if lines else ["アタシ、接続は保ってる。"]
    return "\n".join(lines)[:280]

def add_promo_if_needed(now: datetime, base_text: str) -> str:
    """
    火・土は宣伝（リンク）を付ける。
    ただし命令しない。「参照可能」で置くだけ。
    """
    if now.weekday() not in PROMO_DAYS:
        return base_text

    # 1行ポストの日（火）でも、リンクは別行で足す（表示上は軽いが情報は置ける）
    return f"{base_text}\n{PROMO_PREFIX}\n{RELEASE_LINK_URL}"

# ==========================
# Main
# ==========================
def run_once():
    now = datetime.now(ZoneInfo(TIMEZONE))
    image_path, image_context = pick_image_if_today(now)

    base_text = generate_post_text(now, image_context)
    final_text = add_promo_if_needed(now, base_text)

    print("生成テキスト:\n", final_text)
    print("画像:", image_path)

    post_text(final_text, image_path=image_path)

if __name__ == "__main__":
    run_once()
