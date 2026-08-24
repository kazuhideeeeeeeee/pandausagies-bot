from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .production_storage import SupabaseHttpClient
from .reply_expression import LocalReplyExpressionProvider, classify_reply_intent, validate_reply_candidate
from .x_read import XReadClient, XReadError, classify_mention, utc_now


@dataclass(frozen=True)
class XReadConfig:
    app_env: str
    handle: str
    read_enabled: bool
    write_enabled: bool
    allow_external_send: bool
    autonomous_enabled: bool
    kill_switch: bool
    backfill_limit: int = 10
    max_pages: int = 2

    def require_safe(self) -> None:
        if self.app_env != "staging" or self.handle.casefold() != "pandausagies": raise RuntimeError("X read staging identity guard failed")
        if not self.read_enabled or self.write_enabled or self.allow_external_send or self.autonomous_enabled or not self.kill_switch: raise RuntimeError("X read hard gate failed")


def _cursor(db: SupabaseHttpClient) -> dict[str,Any] | None:
    rows=db.select("x_read_cursors","select=*&key=eq.mentions&limit=1")
    return rows[0] if rows else None


def _identity(db: SupabaseHttpClient,handle:str) -> dict[str,Any] | None:
    rows=db.select("x_account_identities",f"select=*&handle=eq.{handle.casefold()}&limit=1")
    return rows[0] if rows else None


def _save_identity(db:SupabaseHttpClient,handle:str,value:dict[str,str])->None:
    now=utc_now(); payload={"handle":handle.casefold(),"x_user_id":value["id"],"current_username":value["username"],"display_name":value["name"],"resolved_at":now,"updated_at":now}
    current=_identity(db,handle)
    if current: db.patch("x_account_identities",f"handle=eq.{handle.casefold()}",payload)
    else: db.insert("x_account_identities",payload)


def _save_cursor(db:SupabaseHttpClient,current:dict[str,Any]|None,payload:dict[str,Any])->None:
    if current: db.patch("x_read_cursors","key=eq.mentions",payload)
    else: db.insert("x_read_cursors",{"key":"mentions",**payload})


def run_x_read(client:XReadClient,db:SupabaseHttpClient,config:XReadConfig,force_resolve:bool=False)->dict[str,Any]:
    config.require_safe(); current=_cursor(db); identity=_identity(db,config.handle); before_calls=client.api_calls
    expression=LocalReplyExpressionProvider()
    try:
        if force_resolve or not identity:
            me=client.lookup_user(config.handle)
            if me["username"].casefold()!=config.handle.casefold(): raise XReadError("identity_mismatch")
            _save_identity(db,config.handle,me); identity=me
        else:
            me={"id":str(identity["x_user_id"]),"username":str(identity.get("current_username") or config.handle),"name":str(identity.get("display_name") or "")}
        user_id=me["id"]
        page=client.get_mentions(user_id,since_id=current.get("last_seen_mention_id") if current else None,max_results=max(5,config.backfill_limit),max_pages=config.max_pages,total_limit=config.backfill_limit)
        stored=duplicates=ignored=self_excluded=0; classes={"candidate":0,"ignore":0,"needs_human":0,"sensitive":0,"opted_out":0,"spam":0}; observations=[]
        for mention in page.mentions:
            if mention["author_id"]==user_id: self_excluded+=1; continue
            classification,optout=classify_mention(mention["text"]); mention["automation_opt_out"]=optout
            if classification=="candidate":
                intent=classify_reply_intent(mention["text"]); candidate=expression.generate(mention["text"],intent)
                if not validate_reply_candidate(mention["text"],intent,candidate).valid: classification="needs_human"; candidate=None
            else: candidate=None
            inserted=bool(db.rpc("ingest_x_mention",{"p_mention":mention,"p_classification":classification,"p_candidate_body":candidate}))
            if inserted: stored+=1; classes[classification]+=1
            else: duplicates+=1
            if classification!="candidate": ignored+=1
            if inserted and len(observations)<5: observations.append({"author":mention["username"],"text":mention["text"],"conversation_id":mention["conversation_id"],"classification":classification,"candidate":candidate})
        newest=page.newest_id or (max((m["x_post_id"] for m in page.mentions),key=int) if page.mentions else (current.get("last_seen_mention_id") if current else None))
        calls=client.api_calls-before_calls
        _save_cursor(db,current,{"last_seen_mention_id":newest,"last_successful_x_read_at":utc_now(),"last_status":"success","api_call_count":int(current.get("api_call_count",0) if current else 0)+calls,"retry_after":None})
        return {"status":"success","user_id":user_id,"fetched":len(page.mentions),"stored":stored,"duplicates":duplicates,"ignored":ignored,"self_excluded":self_excluded,"classifications":classes,"api_calls":calls,"observations":observations}
    except XReadError as exc:
        calls=client.api_calls-before_calls; retry_at=(datetime.now(timezone.utc)+timedelta(seconds=exc.retry_after)).isoformat() if exc.retry_after else None
        _save_cursor(db,current,{"last_status":exc.kind,"api_call_count":int(current.get("api_call_count",0) if current else 0)+calls,"error_count":int(current.get("error_count",0) if current else 0)+1,"retry_after":retry_at})
        return {"status":"safe_stopped","reason":exc.kind,"api_calls":calls,"observations":[]}
