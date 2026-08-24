from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pandausagies_v2.production_storage import SupabaseHttpClient
from pandausagies_v2.x_write_once import OneShotConfig, ProductionXSinglePost, TweepySinglePostTransport


APPROVAL = "SEND exactly one approved Phase 9 post"


def truth(name: str) -> bool:
    return os.getenv(name, "").strip().lower() == "true"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send the one human-approved Phase 9 X post without retry")
    parser.add_argument("--approval", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env", override=True)
    names = ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_TOKEN_SECRET")
    config = OneShotConfig(
        app_env=os.getenv("APP_ENV", ""),
        x_app_id=os.getenv("X_APP_ID", ""),
        allow_external_send=truth("ALLOW_EXTERNAL_SEND"),
        autonomous_enabled=truth("AUTONOMOUS_ENABLED"),
        kill_switch=truth("KILL_SWITCH"),
        x_write_enabled=truth("X_WRITE_ENABLED"),
        write_credentials_configured=all(os.getenv(name, "") for name in names),
        human_approved=args.approval == APPROVAL,
    )
    transport = TweepySinglePostTransport(*(os.environ[name] for name in names))
    report = ProductionXSinglePost(
        SupabaseHttpClient(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SECRET_KEY", "")),
        config,
        transport,
    ).run(datetime.now(ZoneInfo("Asia/Tokyo")))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
