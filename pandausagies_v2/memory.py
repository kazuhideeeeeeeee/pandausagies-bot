from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Memory:
    posts: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    weeks: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    media_usage: dict[str, list[str]] = field(default_factory=dict)
    song_usage: dict[str, list[str]] = field(default_factory=dict)
    motif_usage: dict[str, list[str]] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=lambda: {
        "normal_daily_limit": 2,
        "weekly_image_limit": 1,
        "weekly_song_limit": 1,
        "continuity_weight": 0.8,
    })

    def clone(self) -> "Memory":
        return Memory(**deepcopy(asdict(self)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Memory":
        known = {key: value.get(key) for key in cls.__dataclass_fields__ if key in value}
        return cls(**known)


class JsonMemoryStore:
    """Local development store. Reads safely; writes only when explicitly requested."""

    def __init__(self, path: Path):
        self.path = path

    def load(self, fallback: Memory | None = None) -> Memory:
        try:
            return Memory.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return (fallback or Memory()).clone()

    def save(self, memory: Memory) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(memory.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
