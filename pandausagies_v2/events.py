from __future__ import annotations

import random
from datetime import date, timedelta


EVENT_SEEDS = (
    ("pot", "鍋にスープを残した", "pot"),
    ("table", "食卓の端を片づけ始めた", "table"),
    ("bread", "パンを一袋買った", "bread"),
    ("glasses", "メガネのねじが少し緩んだ", "glasses"),
    ("train", "知らない駅で一度降りた", "train"),
    ("room", "古い部屋の棚を片づけ始めた", "room"),
    ("flowers", "花を一輪部屋に置いた", "flowers"),
    ("lunch", "お弁当の形を少し変えた", "lunch"),
    ("guitar", "ギターの弦を替え始めた", "guitar"),
    ("crown", "王冠の飾りを直し始めた", "crown"),
)


def evolve_events(events: list[dict], today: date, rng: random.Random) -> tuple[list[dict], dict | None, str]:
    open_events = [event for event in events if event["status"] == "open"]
    ready = [event for event in open_events if date.fromisoformat(event["earliest_next_ref"]) <= today]
    if ready:
        event = rng.choice(ready)
        if event["outcome"] == "forgotten" and rng.random() < 0.55:
            event["status"] = "forgotten"
            event["closed_at"] = today.isoformat()
            return events, event, "forget"
        event["reference_count"] += 1
        if event["reference_count"] >= event["target_refs"]:
            event["status"] = "closed"
            event["closed_at"] = today.isoformat()
            return events, event, "close"
        event["earliest_next_ref"] = (today + timedelta(days=rng.randint(2, 5))).isoformat()
        return events, event, "continue"
    if len(open_events) < 2 and rng.random() < 0.14:
        kind, summary, motif = rng.choice(EVENT_SEEDS)
        event = {
            "id": f"{kind}-{today.isoformat()}", "type": kind, "start_date": today.isoformat(),
            "status": "open", "summary": summary, "motif": motif, "related_posts": [],
            "earliest_next_ref": (today + timedelta(days=rng.randint(2, 5))).isoformat(),
            "reference_count": 1,
            "target_refs": rng.choices((1, 2, 4), weights=(2, 5, 3), k=1)[0],
            "outcome": rng.choices(("closed", "forgotten"), weights=(7, 3), k=1)[0],
            "closed_at": None,
        }
        events.append(event)
        if event["target_refs"] == 1:
            event["status"] = "forgotten" if event["outcome"] == "forgotten" else "closed"
            event["closed_at"] = today.isoformat()
            return events, event, "one_off"
        return events, event, "start"
    return events, None, "none"
