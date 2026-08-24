from __future__ import annotations
import json, sqlite3
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

class SupabaseStorage:
    """Future adapter boundary. It requires an injected client and never creates a connection itself."""
    def __init__(self,client): self.client=client
    def load_memory(self): return Memory.from_dict(self.client.load_memory())
    def save_memory(self,memory): self.client.save_memory(memory.to_dict())
