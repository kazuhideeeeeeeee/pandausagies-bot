from __future__ import annotations
import copy,json
from contextlib import contextmanager
from datetime import datetime,timedelta
from typing import Any
from .memory import Memory

class UniqueViolation(RuntimeError): pass
class PolicyDenied(RuntimeError): pass

class FakeSupabase:
    """In-process Postgres/Supabase behavioral fake. It performs no I/O."""
    PUBLIC_TABLES={"public_state","public_songs","public_media"}
    def __init__(self):
        self.tables={name:{} for name in ("runs","decisions","ledger","weeks","locks","errors","settings","public_state","public_songs","public_media")}; self.memory=Memory(); self.available=True
    @contextmanager
    def transaction(self):
        if not self.available: raise RuntimeError("database unavailable")
        snapshot=(copy.deepcopy(self.tables),self.memory.clone())
        try: yield self
        except Exception: self.tables,self.memory=snapshot; raise
    def insert_unique(self,table:str,key:Any,value:dict):
        if key in self.tables[table]: raise UniqueViolation(f"{table}:{key}")
        self.tables[table][key]=copy.deepcopy(value)
    def compare_and_set(self,table:str,key:Any,expected:str,new:str)->bool:
        row=self.tables[table].get(key)
        if not row or row.get("status")!=expected: return False
        row["status"]=new; return True
    def acquire_lease(self,name:str,owner:str,now:datetime,ttl:int=300)->bool:
        row=self.tables["locks"].get(name)
        if row and row["expires_at"]>now and row["owner"]!=owner: return False
        self.tables["locks"][name]={"owner":owner,"acquired_at":now,"heartbeat_at":now,"expires_at":now+timedelta(seconds=ttl)}; return True
    def heartbeat(self,name:str,owner:str,now:datetime,ttl:int=300)->bool:
        row=self.tables["locks"].get(name)
        if not row or row["owner"]!=owner or row["expires_at"]<=now: return False
        row["heartbeat_at"]=now; row["expires_at"]=now+timedelta(seconds=ttl); return True
    def release_lease(self,name:str,owner:str):
        if self.tables["locks"].get(name,{}).get("owner")==owner: self.tables["locks"].pop(name,None)
    def public_read(self,table:str,role:str="anon"):
        if role=="anon" and table not in self.PUBLIC_TABLES: raise PolicyDenied(table)
        return copy.deepcopy(self.tables[table])
    def publish_snapshot(self,snapshot:dict): self.tables["public_state"]={snapshot["version"]:copy.deepcopy(snapshot)}

class SupabaseStorage:
    def __init__(self,client:FakeSupabase): self.client=client
    def load_memory(self)->Memory:
        if not self.client.available: raise RuntimeError("database unavailable")
        return self.client.memory.clone()
    def save_memory(self,memory:Memory): self.client.memory=memory.clone()
