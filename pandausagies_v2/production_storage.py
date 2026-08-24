from __future__ import annotations
import json, socket, sqlite3
from urllib import error, parse, request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from .memory import Memory

class SafetyStorage(Protocol):
    def load_memory(self) -> Memory: ...
    def save_memory(self, memory: Memory) -> None: ...
    def acquire_lock(self, name: str, owner: str, now: datetime, ttl_seconds: int = 300) -> bool: ...
    def release_lock(self, name: str, owner: str) -> None: ...

SCHEMA = """
create table if not exists state (key text primary key, value text not null, updated_at text not null);
create table if not exists runs (run_id text primary key, status text not null, started_at text not null, finished_at text, decision_json text, error text);
create table if not exists post_deliveries (idempotency_key text primary key, run_id text not null unique, status text not null check(status in ('candidate','sending','sent','failed')), payload_json text not null, external_post_id text unique, updated_at text not null);
create table if not exists week_deliveries (week_number integer primary key, run_id text not null unique, status text not null check(status in ('planned','published','failed')), payload_json text not null, updated_at text not null);
create table if not exists run_locks (name text primary key, owner text not null, expires_at text not null);
create table if not exists errors (id integer primary key autoincrement, run_id text, severity text not null, message text not null, occurred_at text not null);
"""

class SQLiteStorage:
    def __init__(self, path: Path):
        self.path=path; self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path, timeout=2, isolation_level=None); self.db.row_factory=sqlite3.Row
        self.db.executescript(SCHEMA)
    @contextmanager
    def transaction(self):
        self.db.execute("begin immediate")
        try: yield; self.db.execute("commit")
        except Exception: self.db.execute("rollback"); raise
    def load_memory(self)->Memory:
        row=self.db.execute("select value from state where key='memory'").fetchone()
        if not row: return Memory()
        try: return Memory.from_dict(json.loads(row["value"]))
        except (ValueError,TypeError) as exc: raise RuntimeError("stored memory is corrupt") from exc
    def save_memory(self,memory:Memory)->None:
        now=datetime.now(timezone.utc).isoformat(); value=json.dumps(memory.to_dict(),ensure_ascii=False)
        self.db.execute("insert into state(key,value,updated_at) values('memory',?,?) on conflict(key) do update set value=excluded.value,updated_at=excluded.updated_at",(value,now))
    def acquire_lock(self,name:str,owner:str,now:datetime,ttl_seconds:int=300)->bool:
        expires=(now+timedelta(seconds=ttl_seconds)).isoformat()
        try:
            with self.transaction():
                self.db.execute("delete from run_locks where name=? and expires_at<=?",(name,now.isoformat()))
                self.db.execute("insert into run_locks values(?,?,?)",(name,owner,expires))
            return True
        except sqlite3.IntegrityError: return False
    def release_lock(self,name:str,owner:str)->None: self.db.execute("delete from run_locks where name=? and owner=?",(name,owner))
    def get_run(self,run_id:str)->dict|None:
        row=self.db.execute("select * from runs where run_id=?",(run_id,)).fetchone(); return dict(row) if row else None
    def start_run(self,run_id:str,now:datetime)->bool:
        try: self.db.execute("insert into runs(run_id,status,started_at) values(?, 'running', ?)",(run_id,now.isoformat())); return True
        except sqlite3.IntegrityError: return False
    def update_run(self,run_id:str,status:str,decision:dict|None=None,error:str|None=None)->None:
        finished=datetime.now(timezone.utc).isoformat() if status in ("succeeded","failed","safe_stopped") else None
        self.db.execute("update runs set status=?,finished_at=?,decision_json=coalesce(?,decision_json),error=? where run_id=?",(status,finished,json.dumps(decision,ensure_ascii=False) if decision else None,error,run_id))
    def upsert_post(self,key:str,run_id:str,status:str,payload:dict,external_id:str|None=None)->None:
        now=datetime.now(timezone.utc).isoformat(); data=json.dumps(payload,ensure_ascii=False)
        self.db.execute("insert into post_deliveries values(?,?,?,?,?,?) on conflict(idempotency_key) do update set status=excluded.status,external_post_id=coalesce(excluded.external_post_id,post_deliveries.external_post_id),updated_at=excluded.updated_at",(key,run_id,status,data,external_id,now))
    def get_post_for_run(self,run_id:str)->dict|None:
        row=self.db.execute("select * from post_deliveries where run_id=?",(run_id,)).fetchone(); return dict(row) if row else None
    def upsert_week(self,number:int,run_id:str,status:str,payload:dict)->None:
        self.db.execute("insert into week_deliveries values(?,?,?,?,?) on conflict(week_number) do update set status=excluded.status,updated_at=excluded.updated_at",(number,run_id,status,json.dumps(payload,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
    def record_error(self,run_id:str,message:str,severity:str="critical")->None:
        self.db.execute("insert into errors(run_id,severity,message,occurred_at) values(?,?,?,?)",(run_id,severity,message,datetime.now(timezone.utc).isoformat()))
        count=int(self.get_setting("consecutive_errors",0))+1; self.set_setting("consecutive_errors",count)
    def clear_errors(self)->None: self.set_setting("consecutive_errors",0)
    def set_setting(self,key:str,value:Any)->None:
        self.db.execute("insert into state values(?,?,?) on conflict(key) do update set value=excluded.value,updated_at=excluded.updated_at",(f"setting:{key}",json.dumps(value),datetime.now(timezone.utc).isoformat()))
    def get_setting(self,key:str,default:Any=None)->Any:
        row=self.db.execute("select value from state where key=?",(f"setting:{key}",)).fetchone()
        try: return json.loads(row["value"]) if row else default
        except ValueError: return default
    def health(self)->dict:
        memory=self.load_memory(); last=self.db.execute("select * from runs order by started_at desc limit 1").fetchone(); success=self.db.execute("select * from runs where status='succeeded' order by finished_at desc limit 1").fetchone(); sent=self.db.execute("select * from post_deliveries where status='sent' order by updated_at desc limit 1").fetchone()
        return {"storage":"OK","memory":"OK","posts":len(memory.posts),"current_week":memory.weeks[-1]["id"] if memory.weeks else "week-00 preview","open_events":sum(e["status"]=="open" for e in memory.events),"last_run":last["started_at"] if last else None,"last_success":success["finished_at"] if success else None,"last_sent_post":sent["external_post_id"] if sent else None,"last_decision":json.loads(last["decision_json"]) if last and last["decision_json"] else None,"consecutive_errors":self.get_setting("consecutive_errors",0)}

class InMemoryStorage(SQLiteStorage):
    def __init__(self): super().__init__(Path(":memory:"))

class SupabaseError(RuntimeError):
    """Sanitized remote error which never contains credentials or response bodies."""


class SupabaseHttpClient:
    """Small PostgREST/RPC client for the staging backend.

    Responses are held in memory and errors are deliberately redacted. The secret
    key is sent only in request headers and is never logged.
    """
    def __init__(self, url: str, secret_key: str, timeout: int = 20):
        if not url.startswith("https://") or not secret_key:
            raise ValueError("Supabase backend credentials are not configured")
        self.url, self.secret_key, self.timeout = url.rstrip("/"), secret_key, timeout

    def _request(self, method: str, path: str, payload: Any = None, headers: dict[str,str] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # Opaque sb_publishable_/sb_secret_ keys belong only in `apikey`.
        # Supabase's gateway supplies the internal role JWT for Data API calls.
        merged = {"apikey": self.secret_key, "Content-Type": "application/json", "Accept": "application/json", "User-Agent":"pandausagies-v2-staging-backend/1.0"}
        merged.update(headers or {})
        req = request.Request(f"{self.url}/rest/v1/{path}", data=body, method=method, headers=merged)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except (error.HTTPError, error.URLError, TimeoutError, socket.timeout) as exc:
            status = getattr(exc, "code", "network")
            category = "request"
            if isinstance(exc, error.HTTPError):
                raw_error = exc.read().lower()
                error_code = ""
                try:
                    error_code = str(json.loads(raw_error).get("code", ""))
                except (ValueError, AttributeError):
                    pass
                if b"invalid api key" in raw_error: category = "invalid_api_key"
                elif b"browser" in raw_error: category = "browser_rejected"
                elif b"jwt" in raw_error: category = "jwt_header"
                elif b"permission" in raw_error or b"policy" in raw_error: category = "permission"
                elif b"truncate" in raw_error and b"foreign key" in raw_error: category = "truncate_dependency"
                elif b"ambiguous" in raw_error: category = "sql_ambiguous"
                elif b"does not exist" in raw_error: category = "sql_missing_object"
                elif b"more than one row" in raw_error: category = "sql_multiple_rows"
                elif b"cardinality" in raw_error: category = "sql_cardinality"
                elif b"affect row a second time" in raw_error: category = "sql_duplicate_target"
            suffix = f"; code={error_code}" if isinstance(exc, error.HTTPError) and error_code else ""
            raise SupabaseError(f"Supabase request failed ({status}; {category}{suffix})") from None

    def rpc(self, name: str, payload: dict[str,Any]) -> Any:
        return self._request("POST", f"rpc/{parse.quote(name)}", payload)

    def select(self, table: str, query: str = "") -> Any:
        return self._request("GET", f"{parse.quote(table)}?{query}")

    def insert(self, table: str, payload: dict[str,Any], upsert: bool = False) -> Any:
        preference = "return=representation" + (",resolution=merge-duplicates" if upsert else "")
        return self._request("POST", parse.quote(table), payload, {"Prefer": preference})

    def patch(self, table: str, query: str, payload: dict[str,Any]) -> Any:
        return self._request("PATCH", f"{parse.quote(table)}?{query}", payload, {"Prefer":"return=representation"})

    def delete(self, table: str, query: str) -> Any:
        return self._request("DELETE", f"{parse.quote(table)}?{query}", headers={"Prefer":"return=minimal"})


class SupabaseStorage:
    """Real memory/lease adapter with optimistic concurrency semantics."""
    def __init__(self, client):
        self.client, self.memory_version = client, 0

    def load_memory(self) -> Memory:
        if hasattr(self.client, "load_memory"):  # Phase 5 injected boundary compatibility
            return Memory.from_dict(self.client.load_memory())
        rows = self.client.select("memory_state", "select=value,version&singleton=eq.true&limit=1")
        if not rows:
            raise SupabaseError("environment memory row is missing")
        self.memory_version = int(rows[0]["version"])
        value = rows[0].get("value") or {}
        return Memory.from_dict(value)

    def save_memory(self, memory: Memory) -> None:
        if hasattr(self.client, "save_memory"):
            self.client.save_memory(memory.to_dict()); return
        result = self.client.rpc("save_memory_cas", {"p_expected_version":self.memory_version,"p_value":memory.to_dict()})
        self.memory_version = int(result)

    def acquire_lock(self, name: str, owner: str, now: datetime | None = None, ttl_seconds: int = 300) -> bool:
        return bool(self.client.rpc("acquire_job_lease", {"p_name":name,"p_owner":owner,"p_ttl_seconds":ttl_seconds}))

    def heartbeat_lock(self, name: str, owner: str, ttl_seconds: int = 300) -> bool:
        return bool(self.client.rpc("heartbeat_job_lease", {"p_name":name,"p_owner":owner,"p_ttl_seconds":ttl_seconds}))

    def release_lock(self, name: str, owner: str) -> None:
        self.client.rpc("release_job_lease", {"p_name":name,"p_owner":owner})

    def get_setting(self, key: str, default: Any = None) -> Any:
        rows = self.client.select("settings", f"select=value&key=eq.{parse.quote(key)}&limit=1")
        return rows[0]["value"] if rows else default

    def set_setting(self, key: str, value: Any) -> None:
        rows = self.client.select("settings", f"select=key&key=eq.{parse.quote(key)}&limit=1")
        if rows:
            self.client.patch("settings", f"key=eq.{parse.quote(key)}", {"value":value})
        else:
            self.client.insert("settings", {"key":key,"value":value})

    def health(self) -> dict[str,Any]:
        memory = self.load_memory()
        last = self.client.select("job_runs", "select=started_at,status,decision&order=started_at.desc&limit=1")
        success = self.client.select("job_runs", "select=finished_at&status=eq.succeeded&order=finished_at.desc&limit=1")
        cursor=self.client.select("x_read_cursors","select=last_successful_x_read_at,last_status,last_seen_mention_id,error_count&key=eq.mentions&limit=1")
        mentions=self.client.select("mentions","select=x_post_id")
        candidates=self.client.select("reply_candidates","select=id")
        x=cursor[0] if cursor else {}
        return {"environment":"staging","storage":"OK","memory":"OK","posts":len(memory.posts),"current_week":memory.weeks[-1].get("id") if memory.weeks else "week-00 preview","open_events":sum(e.get("status")=="open" for e in memory.events),"last_run":last[0]["started_at"] if last else None,"last_success":success[0]["finished_at"] if success else None,"last_decision":last[0].get("decision") if last else None,"consecutive_errors":self.get_setting("consecutive_errors",0),"circuit_breaker":"OPEN" if self.get_setting("circuit_open",False) else "CLOSED","last_x_read":x.get("last_successful_x_read_at"),"last_x_read_status":x.get("last_status","never"),"last_seen_mention_id":x.get("last_seen_mention_id"),"mentions_stored":len(mentions),"reply_candidates":len(candidates),"x_errors":x.get("error_count",0)}
