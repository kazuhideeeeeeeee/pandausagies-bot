from __future__ import annotations
from datetime import datetime,timedelta
from .production_storage import SQLiteStorage
from .safety import FakeSender,SafetyConfig,SafetyEngine

def run_days(storage:SQLiteStorage,start:datetime,offset:int,days:int,seed:int=1)->dict:
    engine=SafetyEngine(storage,FakeSender(),SafetyConfig(autonomous_enabled=True,allow_external_send=False),seed)
    results=[]
    for day in range(offset,offset+days):
        current=start+timedelta(days=day)
        for hour in (10,19):
            now=current.replace(hour=hour); run_id=f"day-{day:04d}-{hour}"
            results.append(engine.run(run_id,now,start))
    memory=storage.load_memory()
    return {"results":results,"posts":len(memory.posts),"weeks":len(memory.weeks),"events":len(memory.events),"songs":memory.song_usage,"media":memory.media_usage,"motifs":memory.motif_usage}
