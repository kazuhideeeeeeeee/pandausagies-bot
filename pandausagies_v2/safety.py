from __future__ import annotations
import hashlib, os
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from .autonomous import build_director
from .director import Decision, apply_decision, next_week_due
from .production_storage import SQLiteStorage

class Sender(Protocol):
    def send(self,key:str,text:str)->str: ...
    def lookup(self,key:str)->str|None: ...

class FakeSender:
    def __init__(self): self.sent={}; self.calls=0
    def send(self,key:str,text:str)->str:
        if key not in self.sent: self.calls+=1; self.sent[key]=f"fake-{len(self.sent)+1}"
        return self.sent[key]
    def lookup(self,key:str)->str|None: return self.sent.get(key)

@dataclass(frozen=True)
class SafetyConfig:
    autonomous_enabled: bool=False; allow_external_send: bool=False; kill_switch: bool=False
    circuit_breaker_errors: int=3; max_daily_posts:int=2; max_promo_rate:float=.10
    @classmethod
    def from_env(cls):
        def read(name:str,default:bool)->bool:
            value=os.getenv(name)
            if value is None: return default
            normalized=value.strip().lower()
            if normalized in ("1","true","yes","on"): return True
            if normalized in ("0","false","no","off"): return False
            return False if name!="KILL_SWITCH" else True
        return cls(read("AUTONOMOUS_ENABLED",False),read("ALLOW_EXTERNAL_SEND",False),read("KILL_SWITCH",False))

def stable_seed(seed:int,run_id:str)->int: return int(hashlib.sha256(f"{seed}:{run_id}".encode()).hexdigest()[:12],16)

class SafetyEngine:
    def __init__(self,storage:SQLiteStorage,sender:Sender,config:SafetyConfig,seed:int=1): self.storage,self.sender,self.config,self.seed=storage,sender,config,seed
    def _gate(self,memory,now)->str|None:
        if self.config.kill_switch: return "kill switch ON"
        if not self.config.autonomous_enabled: return "autonomous disabled"
        if self.storage.get_setting("consecutive_errors",0)>=self.config.circuit_breaker_errors: return "circuit breaker open"
        if now.tzinfo is None or abs((datetime.now(now.tzinfo)-now).days)>3700: return "system time invalid"
        if sum(p["at"][:10]==now.date().isoformat() for p in memory.posts)>=self.config.max_daily_posts: return "daily hard limit"
        numbers=[w.get("week") for w in memory.weeks]
        if len(numbers)!=len(set(numbers)): return "current week inconsistent"
        return None
    def _candidate_gate(self,memory,decision)->str|None:
        if decision.include_url:
            promo=sum(p.get("category")=="promo" for p in memory.posts)
            allowed=max(1,math.ceil((len(memory.posts)+1)*self.config.max_promo_rate))
            if promo+1>allowed: return "promo hard limit"
        recent=memory.posts[-3:]
        if decision.song_id and any(p.get("song_id")==decision.song_id for p in recent): return "song cooldown"
        if decision.media_id and any(p.get("media_id")==decision.media_id for p in recent): return "media cooldown"
        if decision.include_url and decision.song_id and any(p.get("include_url") and p.get("song_id")==decision.song_id for p in recent): return "URL cooldown"
        return None
    def run(self,run_id:str,now:datetime,start:datetime,crash_at:str|None=None)->dict:
        if not run_id: return {"status":"safe_stopped","reason":"missing run_id"}
        if not self.storage.acquire_lock("autonomous",run_id,now): return {"status":"safe_stopped","reason":"lock unavailable"}
        try:
            existing=self.storage.get_run(run_id); delivery=self.storage.get_post_for_run(run_id)
            if existing:
                if existing["status"] in ("succeeded","safe_stopped"): return {"status":"duplicate","run_status":existing["status"]}
                import json
                if not delivery and existing.get("decision_json"):
                    memory=self.storage.load_memory(); decision=Decision(**json.loads(existing["decision_json"])); apply_decision(memory,decision); self.storage.save_memory(memory)
                    if decision.action=="skip": self.storage.update_run(run_id,"succeeded"); return {"status":"recovered_skip"}
                    key=f"post:{run_id}"; self.storage.upsert_post(key,run_id,"candidate",decision.to_dict()); delivery=self.storage.get_post_for_run(run_id)
                    if decision.week_id: self.storage.upsert_week(int(decision.week_id.split("-")[1]),run_id,"planned",decision.to_dict())
                if delivery and delivery["status"] in ("candidate","sending"):
                    payload=json.loads(delivery["payload_json"]); external=self.sender.lookup(delivery["idempotency_key"])
                    if not external:
                        if self.config.kill_switch or not self.config.autonomous_enabled or not self.config.allow_external_send: return {"status":"safe_stopped","reason":"recovery send gate closed"}
                        self.storage.upsert_post(delivery["idempotency_key"],run_id,"sending",payload); external=self.sender.send(delivery["idempotency_key"],payload["text"])
                    self.storage.upsert_post(delivery["idempotency_key"],run_id,"sent",payload,external)
                    if payload.get("week_id"): self.storage.upsert_week(int(payload["week_id"].split("-")[1]),run_id,"published",payload)
                    self.storage.update_run(run_id,"succeeded"); self.storage.clear_errors(); return {"status":"recovered","external_post_id":external}
                return {"status":"duplicate","run_status":existing["status"]}
            self.storage.start_run(run_id,now)
            try: memory=self.storage.load_memory()
            except Exception as exc: self.storage.record_error(run_id,str(exc)); self.storage.update_run(run_id,"safe_stopped",error=str(exc)); return {"status":"safe_stopped","reason":"storage unreadable"}
            gate=self._gate(memory,now)
            if gate: self.storage.update_run(run_id,"safe_stopped",error=gate); return {"status":"safe_stopped","reason":gate}
            weekly=next_week_due(memory,now,start); decision=build_director(stable_seed(self.seed,run_id)).decide(now,memory,weekly)
            self.storage.update_run(run_id,"decided",decision.to_dict())
            if crash_at=="after_decision": raise RuntimeError("simulated crash after decision")
            candidate_gate=self._candidate_gate(memory,decision)
            if candidate_gate: self.storage.update_run(run_id,"safe_stopped",decision.to_dict(),candidate_gate); return {"status":"safe_stopped","reason":candidate_gate}
            apply_decision(memory,decision); self.storage.save_memory(memory)
            if decision.action=="skip": self.storage.update_run(run_id,"succeeded"); self.storage.clear_errors(); return {"status":"skipped","decision":decision.to_dict()}
            key=f"post:{run_id}"; self.storage.upsert_post(key,run_id,"candidate",decision.to_dict())
            if decision.week_id: self.storage.upsert_week(int(decision.week_id.split("-")[1]),run_id,"planned",decision.to_dict())
            if crash_at=="after_candidate": raise RuntimeError("simulated crash after candidate")
            if not self.config.allow_external_send: self.storage.update_run(run_id,"succeeded"); self.storage.clear_errors(); return {"status":"candidate","reason":"external send disabled"}
            self.storage.upsert_post(key,run_id,"sending",decision.to_dict())
            if crash_at=="before_send": raise RuntimeError("simulated crash before send")
            external_id=self.sender.send(key,decision.text)
            if crash_at=="after_send": raise RuntimeError("simulated crash after send")
            self.storage.upsert_post(key,run_id,"sent",decision.to_dict(),external_id)
            if decision.week_id: self.storage.upsert_week(int(decision.week_id.split("-")[1]),run_id,"published",decision.to_dict())
            self.storage.update_run(run_id,"succeeded"); self.storage.clear_errors(); return {"status":"sent","external_post_id":external_id}
        except Exception as exc:
            try:
                self.storage.record_error(run_id,str(exc)); self.storage.update_run(run_id,"failed",error=str(exc))
            except Exception:
                pass
            return {"status":"crashed","reason":str(exc)}
        finally:
            try: self.storage.release_lock("autonomous",run_id)
            except Exception: pass

def public_state(memory,media_records:list[dict]|None=None)->dict:
    paths={item["id"]:item["path"] for item in (media_records or [])}
    weeks=[]
    for week in memory.weeks:
        item={k:week.get(k) for k in ("id","week","date","text","song_id")}
        item["image"]=paths.get(week.get("media_id"))
        weeks.append(item)
    return {"currentWeek":weeks[-1] if weeks else None,"pastWeeks":weeks[:-1]}
