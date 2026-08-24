from __future__ import annotations

from typing import Protocol

from .models import PostCandidate, PostResult


class Storage(Protocol):
    def record_attempt(self, candidate: PostCandidate, result: PostResult) -> None: ...


class NullStorage:
    """Development fallback. It never claims that a post was persisted."""

    def record_attempt(self, candidate: PostCandidate, result: PostResult) -> None:
        return None
