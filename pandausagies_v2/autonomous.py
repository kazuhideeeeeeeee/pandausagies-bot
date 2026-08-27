from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .content import read_json
from .director import AutonomousDirector
from .media import ExistingMediaProvider
from .memory import JsonMemoryStore, Memory


ROOT = Path(__file__).resolve().parent.parent


def build_director(seed: int | None = None, image_autogen_enabled: bool = False, image_post_ratio: float = 0.0, image_skip_ratio: float = 0.0) -> AutonomousDirector:
    return AutonomousDirector(
        read_json(ROOT / "content" / "songs.json"),
        ExistingMediaProvider(ROOT, read_json(ROOT / "content" / "media.json")),
        random.Random(seed),
        image_autogen_enabled=image_autogen_enabled,
        image_post_ratio=image_post_ratio,
        image_skip_ratio=image_skip_ratio,
    )


def observe(now: datetime | None = None, state_path: Path | None = None, seed: int = 1) -> dict:
    """Read-only preview: never saves state and never reaches a sender or external API."""
    current = now or datetime.now(ZoneInfo("Asia/Tokyo"))
    memory = JsonMemoryStore(state_path or ROOT / "var" / "autonomous-state.json").load(Memory())
    preview_memory = memory.clone()
    decision = build_director(seed).decide(current, preview_memory, weekly_due=False)
    return {
        "mode": "OBSERVE", "external_calls": 0, "sent": False, "time_jst": current.isoformat(),
        "memory": {"posts": len(memory.posts), "weeks": len(memory.weeks), "open_events": sum(e["status"] == "open" for e in memory.events)},
        "current_week": memory.weeks[-1] if memory.weeks else "week-00 preview",
        "recent_songs": [p["song_id"] for p in memory.posts[-5:] if p.get("song_id")],
        "recent_media": [p["media_id"] for p in memory.posts[-5:] if p.get("media_id")],
        "decision": decision.to_dict(), "next_week": "not finalized in OBSERVE",
    }


def format_observation(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
