#!/usr/bin/env python3
"""Emit a try/<label> commit from current strategy codebase by rewriting levers.py.

Usage:
  python3 tools/emit_variant.py roof-all S1 --desc "every loadout camps on a roof"
  python3 tools/emit_variant.py r3-full ALL --desc "all approved strategy rows"
  python3 tools/emit_variant.py r3-core S1,N1,N2,N3,S2,S3,S4,F1 --desc "core stack sans N4/N5/N6"

Does not push. After emit: bash tools/push_variant.sh <label> "<desc>"
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL = ["S1", "N1", "N2", "N3", "S2", "S3", "N4", "N5", "N6", "S4", "F1"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("label")
    ap.add_argument("levers", help="comma list or ALL or NONE")
    ap.add_argument("--desc", default="")
    args = ap.parse_args()
    label = args.label
    if args.levers.upper() == "ALL":
        on = set(ALL)
    elif args.levers.upper() == "NONE":
        on = set()
    else:
        on = {x.strip().upper() for x in args.levers.split(",") if x.strip()}
        bad = on - set(ALL)
        if bad:
            print(f"unknown levers: {bad}", file=sys.stderr)
            return 2

    lines = [
        '"""Strategy-plan levers for try/* A/B builds (robo-fight-strategy-plan.md).',
        "",
        "Each try/<label> commit sets LABEL + which LEVERS are True. Bot.name = lh-<LABEL>.",
        '"""',
        "from __future__ import annotations",
        "",
        "from typing import Dict",
        "",
        f'LABEL = "{label}"',
        "",
        "LEVERS: Dict[str, bool] = {",
    ]
    comments = {
        "S1": "every loadout camps on a roof",
        "N1": "laser counter for every loadout",
        "N2": "edge-guard hunters climbing our roof",
        "N3": "after kill: loot then heal ≥90%",
        "S2": "remove 1v1 ambush",
        "S3": "no ARM boost inside the zone",
        "N4": "pre-charged laser peeks",
        "N5": "cube snowball (drones + kill cubes)",
        "N6": "contest supply drop 1",
        "S4": "ROTATE gatekeep off in practice",
        "F1": "FFA detector + survival mode",
    }
    for k in ALL:
        lines.append(f'    "{k}": {"True" if k in on else "False"},  # {comments[k]}')
    lines += [
        "}",
        "",
        "",
        "def on(key: str) -> bool:",
        "    return bool(LEVERS.get(key))",
        "",
    ]
    path = os.path.join(ROOT, "levers.py")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"wrote {path} LABEL={label} on={sorted(on)}")
    # Ensure Bot.name stays derived from levers.LABEL (no hardcoded edit needed).
    bot_path = os.path.join(ROOT, "bot.py")
    with open(bot_path) as f:
        bot = f.read()
    if "name = f\"lh-{levers.LABEL}\"" not in bot and "name = f'lh-{levers.LABEL}'" not in bot:
        bot2 = re.sub(
            r'^\s*name\s*=\s*["\'][^"\']+["\']',
            '    name = f"lh-{levers.LABEL}"',
            bot,
            count=1,
            flags=re.M,
        )
        if bot2 != bot:
            with open(bot_path, "w") as f:
                f.write(bot2)
            print("normalized Bot.name to f\"lh-{levers.LABEL}\"")
    if args.desc:
        print(f"desc: {args.desc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
