from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pandausagies_v2.autonomous import build_director
from pandausagies_v2.image_autogen import (
    ImageAutogenConfig,
    StagingImagePipeline,
    SupabaseImageObjectStore,
    SupabaseImageRepository,
    build_image_provider,
)
from pandausagies_v2.production_storage import SupabaseHttpClient, SupabaseStorage
from pandausagies_v2.safety import stable_seed


def load_environment(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one staging-only fake image candidate flow")
    parser.add_argument("--seed", type=int, default=2708)
    args = parser.parse_args()
    load_environment(ROOT / ".env")
    config = ImageAutogenConfig.from_env()
    config.require_phase_a()
    now = datetime.now(ZoneInfo(os.getenv("TIMEZONE", "Asia/Tokyo")))
    client = SupabaseHttpClient(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SECRET_KEY", ""))
    memory = SupabaseStorage(client).load_memory()
    run_id = "image-phase-a:" + now.isoformat(timespec="seconds")
    decision = None
    selected_seed = None
    for offset in range(200):
        seed = stable_seed(args.seed + offset, run_id)
        candidate = build_director(
            seed,
            image_autogen_enabled=config.enabled,
            image_post_ratio=config.post_ratio,
            image_skip_ratio=config.skip_ratio,
        ).decide(now, memory.clone(), weekly_due=False)
        if candidate.action == "post" and candidate.post_type == "image_single":
            decision = candidate
            selected_seed = seed
            break
    if decision is None:
        report = {
            "status": "skipped",
            "reason": "Director did not select image_single within bounded staging probe",
            "attempts": 200,
            "image_api_requests": 0,
            "x_api_requests": 0,
            "x_write": 0,
        }
    else:
        provider = build_image_provider(config)
        result = StagingImagePipeline(
            config,
            provider,
            SupabaseImageRepository(client),
            SupabaseImageObjectStore(
                os.getenv("SUPABASE_URL", ""),
                os.getenv("SUPABASE_SECRET_KEY", ""),
                timeout=config.timeout_seconds,
            ),
        ).run(decision, run_id, now)
        report = {
            **result.to_dict(),
            "director_decision": decision.action,
            "director_post_type": decision.post_type,
            "selected_seed": selected_seed,
            "image_api_requests": 0,
            "supabase_storage": "stored" if result.storage_path else "not_stored",
            "metadata": "stored" if result.status == "approved_candidate" else "job_recorded" if result.plan else "not_stored",
            "safety_gates": {
                "allow_external_send": config.allow_external_send,
                "autonomous_enabled": config.autonomous_enabled,
                "kill_switch": config.kill_switch,
                "x_write_enabled": config.x_write_enabled,
            },
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
