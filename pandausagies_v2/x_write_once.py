from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib import parse

from .director import Decision, apply_decision
from .fake_production import logical_run_id
from .memory import Memory
from .production_adapters import payload_fingerprint
from .production_storage import SupabaseHttpClient, SupabaseStorage
from .write_preflight import _parse_time, validate_post_candidate


EXPECTED_APP_ID = "31849050"
APPROVED_TEXT = "メガネのねじを締めた\n小さいドライバーを使った"
APPROVED_CATEGORY = "ordinary"
APPROVED_MOTIF = "glasses"
PHASE8_RUN_ID = "x-first-post-preflight:2026-08-24T07:37:00Z"


@dataclass(frozen=True)
class OneShotConfig:
    app_env: str
    x_app_id: str
    allow_external_send: bool
    autonomous_enabled: bool
    kill_switch: bool
    x_write_enabled: bool
    write_credentials_configured: bool
    human_approved: bool
    max_daily_posts: int = 2

    def require_persisted_stop_state(self) -> None:
        if self.app_env != "staging":
            raise RuntimeError("one-shot send is staging-only")
        if self.x_app_id != EXPECTED_APP_ID:
            raise RuntimeError("unexpected X app")
        if not self.write_credentials_configured:
            raise RuntimeError("write credentials incomplete")
        if self.allow_external_send or self.autonomous_enabled or not self.kill_switch or self.x_write_enabled:
            raise RuntimeError("persisted safety flags are not stopped")
        if not self.human_approved:
            raise RuntimeError("one-shot human approval missing")


@dataclass(frozen=True)
class XPostResponse:
    http_status: int
    post_id: str


class XPostTransport(Protocol):
    calls: int

    def create_post_once(self, text: str) -> XPostResponse: ...


class DeliveryStateUnknown(RuntimeError):
    def __init__(self, category: str = "response_unknown"):
        super().__init__(category)
        self.category = category


class DefiniteDeliveryFailure(RuntimeError):
    def __init__(self, http_status: int | None, category: str):
        super().__init__(category)
        self.http_status, self.category = http_status, category


def rollback_phase8_memory(memory: Memory) -> Memory:
    """Remove only the exact, sole Phase 8 dry-run mutation; fail closed otherwise."""
    cleaned = memory.clone()
    expected = {
        "at": "2026-08-24T16:37:00+09:00",
        "text": APPROVED_TEXT,
        "motif": APPROVED_MOTIF,
        "action": "post",
        "reason": "daily autonomous trace",
        "song_id": None,
        "week_id": None,
        "category": APPROVED_CATEGORY,
        "event_id": "glasses-2026-08-24",
        "media_id": None,
        "include_url": False,
        "event_action": "start",
    }
    if len(cleaned.posts) != 1 or cleaned.posts[0] != expected:
        raise RuntimeError("Phase 8 post memory is not exactly supersedable")
    if len(cleaned.decisions) != 1 or cleaned.decisions[0] != expected:
        raise RuntimeError("Phase 8 decision memory is not exactly supersedable")
    if cleaned.motif_usage != {APPROVED_MOTIF: [expected["at"]]}:
        raise RuntimeError("Phase 8 motif memory is not exactly supersedable")
    if len(cleaned.events) != 1 or cleaned.events[0].get("id") != expected["event_id"] or cleaned.events[0].get("related_posts") != [0]:
        raise RuntimeError("Phase 8 event memory is not exactly supersedable")
    cleaned.posts.clear()
    cleaned.decisions.clear()
    cleaned.events.clear()
    cleaned.motif_usage.clear()
    return cleaned


def _safe_report_base(run_id: str | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "http_status": None,
        "post_text": APPROVED_TEXT,
        "remote_post_id": None,
        "run_id": run_id,
        "ledger_status": None,
        "memory_saved": False,
        "usage_updated": False,
        "duplicate_external_effects": 0,
        "x_api_requests": 0,
        "x_write_count": 0,
        "safety_flags_restored": True,
    }


class ProductionXSinglePost:
    """Human-approved, no-retry path for exactly one text-only X post."""

    def __init__(self, client: SupabaseHttpClient, config: OneShotConfig, transport: XPostTransport):
        self.client, self.storage, self.config, self.transport = client, SupabaseStorage(client), config, transport

    def run(self, now: datetime) -> dict[str, Any]:
        self.config.require_persisted_stop_state()
        if now.tzinfo is None:
            raise RuntimeError("current time must be timezone-aware")
        scheduled = now.replace(microsecond=0)
        run_id = logical_run_id("x-first-live-post", scheduled)
        idempotency_key = f"x:{run_id}"
        report = _safe_report_base(run_id)
        if not self.storage.acquire_lock("x-write-once", run_id, scheduled, ttl_seconds=300):
            report["ledger_status"] = "not_staged"
            report["error_category"] = "lock_unavailable"
            return report
        staged = False
        external_attempted = False
        try:
            memory = self.storage.load_memory()
            phase8 = self.client.select(
                "delivery_ledger",
                f"select=run_id,status,external_id&run_id=eq.{parse.quote(PHASE8_RUN_ID)}&limit=1",
            )
            if phase8 and phase8[0].get("status") == "candidate" and not phase8[0].get("external_id"):
                cleaned = rollback_phase8_memory(memory)
                self.client.rpc(
                    "supersede_x_write_preflight",
                    {
                        "p_run_id": PHASE8_RUN_ID,
                        "p_expected_memory_version": self.storage.memory_version,
                        "p_memory": cleaned.to_dict(),
                    },
                )
                memory = self.storage.load_memory()
            elif phase8 and phase8[0].get("status") != "failed":
                raise RuntimeError("Phase 8 ledger has an unsafe state")

            now_utc = scheduled.astimezone(timezone.utc)
            existing_run = self.client.select("job_runs", f"select=run_id&run_id=eq.{parse.quote(run_id)}&limit=1")
            existing_key = self.client.select("delivery_ledger", f"select=idempotency_key&idempotency_key=eq.{parse.quote(idempotency_key)}&limit=1")
            if existing_run or existing_key:
                raise RuntimeError("duplicate run or idempotency key")
            circuit_open = bool(self.storage.get_setting("circuit_open", False)) or int(self.storage.get_setting("consecutive_errors", 0) or 0) >= 3
            if circuit_open:
                raise RuntimeError("circuit breaker open")
            today_count = sum(p.get("at", "")[:10] == scheduled.date().isoformat() for p in memory.posts)
            if today_count >= self.config.max_daily_posts:
                raise RuntimeError("daily hard limit")
            validation = validate_post_candidate(APPROVED_TEXT, APPROVED_CATEGORY, False)
            if not validation["valid"]:
                raise RuntimeError("social voice validation failed")
            payload = {
                "at": scheduled.isoformat(),
                "text": APPROVED_TEXT,
                "action": "post",
                "category": APPROVED_CATEGORY,
                "motif": APPROVED_MOTIF,
                "event_id": None,
                "event_action": "none",
                "song_id": None,
                "media_id": None,
                "media_hash": None,
                "media_path": None,
                "include_url": False,
                "url": None,
                "week_id": None,
                "reason": "Phase 8 validated first live post",
                "scheduled_jst": scheduled.isoformat(),
                "run_id": run_id,
                "idempotency_key": idempotency_key,
                "x_app_id": EXPECTED_APP_ID,
                "human_approved_single_post": True,
            }
            fingerprint = payload_fingerprint(payload)
            payload["fingerprint"] = fingerprint
            cutoff = now_utc - timedelta(hours=24)
            ledgers = self.client.select("delivery_ledger", "select=status,payload,updated_at")
            duplicate = any(
                row.get("status") in ("candidate", "sending", "sent")
                and (row.get("payload") or {}).get("fingerprint") == fingerprint
                and (_parse_time(row.get("updated_at")) or now_utc) >= cutoff
                for row in ledgers
            )
            text_duplicate = any(
                p.get("text") == APPROVED_TEXT and (_parse_time(p.get("at")) or now_utc) >= cutoff
                for p in memory.posts
            )
            if duplicate or text_duplicate:
                raise RuntimeError("duplicate guard")
            decision = Decision(
                scheduled.isoformat(), "post", APPROVED_CATEGORY, APPROVED_MOTIF, None, "none",
                None, None, False, APPROVED_TEXT, "Phase 8 validated first live post", None,
            )
            updated_memory = memory.clone()
            apply_decision(updated_memory, decision, mutate_week=False)
            self.client.rpc(
                "stage_x_single_post",
                {
                    "p_run_id": run_id,
                    "p_idempotency_key": idempotency_key,
                    "p_fingerprint": fingerprint,
                    "p_payload": payload,
                    "p_decision": decision.to_dict(),
                    "p_expected_memory_version": self.storage.memory_version,
                    "p_memory": updated_memory.to_dict(),
                },
            )
            staged = True
            report.update(
                ledger_status="candidate",
                memory_saved=True,
                fingerprint=fingerprint,
                validation=validation,
                preflight={
                    "duplicate_guard": "passed",
                    "fingerprint_24h": "passed",
                    "daily_hard_limit": "passed",
                    "circuit_breaker": "passed",
                    "supabase": "passed",
                    "ledger": "candidate",
                },
            )

            # Temporary gates exist only in this call. The persisted .env remains stopped.
            temporary_allow_external_send = True
            temporary_kill_switch = False
            temporary_x_write_enabled = True
            if not (temporary_allow_external_send and not temporary_kill_switch and temporary_x_write_enabled):
                raise RuntimeError("temporary one-shot gates failed")
            self.client.rpc(
                "begin_x_single_post",
                {"p_run_id": run_id, "p_idempotency_key": idempotency_key, "p_fingerprint": fingerprint},
            )
            report["ledger_status"] = "sending"
            external_attempted = True
            response = self.transport.create_post_once(APPROVED_TEXT)
            report["x_api_requests"] = self.transport.calls
            report["x_write_count"] = self.transport.calls
            if not response.post_id:
                raise DeliveryStateUnknown("missing_post_id")
            self.client.rpc(
                "complete_x_single_post",
                {
                    "p_run_id": run_id,
                    "p_idempotency_key": idempotency_key,
                    "p_external_id": response.post_id,
                    "p_motif": APPROVED_MOTIF,
                },
            )
            report.update(
                success=True,
                http_status=response.http_status,
                remote_post_id=response.post_id,
                ledger_status="sent",
                usage_updated=True,
            )
            return report
        except DeliveryStateUnknown as exc:
            report["x_api_requests"] = self.transport.calls
            report["x_write_count"] = self.transport.calls
            if staged:
                self.client.rpc("stop_x_single_post", {"p_run_id": run_id, "p_idempotency_key": idempotency_key, "p_delivery_unknown": True, "p_error_category": exc.category})
                report["ledger_status"] = "sending_reconciliation_required"
            report["error_category"] = exc.category
            return report
        except DefiniteDeliveryFailure as exc:
            report.update(http_status=exc.http_status, x_api_requests=self.transport.calls, x_write_count=self.transport.calls)
            if staged:
                self.client.rpc("stop_x_single_post", {"p_run_id": run_id, "p_idempotency_key": idempotency_key, "p_delivery_unknown": False, "p_error_category": exc.category})
                report["ledger_status"] = "failed"
            report["error_category"] = exc.category
            return report
        except Exception as exc:
            report.update(x_api_requests=self.transport.calls, x_write_count=self.transport.calls)
            if staged:
                unknown = external_attempted
                self.client.rpc("stop_x_single_post", {"p_run_id": run_id, "p_idempotency_key": idempotency_key, "p_delivery_unknown": unknown, "p_error_category": "unexpected_after_send" if unknown else "local_preflight_failure"})
                report["ledger_status"] = "sending_reconciliation_required" if unknown else "failed"
            report["error_category"] = "unexpected_after_send" if external_attempted else "local_preflight_failure"
            return report
        finally:
            try:
                self.storage.release_lock("x-write-once", run_id)
            except Exception:
                pass


class TweepySinglePostTransport:
    def __init__(self, consumer_key: str, consumer_secret: str, access_token: str, access_token_secret: str):
        import requests
        import tweepy

        self.calls = 0
        self._requests = requests
        self._tweepy = tweepy
        self._client = tweepy.Client(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
            return_type=requests.Response,
            wait_on_rate_limit=False,
        )

    def create_post_once(self, text: str) -> XPostResponse:
        self.calls += 1
        try:
            response = self._client.create_tweet(text=text)
        except (self._requests.Timeout, self._requests.ConnectionError):
            raise DeliveryStateUnknown("network_or_response_unknown") from None
        except self._tweepy.TweepyException as exc:
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            if status is None:
                raise DeliveryStateUnknown("x_response_unknown") from None
            raise DefiniteDeliveryFailure(int(status), "x_http_rejection") from None
        status = int(response.status_code)
        try:
            post_id = str(response.json().get("data", {}).get("id", ""))
        except (ValueError, AttributeError, TypeError):
            raise DeliveryStateUnknown("invalid_success_response") from None
        if status < 200 or status >= 300:
            raise DefiniteDeliveryFailure(status, "x_http_rejection")
        if not post_id:
            raise DeliveryStateUnknown("missing_post_id")
        return XPostResponse(status, post_id)
