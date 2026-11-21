#!/usr/bin/env python3
"""Spectate private-room house/expert bots on play.joinbuilders.org (read-only).

Creates private rooms, hosts with one idle seat (empty seats → house bots),
records mechreplay/1 /live frames + events, and emits a behavioral playbook.

Header `bots` labels are authoritative, e.g.:
  human | house:expert | house:probe-red-honest | house:probe-astra-finalist |
  house:probe-astra-skirmish | house:probe-red-best

Usage:
  python3 tools/play_harness/spectate_experts.py --matches 6 --concurrency 3 \\
      --out results/expert-spectate.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import ssl
import statistics
import struct
import sys
import time
import uuid
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOST = "play.joinbuilders.org"
WATCH_HOST = "watch.joinbuilders.org"

F_ID, F_X, F_Y, F_Z, F_YAW, F_PITCH, F_HP, F_EN, F_FLAGS, F_CUBES, F_MAXHP, F_S0, F_S1 = range(13)


def _ssl():
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _http_get(url: str) -> Tuple[int, Any]:
    import subprocess

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
            "User-Agent: rf-expert-spectate/1",
            url,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"curl exit {proc.returncode}")
    body, _, code_s = proc.stdout.rpartition("\n")
    code = int(code_s or "0")
    try:
        data = json.loads(body) if body.strip() else None
    except json.JSONDecodeError:
        data = {"raw": body[:200]}
    return code, data


def new_room(sid: str, retries: int = 16) -> dict:
    url = f"https://{HOST}/mm/code/new?sid={sid}"
    last = ""
    for i in range(retries):
        code, data = _http_get(url)
        last = str(data)[:200]
        if code == 200 and isinstance(data, dict) and data.get("code"):
            return data
        retry_s = 2.0
        if isinstance(data, dict):
            retry_s = float(data.get("retry_s") or retry_s)
        wait = max(retry_s, min(55.0, 1.55 ** i)) + random.random()
        print(f"mm/code/new HTTP {code} ({last[:80]}); wait {wait:.1f}s", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"mm/code/new failed: {last}")


class Ground:
    def __init__(self) -> None:
        w = json.load(open(os.path.join(ROOT, "arena/v2/world.json")))
        T = w["terrain"]
        self.minX = float(T["minX"])
        self.minY = float(T["minY"])
        self.step = float(T["step"])
        self.nx = int(T["nx"])
        self.ny = int(T["ny"])
        self.scale = float(T.get("scale") or 0.01)
        raw = open(os.path.join(ROOT, "arena/v2/terrain.i16"), "rb").read()
        self.h = struct.unpack(f"<{self.nx * self.ny}h", raw)

    def __call__(self, x: float, y: float) -> float:
        u = (x - self.minX) / self.step
        v = (y - self.minY) / self.step
        u = max(0.0, min(self.nx - 1.001, u))
        v = max(0.0, min(self.ny - 1.001, v))
        i, j = int(u), int(v)
        tx, ty = u - i, v - j

        def g(a: int, b: int) -> float:
            return self.h[b * self.nx + a] * self.scale

        return (g(i, j) * (1 - tx) + g(i + 1, j) * tx) * (1 - ty) + (
            g(i, j + 1) * (1 - tx) + g(i + 1, j + 1) * tx
        ) * ty


GROUND: Optional[Ground] = None


def ground_z(x: float, y: float) -> float:
    global GROUND
    if GROUND is None:
        GROUND = Ground()
    return GROUND(x, y)


def med(xs: List[float]) -> Optional[float]:
    if not xs:
        return None
    return round(float(statistics.median(xs)), 2)


def pct(num: float, den: float) -> float:
    return round(100.0 * num / max(1.0, den), 1)


def classify_from_bots_field(bot_label: Optional[str], name: str) -> str:
    b = (bot_label or "").lower()
    n = (name or "").lower()
    if b == "human" or n.startswith("idle-") or n.startswith("rf-") or n.startswith("harness"):
        return "idle_host"
    if b.startswith("house:expert") or (not b and n == "expert"):
        return "expert"
    if "probe-red-best" in b or (not b and n == "red"):
        return "probe_red_best"
    if "probe-red-honest" in b or (not b and n == "crimson"):
        return "probe_red_honest"
    if "probe-astra-finalist" in b or (not b and n == "astra"):
        return "probe_astra_finalist"
    if "probe-astra-skirmish" in b or (not b and n == "skirmish"):
        return "probe_astra_skirmish"
    if b.startswith("house:probe") or n.startswith("probe"):
        return "probe_other"
    if b.startswith("docker:") or "buildathon" in b or "docker:" in n:
        return "contestant"
    if b.startswith("house:"):
        return "house_other"
    return "unknown"


def analyze_airing(hdr: dict, frames: List[dict], events: List[dict]) -> List[dict]:
    mechs = hdr.get("mechs") or []
    bots_field = hdr.get("bots") or []
    N = len(mechs)
    S: List[Dict[str, Any]] = []
    for i, m in enumerate(mechs):
        name = m.get("name") if isinstance(m, dict) else str(m)
        bot = m.get("bot") if isinstance(m, dict) else None
        label = bots_field[i] if i < len(bots_field) else bot
        S.append(
            {
                "id": i,
                "name": name,
                "bot": bot,
                "botLabel": label,
                "class": classify_from_bots_field(label if isinstance(label, str) else None, name or ""),
                "kills": 0,
                "deathT": None,
                "place": None,
                "cubes": {},
                "weap": defaultdict(int),
                "ups": [],
                "z": [],
                "spd": [],
                "still": 0,
                "n": 0,
                "boost": 0,
                "laserCharge": 0,
                "heal": 0.0,
                "dmgOut": 0.0,
                "dmgIn": 0.0,
                "multiIn": 0.0,
                "crateHits": 0,
                "firstCrate": None,
                "droneHits": 0,
                "firstMechHit": None,
                "range": [],
                "pickups": 0,
                "weaponTakes": [],
                "firstWeaponT": None,
                "firstWeapon": None,
                "firstRoofT": None,
                "firstCubeT": None,
                "zoneExitT": None,
                "zoneSamples": 0,
                "inZone": 0,
                "fires": defaultdict(int),
                "hitByWeapon": defaultdict(float),
                "dealtByWeapon": defaultdict(float),
                "openMove": [],
                "lateHeight": [],
                "engageHeights": [],
                "timeOnRoof": 0,
                "samplesAfterArm": 0,
                "roofAfterArm": 0,
            }
        )

    pos_by_t: Dict[int, Dict[int, list]] = {}
    prev: Dict[int, list] = {}
    zone_center = None
    armed_since: Dict[int, float] = {}

    for fr in frames:
        t_tick = int(fr.get("t") or 0)
        t_s = t_tick / 20.0
        cur: Dict[int, list] = {}
        for m in fr.get("m") or []:
            if not m:
                continue
            mid = int(m[0])
            cur[mid] = m
        pos_by_t[t_tick] = cur

        zinfo = fr.get("z")
        if isinstance(zinfo, (list, tuple)) and len(zinfo) >= 3:
            zone_center = (float(zinfo[0]), float(zinfo[1]), float(zinfo[2]))

        if t_tick % 10:
            prev = cur
            continue

        for mid, m in cur.items():
            if mid >= N:
                continue
            s = S[mid]
            s["n"] += 1
            try:
                height = float(m[F_Z]) - ground_z(float(m[F_X]), float(m[F_Y]))
            except Exception:
                height = float(m[F_Z]) if len(m) > F_Z else 0.0
            s["z"].append(height)
            on_roof = height > 4.0
            if on_roof:
                s["timeOnRoof"] += 1
                if s["firstRoofT"] is None:
                    s["firstRoofT"] = round(t_s, 1)
            flags = int(m[F_FLAGS]) if len(m) > F_FLAGS else 0
            if flags & 2:
                s["boost"] += 1
            if flags & 4:
                s["laserCharge"] += 1
            cubes = int(m[F_CUBES]) if len(m) > F_CUBES else 0
            if cubes > 0 and s["firstCubeT"] is None:
                s["firstCubeT"] = round(t_s, 1)
            if mid in armed_since:
                s["samplesAfterArm"] += 1
                if on_roof:
                    s["roofAfterArm"] += 1
            if t_s <= 25:
                s["openMove"].append(
                    [round(t_s, 1), round(float(m[F_X]), 1), round(float(m[F_Y]), 1), round(height, 1), cubes]
                )
            if t_s >= 120:
                s["lateHeight"].append(height)
            if zone_center is not None:
                s["zoneSamples"] += 1
                dx = float(m[F_X]) - zone_center[0]
                dy = float(m[F_Y]) - zone_center[1]
                if math.hypot(dx, dy) <= float(zone_center[2]) + 2:
                    s["inZone"] += 1
                elif s["zoneExitT"] is None and t_s > 30:
                    s["zoneExitT"] = round(t_s, 1)
            p = prev.get(mid)
            if p is not None:
                sp = math.hypot(float(m[F_X]) - float(p[F_X]), float(m[F_Y]) - float(p[F_Y])) / 0.5
                s["spd"].append(sp)
                if sp < 1.0:
                    s["still"] += 1
                if float(m[F_HP]) > float(p[F_HP]) + 5:
                    s["heal"] += float(m[F_HP]) - float(p[F_HP])
        for mark in (20, 30, 45, 60, 90, 120, 180):
            if abs(t_tick - mark * 20) < 5:
                for mid, m in cur.items():
                    if mid < N:
                        S[mid]["cubes"][str(mark)] = int(m[F_CUBES]) if len(m) > F_CUBES else 0
        prev = cur

    def at(t_tick: int, mid: int):
        for k in range(8):
            c = pos_by_t.get(t_tick - k) or pos_by_t.get(t_tick + k)
            if c and mid in c:
                return c[mid]
        return None

    attackers: Dict[int, Dict[int, float]] = defaultdict(dict)

    for x in events:
        e = x.get("e")
        t_tick = int(x.get("t") or 0)
        t_s = t_tick / 20.0
        if e == "death" and isinstance(x.get("id"), int) and x["id"] < N:
            S[x["id"]]["deathT"] = round(t_s, 1)
            if x.get("place") is not None:
                S[x["id"]]["place"] = x["place"]
            by = x.get("by")
            if isinstance(by, int) and by < N:
                S[by]["kills"] += 1
        elif e == "hit":
            src, dst = x.get("src"), x.get("dst")
            amt = float(x.get("amt") or 0)
            w = x.get("w") or "?"
            if isinstance(src, int) and src < N:
                s = S[src]
                if isinstance(dst, int) and dst < N:
                    s["dmgOut"] += amt
                    s["dealtByWeapon"][str(w)] += amt
                    if s["firstMechHit"] is None:
                        s["firstMechHit"] = round(t_s, 1)
                    p, q = at(t_tick, src), at(t_tick, dst)
                    if p and q:
                        s["range"].append(
                            math.hypot(float(p[F_X]) - float(q[F_X]), float(p[F_Y]) - float(q[F_Y]))
                        )
                        try:
                            s["engageHeights"].append(
                                float(p[F_Z]) - ground_z(float(p[F_X]), float(p[F_Y]))
                            )
                        except Exception:
                            pass
                elif isinstance(dst, int) and 1000 <= dst < 5000:
                    s["crateHits"] += 1
                    if s["firstCrate"] is None:
                        s["firstCrate"] = round(t_s, 1)
                elif isinstance(dst, int) and dst >= 100:
                    s["droneHits"] += 1
            if isinstance(dst, int) and dst < N:
                S[dst]["dmgIn"] += amt
                S[dst]["hitByWeapon"][str(w)] += amt
                if isinstance(src, int) and src < N:
                    attackers[dst][src] = t_s
                    recent = [u for u in attackers[dst].values() if t_s - u < 3]
                    if len(recent) >= 2:
                        S[dst]["multiIn"] += amt
        elif e == "fire" and isinstance(x.get("id"), int) and x["id"] < N:
            S[x["id"]]["fires"][str(x.get("w") or "?")] += 1
        elif e == "upgrade" and isinstance(x.get("id"), int) and x["id"] < N:
            S[x["id"]]["ups"].append(x.get("up"))
        elif e == "pickup" and isinstance(x.get("by"), int) and x["by"] < N:
            S[x["by"]]["pickups"] += 1
        elif e == "weapon" and x.get("op") == "take" and isinstance(x.get("by"), int) and x["by"] < N:
            kind = x.get("kind") or "?"
            S[x["by"]]["weap"][kind] += 1
            S[x["by"]]["weaponTakes"].append([round(t_s, 1), kind])
            if S[x["by"]]["firstWeaponT"] is None:
                S[x["by"]]["firstWeaponT"] = round(t_s, 1)
                S[x["by"]]["firstWeapon"] = kind
                armed_since[x["by"]] = t_s
        elif e == "cube" and isinstance(x.get("by"), int) and x["by"] < N:
            if S[x["by"]]["firstCubeT"] is None:
                S[x["by"]]["firstCubeT"] = round(t_s, 1)

    order = sorted(
        range(N),
        key=lambda i: S[i]["deathT"] if S[i]["deathT"] is not None else 1e9,
        reverse=True,
    )
    for rank, i in enumerate(order, 1):
        if S[i]["place"] is None:
            S[i]["place"] = rank

    out = []
    for s in S:
        out.append(
            {
                "id": s["id"],
                "name": s["name"],
                "bot": s["bot"],
                "botLabel": s["botLabel"],
                "class": s["class"],
                "place": s["place"],
                "kills": s["kills"],
                "deathT": s["deathT"],
                "cubes": {str(k): v for k, v in s["cubes"].items()},
                "weap": dict(s["weap"]),
                "ups": s["ups"][:12],
                "firstWeaponT": s["firstWeaponT"],
                "firstWeapon": s["firstWeapon"],
                "weaponTakes": s["weaponTakes"][:8],
                "firstCrate": s["firstCrate"],
                "firstCubeT": s["firstCubeT"],
                "firstRoofT": s["firstRoofT"],
                "firstMechHit": s["firstMechHit"],
                "medHeight": med(s["z"]),
                "roofPct": pct(s["timeOnRoof"], s["n"]),
                "roofAfterArmPct": pct(s["roofAfterArm"], s["samplesAfterArm"]),
                "lateMedHeight": med(s["lateHeight"]),
                "medSpeed": med(s["spd"]),
                "stillPct": pct(s["still"], s["n"]),
                "boostPct": pct(s["boost"], s["n"]),
                "laserChargePct": pct(s["laserCharge"], s["n"]),
                "dmgOut": round(s["dmgOut"]),
                "dmgIn": round(s["dmgIn"]),
                "multiAttackerPct": pct(s["multiIn"], s["dmgIn"]),
                "crateHits": s["crateHits"],
                "droneHits": s["droneHits"],
                "medRange": med(s["range"]),
                "medEngageHeight": med(s["engageHeights"]),
                "healed": round(s["heal"]),
                "cubePickups": s["pickups"],
                "fires": dict(s["fires"]),
                "dealtByWeapon": {k: round(v) for k, v in s["dealtByWeapon"].items()},
                "hitByWeapon": {k: round(v) for k, v in s["hitByWeapon"].items()},
                "inZonePct": pct(s["inZone"], s["zoneSamples"]),
                "zoneExitT": s["zoneExitT"],
                "openMove": s["openMove"][:: max(1, len(s["openMove"]) // 8)][:8],
                "upgradeCount": len(s["ups"]),
            }
        )
    out.sort(key=lambda r: (r["place"] is None, r["place"] or 99))
    return out


async def host_idle_and_spectate(match_idx: int, timeout_s: float = 8.5 * 60) -> dict:
    import websockets

    sid = uuid.uuid4().hex
    name = f"idle-{match_idx}-{sid[:4]}"
    room = await asyncio.to_thread(new_room, sid)
    code, room_id = room["code"], room["room"]
    play_url = (
        f"wss://{HOST}/r/{room_id}/play?token=&sid={sid}"
        f"&name={quote(name)}&code={code}"
    )
    live_url = (
        f"wss://{HOST}/r/{room_id}/live?token=&code={code}"
        f"&sid=watch{uuid.uuid4().hex[:8]}"
    )

    result: Dict[str, Any] = {
        "match": match_idx,
        "code": code,
        "room": room_id,
        "host": name,
        "header": None,
        "frames": 0,
        "events": 0,
        "end": None,
        "analysis": None,
        "err": None,
        "started": time.time(),
        "source": "private_room",
    }

    frames: List[dict] = []
    events: List[dict] = []
    hdr: Dict[str, Any] = {}
    done = asyncio.Event()

    async def spectator():
        nonlocal hdr
        try:
            async with websockets.connect(
                live_url, open_timeout=20, max_size=40_000_000, ssl=_ssl()
            ) as lws:
                result["live_ok"] = True
                while not done.is_set() and time.time() - result["started"] < timeout_s:
                    try:
                        raw = await asyncio.wait_for(lws.recv(), timeout=8)
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
                            hdr = d
                            result["header"] = {
                                "bots": d.get("bots"),
                                "mechs": [
                                    {"id": m.get("id"), "name": m.get("name"), "bot": m.get("bot")}
                                    for m in (d.get("mechs") or [])
                                ],
                            }
                            frames.clear()
                            events.clear()
                        elif "t" in d:
                            t_tick = int(d["t"])
                            if d.get("ev"):
                                for x in d["ev"]:
                                    xx = dict(x)
                                    xx["t"] = t_tick
                                    events.append(xx)
                            if t_tick % 5 == 0 or d.get("ev"):
                                frames.append(
                                    {"t": t_tick, "m": d.get("m"), "n": d.get("n"), "z": d.get("z")}
                                )
                            result["frames"] = len(frames)
                            result["events"] = len(events)
        except Exception as e:
            result["watchErr"] = str(e)

    async def host():
        started_host = False
        try:
            async with websockets.connect(
                play_url, open_timeout=20, max_size=8_000_000, ssl=_ssl()
            ) as ws:
                result["play_ok"] = True
                while not done.is_set() and time.time() - result["started"] < timeout_s:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=12)
                    except asyncio.TimeoutError:
                        if result.get("end") is not None:
                            break
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
                                await asyncio.sleep(0.4)
                                await ws.send(json.dumps({"type": "start"}))
                                result["host_started"] = True
                        elif typ == "hello":
                            result["hello_slot"] = d.get("slot")
                            await ws.send(json.dumps({"type": "loaded"}))
                        elif typ == "obs":
                            await ws.send(json.dumps({"tick": d.get("tick")}))
                        elif typ == "end":
                            result["end"] = {"place": d.get("place"), "kills": d.get("kills")}
                        elif typ == "results":
                            result["results"] = {
                                k: d.get(k) for k in ("places", "kills", "names", "bots") if k in d
                            }
                            done.set()
                            return
        except Exception as e:
            result["playErr"] = str(e)
            done.set()

    watch_task = asyncio.create_task(spectator())
    await host()
    done.set()
    try:
        await asyncio.wait_for(watch_task, timeout=8)
    except Exception:
        watch_task.cancel()

    if hdr:
        try:
            result["analysis"] = analyze_airing(hdr, frames, events)
        except Exception as e:
            result["err"] = f"analyze: {e}"
    result["duration_s"] = round(time.time() - result["started"], 1)
    return result


async def watch_public_stream(timeout_s: float = 90.0, max_matches: int = 1) -> List[dict]:
    import websockets

    url = f"wss://{WATCH_HOST}/live"
    airings: List[dict] = []
    cur: Optional[dict] = None
    frames: List[dict] = []
    events: List[dict] = []
    t0 = time.time()
    try:
        async with websockets.connect(url, open_timeout=20, max_size=40_000_000, ssl=_ssl()) as ws:
            while time.time() - t0 < timeout_s and len(airings) < max_matches:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
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
                        if cur and frames:
                            try:
                                cur["analysis"] = analyze_airing(cur["hdr"], frames, events)
                            except Exception as e:
                                cur["err"] = str(e)
                            cur["frames"] = len(frames)
                            cur["events"] = len(events)
                            airings.append(cur)
                            if len(airings) >= max_matches:
                                return airings
                        frames, events = [], []
                        cur = {
                            "source": "watch.joinbuilders.org",
                            "match": f"public-{len(airings)}",
                            "hdr": d,
                            "header": {
                                "bots": d.get("bots"),
                                "mechs": [
                                    {"id": m.get("id"), "name": m.get("name"), "bot": m.get("bot")}
                                    for m in (d.get("mechs") or [])
                                ],
                            },
                        }
                    elif "t" in d and cur is not None:
                        t_tick = int(d["t"])
                        if d.get("ev"):
                            for x in d["ev"]:
                                xx = dict(x)
                                xx["t"] = t_tick
                                events.append(xx)
                        if t_tick % 5 == 0 or d.get("ev"):
                            frames.append({"t": t_tick, "m": d.get("m"), "n": d.get("n"), "z": d.get("z")})
            if cur and frames and len(airings) < max_matches:
                try:
                    cur["analysis"] = analyze_airing(cur["hdr"], frames, events)
                except Exception as e:
                    cur["err"] = str(e)
                cur["frames"] = len(frames)
                cur["events"] = len(events)
                airings.append(cur)
    except Exception as e:
        return [{"source": "watch.joinbuilders.org", "err": str(e)}]
    return airings


def _cube_at(row: dict, t: int) -> Optional[float]:
    c = row.get("cubes") or {}
    if t in c:
        return c[t]
    if str(t) in c:
        return c[str(t)]
    return None


def aggregate(matches: List[dict]) -> dict:
    by_class: Dict[str, List[dict]] = defaultdict(list)
    top_rows: List[dict] = []
    for m in matches:
        for row in m.get("analysis") or []:
            by_class[row["class"]].append(row)
            if row["class"] != "idle_host" and (row.get("place") or 99) <= 4:
                top_rows.append({**row, "match": m.get("match"), "source": m.get("source")})

    def summarize(rows: List[dict]) -> dict:
        if not rows:
            return {"n": 0}

        def vals(key):
            return [r[key] for r in rows if r.get(key) is not None]

        places = vals("place")
        cubes30 = [v for v in (_cube_at(r, 30) for r in rows) if v is not None]
        cubes60 = [v for v in (_cube_at(r, 60) for r in rows) if v is not None]
        return {
            "n": len(rows),
            "meanPlace": round(statistics.mean(places), 2) if places else None,
            "meanKills": round(statistics.mean(vals("kills")), 2) if rows else None,
            "meanRoofPct": round(statistics.mean(vals("roofPct")), 1) if vals("roofPct") else None,
            "meanRoofAfterArmPct": round(statistics.mean(vals("roofAfterArmPct")), 1)
            if vals("roofAfterArmPct")
            else None,
            "meanStillPct": round(statistics.mean(vals("stillPct")), 1) if vals("stillPct") else None,
            "meanBoostPct": round(statistics.mean(vals("boostPct")), 1) if vals("boostPct") else None,
            "meanLaserChargePct": round(statistics.mean(vals("laserChargePct")), 1)
            if vals("laserChargePct")
            else None,
            "medFirstWeaponT": med(vals("firstWeaponT")),
            "medFirstRoofT": med(vals("firstRoofT")),
            "medFirstCubeT": med(vals("firstCubeT")),
            "medFirstMechHit": med(vals("firstMechHit")),
            "medFirstCrate": med(vals("firstCrate")),
            "meanDroneHits": round(statistics.mean(vals("droneHits")), 1) if vals("droneHits") else None,
            "meanCubes30": round(statistics.mean(cubes30), 2) if cubes30 else None,
            "meanCubes60": round(statistics.mean(cubes60), 2) if cubes60 else None,
            "meanUpgrades": round(statistics.mean(vals("upgradeCount")), 2) if vals("upgradeCount") else None,
            "medEngageRange": med(vals("medRange")),
            "meanMultiAttackerPct": round(statistics.mean(vals("multiAttackerPct")), 1)
            if vals("multiAttackerPct")
            else None,
            "meanInZonePct": round(statistics.mean(vals("inZonePct")), 1) if vals("inZonePct") else None,
            "weaponTakes": {
                k: sum((r.get("weap") or {}).get(k, 0) for r in rows) for k in ("laser", "mortar", "lightning")
            },
            "firstWeapon": {
                w: sum(1 for r in rows if r.get("firstWeapon") == w) for w in ("laser", "mortar", "lightning")
            },
            "dealtByWeapon": {},
            "top4rate": pct(sum(1 for r in rows if (r.get("place") or 99) <= 4), len(rows)),
            "winRate": pct(sum(1 for r in rows if r.get("place") == 1), len(rows)),
        }

    out_by = {}
    for cls, rows in by_class.items():
        s = summarize(rows)
        dealt: Dict[str, float] = defaultdict(float)
        for r in rows:
            for k, v in (r.get("dealtByWeapon") or {}).items():
                dealt[k] += float(v)
        s["dealtByWeapon"] = {k: round(v) for k, v in sorted(dealt.items(), key=lambda kv: -kv[1])}
        out_by[cls] = s

    return {
        "byClass": out_by,
        "topFinishes": sorted(top_rows, key=lambda r: (r.get("place") or 99, -(r.get("kills") or 0)))[:30],
        "nMatches": len(matches),
    }


def derive_tactics(agg: dict, matches: List[dict]) -> List[dict]:
    by = agg.get("byClass") or {}
    expert = by.get("expert") or {}
    red_best = by.get("probe_red_best") or {}
    astra = by.get("probe_astra_finalist") or {}
    crimson = by.get("probe_red_honest") or {}
    skirmish = by.get("probe_astra_skirmish") or {}
    top = [r for r in (agg.get("topFinishes") or []) if r.get("class") != "idle_host"]

    def snap(c: dict) -> dict:
        keys = (
            "n",
            "meanPlace",
            "top4rate",
            "winRate",
            "medFirstWeaponT",
            "medFirstRoofT",
            "medFirstCubeT",
            "medFirstMechHit",
            "meanRoofPct",
            "meanRoofAfterArmPct",
            "meanBoostPct",
            "meanStillPct",
            "meanLaserChargePct",
            "medEngageRange",
            "meanMultiAttackerPct",
            "meanDroneHits",
            "meanCubes30",
            "meanCubes60",
            "meanUpgrades",
            "firstWeapon",
            "dealtByWeapon",
            "meanInZonePct",
        )
        return {k: c.get(k) for k in keys}

    return [
        {
            "rank": 1,
            "id": "laser-first-arm-under-15s",
            "title": "Take laser within ~8–15s; fight only after armed",
            "fit": "ARM mode; prefer laser like house:expert / probe-red-best",
            "procedure": [
                f"expert medFirstWeaponT={expert.get('medFirstWeaponT')} firstWeapon={expert.get('firstWeapon')}",
                f"probe-red-best medFirstWeaponT={red_best.get('medFirstWeaponT')} firstWeapon={red_best.get('firstWeapon')}",
                "Spawn → nearest laser loot; lightning only if laser >~80m.",
                "Exit ARM on laser take; allow crate/drone gun poke before secondary.",
            ],
            "evidence": {
                "expert": snap(expert),
                "probe_red_best": snap(red_best),
                "topArms": [
                    {
                        "name": r.get("name"),
                        "class": r.get("class"),
                        "place": r.get("place"),
                        "firstWeapon": r.get("firstWeapon"),
                        "firstWeaponT": r.get("firstWeaponT"),
                        "firstMechHit": r.get("firstMechHit"),
                    }
                    for r in top[:10]
                ],
            },
            "change_first": "Hard-prefer laser in ARM loot ranking; exit ARM immediately on laser take.",
        },
        {
            "rank": 2,
            "id": "brief-roof-then-mobile-midrange",
            "title": "Roof as short staging (≈10–25% time), laser peek 50–70m, then relocate",
            "fit": "S1 roof camp — soften with peek-timeout, do not delete S1 for practice",
            "procedure": [
                f"expert meanRoofPct={expert.get('meanRoofPct')} roofAfterArm={expert.get('meanRoofAfterArmPct')} firstRoofT={expert.get('medFirstRoofT')}",
                f"engage range med≈{expert.get('medEngageRange') or red_best.get('medEngageRange')}m; boost≈{expert.get('meanBoostPct') or red_best.get('meanBoostPct')}%",
                "After arm: climb ≤15s, one laser cycle, leave if no isolate / after ~8s empty.",
                "Winners keep inZone≈100 and stay mobile — not AFK roof camps.",
            ],
            "evidence": {
                "expert": snap(expert),
                "crimson": snap(crimson),
                "astra": snap(astra),
                "topRoof": [
                    {
                        "name": r.get("name"),
                        "class": r.get("class"),
                        "place": r.get("place"),
                        "roofPct": r.get("roofPct"),
                        "boostPct": r.get("boostPct"),
                        "stillPct": r.get("stillPct"),
                        "medRange": r.get("medRange"),
                        "laserChargePct": r.get("laserChargePct"),
                    }
                    for r in top[:10]
                ],
            },
            "change_first": "Add CAMP peek-timeout → RELOCATE after laser cycle with no target.",
        },
        {
            "rank": 3,
            "id": "disengage-multi-attacker",
            "title": "Hard DISENGAGE when 2+ mechs hit within ~3s",
            "fit": "DISENGAGE mode; multiAttackerPct is the mid-pack death signature",
            "procedure": [
                f"expert meanMulti={expert.get('meanMultiAttackerPct')}; top places often multi≪30%",
                "Trigger on ≥2 mech damage sources in 2.5s OR dmgIn spike >250/2s.",
                "Boost perpendicular + break LOS; no greed laser finish.",
                "Re-enter FIGHT only if ≤1 aggressor and HP≥45%.",
            ],
            "evidence": {
                "byClassMulti": {k: v.get("meanMultiAttackerPct") for k, v in by.items()},
                "topMulti": [
                    {
                        "name": r.get("name"),
                        "class": r.get("class"),
                        "place": r.get("place"),
                        "multi": r.get("multiAttackerPct"),
                        "dmgIn": r.get("dmgIn"),
                    }
                    for r in top[:12]
                ],
            },
            "change_first": "Lower multi-source DISENGAGE threshold; forbid THIRD while multi flag set.",
        },
        {
            "rank": 4,
            "id": "cube-upgrade-snowball-like-astra",
            "title": "Early cube/crate/drone path + spend upgrades (astra-finalist pattern)",
            "fit": "N5 cube snowball + upgrade picker",
            "procedure": [
                f"astra cubes30={astra.get('meanCubes30')} cubes60={astra.get('meanCubes60')} ups={astra.get('meanUpgrades')} drones={astra.get('meanDroneHits')}",
                f"expert cubes30={expert.get('meanCubes30')} ups={expert.get('meanUpgrades')}",
                "On ARM/RELOCATE: crate ≤40m, scoop cubes, 1–2 drones before long rotate.",
                "Spend promptly: armor/plating → gun_damage → laser_damage/charge.",
            ],
            "evidence": {
                "astra": snap(astra),
                "expert": snap(expert),
                "topCubes": [
                    {
                        "name": r.get("name"),
                        "class": r.get("class"),
                        "place": r.get("place"),
                        "cubes": r.get("cubes"),
                        "ups": r.get("ups"),
                        "droneHits": r.get("droneHits"),
                        "cubePickups": r.get("cubePickups"),
                    }
                    for r in top[:10]
                ],
            },
            "change_first": "Keep/enable N5; earlier armor+gun upgrades; short crate detour during ARM.",
        },
        {
            "rank": 5,
            "id": "zone-hug-skip-early-third",
            "title": "Always hug zone; delay thirds until armed+healthy; skip skirmish early brawls",
            "fit": "ESCAPE_ZONE + THIRD gates",
            "procedure": [
                f"Top inZonePct≈{red_best.get('meanInZonePct') or expert.get('meanInZonePct') or 100}",
                "Never leave ring for loot after t>45s.",
                "THIRD only if armed, HP≥55%, target already fighting, path stays in zone.",
                f"skirmish meanPlace={skirmish.get('meanPlace')} firstHit={skirmish.get('medFirstMechHit')} — early brawl places worse",
            ],
            "evidence": {
                "skirmish": snap(skirmish),
                "expert": snap(expert),
                "red_best": snap(red_best),
            },
            "change_first": "Tighten THIRD preconditions; never fail ESCAPE_ZONE; no FIGHT before arm complete.",
        },
    ]


async def run_batch(n_matches: int, concurrency: int, timeout_s: float) -> List[dict]:
    sem = asyncio.Semaphore(concurrency)
    results: List[dict] = []

    async def one(i: int):
        async with sem:
            await asyncio.sleep(1.2 * i + random.random())
            print(f"[match {i}] requesting private room…", flush=True)
            try:
                r = await host_idle_and_spectate(i, timeout_s=timeout_s)
                results.append(r)
                tops = []
                if r.get("analysis"):
                    tops = [
                        f"{x['name']}({x['class']}):{x['place']}"
                        for x in r["analysis"]
                        if x.get("class") != "idle_host"
                    ][:6]
                print(
                    f"[match {i}] done frames={r.get('frames')} events={r.get('events')} "
                    f"dur={r.get('duration_s')}s top={','.join(tops)} "
                    f"err={r.get('err') or r.get('playErr') or r.get('watchErr')}",
                    flush=True,
                )
            except Exception as e:
                print(f"[match {i}] FAIL {e}", flush=True)
                results.append({"match": i, "err": str(e), "source": "private_room"})

    await asyncio.gather(*[one(i) for i in range(n_matches)])
    return sorted(results, key=lambda r: r.get("match") if isinstance(r.get("match"), int) else 999)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=6)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout-s", type=float, default=8.5 * 60)
    ap.add_argument("--also-public-watch", action="store_true")
    ap.add_argument("--public-watch-s", type=float, default=90.0)
    ap.add_argument("--out", default="results/expert-spectate.json")
    args = ap.parse_args()

    conc = max(1, min(8, args.concurrency))
    print(f"spectate experts: matches={args.matches} concurrency={conc} out={args.out}", flush=True)

    matches = asyncio.run(run_batch(args.matches, conc, args.timeout_s))
    if args.also_public_watch:
        print("tapping watch.joinbuilders.org …", flush=True)
        matches.extend(asyncio.run(watch_public_stream(timeout_s=args.public_watch_s, max_matches=1)))

    analyzed = [m for m in matches if m.get("analysis")]
    agg = aggregate(analyzed)
    tactics = derive_tactics(agg, matches)

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline": "2.65 @ b7b5c38367dbf208f836f77d8f8a1ee4dd2658f4",
        "n_requested": args.matches,
        "n_with_analysis": len(analyzed),
        "concurrency": conc,
        "note": "Private rooms are FFA house-bot mix (expert + probe-*); not practice scoring.",
        "aggregate": agg,
        "tactics": tactics,
        "matches": [
            {
                "match": m.get("match"),
                "source": m.get("source", "private_room"),
                "code": m.get("code"),
                "room": m.get("room"),
                "duration_s": m.get("duration_s"),
                "frames": m.get("frames"),
                "events": m.get("events"),
                "header": m.get("header"),
                "end_host": m.get("end"),
                "analysis": m.get("analysis"),
                "err": m.get("err") or m.get("playErr") or m.get("watchErr"),
            }
            for m in matches
        ],
    }

    out_path = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    # Durable copies outside branch thrash
    for alt in (
        "/tmp/mech-expert-spectate/expert-spectate.json",
        os.path.join(
            os.path.expanduser(
                "~/Library/Application Support/Cursor/AgentStores/cursor_agent_stores/"
                "bc-b7f847d7-a956-44ed-afb3-b60e742ad18e/files"
            ),
            "expert-spectate-intel.json",
        ),
    ):
        try:
            os.makedirs(os.path.dirname(alt), exist_ok=True)
            with open(alt, "w") as f:
                json.dump(out, f, indent=2)
            print(f"also wrote {alt}", flush=True)
        except Exception as e:
            print(f"skip alt {alt}: {e}", flush=True)

    print(f"wrote {out_path}", flush=True)
    summary = {
        "n_with_analysis": out["n_with_analysis"],
        "byClass": {
            k: {
                "n": v.get("n"),
                "meanPlace": v.get("meanPlace"),
                "top4rate": v.get("top4rate"),
                "meanRoofPct": v.get("meanRoofPct"),
                "medFirstWeaponT": v.get("medFirstWeaponT"),
                "firstWeapon": v.get("firstWeapon"),
                "medEngageRange": v.get("medEngageRange"),
                "meanMultiAttackerPct": v.get("meanMultiAttackerPct"),
                "meanCubes30": v.get("meanCubes30"),
            }
            for k, v in (agg.get("byClass") or {}).items()
        },
        "tactics": [
            {"rank": t["rank"], "id": t["id"], "title": t["title"], "change_first": t["change_first"]}
            for t in tactics
        ],
    }
    print(json.dumps(summary, indent=2), flush=True)
    with open("/tmp/mech-expert-spectate/summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    return 0 if out["n_with_analysis"] else 2


if __name__ == "__main__":
    sys.exit(main())
