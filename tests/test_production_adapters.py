import json,unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from pandausagies_v2.fake_production import FakeProductionRunner,ProductionConfig,logical_run_id
from pandausagies_v2.fake_supabase import FakeSupabase,PolicyDenied,UniqueViolation
from pandausagies_v2.production_adapters import DeliveryUnknown,FakeClock,FakeNotifier,FakeWeekPublisher,FakeXSender,RetryableDelivery,payload_fingerprint

JST=ZoneInfo("Asia/Tokyo"); EPOCH=datetime(2026,8,24,10,tzinfo=JST)
def setup():
 db=FakeSupabase();x=FakeXSender();pub=FakeWeekPublisher();note=FakeNotifier();clock=FakeClock(EPOCH);runner=FakeProductionRunner(db,x,pub,note,clock,ProductionConfig(True,True,False,EPOCH),3);return db,x,pub,note,clock,runner

class ProductionAdapterTests(unittest.TestCase):
 def test_fingerprint_normalizes_text_and_changes_material_fields(self):
  a=payload_fingerprint({"text":"パン  を\n買った","media_id":"a","song_id":"s","category":"ordinary"});b=payload_fingerprint({"text":"パン を 買った","media_id":"a","song_id":"s","category":"ordinary"});self.assertEqual(a,b);self.assertNotEqual(a,payload_fingerprint({"text":"パン を 買った","media_id":"b","song_id":"s","category":"ordinary"}))
 def test_fake_transaction_rolls_back_and_unique_constraint(self):
  db=FakeSupabase()
  with self.assertRaises(RuntimeError):
   with db.transaction():db.insert_unique("runs","x",{"status":"running"});raise RuntimeError("fail")
  self.assertNotIn("x",db.tables["runs"]);db.insert_unique("runs","x",{})
  with self.assertRaises(UniqueViolation):db.insert_unique("runs","x",{})
 def test_lease_heartbeat_and_expiry(self):
  db=FakeSupabase();self.assertTrue(db.acquire_lease("job","a",EPOCH,60));self.assertFalse(db.acquire_lease("job","b",EPOCH+timedelta(seconds=30),60));self.assertTrue(db.heartbeat("job","a",EPOCH+timedelta(seconds=30),60));self.assertTrue(db.acquire_lease("job","b",EPOCH+timedelta(seconds=91),60))
 def test_anon_policy_and_public_privacy(self):
  db,x,pub,note,clock,runner=setup();runner.run(logical_run_id("check",clock.now));snapshot=db.public_read("public_state","anon");rendered=json.dumps(snapshot,default=str)
  for forbidden in ("reason","contacts","conversations","user_id","service_role","API_KEY","errors","settings","locks"):self.assertNotIn(forbidden,rendered)
  with self.assertRaises(PolicyDenied):db.public_read("runs","anon")
 def test_timeout_success_reconciles_without_resend(self):
  db,x,pub,note,clock,runner=setup();x.queue("timeout_success");rid=logical_run_id("check",clock.now);self.assertEqual(runner.run(rid)["status"],"unknown");clock.advance(61);result=runner.run(rid);self.assertIn(result["status"],("published","sent"));self.assertEqual(x.effects,1)
 def test_response_lost_reconciles_without_resend(self):
  db,x,pub,note,clock,runner=setup();x.queue("response_lost");rid=logical_run_id("check",clock.now);self.assertEqual(runner.run(rid)["status"],"unknown");clock.advance(61);runner.run(rid);self.assertEqual(x.effects,1)
 def test_timeout_failure_waits_before_retry(self):
  db,x,pub,note,clock,runner=setup();x.queue("timeout_failure");rid=logical_run_id("check",clock.now);self.assertEqual(runner.run(rid)["status"],"retry_wait");self.assertEqual(runner.run(rid)["status"],"retry_wait");clock.advance(121);runner.run(rid);self.assertEqual(x.effects,1)
 def test_429_records_retry_after(self):
  db,x,pub,note,clock,runner=setup();x.queue("429");rid=logical_run_id("check",clock.now);result=runner.run(rid);self.assertEqual(result["retry_after"],300);self.assertEqual(x.effects,0)
 def test_auth_failure_notifies_and_does_not_retry(self):
  db,x,pub,note,clock,runner=setup();x.queue("auth");rid=logical_run_id("check",clock.now);self.assertEqual(runner.run(rid)["status"],"failed");self.assertEqual(note.events[0]["kind"],"auth");self.assertEqual(runner.run(rid)["status"],"human_required")
 def test_media_success_text_failure_is_permanent(self):
  db,x,pub,note,clock,runner=setup();x.queue("media_success_text_fail");rid=logical_run_id("check",clock.now);self.assertEqual(runner.run(rid)["status"],"failed");self.assertEqual(x.media_uploads,1);self.assertEqual(x.effects,0)
 def test_week_timeout_reconciles(self):
  db,x,pub,note,clock,runner=setup();pub.queue("timeout_published");rid=logical_run_id("check",clock.now);self.assertEqual(runner.run(rid)["status"],"week_unknown");self.assertEqual(runner.run(rid)["status"],"published");self.assertEqual(pub.effects,1)
 def test_service_role_name_is_absent_from_site_code(self):
  from pathlib import Path
  site=(Path(__file__).resolve().parent.parent/"site"/"app.js").read_text(encoding="utf-8");self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY",site);self.assertNotIn("service_role",site)
 def test_clock_backwards_and_epoch_missing_stop(self):
  db,x,pub,note,clock,runner=setup();runner.run(logical_run_id("check",clock.now));clock.now-=timedelta(days=1);self.assertEqual(runner.run("back")["reason"],"clock moved backwards")
  runner2=FakeProductionRunner(FakeSupabase(),FakeXSender(),FakeWeekPublisher(),FakeNotifier(),FakeClock(EPOCH),ProductionConfig(True,True,False,None));self.assertEqual(runner2.run("none")["reason"],"epoch missing")
 def test_logical_run_id_is_timezone_stable(self):
  self.assertEqual(logical_run_id("check",EPOCH),"check:2026-08-24T01:00:00Z")
 def test_kill_switch_cannot_reach_sender(self):
  db,x,pub,note,clock,runner=setup();killed=FakeProductionRunner(db,x,pub,note,clock,ProductionConfig(True,True,True,EPOCH));self.assertEqual(killed.run("kill")["status"],"safe_stopped");self.assertEqual(x.effects,0)

if __name__=="__main__":unittest.main()
