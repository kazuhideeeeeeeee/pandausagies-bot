from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def event(channel: str, message: str, **fields: Any) -> None:
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "message": message,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)
