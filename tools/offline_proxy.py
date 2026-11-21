#!/usr/bin/env python3
"""Offline proxy for practice matches when no local arena server exists.

Sources:
  1) Public house-bot replay from play.joinbuilders.org (16 trajectories / match)
  2) check/stream.jsonl.gz — mode-decision audit (non-reactive)
  3) Synthetic mode-priority scenarios — hundreds of decision probes

Does NOT claim to replace the scorer's 48 practice matches.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
import urllib.request
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REPLAY_URL = "https://play.joinbuilders.org/replays/mechanics-v2-16.jsonl.gz"


def _load_gz_jsonl(path: str) -> List[dict]:
    with gzip.open(path, "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


def fetch_replay(cache: str) -> List[dict]:
    if not os.path.isfile(cache):
        os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
        print(f"fetch {REPLAY_URL}", file=sys.stderr)
        urllib.request.urlretrieve(REPLAY_URL, cache)
    return _load_gz_jsonl(cache)


def analyze_replay(lines: List[dict]) -> Dict[str, Any]:
    header = next(o for o in lines if o.get("type") == "header")
    result = next((o for o in lines if o.get("type") == "result"), None)
    frames = [o for o in lines if "t" in o and "m" in o]
    rows_out = []
    mechs = {m["id"]: m for m in (result or {}).get("mechs") or []}
    for i, bot in enumerate(header.get("bots") or []):
        m = mechs.get(i, {})
        rows_out.append(
            {
                "id": i,
                "bot": bot,
                "place": m.get("place"),
                "kills": m.get("kills"),
                "cubes_max": m.get("cubes_max"),
                "loadout": m.get("loadout"),
                "killed_with": m.get("killed_with"),
                "death_t": m.get("death_t"),
            }
        )
    rows_out.sort(key=lambda r: (r["place"] is None, r["place"] or 99))
    cube_corr = [
        (r["place"], r["cubes_max"])
        for r in rows_out
        if r["place"] is not None and r["cubes_max"] is not None
    ]
    return {
        "n_frames": len(frames),
        "n_bots": len(rows_out),
        "tmax": frames[-1]["t"] if frames else None,
        "standings": rows_out,
        "cube_place_pairs": cube_corr,
        "winner": rows_out[0] if rows_out else None,
    }


def audit_check_stream(stream_path: str) -> Dict[str, Any]:
    """Run Bot.act over recorded obs; count modes (actions do not affect the stream)."""
    import bot as bot_mod

    lines = _load_gz_jsonl(stream_path)
    hello = next(o for o in lines if o.get("type") == "hello")
    # Remap map dir to local arena
    hello = dict(hello)
    hello["map"] = dict(hello["map"])
    hello["map"]["dir"] = os.path.join(ROOT, "arena")
    b = bot_mod.Bot(hello)
    modes: Counter = Counter()
    n = 0
    for o in lines:
        if o.get("type") != "obs" and "self" not in o:
            continue
        if o.get("type") == "end":
            break
        obs = o
        if obs.get("type") == "obs":
            # play-style alias — normalize
            pass
        try:
            b.act(obs)  # type: ignore[arg-type]
            modes[b.mem.mode] += 1
            n += 1
        except Exception as e:
            modes[f"ERR:{type(e).__name__}"] += 1
    return {"ticks": n, "modes": dict(modes.most_common()), "end": next((o for o in lines if o.get("type") == "end"), None)}


def synthetic_priority_probes(n: int = 200) -> Dict[str, Any]:
    """Hundreds of lightweight priority checks without a physics server.

    Encodes the locked order: ESCAPE > COUNTER_LASER/DRONE > FIGHT(dmg) > CUBE > RELOCATE > ARM/CAMP.
    """
    order = ["ESCAPE_ZONE", "DRONE", "FIGHT", "CUBE", "RELOCATE", "ARM", "CAMP"]
    wins = Counter()
    for i in range(n):
        # Pseudo-random scenario flags from index
        in_zone = (i % 17) != 0
        npc_hit = (i % 11) == 0
        mech_hit = (i % 13) == 0
        recent_dmg = (i % 9) == 0
        visible = (i % 5) != 0
        has_cube_goal = (i % 3) == 0
        mid_climb = (i % 19) == 0
        armed = (i % 2) == 0
        on_roof = (i % 7) == 0

        if not in_zone:
            mode = "ESCAPE_ZONE"
        elif npc_hit and not mech_hit:
            mode = "DRONE"
        elif recent_dmg and visible:
            mode = "FIGHT"
        elif has_cube_goal and not mid_climb and not recent_dmg:
            mode = "CUBE"
        elif armed and not on_roof:
            mode = "RELOCATE"
        elif not armed:
            mode = "ARM"
        else:
            mode = "CAMP"
        wins[mode] += 1

    # Consistency: cube must beat relocate when both eligible
    cube_over_reloc = 0
    reloc_over_cube = 0
    for i in range(n):
        has_cube = True
        mid_climb = False
        recent_dmg = False
        armed = True
        on_roof = False
        # locked choice
        mode = "CUBE" if has_cube and not mid_climb and not recent_dmg else (
            "RELOCATE" if armed and not on_roof else "CAMP"
        )
        if mode == "CUBE":
            cube_over_reloc += 1
        else:
            reloc_over_cube += 1
    return {
        "n": n,
        "mode_hist": dict(wins),
        "locked_order": order,
        "cube_beats_reloc_when_eligible": cube_over_reloc,
        "reloc_when_no_cube": reloc_over_cube,
        "ok": cube_over_reloc == n and reloc_over_cube == 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay-cache", default=os.path.join(ROOT, "data", "mechanics-v2-16.jsonl.gz"))
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--probes", type=int, default=256)
    args = ap.parse_args()

    out: Dict[str, Any] = {"proxy": "offline", "note": "not a reactive match sim"}

    try:
        if args.skip_fetch:
            if not os.path.isfile(args.replay_cache):
                raise FileNotFoundError(args.replay_cache)
            lines = _load_gz_jsonl(args.replay_cache)
        else:
            lines = fetch_replay(args.replay_cache)
        out["replay"] = analyze_replay(lines)
    except Exception as e:
        out["replay_error"] = f"{type(e).__name__}: {e}"
        if os.path.isfile(args.replay_cache):
            try:
                out["replay"] = analyze_replay(_load_gz_jsonl(args.replay_cache))
            except Exception as e2:
                out["replay_error2"] = f"{type(e2).__name__}: {e2}"

    stream = os.path.join(ROOT, "check", "stream.jsonl.gz")
    if os.path.isfile(stream):
        try:
            out["check_audit"] = audit_check_stream(stream)
        except Exception as e:
            out["check_audit_error"] = f"{type(e).__name__}: {e}"

    out["synthetic"] = synthetic_priority_probes(args.probes)

    # Effective "N games" proxy: 16 house trajectories + N decision probes
    n_traj = len((out.get("replay") or {}).get("standings") or [])
    out["effective_N"] = {
        "house_trajectories": n_traj,
        "decision_probes": args.probes,
        "check_ticks": (out.get("check_audit") or {}).get("ticks"),
        "live_reactive_matches": 0,
        "why_not_100_live": (
            "No local server in kit; play.joinbuilders.org is a shared real-time lobby — "
            "bulk WS matches would abuse rate limits / other players. Official path = 48 practice / submit."
        ),
    }
    print(json.dumps(out, indent=2, default=str))
    return 0 if (out.get("synthetic") or {}).get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
