from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib import error, parse, request

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pandausagies_v2.production_storage import SupabaseHttpClient, SupabaseStorage


def anon_status(url: str, publishable: str, table: str, query: str = "select=*&limit=1") -> int:
    req = request.Request(
        f"{url.rstrip('/')}/rest/v1/{parse.quote(table)}?{query}",
        method="GET",
        headers={"apikey": publishable, "Accept": "application/json", "User-Agent": "pandausagies-v2-production-rls-check/1.0"},
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            response.read()
            return int(response.status)
    except error.HTTPError as exc:
        exc.read()
        return int(exc.code)


def main() -> None:
    env = dotenv_values(ROOT / ".env.production")
    url = str(env.get("SUPABASE_URL") or "")
    publishable = str(env.get("SUPABASE_PUBLISHABLE_KEY") or "")
    secret = str(env.get("SUPABASE_SECRET_KEY") or "")
    if env.get("APP_ENV") != "production" or not url.startswith("https://") or not publishable or not secret:
        raise SystemExit("production storage configuration is incomplete")

    client = SupabaseHttpClient(url, secret)
    marker = client.select("production_metadata", "select=environment,schema_version&singleton=eq.true&limit=1")
    storage = SupabaseStorage(client)
    memory = storage.load_memory()
    counts = {
        "songs": len(client.select("public_songs", "select=id&active=eq.true")),
        "media": len(client.select("public_media", "select=id&active=eq.true")),
        "identities": len(client.select("x_account_identities", "select=handle")),
        "sent_ledgers": len(client.select("delivery_ledger", "select=run_id&status=eq.sent")),
        "contacts": len(client.select("contacts", "select=x_user_id")),
        "conversations": len(client.select("conversations", "select=conversation_id")),
        "mentions": len(client.select("mentions", "select=x_post_id")),
        "reply_candidates": len(client.select("reply_candidates", "select=id")),
        "cursors": len(client.select("x_read_cursors", "select=key")),
    }
    public_tables = {
        table: anon_status(url, publishable, table)
        for table in ("public_state_snapshots", "public_songs", "public_media")
    }
    private_tables = {
        table: anon_status(url, publishable, table)
        for table in ("memory_state", "delivery_ledger", "contacts", "mentions", "x_account_identities")
    }
    report = {
        "app_env": "production",
        "production_marker": bool(marker and marker[0].get("environment") == "production"),
        "backend_data_api": "passed",
        "memory_version": storage.memory_version,
        "memory_posts": len(memory.posts),
        **counts,
        "public_rls": "passed" if all(status == 200 for status in public_tables.values()) else "failed",
        "private_rls": "passed" if all(status in (401, 403) for status in private_tables.values()) else "failed",
        "public_statuses": public_tables,
        "private_statuses": private_tables,
        "secret_values_exposed": False,
        "external_writes": 0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
