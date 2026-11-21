#!/usr/bin/env python3
"""Private-room live testbed for play.joinbuilders.org (Python port of lobby_harness.js).

Creates private rooms via /mm/code/new, hosts a match (empty seats → house bots),
runs a Bot from a git commit (or local tree), records place/kills/hp/events, and
aggregates H.cmp()-style stats.

Sameer approved private rooms. Do not use the public lobby (/play) for bulk runs.

Examples:
  python3 tools/private_room_harness.py one --tag best --commit b7b5c38367dbf208f836f77d8f8a1ee4dd2658f4
  python3 tools/private_room_harness.py batch \\
      --commits best=b7b5c38367dbf208f836f77d8f8a1ee4dd2658f4,sticky=cc6052e5513b3c5b1eaec151ce127c57e871ed88 \\
      --per-tag 4 --rooms 4 --out results/live-batch.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import ssl
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "play.joinbuilders.org"
FILES = [
    "mechfight.py",
    "bot.py",
    "world.py",
    "cover.py",
    "nav.py",
    "combat.py",
    "memory.py",
    "levers.py",
]
DATA = ["data/cover.bin", "data/roofs.json"]

RUNS: List[Dict[str, Any]] = []
STOP = False


def _ssl():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _http_get(url: str) -> Tuple[int, str]:
    """Return (status, body). Uses curl so we can read 429 JSON bodies."""
    proc = subprocess.run(
        [
            "curl",
            "-sS",
            "-m",
            "25",
            "-w",
            "\n%{http_code}",
            "-H",
            "Cache-Control: no-store",
            "-H",
            "User-Agent: rf-private-room/1",
            url,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"curl exit {proc.returncode}")
    body, _, code_s = proc.stdout.rpartition("\n")
    return int(code_s or "0"), body


def new_room(sid: str, retries: int = 30) -> dict:
    url = f"https://{HOST}/mm/code/new?sid={sid}"
    last = ""
    for i in range(retries):
        code, body = _http_get(url)
        last = body
        if code == 200:
            data = json.loads(body)
            if data.get("code"):
                return data
            # unexpected 200
            print(f"mm/code/new unexpected: {data}", flush=True)
        retry_s = 2.0
        try:
            retry_s = float(json.loads(body).get("retry_s") or retry_s)
        except Exception:
            pass
        wait = max(retry_s + 2.0, min(90.0, 1.7 ** i)) + random.random()
        print(f"mm/code/new HTTP {code} ({body[:80]}); wait {wait:.1f}s", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"mm/code/new failed after retries: {last[:200]}")


def _action_for_play(act: Dict[str, Any], tick: float) -> Dict[str, Any]:
    out: Dict[str, Any] = {"tick": tick}
    for k in ("move", "aim", "boost", "jump", "fire", "reload", "pick", "take", "drop"):
        if k in act and act[k] is not None:
            out[k] = act[k]
    return out


def materialize_commit(commit: str, cache_dir: str) -> str:
    """Extract bot sources for `commit` into cache_dir/<commit>/ and return that path.

    commit='local' uses the current working tree (ROOT).
    """
    if commit in ("local", ".", "HEAD"):
        return ROOT
    dest = os.path.join(cache_dir, commit)
    marker = os.path.join(dest, ".ok")
    if os.path.isfile(marker):
        return dest
    os.makedirs(dest, exist_ok=True)
    os.makedirs(os.path.join(dest, "data"), exist_ok=True)
    # Symlink arena so hello map.dir works
    arena_link = os.path.join(dest, "arena")
    if not os.path.exists(arena_link):
        os.symlink(os.path.join(ROOT, "arena"), arena_link)
    listed = subprocess.check_output(
        ["git", "-C", ROOT, "ls-tree", "-r", "--name-only", commit],
        text=True,
    ).splitlines()
    want = set(FILES + DATA)
    paths = [p for p in listed if p in want]
    if "bot.py" not in paths:
        raise RuntimeError(f"commit {commit} missing bot.py")
    # levers.py optional on older commits
    cmd = ["git", "-C", ROOT, "archive", commit] + paths
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
    subprocess.run(["tar", "-x", "-C", dest, "-f", "-"], input=proc.stdout, check=True)
    open(marker, "w").write("1")
    return dest


def load_bot_class(bot_dir: str):
    """Import Bot from bot_dir with a clean module namespace."""
    # Drop previously loaded game modules so commit A/B don't share state.
    for m in list(sys.modules):
        if m in FILES or m.split(".")[0] in {f[:-3] for f in FILES}:
            if m.split(".")[0] in {
                "mechfight",
                "bot",
                "world",
                "cover",
                "nav",
                "combat",
                "memory",
                "levers",
            }:
                sys.modules.pop(m, None)
    # Prefer bot_dir on sys.path
    sys.path = [p for p in sys.path if not p.startswith(tempfile.gettempdir())]
    if bot_dir in sys.path:
        sys.path.remove(bot_dir)
    sys.path.insert(0, bot_dir)
    import mechfight as mf  # noqa: F401
    import bot as bot_mod

    return bot_mod, mf


async def run_one(
    commit: str,
    tag: str,
    cache_dir: str,
    name: Optional[str] = None,
    timeout_s: float = 9.5 * 60,
    keep_frames: bool = False,
) -> Dict[str, Any]:
    import websockets

    sid = uuid.uuid4().hex
    name = name or f"rf-{tag}"
    room = new_room(sid)
    if not room.get("code"):
        raise RuntimeError(f"no room: {room}")
    code, room_id = room["code"], room["room"]
    url = (
        f"wss://{HOST}/r/{room_id}/play?token=&sid={sid}"
        f"&name={quote(name)}&code={code}"
    )
    S: Dict[str, Any] = {
        "commit": commit,
        "tag": tag,
        "name": name,
        "code": code,
        "room": room_id,
        "started": time.time(),
        "ticks": 0,
        "hpLog": [],
        "ev": [],
        "end": None,
        "lateMs": 0.0,
        "slow": 0,
        "hello": None,
        "modes": {},
        "done": None,
        "err": None,
    }
    RUNS.append(S)

    bot_dir = materialize_commit(commit, cache_dir)
    bot = None
    mf = None
    last_act: Dict[str, Any] = {}
    started_host = False
    t_deadline = time.time() + timeout_s

    live_task = None

    async with websockets.connect(
        url, open_timeout=20, max_size=20_000_000, ssl=_ssl()
    ) as ws:
        # Spectator attach shortly after join (mirrors H.one)
        async def watch():
            wurl = (
                f"wss://{HOST}/r/{room_id}/live?token=&code={code}"
                f"&sid=watch{uuid.uuid4().hex[:8]}"
            )
            S["liveEv"] = []
            S["fires"] = []
            S["ff"] = []
            try:
                async with websockets.connect(
                    wurl, open_timeout=15, max_size=40_000_000, ssl=_ssl()
                ) as lws:
                    S["livews"] = True
                    while S.get("done") is None and time.time() < t_deadline:
                        try:
                            raw = await asyncio.wait_for(lws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            continue
                        for line in str(raw).split("\n"):
                            if not line:
                                continue
                            try:
                                d = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if d.get("type") == "header":
                                S["header"] = {
                                    "bots": d.get("bots"),
                                    "mechs": [[m["id"], m["name"]] for m in d.get("mechs", [])],
                                }
                                S["liveEv"] = []
                                S["fires"] = []
                                S["ff"] = []
                            elif "t" in d:
                                if d.get("ev"):
                                    for x in d["ev"]:
                                        if x.get("e") == "death":
                                            S["liveEv"].append(
                                                [d["t"] / 20, "death", x.get("id"), x.get("by"), x.get("place")]
                                            )
                                        elif x.get("e") == "hit":
                                            S["liveEv"].append(
                                                [
                                                    d["t"] / 20,
                                                    "hit",
                                                    x.get("src"),
                                                    x.get("dst"),
                                                    round(x.get("amt") or 0),
                                                    x.get("w"),
                                                ]
                                            )
                                        elif x.get("e") == "fire":
                                            S["fires"].append([d["t"] / 20, x.get("id"), x.get("w")])
                                if keep_frames and "m" in d:
                                    S["ff"].append(
                                        [
                                            d["t"],
                                            [
                                                [
                                                    m[0],
                                                    round(m[1], 1),
                                                    round(m[2], 1),
                                                    round(m[3], 1),
                                                    round(m[4], 3),
                                                    round(m[5], 3),
                                                    round(m[6]),
                                                ]
                                                for m in d["m"]
                                            ],
                                        ]
                                    )
            except Exception as e:
                S["watchErr"] = str(e)

        # Delay watch start a bit like H.one
        async def start_watch_later():
            await asyncio.sleep(1.5)
            await watch()

        live_task = asyncio.create_task(start_watch_later())

        while time.time() < t_deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                if S["end"] is not None:
                    break
                continue
            if isinstance(raw, bytes):
                continue
            for line in str(raw).split("\n"):
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                typ = d.get("type")

                if typ == "lobby":
                    you = d.get("you") or {}
                    if not you.get("ready"):
                        await ws.send(json.dumps({"type": "ready", "name": name}))
                    if (
                        not started_host
                        and you.get("host")
                        and d.get("phase") != "running"
                    ):
                        started_host = True
                        await asyncio.sleep(0.5)
                        await ws.send(json.dumps({"type": "start"}))
                    continue

                if typ == "hello":
                    hello = dict(d)
                    hello.setdefault("map", {})
                    hello["map"] = dict(hello["map"])
                    hello["map"]["dir"] = os.path.join(bot_dir, "arena") if os.path.isdir(
                        os.path.join(bot_dir, "arena")
                    ) else os.path.join(ROOT, "arena")
                    S["hello"] = {"slot": hello.get("slot"), "seed": hello.get("seed")}
                    S["zoneCfg"] = (hello.get("config") or {}).get("zone")
                    try:
                        bot_mod, mf = load_bot_class(bot_dir)
                        if hasattr(mf, "draw") and hasattr(mf.draw, "caps"):
                            mf.draw.caps = (hello.get("config") or {}).get("debug", {})
                        bot = bot_mod.Bot(hello)
                    except Exception as e:
                        S["err"] = f"bot_init: {e}"
                        bot = None
                    await ws.send(json.dumps({"type": "loaded"}))
                    continue

                if typ == "obs" or (
                    bot is not None
                    and "self" in d
                    and "tick" in d
                    and typ not in ("end", "results", "lobby", "hello")
                ):
                    if bot is None:
                        continue
                    t0 = time.perf_counter()
                    try:
                        if mf is not None and hasattr(mf, "draw"):
                            mf.draw.clear()
                        a = dict(bot.act(d) or {})
                        last_act = {k: a[k] for k in ("move", "boost", "aim") if k in a}
                    except Exception as e:
                        S["err"] = f"act: {e}"
                        a = dict(last_act)
                    dt_ms = (time.perf_counter() - t0) * 1000
                    if dt_ms > 45:
                        S["slow"] += 1
                    S["lateMs"] = max(S["lateMs"], dt_ms)
                    mode = ""
                    try:
                        if mf is not None and hasattr(mf, "draw"):
                            label = (mf.draw.take() or {}).get("label") or ""
                            mode = str(label).split("/")[0][:20]
                    except Exception:
                        mode = ""
                    if mode:
                        S["modes"][mode] = S["modes"].get(mode, 0) + 1
                    tick = float(d.get("tick") or 0)
                    await ws.send(json.dumps(_action_for_play(a, tick)))
                    S["ticks"] += 1
                    me = d.get("self") or {}
                    if S["ticks"] % 10 == 0:
                        weap = "-"
                        try:
                            w1 = (me.get("weapons") or [None, {}])[1] or {}
                            weap = w1.get("kind") or "-"
                        except Exception:
                            pass
                        pos = me.get("pos") or [0, 0, 0]
                        S["hpLog"].append(
                            [
                                d.get("t"),
                                round(me.get("hp") or 0),
                                d.get("alive"),
                                me.get("cubes"),
                                weap,
                                round(pos[0]),
                                round(pos[1]),
                                round(pos[2]),
                                mode,
                                1 if me.get("in_zone") else 0,
                            ]
                        )
                    for e in d.get("events") or []:
                        if e.get("type") == "pickup":
                            continue
                        S["ev"].append(
                            [
                                d.get("t"),
                                e.get("type"),
                                round(e["amount"]) if e.get("amount") else "",
                                e.get("weapon") or e.get("kind") or "",
                                e.get("by") if e.get("by") is not None else e.get("target") or "",
                                "R" if e.get("rear") else "",
                            ]
                        )
                    S["last"] = {"t": d.get("t"), "alive": d.get("alive")}
                    continue

                if typ == "end":
                    S["end"] = {"place": d.get("place"), "kills": d.get("kills")}
                    S["endT"] = (S.get("last") or {}).get("t")
                    continue

                if typ == "results":
                    S["results"] = {
                        k: d.get(k) for k in ("places", "kills", "names") if k in d
                    }
                    S["done"] = time.time()
                    if live_task:
                        live_task.cancel()
                    if not keep_frames:
                        S.pop("ff", None)
                    return S

        S["done"] = time.time()
        S["err"] = S.get("err") or "timeout"
        if live_task:
            live_task.cancel()
        if not keep_frames:
            S.pop("ff", None)
        return S


def cmp(runs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    runs = runs if runs is not None else RUNS

    def med(a):
        a = [x for x in a if x is not None]
        return float(statistics.median(a)) if a else None

    g: Dict[str, Any] = {}
    for S in runs:
        if not S.get("end") or not S.get("hpLog") or not S.get("tag"):
            continue
        o = g.setdefault(
            S["tag"],
            {
                "n": 0,
                "kills": 0,
                "place": 0,
                "alive": [],
                "dealt": 0,
                "taken": 0,
                "cubes": 0,
                "killedBy": {},
                "modes": {},
            },
        )
        lt = S["hpLog"][-1][0]
        o["n"] += 1
        o["kills"] += S["end"].get("kills") or 0
        o["place"] += S["end"].get("place") or 0
        o["alive"].append(lt)
        o["cubes"] += max((h[3] or 0) for h in S["hpLog"])
        tail: Dict[str, float] = {}
        for e in S.get("ev") or []:
            if e[1] == "hit" and not (isinstance(e[4], (int, float)) and e[4] >= 100):
                o["dealt"] += float(e[2] or 0)
            if e[1] == "damaged":
                if e[3] != "zone":
                    o["taken"] += float(e[2] or 0)
                if isinstance(lt, (int, float)) and isinstance(e[0], (int, float)) and e[0] > lt - 8:
                    tail[e[3]] = tail.get(e[3], 0) + float(e[2] or 0)
        if tail:
            k = max(tail.items(), key=lambda kv: kv[1])[0]
            o["killedBy"][k] = o["killedBy"].get(k, 0) + 1
        for m, v in (S.get("modes") or {}).items():
            o["modes"][m] = o["modes"].get(m, 0) + v

    out: Dict[str, Any] = {}
    for t, o in g.items():
        tot = sum(o["modes"].values()) or 1
        out[t] = {
            "n": o["n"],
            "score": round(16 - o["place"] / o["n"], 2),
            "kills": round(o["kills"] / o["n"], 2),
            "place": round(o["place"] / o["n"], 1),
            "medAlive": med(o["alive"]),
            "cubes": round(o["cubes"] / o["n"], 1),
            "dealtPerTaken": round(o["dealt"] / max(1, o["taken"]), 2),
            "killedBy": o["killedBy"],
            "modes": {
                m: f"{round(100 * v / tot)}%"
                for m, v in sorted(o["modes"].items(), key=lambda kv: -kv[1])[:6]
            },
        }
    return out


def summarize_runs(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for S in runs:
        rows.append(
            {
                "tag": S.get("tag"),
                "commit": S.get("commit"),
                "room": S.get("room"),
                "code": S.get("code"),
                "place": (S.get("end") or {}).get("place"),
                "kills": (S.get("end") or {}).get("kills"),
                "ticks": S.get("ticks"),
                "slow": S.get("slow"),
                "lateMs": round(S.get("lateMs") or 0, 1),
                "endT": S.get("endT"),
                "err": S.get("err"),
                "modesTop": sorted(
                    (S.get("modes") or {}).items(), key=lambda kv: -kv[1]
                )[:5],
            }
        )
    return rows


async def batch(
    commits: Dict[str, str],
    per_tag: int,
    rooms: int,
    cache_dir: str,
    keep_frames: bool = False,
) -> List[Dict[str, Any]]:
    global STOP
    STOP = False
    q: List[str] = []
    for _ in range(per_tag):
        for tag in commits:
            q.append(tag)
    random.shuffle(q)  # mild mix; still round-robin-ish via workers

    lock = asyncio.Lock()

    async def worker(wid: int):
        await asyncio.sleep(wid * 2.5)
        while not STOP:
            async with lock:
                if not q:
                    return
                tag = q.pop(0)
            commit = commits[tag]
            try:
                print(f"[w{wid}] start tag={tag} commit={commit[:12]}… queue={len(q)}", flush=True)
                S = await run_one(
                    commit, tag, cache_dir, keep_frames=keep_frames
                )
                end = S.get("end") or {}
                print(
                    f"[w{wid}] done tag={tag} place={end.get('place')} kills={end.get('kills')} "
                    f"ticks={S.get('ticks')} err={S.get('err')}",
                    flush=True,
                )
            except Exception as e:
                print(f"[w{wid}] room error: {e}", flush=True)
                await asyncio.sleep(5)

    await asyncio.gather(*[worker(i) for i in range(rooms)])
    return RUNS


def parse_commits(s: str) -> Dict[str, str]:
    out = {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(f"bad --commits entry (want tag=hash): {part}")
        tag, commit = part.split("=", 1)
        out[tag.strip()] = commit.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    one = sub.add_parser("one", help="Run a single private-room match")
    one.add_argument("--tag", default="probe")
    one.add_argument("--commit", default="local")
    one.add_argument("--out", default="")
    one.add_argument("--keep-frames", action="store_true")

    bat = sub.add_parser("batch", help="Parallel private-room batch")
    bat.add_argument(
        "--commits",
        required=True,
        help="tag=fullhash,tag2=fullhash (full 40-char hashes)",
    )
    bat.add_argument("--per-tag", type=int, default=4)
    bat.add_argument("--rooms", type=int, default=4, help="Concurrent rooms (start modest)")
    bat.add_argument("--out", default="results/live-batch.json")
    bat.add_argument("--keep-frames", action="store_true")

    cmp_p = sub.add_parser("cmp", help="Recompute cmp from a saved results JSON")
    cmp_p.add_argument("path")

    args = ap.parse_args()
    cache_dir = os.path.join(ROOT, ".cache", "bot-commits")
    os.makedirs(cache_dir, exist_ok=True)

    if args.cmd == "cmp":
        data = json.load(open(args.path))
        runs = data.get("runs") or data
        print(json.dumps(cmp(runs), indent=2))
        return 0

    if args.cmd == "one":
        S = asyncio.run(
            run_one(args.commit, args.tag, cache_dir, keep_frames=args.keep_frames)
        )
        payload = {
            "cmp": cmp([S]),
            "row": summarize_runs([S])[0],
            "runs": [
                {
                    k: v
                    for k, v in S.items()
                    if k not in ("ff", "livews")
                }
            ],
        }
        text = json.dumps(payload, indent=2, default=str)
        if args.out:
            os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
            open(args.out, "w").write(text)
            print(f"wrote {args.out}", flush=True)
        print(json.dumps({"cmp": payload["cmp"], "row": payload["row"]}, indent=2))
        return 0 if S.get("end") else 1

    if args.cmd == "batch":
        commits = parse_commits(args.commits)
        # Cap concurrency politely on shared public server
        if args.rooms > 12:
            print("refusing --rooms>12 (shared public server)", file=sys.stderr)
            return 2
        if args.per_tag > 20:
            print("refusing --per-tag>20", file=sys.stderr)
            return 2
        print(f"batch commits={commits} per_tag={args.per_tag} rooms={args.rooms}", flush=True)
        runs = asyncio.run(
            batch(commits, args.per_tag, args.rooms, cache_dir, keep_frames=args.keep_frames)
        )
        payload = {
            "cmp": cmp(runs),
            "rows": summarize_runs(runs),
            "runs": [
                {k: v for k, v in S.items() if k not in ("ff", "livews", "results")}
                for S in runs
            ],
            "meta": {
                "commits": commits,
                "per_tag": args.per_tag,
                "rooms": args.rooms,
                "host": HOST,
                "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        }
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        # Slim save: drop bulky event logs unless needed
        slim = dict(payload)
        keep_keys = (
            "commit",
            "tag",
            "name",
            "code",
            "room",
            "started",
            "ticks",
            "hpLog",
            "ev",
            "end",
            "endT",
            "lateMs",
            "slow",
            "hello",
            "modes",
            "done",
            "err",
        )
        slim["runs"] = [{k: S[k] for k in keep_keys if k in S} for S in runs]
        open(args.out, "w").write(json.dumps(slim, indent=2, default=str))
        print(f"wrote {args.out}", flush=True)
        print(json.dumps({"cmp": payload["cmp"], "rows": payload["rows"]}, indent=2))
        ok = sum(1 for S in runs if S.get("end"))
        return 0 if ok else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
