from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import re
from pathlib import Path
from typing import Any
from urllib import parse

from .autonomous import ROOT, build_director
from .content import read_json
from .director import BANNED, apply_decision
from .expression import ExpressionValidator
from .fake_production import logical_run_id
from .media import sha256
from .production_adapters import payload_fingerprint
from .production_storage import SupabaseHttpClient, SupabaseStorage
from .safety import stable_seed


EMOJI_RE=re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF]")
PROMO_WORDS=("DOWNLOAD","http://","https://","ぜひ","配信中","フォロー","リポスト","拡散")
LESSON_WORDS=("大切です","べきです","人生とは","教訓","つまりみんな")


@dataclass(frozen=True)
class WritePreflightConfig:
    app_env:str
    x_app_id:str
    allow_external_send:bool
    autonomous_enabled:bool
    kill_switch:bool
    x_write_enabled:bool
    write_credentials_configured:bool
    max_daily_posts:int=2
    max_promo_rate:float=.10
    fingerprint_cooldown_hours:int=24

    def require_safe_preflight(self)->None:
        if self.app_env!="staging": raise RuntimeError("preflight is staging-only")
        if self.allow_external_send or self.x_write_enabled: raise RuntimeError("preflight send gate must remain closed")


def validate_post_candidate(text:str,category:str,include_url:bool)->dict[str,Any]:
    reasons=[]; voice=ExpressionValidator().validate(text); lines=text.splitlines()
    if not 1<=len(lines)<=2: reasons.append("line_count")
    if category not in ("ordinary","offbeat"): reasons.append("category")
    if include_url or any(word.casefold() in text.casefold() for word in PROMO_WORDS): reasons.append("promotion_or_link")
    if any(word in text for word in LESSON_WORDS): reasons.append("lesson")
    if EMOJI_RE.search(text): reasons.append("emoji")
    if "#" in text: reasons.append("hashtag")
    if any(word in text for word in BANNED): reasons.append("character_bible")
    reasons.extend(reason for reason in voice.reasons if reason not in reasons)
    return {"valid":not reasons,"reasons":reasons,"voice_score":voice.score}


def _parse_time(value:str)->datetime|None:
    try: return datetime.fromisoformat(value.replace("Z","+00:00"))
    except (ValueError,TypeError,AttributeError): return None


class ProductionWritePreflight:
    """Stages one immutable candidate while structurally omitting every X write adapter."""

    def __init__(self,client:SupabaseHttpClient,config:WritePreflightConfig,seed:int=1):
        self.client,self.storage,self.config,self.seed=client,SupabaseStorage(client),config,seed
        self.media=read_json(ROOT/"content"/"media.json")

    def run(self,now:datetime)->dict[str,Any]:
        self.config.require_safe_preflight()
        if now.tzinfo is None: raise RuntimeError("scheduled time must be timezone-aware")
        scheduled=now.replace(second=0,microsecond=0); run_id=logical_run_id("x-first-post-preflight",scheduled); lock_name="x-write-preflight"
        if not self.storage.acquire_lock(lock_name,run_id,scheduled):
            return {"decision":"skip","reason":"lock unavailable","run_id":run_id,"x_api_requests":0,"x_write":0}
        lock_result="passed"
        try:
            memory=self.storage.load_memory(); memory_before=memory.clone(); now_utc=scheduled.astimezone(timezone.utc)
            existing_run=self.client.select("job_runs",f"select=run_id&run_id=eq.{parse.quote(run_id)}&limit=1")
            idempotency_key=f"x:{run_id}"
            existing_ledger=self.client.select("delivery_ledger",f"select=idempotency_key&idempotency_key=eq.{parse.quote(idempotency_key)}&limit=1")
            if existing_run or existing_ledger:
                return {"decision":"skip","reason":"duplicate run or idempotency key","run_id":run_id,"x_api_requests":0,"x_write":0}
            consecutive=int(self.storage.get_setting("consecutive_errors",0) or 0); circuit_open=bool(self.storage.get_setting("circuit_open",False)) or consecutive>=3
            if circuit_open:
                return {"decision":"skip","reason":"circuit breaker open","run_id":run_id,"x_api_requests":0,"x_write":0}
            today=sum(p.get("at","")[:10]==scheduled.date().isoformat() for p in memory.posts)
            if today>=self.config.max_daily_posts:
                return {"decision":"skip","reason":"daily hard limit","run_id":run_id,"x_api_requests":0,"x_write":0}
            decision=build_director(stable_seed(self.seed,run_id)).decide(scheduled,memory,weekly_due=False)
            if decision.action=="skip":
                return {"decision":"skip","reason":decision.reason,"run_id":run_id,"scheduled_jst":scheduled.isoformat(),"x_api_requests":0,"x_write":0}
            validation=validate_post_candidate(decision.text,decision.category or "",decision.include_url)
            media_record=next((m for m in self.media if m["id"]==decision.media_id and m.get("active",True)),None) if decision.media_id else None
            media_path=(ROOT/media_record["path"]) if media_record else None
            media_hash=sha256(media_path) if media_path else None
            media_ok=not decision.media_id or bool(media_record and media_path and media_path.is_file() and media_hash==media_record.get("sha256"))
            payload={**decision.to_dict(),"scheduled_jst":scheduled.isoformat(),"run_id":run_id,"idempotency_key":idempotency_key,"media_path":str(media_path) if media_path else None,"media_hash":media_hash,"fingerprint":None}
            fingerprint=payload_fingerprint(payload); payload["fingerprint"]=fingerprint
            cutoff=now_utc-timedelta(hours=self.config.fingerprint_cooldown_hours)
            ledger_rows=self.client.select("delivery_ledger","select=idempotency_key,status,payload,updated_at")
            fingerprint_duplicate=any(row.get("status") in ("candidate","sending","sent") and (row.get("payload") or {}).get("fingerprint")==fingerprint and (_parse_time(row.get("updated_at")) or now_utc)>=cutoff for row in ledger_rows)
            text_duplicate=any(p.get("text")==decision.text and (_parse_time(p.get("at")) or now_utc)>=cutoff for p in memory_before.posts)
            promo_count=sum(p.get("category")=="promo" for p in memory_before.posts); promo_ok=decision.category!="promo" and not decision.include_url
            guards={"duplicate_guard":"passed" if not text_duplicate else "failed","fingerprint_24h":"passed" if not fingerprint_duplicate else "failed","daily_hard_limit":"passed","promo_limit":"passed" if promo_ok else "failed","circuit_breaker":"passed","lock":lock_result,"supabase":"passed","media":"passed" if media_ok else "failed"}
            if not validation["valid"] or not media_ok or fingerprint_duplicate or text_duplicate or not promo_ok:
                return {"decision":"skip","reason":"candidate safety validation failed","run_id":run_id,"validation":validation,"guards":guards,"x_api_requests":0,"x_write":0}
            apply_decision(memory,decision,mutate_week=False)
            staged=bool(self.client.rpc("stage_x_write_preflight",{"p_run_id":run_id,"p_idempotency_key":idempotency_key,"p_fingerprint":fingerprint,"p_payload":payload,"p_decision":decision.to_dict(),"p_expected_memory_version":self.storage.memory_version,"p_memory":memory.to_dict()}))
            guards["ledger"]="candidate" if staged else "failed"
            send_gates={"allow_external_send":self.config.allow_external_send,"autonomous_enabled":self.config.autonomous_enabled,"kill_switch":self.config.kill_switch,"x_write_enabled":self.config.x_write_enabled,"write_credentials":self.config.write_credentials_configured,"active_app":self.config.x_app_id=="31849050"}
            payload_sendable=all((validation["valid"],media_ok,not fingerprint_duplicate,not text_duplicate,promo_ok,not circuit_open,self.config.write_credentials_configured,self.config.x_app_id=="31849050"))
            return {"decision":"post","reason":decision.reason,"payload":payload,"validation":validation,"guards":guards,"send_gates":send_gates,"payload_sendable":payload_sendable,"x_api_requests":0,"x_write":0}
        finally:
            self.storage.release_lock(lock_name,run_id)
