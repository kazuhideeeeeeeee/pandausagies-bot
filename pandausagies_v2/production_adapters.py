from __future__ import annotations
import hashlib,json,re,unicodedata
from dataclasses import dataclass
from datetime import datetime,timedelta

def payload_fingerprint(payload:dict)->str:
    text=unicodedata.normalize("NFKC",payload.get("text", "")); text=re.sub(r"\s+"," ",text).strip()
    stable={"text":text,"media_hash":payload.get("media_hash") or payload.get("media_id"),"song_id":payload.get("song_id"),"url":payload.get("url"),"category":payload.get("category")}
    return hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

class DeliveryUnknown(Exception): pass
class RetryableDelivery(Exception):
    def __init__(self,message:str,retry_after:int=60): super().__init__(message); self.retry_after=retry_after
class PermanentDelivery(Exception): pass

class FakeClock:
    def __init__(self,now:datetime): self.now=now
    def advance(self,seconds:int): self.now+=timedelta(seconds=seconds)

class FakeXSender:
    def __init__(self): self.outcomes=[]; self.posts={}; self.effects=0; self.media_uploads=0
    def queue(self,*outcomes): self.outcomes.extend(outcomes)
    def send(self,fingerprint:str,payload:dict)->str:
        outcome=self.outcomes.pop(0) if self.outcomes else "success"
        if outcome=="429": raise RetryableDelivery("rate limited",300)
        if outcome in ("5xx","timeout_failure"): raise RetryableDelivery(outcome,120)
        if outcome=="auth": raise PermanentDelivery("authentication failure")
        if outcome=="media_success_text_fail": self.media_uploads+=1; raise PermanentDelivery("text rejected after media upload")
        if fingerprint not in self.posts: self.effects+=1; self.posts[fingerprint]=f"fake-x-{len(self.posts)+1}"
        if outcome in ("timeout_success","response_lost"): raise DeliveryUnknown(outcome)
        return self.posts[fingerprint]
    def lookup(self,fingerprint:str)->str|None: return self.posts.get(fingerprint)

class FakeWeekPublisher:
    def __init__(self): self.outcomes=[]; self.published={}; self.effects=0
    def queue(self,*outcomes): self.outcomes.extend(outcomes)
    def publish(self,week_number:int,payload:dict)->str:
        outcome=self.outcomes.pop(0) if self.outcomes else "success"
        if outcome in ("failed","timeout_unpublished"): raise RetryableDelivery(outcome,180)
        if week_number not in self.published: self.effects+=1; self.published[week_number]=f"fake-week-{week_number}"
        if outcome in ("timeout_published","response_lost"): raise DeliveryUnknown(outcome)
        return self.published[week_number]
    def lookup(self,week_number:int)->str|None: return self.published.get(week_number)

class FakeNotifier:
    def __init__(self): self.events=[]
    def notify(self,kind:str,summary:str): self.events.append({"kind":kind,"summary":summary})

RETRY_CLASSIFICATION={"timeout":"retry_after_reconcile","temporary_network":"retry","429":"retry_after","5xx":"retry","authentication":"human_required","permission":"human_required","malformed":"no_retry","policy_rejection":"human_required","invalid_media":"human_required"}
