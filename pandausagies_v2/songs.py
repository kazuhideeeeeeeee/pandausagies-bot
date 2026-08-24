from __future__ import annotations

import random
from typing import Any


def choose_song(songs: list[dict[str, Any]], recent_ids: list[str], rng: random.Random) -> dict[str, Any] | None:
    active = [song for song in songs if song.get("active") is True]
    if not active:
        return None
    avoid = set(recent_ids[-3:])
    pool = [song for song in active if song.get("id") not in avoid] or active
    counts = {song["id"]: recent_ids.count(song["id"]) for song in pool}
    least = min(counts.values())
    return rng.choice([song for song in pool if counts[song["id"]] == least])
