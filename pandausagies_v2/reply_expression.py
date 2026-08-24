from __future__ import annotations

from dataclasses import dataclass
import re

from .expression import LocalExpressionProvider


INTENTS = ("greeting", "question", "compliment", "music", "other")
GREETING_WORDS = ("ハロー", "こんにちは", "こんばんは", "おはよう", "やあ", "hello", "hi")
COMPLIMENT_WORDS = ("好きです", "かわいい", "可愛い", "かっこいい", "素敵", "最高", "すごい")
MUSIC_WORDS = ("曲", "音楽", "歌", "ギター", "ライブ", "聴いた", "聞いた")
QUESTION_WORDS = ("？", "?", "好き", "どう", "なに", "何", "どこ", "いつ", "だれ", "誰")
FORBIDDEN = ("皆さん", "ぜひ", "応援よろしく", "フォローして", "拡散して", "新曲配信中", "特に理由はない", "景色は同じ")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF]")


@dataclass(frozen=True)
class ReplyValidation:
    valid: bool
    reasons: tuple[str, ...]


def classify_reply_intent(text: str) -> str:
    lowered=text.casefold().strip()
    if any(word.casefold() in lowered for word in QUESTION_WORDS): return "question"
    if any(word.casefold() in lowered for word in GREETING_WORDS): return "greeting"
    if any(word.casefold() in lowered for word in COMPLIMENT_WORDS): return "compliment"
    if any(word.casefold() in lowered for word in MUSIC_WORDS): return "music"
    return "other"


class LocalReplyExpressionProvider:
    """Deterministic, offline reply wording. It never invents a current life event."""

    def __init__(self) -> None:
        self._provider=LocalExpressionProvider()

    def generate(self, source_text: str, intent: str | None = None) -> str:
        selected=intent or classify_reply_intent(source_text)
        lowered=source_text.casefold()
        if selected=="greeting":
            draft="ハロー"
        elif selected=="question" and ("パン" in source_text or "bread" in lowered):
            draft="好き\nお弁当のすき間にも入る"
        elif selected=="question" and any(word in source_text for word in ("曲","音楽","歌","ギター")):
            draft="好き\nギターもある"
        elif selected=="question":
            draft="わからない\nもう少し聞きたい"
        elif selected=="compliment":
            draft="うれしい\nありがとう"
        elif selected=="music":
            draft="聴いてくれてうれしい\nギターは好き"
        else:
            draft="読んだ\nもう少し聞きたい"
        return self._provider.polish(draft)


def validate_reply_candidate(source_text: str, intent: str, candidate: str) -> ReplyValidation:
    reasons=[]; lines=candidate.splitlines()
    if not 1<=len(lines)<=2: reasons.append("line_count")
    if not candidate.strip(): reasons.append("empty")
    if "#" in candidate: reasons.append("hashtag")
    if EMOJI_RE.search(candidate): reasons.append("emoji")
    if any(word in candidate for word in FORBIDDEN): reasons.append("forbidden_voice")
    if candidate=="読んだ\nありがとう": reasons.append("generic_fallback")
    if intent=="question" and candidate.splitlines()[0] not in ("好き","わからない","ある","ない","そう","ちがう"):
        reasons.append("question_not_answered")
    if intent=="greeting" and not any(word.casefold() in candidate.casefold() for word in GREETING_WORDS):
        reasons.append("greeting_not_returned")
    return ReplyValidation(not reasons,tuple(reasons))
