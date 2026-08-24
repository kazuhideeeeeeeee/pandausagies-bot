from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pandausagies_v2.production_storage import SupabaseHttpClient
from pandausagies_v2.write_preflight import ProductionWritePreflight,WritePreflightConfig


ROOT=Path(__file__).resolve().parent.parent


def truth(name:str)->bool: return os.getenv(name,"").strip().lower()=="true"


def main()->None:
    for raw in (ROOT/".env").read_text(encoding="utf-8").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            key,value=raw.split("=",1);os.environ.setdefault(key.strip(),value.strip())
    write_names=("API_KEY","API_SECRET","ACCESS_TOKEN","ACCESS_TOKEN_SECRET")
    config=WritePreflightConfig(os.getenv("APP_ENV",""),os.getenv("X_APP_ID",""),truth("ALLOW_EXTERNAL_SEND"),truth("AUTONOMOUS_ENABLED"),truth("KILL_SWITCH"),truth("X_WRITE_ENABLED"),all(os.getenv(name,"") for name in write_names))
    result=ProductionWritePreflight(SupabaseHttpClient(os.getenv("SUPABASE_URL",""),os.getenv("SUPABASE_SECRET_KEY","")),config).run(datetime.now(ZoneInfo("Asia/Tokyo")))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__": main()
