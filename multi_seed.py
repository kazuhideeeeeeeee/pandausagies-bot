from __future__ import annotations
import argparse, json
from datetime import datetime
from zoneinfo import ZoneInfo
from pandausagies_v2.simulation import simulate

DEFAULT_SEEDS=(1001,2002,3003,4004,5005)
def main()->None:
 parser=argparse.ArgumentParser(); parser.add_argument("--days",type=int,default=90); parser.add_argument("--seeds",type=int,nargs="*",default=DEFAULT_SEEDS); args=parser.parse_args()
 start=datetime(2026,8,24,tzinfo=ZoneInfo("Asia/Tokyo")); reports=[]; all_posts=[]
 for seed in args.seeds:
  memory,report=simulate(args.days,seed,start); reports.append(report); all_posts.extend({**p,"seed":seed} for p in memory.posts)
 good=[p for p in all_posts if p["category"]=="ordinary"][:20]
 unsure=[p for p in all_posts if p["category"]=="offbeat"][:10]
 output={"mode":"MULTI_SEED_SIMULATION","external_calls":0,"sent":False,"reports":reports,"good_posts":good,"unsure_posts":unsure,"ng_posts":[]}
 print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
