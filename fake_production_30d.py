from __future__ import annotations
import json
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from pandausagies_v2.fake_production import FakeProductionRunner,ProductionConfig,logical_run_id
from pandausagies_v2.fake_supabase import FakeSupabase
from pandausagies_v2.production_adapters import FakeClock,FakeNotifier,FakeWeekPublisher,FakeXSender

def main():
 epoch=datetime(2026,8,24,10,tzinfo=ZoneInfo("Asia/Tokyo")); clock=FakeClock(epoch); db=FakeSupabase(); x=FakeXSender(); publisher=FakeWeekPublisher(); notifier=FakeNotifier(); runner=FakeProductionRunner(db,x,publisher,notifier,clock,ProductionConfig(True,True,False,epoch),55); injected=[]
 for day in range(30):
  clock.now=epoch+timedelta(days=day)
  if day==2:x.queue("timeout_success");injected.append("x timeout but success")
  if day==4:x.queue("429");injected.append("x 429")
  if day==6:db.available=False;injected.append("db unavailable")
  if day==7:db.available=True
  if day==8:db.acquire_lease("autonomous","competing-run",clock.now,3600);injected.append("lock conflict")
  if day==9:db.release_lease("autonomous","competing-run")
  if day==14:publisher.queue("timeout_published");injected.append("publish timeout but published")
  if day==18:x.queue("auth");injected.append("auth notification")
  run_id=logical_run_id("daily-check",clock.now); result=runner.run(run_id)
  if result["status"] in ("unknown","retry_wait","week_unknown","week_retry_wait"):
   clock.advance(400); runner.run(run_id); clock.advance(400); runner.run(run_id)
  if day==15: runner=FakeProductionRunner(db,x,publisher,notifier,clock,ProductionConfig(True,True,False,epoch),55)
 memory=db.memory; week_numbers=[w["week"] for w in memory.weeks]; sent=[r for r in db.tables["ledger"].values() if r["status"]=="sent"]
 report={"mode":"FAKE_PRODUCTION_30D","network_calls":0,"injected":injected,"posts":len(memory.posts),"weeks":len(memory.weeks),"sent_ledger":len(sent),"x_remote_effects":x.effects,"duplicate_external_effects":x.effects-len({r["payload_hash"] for r in sent}),"week_publish_effects":publisher.effects,"duplicate_weeks":len(week_numbers)-len(set(week_numbers)),"memory_corruption":0,"notifications":notifier.events,"public_snapshot_version":db.tables["settings"].get("public_version",0),"restart_readable":db.memory.to_dict()==db.memory.clone().to_dict()}
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
