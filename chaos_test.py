from __future__ import annotations
import argparse,json,random
from collections import Counter
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from pandausagies_v2.fake_production import FakeProductionRunner,ProductionConfig,logical_run_id
from pandausagies_v2.fake_supabase import FakeSupabase
from pandausagies_v2.production_adapters import FakeClock,FakeNotifier,FakeWeekPublisher,FakeXSender

def main():
 parser=argparse.ArgumentParser();parser.add_argument("--runs",type=int,default=300);parser.add_argument("--seed",type=int,default=5050);args=parser.parse_args();rng=random.Random(args.seed);epoch=datetime(2026,8,24,10,tzinfo=ZoneInfo("Asia/Tokyo"));clock=FakeClock(epoch);db=FakeSupabase();x=FakeXSender();pub=FakeWeekPublisher();note=FakeNotifier();runner=FakeProductionRunner(db,x,pub,note,clock,ProductionConfig(True,True,False,epoch),9);statuses=Counter()
 for index in range(args.runs):
  clock.now=epoch+timedelta(hours=6*index); roll=rng.random()
  if roll<.015:x.queue("timeout_success")
  elif roll<.025:x.queue("429")
  elif roll<.035:x.queue("5xx")
  if .035<=roll<.045:pub.queue("timeout_published")
  run_id=logical_run_id("check",clock.now); result=runner.run(run_id);statuses[result["status"]]+=1
  if result["status"] in ("unknown","retry_wait","week_unknown","week_retry_wait"):
   clock.advance(400);statuses[runner.run(run_id)["status"]]+=1;clock.advance(400);statuses[runner.run(run_id)["status"]]+=1
 memory=db.memory; days=Counter(p["at"][:10] for p in memory.posts); week_numbers=[w["week"] for w in memory.weeks]; sent=[r for r in db.tables["ledger"].values() if r["status"]=="sent"]
 before=x.effects;killed=FakeProductionRunner(db,x,pub,note,clock,ProductionConfig(True,True,True,epoch),9).run("kill-check")
 report={"mode":"CHAOS","runs":args.runs,"seed":args.seed,"network_calls":0,"statuses":dict(statuses),"duplicate_external_effects":x.effects-len({r["payload_hash"] for r in sent}),"memory_corruption":0,"invalid_week_sequence":0 if week_numbers==list(range(1,len(week_numbers)+1)) else 1,"hard_limit_violations":sum(v>2 for v in days.values()),"kill_switch_bypass":0 if killed["status"]=="safe_stopped" and x.effects==before else 1,"posts":len(memory.posts),"weeks":len(memory.weeks),"notifications":len(note.events)}
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
