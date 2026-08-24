from __future__ import annotations

import argparse
from pathlib import Path

from pandausagies_v2.autonomous import format_observation, observe
from pandausagies_v2.production_storage import SQLiteStorage
from pandausagies_v2.safety import SafetyConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Observe pandausagies autonomous decisions safely")
    parser.add_argument("--observe", action="store_true", help="read-only decision preview")
    parser.add_argument("--health", action="store_true", help="read-only production safety status")
    parser.add_argument("--storage", default="var/autonomous.sqlite3")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.health:
        import json
        config=SafetyConfig.from_env()
        try:
            report=SQLiteStorage(Path(args.storage)).health(); report.update({"mode":"HEALTH","kill_switch":"ON" if config.kill_switch else "OFF","external_send":"ENABLED" if config.allow_external_send else "DISABLED","autonomous":"ENABLED" if config.autonomous_enabled else "DISABLED"})
        except Exception:
            report={"mode":"HEALTH","storage":"ERROR","memory":"UNKNOWN","kill_switch":"ON" if config.kill_switch else "OFF","external_send":"DISABLED","autonomous":"DISABLED","consecutive_errors":"UNKNOWN"}
        print(json.dumps(report,ensure_ascii=False,indent=2)); return
    if args.observe: print(format_observation(observe(seed=args.seed))); return
    parser.error("use --observe or --health")


if __name__ == "__main__":
    main()
