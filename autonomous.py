from __future__ import annotations

import argparse

from pandausagies_v2.autonomous import format_observation, observe


def main() -> None:
    parser = argparse.ArgumentParser(description="Observe pandausagies autonomous decisions safely")
    parser.add_argument("--observe", action="store_true", help="read-only decision preview")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if not args.observe:
        parser.error("Phase 3 only permits --observe")
    print(format_observation(observe(seed=args.seed)))


if __name__ == "__main__":
    main()
