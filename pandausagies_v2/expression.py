from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

CONCRETE_WORDS = ("鍋", "食卓", "パン", "ギター", "メガネ", "王冠", "花", "電車", "部屋", "弁当", "机", "椅子", "窓", "皿", "卵", "ごはん", "マイク", "駅", "棚", "本", "電球", "脚立", "おかず", "梅干し", "箸", "売店", "スプーン", "歌詞")
POETIC_TURNS = ("が元気", "が待っていた", "理由も", "部屋が広く", "音はしない", "特に理由はない", "景色は同じ", "夜が近く")

@dataclass(frozen=True)
class Validation:
    valid: bool
    score: int
    reasons: tuple[str, ...]

class ExpressionValidator:
    def score(self, text: str) -> int:
        score = sum(5 for phrase in POETIC_TURNS if phrase in text)
        if not any(word in text for word in CONCRETE_WORDS): score += 8
        if not any(verb in text for verb in ("入れ", "置い", "買っ", "食べ", "乗っ", "降り", "拭い", "洗っ", "切っ", "閉め", "開け", "動か", "替え", "持っ", "包ん", "焼い", "弾い", "録っ", "直し", "使っ", "探し")): score += 3
        return score
    def validate(self, text: str) -> Validation:
        reasons=[]
        if len(text.splitlines())>2: reasons.append("more than two lines")
        if "#" in text: reasons.append("hashtag")
        if not any(word in text for word in CONCRETE_WORDS): reasons.append("no concrete object/place")
        if self.score(text)>=5: reasons.append("poetic recovery")
        return Validation(not reasons,self.score(text),tuple(reasons))


class ExpressionProvider(Protocol):
    """Optional final wording boundary; it cannot choose actions, media, songs, URLs, or events."""

    def polish(self, draft: str) -> str: ...


class LocalExpressionProvider:
    def polish(self, draft: str) -> str:
        return draft


class OpenAIExpressionProvider:
    """Reserved adapter. Intentionally has no network implementation in offline Phase 3."""

    def polish(self, draft: str) -> str:
        raise RuntimeError("OpenAI expression is disabled in offline Phase 3")
