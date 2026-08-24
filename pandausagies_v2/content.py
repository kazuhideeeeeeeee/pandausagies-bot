from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_FILES = ("songs.json", "weeks.json", "current.json")


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_content(content_dir: Path) -> dict[str, Any]:
    return {name: read_json(content_dir / name) for name in REQUIRED_FILES}
