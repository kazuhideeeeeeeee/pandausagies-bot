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

from pandausagies_v2.production_runner import ProductionAutonomousRunner, ProductionRunConfig
from pandausagies_v2.production_storage import SupabaseHttpClient, SupabaseStorage
from pandausagies_v2.x_ingestion import XReadConfig, run_x_read
from pandausagies_v2.x_read import XReadClient
from pandausagies_v2.x_write_once import TweepySinglePostTransport


def truth(name: str) -> bool:
    return os.getenv(name, "").strip().lower() == "true"


def load_environment() -> None:
    local = ROOT / ".env.production"
    if local.exists():
        load_dotenv(local, override=False)


def client() -> SupabaseHttpClient:
    return SupabaseHttpClient(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SECRET_KEY", ""))


def run_config() -> ProductionRunConfig:
    epoch = datetime.fromisoformat(os.getenv("AUTONOMOUS_EPOCH", ""))
    write_names = ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_TOKEN_SECRET")
    return ProductionRunConfig(
        app_env=os.getenv("APP_ENV", ""),
        storage_provider=os.getenv("STORAGE_PROVIDER", ""),
        x_app_id=os.getenv("X_APP_ID", ""),
        autonomous_enabled=truth("AUTONOMOUS_ENABLED"),
        allow_external_send=truth("ALLOW_EXTERNAL_SEND"),
        kill_switch=truth("KILL_SWITCH"),
        x_write_enabled=truth("X_WRITE_ENABLED"),
        allow_automated_replies=truth("ALLOW_AUTOMATED_REPLIES"),
        write_credentials_configured=all(os.getenv(name, "") for name in write_names),
        epoch=epoch,
        max_daily_posts=int(os.getenv("MAX_DAILY_POSTS", "2")),
    )


def run_cycle() -> dict:
    names = ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_TOKEN_SECRET")
    transport = TweepySinglePostTransport(*(os.environ[name] for name in names))
    result = ProductionAutonomousRunner(client(), run_config(), transport, seed=int(os.getenv("DIRECTOR_SEED", "1"))).run(
        datetime.now(ZoneInfo(os.getenv("TIMEZONE", "Asia/Tokyo")))
    )
    return result


def run_mentions() -> dict:
    config = XReadConfig(
        os.getenv("APP_ENV", ""),
        os.getenv("X_HANDLE", ""),
        truth("X_READ_ENABLED"),
        truth("X_WRITE_ENABLED"),
        truth("ALLOW_EXTERNAL_SEND"),
        truth("AUTONOMOUS_ENABLED"),
        truth("KILL_SWITCH"),
        int(os.getenv("X_BACKFILL_LIMIT", "10")),
        int(os.getenv("X_MAX_PAGES", "1")),
        truth("ALLOW_AUTOMATED_REPLIES"),
    )
    result = run_x_read(XReadClient(os.getenv("X_BEARER_TOKEN", "")), client(), config, force_resolve=False)
    return {key: result.get(key) for key in ("status", "fetched", "stored", "duplicates", "ignored", "self_excluded", "classifications", "api_calls", "reason") if key in result}


def health() -> dict:
    db = client()
    storage = SupabaseStorage(db)
    memory = storage.load_memory()
    marker = db.select("production_metadata", "select=environment,schema_version&singleton=eq.true&limit=1")
    snapshots = db.select("public_state_snapshots", "select=id,created_at&published=eq.true&order=created_at.desc&limit=1")
    cursors = db.select("x_read_cursors", "select=last_status,last_successful_x_read_at,last_seen_mention_id&key=eq.mentions&limit=1")
    candidates = db.select("reply_candidates", "select=id,status")
    last_run = db.select("job_runs", "select=run_id,status,decision,finished_at&order=started_at.desc&limit=1")
    return {
        "environment": marker[0]["environment"] if marker else "missing",
        "schema_version": marker[0]["schema_version"] if marker else None,
        "memory_version": storage.memory_version,
        "posts": len(memory.posts),
        "weeks": len(memory.weeks),
        "open_events": sum(event.get("status") == "open" for event in memory.events),
        "last_run": last_run[0] if last_run else None,
        "mentions_cursor": "configured" if cursors and cursors[0].get("last_seen_mention_id") else "empty",
        "last_mentions_status": cursors[0].get("last_status") if cursors else "never",
        "reply_candidates": len(candidates),
        "public_state": "published" if snapshots else "missing",
        "safety": {
            "autonomous": truth("AUTONOMOUS_ENABLED"),
            "external_send": truth("ALLOW_EXTERNAL_SEND"),
            "x_write": truth("X_WRITE_ENABLED"),
            "kill_switch": truth("KILL_SWITCH"),
            "automated_replies": truth("ALLOW_AUTOMATED_REPLIES"),
        },
        "x_api_requests": 0,
        "x_write_count": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="pandausagies V2 production runner")
    parser.add_argument("command", choices=("cycle", "mentions", "run-all", "health"))
    args = parser.parse_args()
    load_environment()
    if args.command == "cycle":
        report = {"cycle": run_cycle()}
    elif args.command == "mentions":
        report = {"mentions": run_mentions()}
    elif args.command == "health":
        report = health()
    else:
        cycle = run_cycle()
        mentions = run_mentions()
        report = {
            "cycle": cycle,
            "mentions": mentions,
            "x_api_requests": int(cycle.get("x_api_requests", 0)) + int(mentions.get("api_calls", 0)),
            "x_write_count": int(cycle.get("x_write_count", 0)),
            "automated_reply_writes": 0,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
