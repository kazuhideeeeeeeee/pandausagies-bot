from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from .autonomous import ROOT,build_director
from .content import read_json
from .director import apply_decision,next_week_due
from .fake_supabase import FakeSupabase,SupabaseStorage,UniqueViolation
from .production_adapters import DeliveryUnknown,FakeClock,FakeNotifier,FakeWeekPublisher,FakeXSender,PermanentDelivery,RetryableDelivery,payload_fingerprint

def logical_run_id(job:str,when:datetime)->str:
    if when.tzinfo is None: raise ValueError("timezone required")
    return f"{job}:{when.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')}"

@dataclass(frozen=True)
class ProductionConfig:
    autonomous_enabled:bool; allow_external_send:bool; kill_switch:bool; epoch:datetime|None
    fake_externals:bool=True; fingerprint_cooldown_hours:int=24; max_errors:int=3

class FakeProductionRunner:
    def __init__(self,db:FakeSupabase,x:FakeXSender,publisher:FakeWeekPublisher,notifier:FakeNotifier,clock:FakeClock,config:ProductionConfig,seed:int=1):
        self.db,self.storage,self.x,self.publisher,self.notifier,self.clock,self.config,self.seed=db,SupabaseStorage(db),x,publisher,notifier,clock,config,seed
        self.media=read_json(ROOT/"content"/"media.json")
    def _stop_reason(self)->str|None:
        if self.config.kill_switch:return "kill switch ON"
        if not self.config.autonomous_enabled:return "autonomous disabled"
        if not self.config.allow_external_send:return "external send disabled"
        if not self.config.fake_externals:return "real externals forbidden in Phase 5"
        if self.config.epoch is None or self.config.epoch.tzinfo is None:return "epoch missing"
        if self.db.tables["settings"].get("circuit_open"):return "circuit breaker open"
        last=self.db.tables["settings"].get("last_clock")
        if last and self.clock.now<last:return "clock moved backwards"
        return None
    def _error(self,run_id:str,kind:str,message:str,critical:bool=True):
        self.db.tables["errors"][len(self.db.tables["errors"])+1]={"run_id":run_id,"kind":kind,"message":message,"at":self.clock.now}
        if critical:
            count=self.db.tables["settings"].get("consecutive_errors",0)+1; self.db.tables["settings"]["consecutive_errors"]=count
            if count>=self.config.max_errors:
                self.db.tables["settings"]["circuit_open"]=True; self.notifier.notify("circuit_breaker_open",f"after {count} critical errors")
        if kind in ("auth","storage","reconciliation_unresolved","publish_repeated"): self.notifier.notify(kind,message)
    def _snapshot(self):
        published=sorted((w for w in self.db.tables["weeks"].values() if w["status"]=="published"),key=lambda w:w["week_number"])
        public_weeks=[]; paths={m["id"]:m["path"] for m in self.media}
        for row in published:
            p=row["payload"]; public_weeks.append({"id":p["week_id"],"week":row["week_number"],"date":p["at"][:10],"text":p["text"],"songId":p.get("song_id"),"image":paths.get(p.get("media_id"))})
        version=self.db.tables["settings"].get("public_version",0)+1; self.db.tables["settings"]["public_version"]=version; self.db.publish_snapshot({"version":version,"generated_at":self.clock.now.isoformat(),"currentWeek":public_weeks[-1] if public_weeks else None,"pastWeeks":public_weeks[:-1]})
    def _reconcile(self,run_id:str)->dict:
        row=self.db.tables["ledger"].get(run_id)
        if not row:return {"status":"duplicate"}
        if row["status"]=="failed":return {"status":"human_required"}
        if row["status"]=="sent":
            payload=row["payload"]
            if payload.get("week_id"):
                number=int(payload["week_id"].split("-")[1]); week=self.db.tables["weeks"].get(number)
                if week and week["status"]!="published": return self._publish_week(run_id,row)
            return {"status":"duplicate_sent"}
        if row.get("next_retry_at") and self.clock.now<row["next_retry_at"]:return {"status":"retry_wait"}
        remote=self.x.lookup(row["payload_hash"])
        if remote:
            row.update(status="sent",remote_post_id=remote,reconciled_at=self.clock.now); return self._publish_week(run_id,row)
        if row["status"]=="unknown":
            row["reconcile_attempts"]=row.get("reconcile_attempts",0)+1
            if row["reconcile_attempts"]<2: row["next_retry_at"]=self.clock.now+timedelta(seconds=120); return {"status":"unknown_wait"}
        return self._deliver(run_id,row)
    def _deliver(self,run_id:str,row:dict)->dict:
        row["status"]="sending"
        try:
            remote=self.x.send(row["payload_hash"],row["payload"]); row.update(status="sent",remote_post_id=remote,sent_at=self.clock.now); self.db.tables["settings"]["consecutive_errors"]=0; return self._publish_week(run_id,row)
        except DeliveryUnknown:
            row.update(status="unknown",next_retry_at=self.clock.now+timedelta(seconds=60)); return {"status":"unknown"}
        except RetryableDelivery as exc:
            row.update(status="retry_wait",next_retry_at=self.clock.now+timedelta(seconds=exc.retry_after),last_error=str(exc)); return {"status":"retry_wait","retry_after":exc.retry_after}
        except PermanentDelivery as exc:
            row.update(status="failed",last_error=str(exc)); kind="auth" if "authentication" in str(exc) else "delivery_permanent"; self._error(run_id,kind,str(exc)); return {"status":"failed","reason":str(exc)}
    def _publish_week(self,run_id:str,ledger:dict)->dict:
        payload=ledger["payload"]
        if not payload.get("week_id"): self.db.tables["runs"][run_id]["status"]="succeeded"; return {"status":"sent"}
        number=int(payload["week_id"].split("-")[1]); week=self.db.tables["weeks"][number]
        if week.get("next_retry_at") and self.clock.now<week["next_retry_at"]: return {"status":"week_retry_wait"}
        remote=self.publisher.lookup(number)
        if remote:
            week.update(status="published",remote_id=remote); self._snapshot(); self.db.tables["runs"][run_id]["status"]="succeeded"; return {"status":"published"}
        try:
            week["status"]="publishing"; remote=self.publisher.publish(number,payload); week.update(status="published",remote_id=remote); self._snapshot(); self.db.tables["runs"][run_id]["status"]="succeeded"; return {"status":"published"}
        except DeliveryUnknown:
            week["status"]="unknown"; return {"status":"week_unknown"}
        except RetryableDelivery as exc:
            attempts=week.get("attempts",0)+1; week.update(status="retry_wait",next_retry_at=self.clock.now+timedelta(seconds=exc.retry_after),attempts=attempts)
            if attempts>=3: week["status"]="failed"; self._error(run_id,"publish_repeated","three publish failures"); return {"status":"week_failed"}
            return {"status":"week_retry_wait"}
    def run(self,run_id:str)->dict:
        reason=self._stop_reason()
        if reason:return {"status":"safe_stopped","reason":reason}
        if not self.db.available:self.notifier.notify("storage","database unavailable"); return {"status":"safe_stopped","reason":"storage unavailable"}
        if run_id in self.db.tables["runs"]:return self._reconcile(run_id)
        try:
            with self.db.transaction():
                if not self.db.acquire_lease("autonomous",run_id,self.clock.now):return {"status":"safe_stopped","reason":"lock unavailable"}
                self.db.insert_unique("runs",run_id,{"run_id":run_id,"status":"running","started_at":self.clock.now})
                memory=self.storage.load_memory(); self.db.tables["settings"]["last_clock"]=self.clock.now
            with self.db.transaction():
                weekly=next_week_due(memory,self.clock.now,self.config.epoch); run_seed=int(hashlib.sha256(f"{self.seed}:{run_id}".encode()).hexdigest()[:12],16); decision=build_director(run_seed).decide(self.clock.now,memory,weekly); payload=decision.to_dict(); payload["media_hash"]=next((m["sha256"] for m in self.media if m["id"]==payload.get("media_id")),None); fingerprint=payload_fingerprint(payload)
                cutoff=self.clock.now-timedelta(hours=self.config.fingerprint_cooldown_hours)
                if any(r["payload_hash"]==fingerprint and r["created_at"]>=cutoff and r["status"] in ("candidate","sending","unknown","retry_wait","sent") for r in self.db.tables["ledger"].values()):
                    self.db.tables["runs"][run_id]["status"]="safe_stopped"; return {"status":"safe_stopped","reason":"duplicate payload fingerprint"}
                self.db.insert_unique("decisions",run_id,{"payload":payload,"created_at":self.clock.now}); apply_decision(memory,decision); self.storage.save_memory(memory)
                if decision.action=="skip":self.db.tables["runs"][run_id]["status"]="succeeded"; return {"status":"skipped"}
                self.db.insert_unique("ledger",run_id,{"run_id":run_id,"idempotency_key":f"x:{run_id}","payload_hash":fingerprint,"text_hash":payload_fingerprint({"text":payload["text"]}),"media_hash":payload.get("media_hash"),"payload":payload,"status":"candidate","created_at":self.clock.now,"remote_post_id":None,"sent_at":None,"reconciled_at":None})
                if decision.week_id:
                    number=int(decision.week_id.split("-")[1]); self.db.insert_unique("weeks",number,{"week_number":number,"run_id":run_id,"status":"planned","payload":payload})
            return self._deliver(run_id,self.db.tables["ledger"][run_id])
        except Exception as exc:
            self._error(run_id,"storage",str(exc)); return {"status":"safe_stopped","reason":"transaction failure"}
        finally:self.db.release_lease("autonomous",run_id)

    def heartbeat(self,run_id:str)->bool:return self.db.heartbeat("autonomous",run_id,self.clock.now)
