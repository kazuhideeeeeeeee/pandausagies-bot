from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pandausagies_v2.memory import JsonMemoryStore, Memory


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="var/autonomous-state.json")
    args = parser.parse_args()
    state = JsonMemoryStore(Path(args.path)).load(Memory())
    print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
