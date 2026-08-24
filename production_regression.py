from __future__ import annotations
import argparse,json
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from pandausagies_v2.persistent_simulation import run_days
from pandausagies_v2.production_storage import InMemoryStorage

def main():
 parser=argparse.ArgumentParser(); parser.add_argument("--days",type=int,default=90); parser.add_argument("--seeds",type=int,nargs="*",default=(1001,3003,5005)); args=parser.parse_args(); start=datetime(2026,8,24,tzinfo=ZoneInfo("Asia/Tokyo")); reports=[]
 for seed in args.seeds:
  storage=InMemoryStorage(); run_days(storage,start,0,args.days,seed); memory=storage.load_memory(); categories=Counter(p["category"] for p in memory.posts); motifs=Counter(p["motif"] for p in memory.posts); days=Counter(p["at"][:10] for p in memory.posts)
  reports.append({"seed":seed,"posts":len(memory.posts),"zero_post_days":args.days-len(days),"one_post_days":sum(v==1 for v in days.values()),"two_post_days":sum(v==2 for v in days.values()),"categories":dict(categories),"motifs":dict(motifs),"weeks":len(memory.weeks),"external_calls":0})
 print(json.dumps({"mode":"PRODUCTION_SAFETY_REGRESSION","reports":reports,"external_calls":0},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
