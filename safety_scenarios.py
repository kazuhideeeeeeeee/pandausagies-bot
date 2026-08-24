from __future__ import annotations
import json,tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from pandausagies_v2.persistent_simulation import run_days
from pandausagies_v2.production_storage import InMemoryStorage,SQLiteStorage
from pandausagies_v2.safety import FakeSender,SafetyConfig,SafetyEngine

def main():
 start=datetime(2026,8,24,tzinfo=ZoneInfo("Asia/Tokyo")); output={"mode":"SAFETY_SCENARIOS","network_calls":0}
 with tempfile.TemporaryDirectory() as folder:
  a=SQLiteStorage(Path(folder)/"a.sqlite3"); ra=run_days(a,start,0,90,77); output["A_90_days"]={"posts":ra["posts"],"weeks":ra["weeks"]}
  bpath=Path(folder)/"b.sqlite3"; b=SQLiteStorage(bpath); run_days(b,start,0,30,77); b.db.close(); b=SQLiteStorage(bpath); rb=run_days(b,start,30,60,77); output["B_restart"]={"posts":rb["posts"],"weeks":rb["weeks"],"matches_A":b.load_memory().to_dict()==a.load_memory().to_dict()}
 config=SafetyConfig(True,False,False); c=InMemoryStorage(); ce=SafetyEngine(c,FakeSender(),config); first=ce.run("same",start,start); second=ce.run("same",start,start); output["C_idempotency"]={"first":first["status"],"second":second["status"],"deliveries":c.db.execute("select count(*) from post_deliveries").fetchone()[0]}
 d=InMemoryStorage(); d.db.execute("insert into state values('memory','{broken','now')"); output["D_storage_failure"]=SafetyEngine(d,FakeSender(),config).run("broken",start,start)
 e=InMemoryStorage(); e.acquire_lock("autonomous","other",start); output["E_lock_conflict"]=SafetyEngine(e,FakeSender(),config).run("locked",start,start)
 crashes={}
 for stage in ("after_decision","after_candidate","before_send","after_send"):
  store=InMemoryStorage(); sender=FakeSender(); engine=SafetyEngine(store,sender,SafetyConfig(True,True,False)); initial=engine.run(stage,start,start,stage); recovery=engine.run(stage,start,start); crashes[stage]={"initial":initial["status"],"recovery":recovery["status"],"mock_send_calls":sender.calls,"sent_rows":store.db.execute("select count(*) from post_deliveries where status='sent'").fetchone()[0]}
 output["F_crash_recovery"]=crashes
 output["G_kill_switch"]=SafetyEngine(InMemoryStorage(),FakeSender(),SafetyConfig(True,True,True)).run("kill",start,start)
 sender=FakeSender(); output["H_external_off"]=SafetyEngine(InMemoryStorage(),sender,config).run("off",start,start); output["H_external_off"]["mock_send_calls"]=sender.calls
 print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
