from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Protocol


class ImageProvider(Protocol):
    def available(self) -> list[dict]: ...


class ExistingMediaProvider:
    def __init__(self, root: Path, records: list[dict]):
        self.root, self.records = root, records

    def available(self) -> list[dict]:
        return [item for item in self.records if item.get("active", True) and (self.root / item["path"]).is_file()]

    def choose(self, recent_ids: list[str], rng: random.Random) -> dict | None:
        items = self.available()
        if not items:
            return None
        avoid = set(recent_ids[-3:])
        pool = [item for item in items if item["id"] not in avoid] or items
        counts = {item["id"]: recent_ids.count(item["id"]) for item in pool}
        least = min(counts.values())
        return rng.choice([item for item in pool if counts[item["id"]] == least])


class GeneratedImageProvider:
    """Future adapter boundary. Phase 3 deliberately performs no API calls."""

    def available(self) -> list[dict]:
        return []


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
