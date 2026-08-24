from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PostCandidate:
    scheduled_at: datetime
    should_post: bool
    category: str
    text: str
    reason: str
    media_path: Optional[str] = None
    song_id: Optional[str] = None
    url: Optional[str] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["scheduled_at"] = self.scheduled_at.isoformat()
        return data


@dataclass(frozen=True)
class PostResult:
    success: bool
    post_id: Optional[str] = None
    error: Optional[str] = None
