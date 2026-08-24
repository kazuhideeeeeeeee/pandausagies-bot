from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import parse

from .autonomous import build_director
from .director import Decision, apply_decision
from .fake_production import logical_run_id
from .production_adapters import payload_fingerprint
from .production_storage import SupabaseHttpClient, SupabaseStorage
from .safety import stable_seed
from .write_preflight import _parse_time, validate_post_candidate
from .x_write_once import (
    DefiniteDeliveryFailure,
    DeliveryStateUnknown,
    EXPECTED_APP_ID,
    XPostTransport,
)


@dataclass(frozen=True)
class ProductionRunConfig:
    app_env: str
    storage_provider: str
    x_app_id: str
    autonomous_enabled: bool
    allow_external_send: bool
    kill_switch: bool
    x_write_enabled: bool
    allow_automated_replies: bool
    write_credentials_configured: bool
    epoch: datetime
    max_daily_posts: int = 2
    fingerprint_cooldown_hours: int = 24

    def require_safe(self) -> None:
        if self.app_env != "production" or self.storage_provider != "supabase":
            raise RuntimeError("production environment guard failed")
        if self.x_app_id != EXPECTED_APP_ID or not self.write_credentials_configured:
            raise RuntimeError("production X credential guard failed")
        if not self.autonomous_enabled or not self.allow_external_send or self.kill_switch or not self.x_write_enabled:
            raise RuntimeError("production autonomous gates are closed")
        if self.allow_automated_replies:
            raise RuntimeError("automated replies must remain disabled")
        if self.epoch.tzinfo is None:
            raise RuntimeError("autonomous epoch must be timezone-aware")


def public_state_payload(client: SupabaseHttpClient, memory: Any, generated_at: datetime, version: int) -> dict[str, Any]:
    media_rows = client.select("public_media", "select=id,public_url&active=eq.true")
    media = {row["id"]: row["public_url"] for row in media_rows}
    weeks = []
    for index, week in enumerate(memory.weeks, start=1):
        weeks.append(
            {
                "id": week.get("id") or f"week-{index:02d}",
                "week": int(week.get("week") or index),
                "date": week.get("date"),
                "image": media.get(week.get("media_id"), ""),
                "text": week.get("text", ""),
                "songId": week.get("song_id"),
            }
        )
    return {
        "version": version,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "currentWeek": weeks[-1] if weeks else None,
        "pastWeeks": weeks[:-1],
    }


class ProductionAutonomousRunner:
    """One production Director cycle with no retries and fail-closed delivery semantics."""

    def __init__(self, client: SupabaseHttpClient, config: ProductionRunConfig, transport: XPostTransport, seed: int = 1):
        self.client = client
        self.storage = SupabaseStorage(client)
        self.config = config
        self.transport = transport
        self.seed = seed

    def _publish_public_state(self, memory: Any, now: datetime) -> int:
        version = int(self.storage.get_setting("public_version", 0) or 0) + 1
        snapshot_id = int(self.client.rpc("publish_public_state", {"p_payload": public_state_payload(self.client, memory, now, version)}))
        self.storage.set_setting("public_version", version)
        return snapshot_id

    def _record_error(self, run_id: str, category: str) -> None:
        count = int(self.storage.get_setting("consecutive_errors", 0) or 0) + 1
        self.storage.set_setting("consecutive_errors", count)
        if count >= 3:
            self.storage.set_setting("circuit_open", True)
        try:
            self.client.insert("errors", {"run_id": run_id, "severity": "critical", "message": category, "context": {"source": "production_runner"}})
        except Exception:
            pass

    def _safe_publish_public_state(self, report: dict[str, Any], memory: Any, now: datetime) -> None:
        try:
            report["public_state_snapshot_id"] = self._publish_public_state(memory, now)
            report["public_state"] = "updated"
        except Exception:
            report["public_state"] = "failed_static_fallback_active"

    def run(self, now: datetime) -> dict[str, Any]:
        self.config.require_safe()
        if now.tzinfo is None or now < self.config.epoch:
            raise RuntimeError("production clock/epoch guard failed")
        scheduled = now.replace(second=0, microsecond=0)
        run_id = logical_run_id("autonomous-cycle", scheduled)
        report: dict[str, Any] = {
            "run_id": run_id,
            "decision": "safe_stopped",
            "reason": None,
            "x_api_requests": 0,
            "x_write_count": 0,
            "ledger_status": None,
            "public_state": "not_updated",
        }
        if not self.storage.acquire_lock("autonomous-cycle", run_id, scheduled, ttl_seconds=300):
            report["reason"] = "lock unavailable"
            return report
        staged = False
        external_attempted = False
        try:
            existing = self.client.select("job_runs", f"select=run_id,status&run_id=eq.{parse.quote(run_id)}&limit=1")
            if existing:
                report.update(decision="duplicate", reason="run already recorded", ledger_status=existing[0].get("status"))
                return report
            unknown = self.client.select("delivery_ledger", "select=run_id&status=eq.sending&external_id=is.null&limit=1")
            if unknown:
                report["reason"] = "delivery reconciliation required"
                return report
            if bool(self.storage.get_setting("circuit_open", False)) or int(self.storage.get_setting("consecutive_errors", 0) or 0) >= 3:
                report["reason"] = "circuit breaker open"
                return report
            last_at = _parse_time(self.storage.get_setting("last_autonomous_at", ""))
            if last_at and scheduled.astimezone(timezone.utc) < last_at.astimezone(timezone.utc):
                report["reason"] = "clock moved backwards"
                return report

            memory = self.storage.load_memory()
            before = memory.clone()
            today_count = sum(p.get("at", "")[:10] == scheduled.date().isoformat() for p in before.posts)
            if today_count >= self.config.max_daily_posts:
                decision = Decision(scheduled.isoformat(), "skip", None, None, None, "none", None, None, False, "", "daily hard limit")
            else:
                decision = build_director(stable_seed(self.seed, run_id)).decide(scheduled, memory, weekly_due=False)

            if decision.action == "skip":
                apply_decision(memory, decision, mutate_week=False)
                self.client.insert("job_runs", {"run_id": run_id, "mode": "send", "status": "running", "started_at": scheduled.astimezone(timezone.utc).isoformat()})
                self.client.rpc(
                    "commit_run_decision",
                    {
                        "p_run_id": run_id,
                        "p_action": "skip",
                        "p_reason": decision.reason,
                        "p_snapshot": decision.to_dict(),
                        "p_expected_memory_version": self.storage.memory_version,
                        "p_memory": memory.to_dict(),
                        "p_category": None,
                        "p_motif": decision.motif,
                        "p_event_id": decision.event_id,
                        "p_song_id": None,
                        "p_media_id": None,
                        "p_include_url": False,
                    },
                )
                self.client.patch("job_runs", f"run_id=eq.{parse.quote(run_id)}", {"status": "succeeded", "finished_at": datetime.now(timezone.utc).isoformat()})
                self.storage.set_setting("last_autonomous_at", scheduled.astimezone(timezone.utc).isoformat())
                report.update(decision="skip", reason=decision.reason, ledger_status="not_created")
                self._safe_publish_public_state(report, memory, scheduled)
                return report

            validation = validate_post_candidate(decision.text, decision.category or "", decision.include_url)
            if not validation["valid"] or decision.category not in ("ordinary", "offbeat") or decision.include_url:
                raise RuntimeError("social voice or category guard failed")
            idempotency_key = f"x:{run_id}"
            payload = {
                **decision.to_dict(),
                "scheduled_jst": scheduled.isoformat(),
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "media_path": None,
                "media_hash": None,
                "url": None,
                "x_app_id": EXPECTED_APP_ID,
                "autonomous": True,
                "fingerprint": None,
            }
            fingerprint = payload_fingerprint(payload)
            payload["fingerprint"] = fingerprint
            cutoff = scheduled.astimezone(timezone.utc) - timedelta(hours=self.config.fingerprint_cooldown_hours)
            ledger_rows = self.client.select("delivery_ledger", "select=status,payload,updated_at")
            fingerprint_duplicate = any(
                row.get("status") in ("candidate", "sending", "sent")
                and (row.get("payload") or {}).get("fingerprint") == fingerprint
                and (_parse_time(row.get("updated_at")) or scheduled.astimezone(timezone.utc)) >= cutoff
                for row in ledger_rows
            )
            text_duplicate = any(
                p.get("text") == decision.text
                and (_parse_time(p.get("at")) or scheduled.astimezone(timezone.utc)) >= cutoff
                for p in before.posts
            )
            if fingerprint_duplicate or text_duplicate:
                raise RuntimeError("duplicate guard failed")

            apply_decision(memory, decision, mutate_week=False)
            self.client.rpc(
                "stage_autonomous_post",
                {
                    "p_run_id": run_id,
                    "p_idempotency_key": idempotency_key,
                    "p_fingerprint": fingerprint,
                    "p_payload": payload,
                    "p_decision": decision.to_dict(),
                    "p_expected_memory_version": self.storage.memory_version,
                    "p_memory": memory.to_dict(),
                },
            )
            staged = True
            report.update(decision="post", reason=decision.reason, text=decision.text, category=decision.category, motif=decision.motif, ledger_status="candidate")
            self.client.rpc("begin_autonomous_post", {"p_run_id": run_id, "p_idempotency_key": idempotency_key, "p_fingerprint": fingerprint})
            report["ledger_status"] = "sending"
            external_attempted = True
            response = self.transport.create_post_once(decision.text)
            report["x_api_requests"] = self.transport.calls
            report["x_write_count"] = self.transport.calls
            if not response.post_id:
                raise DeliveryStateUnknown("missing_post_id")
            self.client.rpc(
                "complete_autonomous_post",
                {
                    "p_run_id": run_id,
                    "p_idempotency_key": idempotency_key,
                    "p_external_id": response.post_id,
                    "p_motif": decision.motif,
                    "p_song_id": decision.song_id,
                    "p_media_id": decision.media_id,
                },
            )
            self.storage.set_setting("last_autonomous_at", scheduled.astimezone(timezone.utc).isoformat())
            report.update(http_status=response.http_status, remote_post_id=response.post_id, ledger_status="sent")
            external_attempted = False
            self._safe_publish_public_state(report, memory, scheduled)
            return report
        except DeliveryStateUnknown as exc:
            report.update(reason=exc.category, x_api_requests=self.transport.calls, x_write_count=self.transport.calls)
            if staged:
                self.client.rpc("stop_autonomous_post", {"p_run_id": run_id, "p_idempotency_key": f"x:{run_id}", "p_delivery_unknown": True, "p_error_category": exc.category})
                report["ledger_status"] = "sending_reconciliation_required"
            self._record_error(run_id, exc.category)
            return report
        except DefiniteDeliveryFailure as exc:
            report.update(reason=exc.category, http_status=exc.http_status, x_api_requests=self.transport.calls, x_write_count=self.transport.calls)
            if staged:
                self.client.rpc("stop_autonomous_post", {"p_run_id": run_id, "p_idempotency_key": f"x:{run_id}", "p_delivery_unknown": False, "p_error_category": exc.category})
                report["ledger_status"] = "failed"
            self._record_error(run_id, exc.category)
            return report
        except Exception:
            category = "unexpected_after_send" if external_attempted else "local_preflight_failure"
            report.update(reason=category, x_api_requests=self.transport.calls, x_write_count=self.transport.calls)
            if staged:
                self.client.rpc("stop_autonomous_post", {"p_run_id": run_id, "p_idempotency_key": f"x:{run_id}", "p_delivery_unknown": external_attempted, "p_error_category": category})
                report["ledger_status"] = "sending_reconciliation_required" if external_attempted else "failed"
            self._record_error(run_id, category)
            return report
        finally:
            try:
                self.storage.release_lock("autonomous-cycle", run_id)
            except Exception:
                pass
