import json, tempfile, unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from pandausagies_v2.persistent_simulation import run_days
from pandausagies_v2.production_storage import InMemoryStorage, SQLiteStorage
from pandausagies_v2.safety import FakeSender, SafetyConfig, SafetyEngine, public_state
from pandausagies_v2.memory import Memory
from pandausagies_v2.production_storage import SupabaseStorage

JST=ZoneInfo("Asia/Tokyo"); START=datetime(2026,8,24,tzinfo=JST)

class ProductionSafetyTests(unittest.TestCase):
 def engine(self,storage=None,sender=None,send=False): return SafetyEngine(storage or InMemoryStorage(),sender or FakeSender(),SafetyConfig(True,send,False),seed=99)
 def test_restart_30_then_60_matches_continuous_90(self):
  with tempfile.TemporaryDirectory() as folder:
   split=Path(folder)/"split.sqlite3"; continuous=Path(folder)/"continuous.sqlite3"
   first=SQLiteStorage(split); run_days(first,START,0,30,77); first.db.close()
   restarted=SQLiteStorage(split); resumed=run_days(restarted,START,30,60,77)
   uninterrupted=SQLiteStorage(continuous); whole=run_days(uninterrupted,START,0,90,77)
   self.assertEqual(resumed["posts"],whole["posts"]); self.assertEqual(resumed["weeks"],13)
   self.assertEqual(restarted.load_memory().to_dict(),uninterrupted.load_memory().to_dict())
 def test_same_run_id_is_idempotent(self):
  storage=InMemoryStorage(); engine=self.engine(storage)
  first=engine.run("same",START,START); before=storage.load_memory().to_dict(); second=engine.run("same",START,START)
  self.assertEqual(first["status"],"candidate"); self.assertEqual(second["status"],"duplicate"); self.assertEqual(before,storage.load_memory().to_dict())
  self.assertEqual(storage.db.execute("select count(*) from post_deliveries").fetchone()[0],1); self.assertEqual(storage.db.execute("select count(*) from week_deliveries").fetchone()[0],1)
 def test_lock_contention_safe_stops(self):
  storage=InMemoryStorage(); self.assertTrue(storage.acquire_lock("autonomous","other",START)); result=self.engine(storage).run("blocked",START,START); self.assertEqual(result["reason"],"lock unavailable"); self.assertEqual(len(storage.load_memory().posts),0)
 def test_kill_switch_and_external_gate(self):
  killed=SafetyEngine(InMemoryStorage(),FakeSender(),SafetyConfig(True,True,True)).run("kill",START,START); self.assertEqual(killed["status"],"safe_stopped")
  sender=FakeSender(); result=SafetyEngine(InMemoryStorage(),sender,SafetyConfig(True,False,False)).run("off",START,START); self.assertEqual(result["status"],"candidate"); self.assertEqual(sender.calls,0)
 def test_circuit_breaker(self):
  storage=InMemoryStorage(); storage.set_setting("consecutive_errors",3); result=self.engine(storage,send=True).run("breaker",START,START); self.assertEqual(result["reason"],"circuit breaker open")
 def test_corrupt_memory_fails_closed(self):
  storage=InMemoryStorage(); storage.db.execute("insert into state values('memory','{broken','now')"); result=self.engine(storage).run("corrupt",START,START); self.assertEqual(result["reason"],"storage unreadable"); self.assertEqual(storage.db.execute("select count(*) from post_deliveries").fetchone()[0],0)
 def test_crash_recovery_all_stages_without_duplicate_send(self):
  for stage in ("after_decision","after_candidate","before_send","after_send"):
   with self.subTest(stage=stage):
    storage=InMemoryStorage(); sender=FakeSender(); engine=self.engine(storage,sender,True)
    crashed=engine.run(stage,START,START,crash_at=stage); self.assertEqual(crashed["status"],"crashed")
    recovered=engine.run(stage,START,START); self.assertIn(recovered["status"],("recovered","recovered_skip")); self.assertLessEqual(sender.calls,1)
    self.assertEqual(storage.db.execute("select count(*) from post_deliveries").fetchone()[0],1)
    self.assertEqual(storage.db.execute("select count(*) from post_deliveries where status='sent'").fetchone()[0],1)
 def test_sent_is_only_after_sender_success(self):
  storage=InMemoryStorage(); sender=FakeSender(); engine=self.engine(storage,sender,True); engine.run("pre",START,START,crash_at="before_send")
  self.assertEqual(storage.get_post_for_run("pre")["status"],"sending"); self.assertEqual(sender.calls,0)
 def test_health_and_public_state_exclude_secrets(self):
  storage=InMemoryStorage(); self.engine(storage).run("health",START,START); health=storage.health(); self.assertEqual(health["storage"],"OK"); self.assertIn("last_decision",health)
  public=public_state(storage.load_memory(),[{"id":"portrait-coat","path":"media/weeks/week-00.png"}]); rendered=json.dumps(public); self.assertNotIn("reason",rendered); self.assertNotIn("error",rendered); self.assertNotIn("user",rendered); self.assertIn("image",rendered)
 def test_week_state_is_planned_until_publish(self):
  storage=InMemoryStorage(); self.engine(storage).run("planned",START,START); self.assertEqual(storage.db.execute("select status from week_deliveries").fetchone()[0],"planned")
  storage2=InMemoryStorage(); self.engine(storage2,FakeSender(),True).run("published",START,START); self.assertEqual(storage2.db.execute("select status from week_deliveries").fetchone()[0],"published")
 def test_supabase_adapter_uses_only_injected_fake(self):
  class FakeClient:
   def __init__(self): self.value=Memory().to_dict()
   def load_memory(self): return self.value
   def save_memory(self,value): self.value=value
  client=FakeClient(); adapter=SupabaseStorage(client); memory=adapter.load_memory(); memory.settings["test"]=True; adapter.save_memory(memory); self.assertTrue(client.value["settings"]["test"])

if __name__=="__main__": unittest.main()
