from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from pandausagies_v2.config import load_settings
from pandausagies_v2.content import load_content
from pandausagies_v2.generator import build_candidate
from pandausagies_v2.logging import event
from pandausagies_v2.sender import send_to_x


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="pandausagies V2 post runner")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Explicitly enable an X write. Omit for safe dry run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    dry_run = not args.send
    event("BOOT", "runner started", dry_run=dry_run)
    event(
        "CONFIG",
        "configuration loaded",
        timezone=settings.timezone,
        x_configured=settings.x_configured,
        openai_configured=bool(settings.openai_api_key),
        db_configured=settings.db_configured,
    )

    try:
        content = load_content(settings.content_dir)
        event("STORAGE", "content loaded", source=str(settings.content_dir))
        now = datetime.now(settings.zone())
        candidate = build_candidate(now, content, settings.media_dir)
        event(
            "POST DECISION",
            "candidate evaluated",
            should_post=candidate.should_post,
            reason=candidate.reason,
        )
        event("GENERATION", "candidate ready", category=candidate.category, text=candidate.text)
        event("MEDIA", "media selected", path=candidate.media_path)
        event("SONG", "song selected", song_id=candidate.song_id, url=candidate.url)

        if dry_run:
            print(json.dumps({"dry_run": True, **candidate.to_dict()}, ensure_ascii=False, indent=2))
            event("X POST", "skipped by dry-run safety gate")
            return 0

        if not candidate.should_post:
            event("X POST", "skipped by decision", reason=candidate.reason)
            return 0

        result = send_to_x(candidate, settings)
        if not result.success:
            event("ERROR", "X post failed", error=result.error)
            return 1
        event("X POST", "post succeeded", post_id=result.post_id)
        return 0
    except Exception as exc:
        event("ERROR", "fatal runner failure", error=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
