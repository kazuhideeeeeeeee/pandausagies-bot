from __future__ import annotations

import argparse
import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path

from pandausagies_v2.autonomous import format_observation, observe
from pandausagies_v2.production_storage import SQLiteStorage, SupabaseHttpClient, SupabaseStorage
from pandausagies_v2.safety import SafetyConfig


def main() -> None:
    env_path=Path(__file__).resolve().parent/".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                key,value=raw.split("=",1); os.environ.setdefault(key.strip(),value.strip())
    parser = argparse.ArgumentParser(description="Observe pandausagies autonomous decisions safely")
    parser.add_argument("--observe", action="store_true", help="read-only decision preview")
    parser.add_argument("--health", action="store_true", help="read-only production safety status")
    parser.add_argument("--storage", default="var/autonomous.sqlite3")
    parser.add_argument("--credentials", action="store_true", help="show configured/missing/invalid only")
    parser.add_argument("--reset-circuit", action="store_true")
    parser.add_argument("--confirm-reset-circuit", action="store_true")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if args.credentials:
        import json
        present=lambda *names: "configured" if all(os.getenv(name,"") for name in names) else "missing"
        url=os.getenv("SUPABASE_URL",""); epoch=os.getenv("AUTONOMOUS_EPOCH",""); timezone=os.getenv("TIMEZONE","Asia/Tokyo")
        try: ZoneInfo(timezone); tz="configured"
        except ZoneInfoNotFoundError: tz="invalid format"
        try: parsed=datetime.fromisoformat(epoch); epoch_status="configured" if parsed.tzinfo else "invalid format"
        except ValueError: epoch_status="missing" if not epoch else "invalid format"
        report={"mode":"CREDENTIALS","x_credentials":present("API_KEY","API_SECRET","ACCESS_TOKEN","ACCESS_TOKEN_SECRET"),"supabase_url":"configured" if url.startswith("https://") else ("missing" if not url else "invalid format"),"supabase_publishable_key":present("SUPABASE_PUBLISHABLE_KEY"),"supabase_secret_key":present("SUPABASE_SECRET_KEY"),"timezone":tz,"autonomous_epoch":epoch_status}
        print(json.dumps(report,ensure_ascii=False,indent=2)); return
    if args.reset_circuit:
        if not args.confirm_reset_circuit: parser.error("--confirm-reset-circuit is required")
        if os.getenv("STORAGE_PROVIDER")=="supabase":
            if os.getenv("APP_ENV")!="staging": parser.error("Supabase circuit reset is staging-only")
            store=SupabaseStorage(SupabaseHttpClient(os.getenv("SUPABASE_URL",""),os.getenv("SUPABASE_SECRET_KEY","")))
            store.set_setting("consecutive_errors",0); store.set_setting("circuit_open",False)
        else: SQLiteStorage(Path(args.storage)).set_setting("consecutive_errors",0)
        print("circuit breaker reset by human command"); return
    if args.health:
        import json
        config=SafetyConfig.from_env()
        try:
            if os.getenv("STORAGE_PROVIDER")=="supabase": store=SupabaseStorage(SupabaseHttpClient(os.getenv("SUPABASE_URL",""),os.getenv("SUPABASE_SECRET_KEY","")))
            else: store=SQLiteStorage(Path(args.storage))
            report=store.health(); report.update({"mode":"HEALTH","kill_switch":"ON" if config.kill_switch else "OFF","x_provider":os.getenv("X_PROVIDER","fake").upper(),"external_send":"ENABLED" if config.allow_external_send else "DISABLED","autonomous":"ENABLED" if config.autonomous_enabled else "DISABLED"})
        except Exception:
            report={"mode":"HEALTH","storage":"ERROR","memory":"UNKNOWN","kill_switch":"ON" if config.kill_switch else "OFF","external_send":"DISABLED","autonomous":"DISABLED","consecutive_errors":"UNKNOWN"}
        print(json.dumps(report,ensure_ascii=False,indent=2)); return
    if args.observe: print(format_observation(observe(seed=args.seed))); return
    parser.error("use --observe or --health")


if __name__ == "__main__":
    main()
