import unittest
from datetime import datetime
from unittest.mock import patch
from urllib import parse
from zoneinfo import ZoneInfo

from pandausagies_v2.director import Decision
from pandausagies_v2.memory import Memory
from pandausagies_v2.production_runner import ProductionAutonomousRunner, ProductionRunConfig
from pandausagies_v2.x_write_once import DeliveryStateUnknown, XPostResponse


JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 8, 25, 10, 0, tzinfo=JST)


class FakeTransport:
    def __init__(self, outcome):
        self.calls = 0
        self.outcome = outcome

    def create_post_once(self, text):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FixedDirector:
    def __init__(self, decision):
        self.decision = decision

    def decide(self, now, memory, weekly_due=False):
        return self.decision


class FakeClient:
    def __init__(self):
        self.memory = Memory().to_dict()
        self.version = 1
        self.settings = {"consecutive_errors": 0, "circuit_open": False, "public_version": 1}
        self.runs = {}
        self.ledgers = []
        self.snapshots = []
        self.released = False

    def select(self, table, query=""):
        if table == "memory_state":
            return [{"value": self.memory, "version": self.version}]
        if table == "settings":
            key = query.split("key=eq.", 1)[1].split("&", 1)[0]
            return [{"key": key, "value": self.settings[key]}] if key in self.settings else []
        if table == "job_runs":
            if "run_id=eq." in query:
                run_id = parse.unquote(query.split("run_id=eq.", 1)[1].split("&", 1)[0])
                return [self.runs[run_id]] if run_id in self.runs else []
            return list(self.runs.values())
        if table == "delivery_ledger":
            if "status=eq.sending" in query:
                return [row for row in self.ledgers if row["status"] == "sending" and not row.get("external_id")]
            return self.ledgers
        if table == "public_media":
            return []
        raise AssertionError((table, query))

    def insert(self, table, payload, upsert=False):
        if table == "job_runs":
            self.runs[payload["run_id"]] = dict(payload)
        elif table == "settings":
            self.settings[payload["key"]] = payload["value"]
        elif table == "errors":
            pass
        else:
            raise AssertionError((table, payload))
        return [payload]

    def patch(self, table, query, payload):
        if table == "settings":
            key = query.split("key=eq.", 1)[1]
            self.settings[key] = payload["value"]
        elif table == "job_runs":
            run_id = parse.unquote(query.split("run_id=eq.", 1)[1])
            self.runs[run_id].update(payload)
        else:
            raise AssertionError((table, query, payload))
        return [payload]

    def rpc(self, name, payload):
        if name == "acquire_job_lease":
            return True
        if name == "release_job_lease":
            self.released = True
            return True
        if name == "commit_run_decision":
            self.memory = payload["p_memory"]
            self.version += 1
            return self.version
        if name == "stage_autonomous_post":
            self.memory = payload["p_memory"]
            self.version += 1
            self.runs[payload["p_run_id"]] = {"run_id": payload["p_run_id"], "status": "decided"}
            self.ledgers.append({"run_id": payload["p_run_id"], "status": "candidate", "payload": payload["p_payload"], "updated_at": NOW.isoformat()})
            return True
        if name == "begin_autonomous_post":
            self.ledgers[-1]["status"] = "sending"
            return True
        if name == "complete_autonomous_post":
            self.ledgers[-1].update(status="sent", external_id=payload["p_external_id"])
            self.runs[payload["p_run_id"]]["status"] = "succeeded"
            return True
        if name == "stop_autonomous_post":
            self.ledgers[-1]["status"] = "sending" if payload["p_delivery_unknown"] else "failed"
            return True
        if name == "publish_public_state":
            self.snapshots.append(payload["p_payload"])
            return len(self.snapshots)
        raise AssertionError((name, payload))


def config(**overrides):
    values = dict(
        app_env="production",
        storage_provider="supabase",
        x_app_id="31849050",
        autonomous_enabled=True,
        allow_external_send=True,
        kill_switch=False,
        x_write_enabled=True,
        allow_automated_replies=False,
        write_credentials_configured=True,
        epoch=datetime(2026, 8, 24, 17, 8, tzinfo=JST),
    )
    values.update(overrides)
    return ProductionRunConfig(**values)


class ProductionRunnerTests(unittest.TestCase):
    def test_config_keeps_reply_writes_structurally_disabled(self):
        config().require_safe()
        for invalid in (
            config(app_env="staging"),
            config(kill_switch=True),
            config(allow_automated_replies=True),
            config(x_write_enabled=False),
        ):
            with self.assertRaises(RuntimeError):
                invalid.require_safe()

    def test_skip_is_persisted_without_x_request(self):
        db = FakeClient()
        transport = FakeTransport(XPostResponse(201, "unused"))
        decision = Decision(NOW.isoformat(), "skip", None, None, None, "none", None, None, False, "", "quiet day chosen")
        with patch("pandausagies_v2.production_runner.build_director", return_value=FixedDirector(decision)):
            result = ProductionAutonomousRunner(db, config(), transport).run(NOW)
        self.assertEqual(result["decision"], "skip")
        self.assertEqual(transport.calls, 0)
        self.assertEqual(len(db.memory["decisions"]), 1)
        self.assertEqual(len(db.snapshots), 1)
        self.assertTrue(db.released)

    def test_post_has_exactly_one_write_and_persists_memory(self):
        db = FakeClient()
        transport = FakeTransport(XPostResponse(201, "remote-1"))
        decision = Decision(NOW.isoformat(), "post", "ordinary", "bread", None, "none", None, None, False, "パンを買った\n袋を閉じた", "daily autonomous trace")
        with patch("pandausagies_v2.production_runner.build_director", return_value=FixedDirector(decision)):
            result = ProductionAutonomousRunner(db, config(), transport).run(NOW)
        self.assertEqual(result["ledger_status"], "sent")
        self.assertEqual(transport.calls, 1)
        self.assertEqual(len(db.memory["posts"]), 1)
        self.assertEqual(db.ledgers[0]["external_id"], "remote-1")
        self.assertEqual(len(db.snapshots), 1)

    def test_unknown_delivery_never_retries(self):
        db = FakeClient()
        transport = FakeTransport(DeliveryStateUnknown("response_unknown"))
        decision = Decision(NOW.isoformat(), "post", "ordinary", "bread", None, "none", None, None, False, "パンを買った\n袋を閉じた", "daily autonomous trace")
        with patch("pandausagies_v2.production_runner.build_director", return_value=FixedDirector(decision)):
            result = ProductionAutonomousRunner(db, config(), transport).run(NOW)
        self.assertEqual(transport.calls, 1)
        self.assertEqual(result["ledger_status"], "sending_reconciliation_required")


if __name__ == "__main__":
    unittest.main()
