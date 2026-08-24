import unittest
from datetime import datetime, timezone

from pandausagies_v2.memory import Memory
from pandausagies_v2.x_write_once import (
    APPROVED_TEXT,
    DefiniteDeliveryFailure,
    DeliveryStateUnknown,
    OneShotConfig,
    ProductionXSinglePost,
    XPostResponse,
    rollback_phase8_memory,
)


class FakeTransport:
    def __init__(self, outcome):
        self.calls = 0
        self.outcome = outcome

    def create_post_once(self, text):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def phase8_item():
    return {
        "at": "2026-08-24T16:37:00+09:00",
        "text": APPROVED_TEXT,
        "motif": "glasses",
        "action": "post",
        "reason": "daily autonomous trace",
        "song_id": None,
        "week_id": None,
        "category": "ordinary",
        "event_id": "glasses-2026-08-24",
        "media_id": None,
        "include_url": False,
        "event_action": "start",
    }


class FakeSupabaseClient:
    def __init__(self):
        item = phase8_item()
        self.memory = Memory(
            posts=[item], decisions=[item],
            events=[{"id": "glasses-2026-08-24", "related_posts": [0]}],
            motif_usage={"glasses": [item["at"]]},
        ).to_dict()
        self.version = 1
        self.phase8 = {"run_id": "x-first-post-preflight:2026-08-24T07:37:00Z", "status": "candidate", "external_id": None, "payload": {"fingerprint": "old"}, "updated_at": "2026-08-24T07:37:00+00:00"}
        self.live = None
        self.usage = []

    def select(self, table, query=""):
        if table == "memory_state":
            return [{"value": self.memory, "version": self.version}]
        if table == "settings":
            return []
        if table == "job_runs":
            return []
        if table == "delivery_ledger" and "run_id=eq.x-first-post-preflight" in query:
            return [self.phase8]
        if table == "delivery_ledger" and "idempotency_key=eq." in query:
            return []
        if table == "delivery_ledger":
            rows = [self.phase8]
            if self.live:
                rows.append(self.live)
            return rows
        raise AssertionError((table, query))

    def rpc(self, name, payload):
        if name in ("acquire_job_lease", "release_job_lease"):
            return True
        if name == "supersede_x_write_preflight":
            self.phase8["status"] = "failed"
            self.memory = payload["p_memory"]
            self.version += 1
            return True
        if name == "stage_x_single_post":
            self.memory = payload["p_memory"]
            self.version += 1
            self.live = {"run_id": payload["p_run_id"], "status": "candidate", "external_id": None, "payload": payload["p_payload"], "updated_at": "2026-08-24T08:00:00+00:00"}
            return True
        if name == "begin_x_single_post":
            self.live["status"] = "sending"
            return True
        if name == "complete_x_single_post":
            self.live.update(status="sent", external_id=payload["p_external_id"])
            self.usage.append(payload["p_motif"])
            return True
        if name == "stop_x_single_post":
            self.live["status"] = "sending" if payload["p_delivery_unknown"] else "failed"
            return True
        raise AssertionError((name, payload))


class XWriteOnceTests(unittest.TestCase):
    def test_config_requires_persisted_stop_state_and_approval(self):
        OneShotConfig("staging", "31849050", False, False, True, False, True, True).require_persisted_stop_state()
        invalid = (
            OneShotConfig("production", "31849050", False, False, True, False, True, True),
            OneShotConfig("staging", "wrong", False, False, True, False, True, True),
            OneShotConfig("staging", "31849050", True, False, True, False, True, True),
            OneShotConfig("staging", "31849050", False, True, True, False, True, True),
            OneShotConfig("staging", "31849050", False, False, False, False, True, True),
            OneShotConfig("staging", "31849050", False, False, True, True, True, True),
            OneShotConfig("staging", "31849050", False, False, True, False, True, False),
        )
        for config in invalid:
            with self.assertRaises(RuntimeError):
                config.require_persisted_stop_state()

    def test_transport_fixture_never_retries(self):
        for outcome in (
            XPostResponse(201, "123"),
            DeliveryStateUnknown(),
            DefiniteDeliveryFailure(403, "x_http_rejection"),
        ):
            transport = FakeTransport(outcome)
            try:
                transport.create_post_once(APPROVED_TEXT)
            except Exception:
                pass
            self.assertEqual(transport.calls, 1)

    def test_exact_phase8_memory_can_be_rolled_back(self):
        item = phase8_item()
        memory = Memory(
            posts=[item],
            decisions=[item],
            events=[{"id": "glasses-2026-08-24", "related_posts": [0]}],
            motif_usage={"glasses": [item["at"]]},
        )
        cleaned = rollback_phase8_memory(memory)
        self.assertEqual(cleaned.posts, [])
        self.assertEqual(cleaned.decisions, [])
        self.assertEqual(cleaned.events, [])
        self.assertEqual(cleaned.motif_usage, {})
        self.assertEqual(len(memory.posts), 1)

    def test_rollback_fails_closed_on_unrelated_memory(self):
        with self.assertRaises(RuntimeError):
            rollback_phase8_memory(Memory())

    def test_full_one_shot_success_has_one_external_effect(self):
        client = FakeSupabaseClient()
        transport = FakeTransport(XPostResponse(201, "remote-1"))
        config = OneShotConfig("staging", "31849050", False, False, True, False, True, True)
        report = ProductionXSinglePost(client, config, transport).run(datetime(2026, 8, 24, 17, 0, tzinfo=timezone.utc))
        self.assertTrue(report["success"])
        self.assertEqual(transport.calls, 1)
        self.assertEqual(client.phase8["status"], "failed")
        self.assertEqual(client.live["status"], "sent")
        self.assertEqual(client.live["external_id"], "remote-1")
        self.assertEqual(client.usage, ["glasses"])
        self.assertEqual(len(client.memory["posts"]), 1)

    def test_unknown_delivery_stops_without_retry(self):
        client = FakeSupabaseClient()
        transport = FakeTransport(DeliveryStateUnknown("response_unknown"))
        config = OneShotConfig("staging", "31849050", False, False, True, False, True, True)
        report = ProductionXSinglePost(client, config, transport).run(datetime(2026, 8, 24, 17, 1, tzinfo=timezone.utc))
        self.assertFalse(report["success"])
        self.assertEqual(transport.calls, 1)
        self.assertEqual(client.live["status"], "sending")
        self.assertEqual(report["ledger_status"], "sending_reconciliation_required")


if __name__ == "__main__":
    unittest.main()
