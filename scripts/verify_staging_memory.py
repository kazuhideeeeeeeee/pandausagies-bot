#!/usr/bin/env python3
"""Real Supabase staging verification with Fake X and redacted output."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib import error, request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pandausagies_v2.memory import Memory
from pandausagies_v2.persistent_simulation import run_days
from pandausagies_v2.production_storage import SQLiteStorage, SupabaseError, SupabaseHttpClient, SupabaseStorage

RESET_PHRASE = "RESET pandausagies-v2-staging"


def require_safe_environment() -> None:
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip()
    expected = {
        "APP_ENV": "staging", "STORAGE_PROVIDER": "supabase", "X_PROVIDER": "fake",
        "ALLOW_EXTERNAL_SEND": "false", "AUTONOMOUS_ENABLED": "false",
        "KILL_SWITCH": "true", "FAKE_EXTERNALS": "true",
    }
    if any(os.getenv(key, "").lower() != value for key, value in expected.items()):
        raise SystemExit("safe staging environment check failed")
    if os.getenv("AUTONOMOUS_EPOCH"):
        raise SystemExit("AUTONOMOUS_EPOCH must remain unset")


def anon_status(url: str, key: str, table: str) -> int:
    req = request.Request(
        f"{url.rstrip('/')}/rest/v1/{table}?select=*&limit=1",
        headers={"apikey": key, "Accept": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            response.read()  # held in memory and deliberately not printed
            return response.status
    except error.HTTPError as exc:
        exc.read()
        return exc.code


def anon_read(url: str, key: str, table: str) -> tuple[int, object]:
    req = request.Request(f"{url.rstrip('/')}/rest/v1/{table}?select=*&order=created_at.desc&limit=10", headers={"apikey":key,"Accept":"application/json"})
    try:
        with request.urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read())
    except error.HTTPError as exc:
        exc.read(); return exc.code, None


def clean_staging(client: SupabaseHttpClient) -> None:
    """Client-side double guard plus dependency-ordered staging cleanup."""
    if os.environ.get("APP_ENV") != "staging":
        raise SystemExit("staging cleanup refused")
    marker = client.select("staging_metadata", "select=environment&singleton=eq.true&limit=1")
    if marker != [{"environment": "staging"}]:
        raise SystemExit("remote staging marker missing")
    for table in ("public_state_snapshots","usage_history","delivery_ledger","post_decisions","weeks","errors","life_events","job_runs","job_leases","settings"):
        client.delete(table, "environment=eq.staging")
    client.patch("memory_state", "singleton=eq.true&environment=eq.staging", {"version":0,"value":{}})


def main() -> int:
    require_safe_environment()
    url = os.environ["SUPABASE_URL"]
    publishable = os.environ["SUPABASE_PUBLISHABLE_KEY"]
    secret = os.environ["SUPABASE_SECRET_KEY"]
    client = SupabaseHttpClient(url, secret, timeout=60)
    clean_staging(client)

    first = SupabaseStorage(client)
    assert first.acquire_lock("verify", "owner-a", ttl_seconds=60)
    assert not first.acquire_lock("verify", "owner-b", ttl_seconds=60)
    assert first.heartbeat_lock("verify", "owner-a", ttl_seconds=60)
    first.release_lock("verify", "owner-b")
    assert not first.acquire_lock("verify", "owner-b", ttl_seconds=1)
    first.release_lock("verify", "owner-a")
    assert first.acquire_lock("expiry", "owner-a", ttl_seconds=1)
    time.sleep(1.2)
    assert first.acquire_lock("expiry", "owner-b", ttl_seconds=60)
    first.release_lock("expiry", "owner-b")

    memory = first.load_memory()
    first.save_memory(memory)
    stale = SupabaseStorage(client)
    stale.load_memory()
    fresh = SupabaseStorage(client)
    latest = fresh.load_memory(); latest.settings["cas_probe"] = True; fresh.save_memory(latest)
    conflict = False
    try:
        stale.save_memory(memory)
    except SupabaseError:
        conflict = True
    assert conflict

    before = client.select("memory_state", "select=version&singleton=eq.true")[0]["version"]
    rollback = False
    try:
        client.rpc("commit_run_decision", {"p_run_id":"missing-run","p_action":"skip","p_reason":"rollback probe","p_snapshot":{},"p_expected_memory_version":before,"p_memory":{}})
    except SupabaseError:
        rollback = True
    after = client.select("memory_state", "select=version&singleton=eq.true")[0]["version"]
    assert rollback and before == after

    client.insert("job_runs", {"run_id":"idempotency-probe","mode":"dry_run","status":"running"})
    duplicate_rejected = False
    try:
        client.insert("job_runs", {"run_id":"idempotency-probe","mode":"dry_run","status":"running"})
    except SupabaseError:
        duplicate_rejected = True
    assert duplicate_rejected

    # One run owns at most one decision, ledger row and WEEK.
    client.insert("post_decisions", {"run_id":"idempotency-probe","action":"skip","reason":"probe","snapshot":{}})
    client.insert("delivery_ledger", {"idempotency_key":"probe-key","run_id":"idempotency-probe","kind":"post","status":"candidate","payload":{}})
    client.insert("weeks", {"week_number":999,"run_id":"idempotency-probe","body":"staging probe","status":"simulated"})
    for table,payload in (("post_decisions",{"run_id":"idempotency-probe","action":"skip","reason":"probe","snapshot":{}}),("delivery_ledger",{"idempotency_key":"probe-key","run_id":"idempotency-probe","kind":"post","status":"candidate","payload":{}}),("weeks",{"week_number":999,"run_id":"idempotency-probe","body":"staging probe","status":"simulated"})):
        try: client.insert(table,payload)
        except SupabaseError: pass
        else: raise AssertionError(f"duplicate accepted: {table}")

    assert anon_status(url, publishable, "public_state_snapshots") == 200
    assert anon_status(url, publishable, "memory_state") in (401, 403)
    public_payload={"version":1,"generated_at":"2026-08-24T00:00:00Z","currentWeek":{"id":"staging-week","week":0},"pastWeeks":[]}
    client.insert("public_state_snapshots", {"payload":public_payload,"published":True})
    client.insert("public_state_snapshots", {"payload":{"private":"draft"},"published":False})
    public_status, public_rows = anon_read(url,publishable,"public_state_snapshots")
    assert public_status==200 and len(public_rows)==1 and public_rows[0]["payload"]==public_payload
    for private_table in ("job_runs","post_decisions","errors","settings","job_leases","delivery_ledger","memory_state","life_events","contacts","conversations","reply_candidates","metrics","posts"):
        # 404 is also a safe result for intentionally unprovisioned future tables.
        assert anon_status(url,publishable,private_table) in (401,403,404)

    clean_staging(client)
    with tempfile.TemporaryDirectory(prefix="pandausagies-staging-") as folder:
        local = SQLiteStorage(Path(folder) / "simulation.sqlite3")
        start = datetime(2026, 8, 24, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
        for day in range(30):
            run_days(local, start, day, 1, seed=6100)
            remote = SupabaseStorage(client)
            remote.load_memory()
            remote.save_memory(local.load_memory())
            if day in (9, 19, 29):
                assert SupabaseStorage(client).load_memory().to_dict() == local.load_memory().to_dict()
            if day == 14:
                child=subprocess.run([sys.executable,str(Path(__file__).resolve()),"--restart-probe"],capture_output=True,check=False)
                assert child.returncode==0 and not child.stdout and not child.stderr
        result = local.load_memory()
        summary = {"days":30,"posts":len(result.posts),"weeks":len(result.weeks),"events":len(result.events)}

    # Leave staging clean: no production WEEK 01 and no public snapshot is published.
    clean_staging(client)
    report = {
        "environment":"staging", "x_provider":"fake", "external_send":False,
        "lease":"passed", "heartbeat":"passed", "cas_conflict":"passed",
        "rollback":"passed", "idempotency":"passed", "anon_public":"passed",
        "anon_private":"blocked", "restart":"passed", "simulation":summary,
        "public_state":"passed", "sqlite_semantic_match":"passed",
        "staging_reset":"passed", "production_week_started":False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if "--restart-probe" in sys.argv:
        require_safe_environment()
        probe=SupabaseStorage(SupabaseHttpClient(os.environ["SUPABASE_URL"],os.environ["SUPABASE_SECRET_KEY"],timeout=60)).load_memory()
        raise SystemExit(0 if probe.posts else 2)
    raise SystemExit(main())
