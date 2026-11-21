#!/usr/bin/env python3
"""Drive one (or a few) human-seat matches on play.joinbuilders.org via WebSocket.

Protocol (from assets/play-*.js):
  connect wss://play.joinbuilders.org/play?name=…&sid=…
  ← lobby {phase, you:{ready,seated,…}, …}
  → {type:ready, name}
  ← hello (mechfight/1) then obs… then end / results
  → {type:loaded} once after hello (browser does this on pointer-lock click)
  → action dict {tick, move, aim, boost, fire, …} per obs (no type field)

SAFETY: default max_matches=1, polite waits, unique name. Do NOT loop this at volume —
the lobby is shared with real players. Prefer GitHub submit (48 practice) for scoring.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import time
import uuid
from typing import Any, Dict, Optional
from urllib.request import urlopen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

HOST = "play.joinbuilders.org"


def _ssl():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
        return ctx


def mm_pick() -> dict:
    try:
        with urlopen(f"https://{HOST}/mm/pick", timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:
        import subprocess
        out = subprocess.check_output(["curl", "-sL", f"https://{HOST}/mm/pick"], text=True)
        return json.loads(out)


def _action_for_play(act: Dict[str, Any], tick: float) -> Dict[str, Any]:
    """Strip protocol-only fields the browser client does not send."""
    out = {"tick": tick}
    for k in ("move", "aim", "boost", "jump", "fire", "reload", "pick", "take", "drop"):
        if k in act and act[k] is not None:
            out[k] = act[k]
    return out


async def play_one(
    name: str,
    sid: str,
    max_wait_s: float = 180.0,
    match_timeout_s: float = 600.0,
) -> Dict[str, Any]:
    import websockets
    import bot as bot_mod

    uri = f"wss://{HOST}/play?name={name}&sid={sid}"
    log: Dict[str, Any] = {"name": name, "uri": uri, "events": []}
    bot = None
    t0 = time.time()
    loaded = False

    async with websockets.connect(uri, open_timeout=15, max_size=20_000_000, ssl=_ssl()) as ws:
        # Ready up immediately once we see lobby
        ready_sent = False

        while time.time() - t0 < max_wait_s + match_timeout_s:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                if bot is None and time.time() - t0 > max_wait_s:
                    log["status"] = "timeout_waiting_match"
                    return log
                continue
            if isinstance(raw, bytes):
                continue
            for line in str(raw).split("\n"):
                if not line.strip():
                    continue
                msg = json.loads(line)
                typ = msg.get("type")

                if typ == "lobby":
                    you = msg.get("you") or {}
                    if not ready_sent and not you.get("ready"):
                        await ws.send(json.dumps({"type": "ready", "name": name}))
                        ready_sent = True
                        log["events"].append({"t": time.time() - t0, "e": "ready"})
                    if msg.get("phase") == "running" and you.get("seated"):
                        log["events"].append({"t": time.time() - t0, "e": "seated", "match": msg.get("match")})
                    continue

                if typ == "hello":
                    hello = dict(msg)
                    hello["map"] = dict(hello.get("map") or {})
                    hello["map"]["dir"] = os.path.join(ROOT, "arena")
                    bot = bot_mod.Bot(hello)
                    loaded = False
                    await ws.send(json.dumps({"type": "loaded"}))
                    loaded = True
                    log["events"].append(
                        {"t": time.time() - t0, "e": "hello", "slot": hello.get("slot"), "seed": hello.get("seed")}
                    )
                    continue

                if typ == "obs" or (bot is not None and "self" in msg and "tick" in msg and typ not in ("end", "results", "lobby", "hello")):
                    if bot is None:
                        continue
                    obs = msg
                    if not loaded:
                        await ws.send(json.dumps({"type": "loaded"}))
                        loaded = True
                    act = bot.act(obs)  # type: ignore[arg-type]
                    tick = float(obs.get("tick") or 0)
                    await ws.send(json.dumps(_action_for_play(act, tick)))
                    continue

                if typ == "end":
                    log["end"] = {"place": msg.get("place"), "kills": msg.get("kills")}
                    log["events"].append({"t": time.time() - t0, "e": "end", **log["end"]})
                    continue

                if typ == "results":
                    log["results"] = msg
                    log["status"] = "ok"
                    log["events"].append({"t": time.time() - t0, "e": "results"})
                    return log

        log["status"] = log.get("status") or "timeout"
        return log


async def amain(args: argparse.Namespace) -> int:
    # Prefer system certs via curl for mm if ssl broken
    try:
        pick = mm_pick()
    except Exception as e:
        print(f"mm/pick failed ({e}); connecting without room hint", file=sys.stderr)
        pick = {}
    print(f"mm/pick -> {pick}", file=sys.stderr)

    outcomes = []
    for i in range(args.max_matches):
        name = args.name if args.max_matches == 1 else f"{args.name}-{i+1}"
        sid = args.sid or uuid.uuid4().hex[:16]
        print(f"match {i+1}/{args.max_matches} as {name}", file=sys.stderr)
        out = await play_one(name, sid, max_wait_s=args.wait, match_timeout_s=args.match_timeout)
        outcomes.append(out)
        print(json.dumps(out, indent=2, default=str))
        if i + 1 < args.max_matches:
            await asyncio.sleep(args.gap)
    summary = {
        "n": len(outcomes),
        "places": [o.get("end", {}).get("place") for o in outcomes],
        "kills": [o.get("end", {}).get("kills") for o in outcomes],
        "statuses": [o.get("status") for o in outcomes],
    }
    print("SUMMARY", json.dumps(summary))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default="lh-locked")
    ap.add_argument("--sid", default="")
    ap.add_argument("--max-matches", type=int, default=1, help="Keep tiny. Shared lobby.")
    ap.add_argument("--wait", type=float, default=180.0, help="Seconds to wait to get seated")
    ap.add_argument("--match-timeout", type=float, default=600.0)
    ap.add_argument("--gap", type=float, default=30.0, help="Pause between matches")
    args = ap.parse_args()
    if args.max_matches > 3:
        print("refusing max-matches>3 (rate-limit / shared lobby)", file=sys.stderr)
        return 2
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
