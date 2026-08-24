from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import PostCandidate


LIFE_LINES = (
    ("お弁当のすき間\nパンで埋めた", "life"),
    ("修正7回目\nまだ元気", "life"),
    ("花買った\n鍋より高かった", "offbeat"),
)


def _resolve_current_week(content: dict[str, Any]) -> dict[str, Any] | None:
    current_id = content["current.json"].get("currentWeek")
    return next(
        (week for week in content["weeks.json"] if week.get("id") == current_id),
        None,
    )


def build_candidate(
    now: datetime,
    content: dict[str, Any],
    media_root: Path,
    rng: random.Random | None = None,
) -> PostCandidate:
    chooser = rng or random.Random()
    text, category = chooser.choice(LIFE_LINES)
    current_week = _resolve_current_week(content)
    media_path = None
    if current_week and current_week.get("image"):
        candidate = media_root.parent.parent / current_week["image"]
        if candidate.is_file():
            media_path = str(candidate)

    return PostCandidate(
        scheduled_at=now,
        should_post=True,
        category=category,
        text=text,
        media_path=media_path,
        song_id=content["current.json"].get("currentSong"),
        url=None,
        reason="scheduled daily trace; dry-run approval required",
    )
