from __future__ import annotations

import random
from collections import Counter
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from .autonomous import build_director
from .director import apply_decision, next_week_due
from .memory import Memory
from .expression import CONCRETE_WORDS


def similar_rate(texts: list[str], threshold: float = 0.72) -> float:
    if not texts: return 0.0
    def structure(text: str) -> str:
        value = text
        for word in sorted(CONCRETE_WORDS, key=len, reverse=True): value = value.replace(word, "物")
        for token in ("一つ", "二つ", "三つ", "四つ", "一枚", "二枚", "一本", "二本", "三本", "一度", "二回", "三つ先", "十分"):
            value = value.replace(token, "数")
        return value
    similar = 0
    for index, text in enumerate(texts):
        if any(SequenceMatcher(None, structure(text), structure(previous)).ratio() >= threshold for previous in texts[:index]):
            similar += 1
    return round(similar / len(texts), 4)


def simulate(days: int, seed: int, start: datetime) -> tuple[Memory, dict[str, Any]]:
    if not 30 <= days <= 90:
        raise ValueError("simulation days must be between 30 and 90")
    memory = Memory()
    director = build_director(seed)
    for offset in range(days):
        day = start + timedelta(days=offset)
        for hour in (10, 19):
            now = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            weekly_due = hour == 10 and next_week_due(memory, now, start)
            decision = director.decide(now, memory, weekly_due)
            apply_decision(memory, decision)

    posts = memory.posts
    counts_by_day = Counter(post["at"][:10] for post in posts)
    categories = Counter(post["category"] for post in posts)
    motifs = Counter(post["motif"] for post in posts)
    songs = Counter(post["song_id"] for post in posts if post.get("song_id"))
    media = Counter(post["media_id"] for post in posts if post.get("media_id"))
    texts = [post["text"] for post in posts]
    event_starts = sum(decision.get("event_action") in ("start", "one_off") for decision in memory.decisions)
    event_continues = sum(decision.get("event_action") == "continue" for decision in memory.decisions)
    report = {
        "mode": "SIMULATION", "days": days, "seed": seed, "external_calls": 0, "sent": False,
        "posts": len(posts), "skips": sum(d["action"] == "skip" for d in memory.decisions),
        "max_posts_per_day": max(counts_by_day.values(), default=0), "zero_post_days": days - len(counts_by_day),
        "one_post_days": sum(count == 1 for count in counts_by_day.values()),
        "two_post_days": sum(count == 2 for count in counts_by_day.values()),
        "category_distribution": dict(sorted(categories.items())), "motif_distribution": dict(sorted(motifs.items())),
        "daily_motif_rate": round(sum(motifs[m] for m in ("pot", "table", "bread", "glasses", "train", "room", "lunch")) / len(posts), 4) if posts else 0,
        "celebration_motif_rate": round(sum(motifs[m] for m in ("guitar", "crown", "flowers")) / len(posts), 4) if posts else 0,
        "song_usage": dict(sorted(songs.items())), "media_usage": dict(sorted(media.items())),
        "event_starts": event_starts, "event_continues": event_continues,
        "event_completed": sum(e["status"] == "closed" for e in memory.events),
        "event_forgotten": sum(e["status"] == "forgotten" for e in memory.events),
        "event_open": sum(e["status"] == "open" for e in memory.events),
        "promo_rate": round(sum(bool(post.get("include_url")) for post in posts) / len(posts), 4) if posts else 0,
        "duplicate_rate": round((len(texts) - len(set(texts))) / len(texts), 4) if texts else 0,
        "similar_rate": similar_rate(texts),
        "weeks": len(memory.weeks), "week_ids": [week["id"] for week in memory.weeks],
        "representative_posts": [{key: post.get(key) for key in ("at", "category", "motif", "text", "song_id", "media_id", "week_id")} for post in posts[:25]],
    }
    return memory, report
