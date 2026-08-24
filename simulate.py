from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from pandausagies_v2.simulation import simulate


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an offline pandausagies life simulation")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--start", default="2026-08-24")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=ZoneInfo("Asia/Tokyo"))
    _, report = simulate(args.days, args.seed, start)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
