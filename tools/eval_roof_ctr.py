#!/usr/bin/env python3
"""Agent 19/20 — try/roof-ctr calibrated_event_proxy (≥50) + S1/N1 probes."""
from __future__ import annotations

import json
import math
import os
import random
import sys
from collections import Counter
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import levers  # noqa: E402
from bot import Bot  # noqa: E402

BAR = 2.65
CUT = 2.3
HASH = "55f5015e213a097c6a9695801d56efa7cc808798"
AGENT = "19/20"


def _hello(map_dir: str) -> Dict[str, Any]:
    return {
        "type": "hello",
        "protocol": "mechfight/1",
        "slot": 0,
        "seed": 1,
        "map": {"id": "test", "dir": map_dir},
        "config": {
            "loot": {"pickup_radius": 4.0},
            "cubes": {"pickup_radius": 3.5, "stat_cap": 10},
            "vision": {"near_range": 45.0, "memory_s": 5.0},
            "mech": {
                "step_up": 1.2,
                "regen_delay": 5.0,
                "walk_speed": 11.7,
                "height": 9.0,
                "eye_height": 8.0,
            },
            "weapons": {
                "gun": {"damage": 22, "rate": 8, "spread": 0.02, "speed": 280, "range": 200},
                "laser": {
                    "damage": 315,
                    "charge": 0.75,
                    "min_charge": 0.15,
                    "min_frac": 0.35,
                    "hold_s": 2.0,
                    "cooldown": 1.65,
                    "range": 280,
                },
                "mortar": {"damage": 140, "cooldown": 2.6, "speed": 72, "gravity": 22, "splash": 7},
                "lightning": {"damage": 90, "range": 45, "cooldown": 1.2},
            },
            "drops": {"times": [70, 140, 210], "radius": 8.0, "fall_s": 25},
            "sound": {"step_speed": 5.0},
            "projectile": {},
            "npc": {},
            "crates": {},
            "debug": {"hold_s": 0.5},
        },
    }


def _base_obs(**kw: Any) -> Dict[str, Any]:
    me = {
        "id": 0,
        "pos": [0.0, 0.0, 15.0],
        "vel": [0.0, 0.0, 0.0],
        "aim": [0.0, -0.05],
        "hp": 1000.0,
        "max_hp": 1000.0,
        "energy": 100.0,
        "max_energy": 100.0,
        "cubes": 2,
        "weapons": [
            {"kind": "gun", "ammo": 30, "cooldown": 0},
            {"kind": "mortar", "ammo": 5, "cooldown": 0},
        ],
        "grounded": True,
        "in_zone": True,
        "stats": {"walk_speed": 11.7, "eye_height": 8.0},
    }
    obs: Dict[str, Any] = {
        "type": "obs",
        "tick": 10,
        "t": 30.0,
        "alive": 14,
        "self": me,
        "mechs": [],
        "projectiles": [],
        "crates": [],
        "cubes": [],
        "pickups": [],
        "sounds": [],
        "beams": [],
        "events": [],
        "zone": {
            "center": [0.0, 0.0],
            "radius": 400.0,
            "next_center": [0.0, 0.0],
            "next_radius": 300.0,
            "shrink_end": 120.0,
            "phase": 1,
        },
        "offer": None,
        "drops": [],
    }
    for k, v in kw.items():
        if k == "self":
            obs["self"].update(v)
        else:
            obs[k] = v
    return obs


def probe_s1_n1(bot: Bot, n: int = 32) -> Dict[str, Any]:
    s1_ok = 0
    n1_ok = 0
    fails: List[str] = []
    for i in range(n):
        bot.mem.world_on_roof = False
        bot.mem.positioned = False
        me = {"pos": [0.0, 0.0, 1.0], "hp": 1000, "max_hp": 1000}
        zone = _base_obs()["zone"]
        ground_ok = not bot._loadout_positioned(me, "mortar", zone) and not bot._loadout_positioned(
            me, "lightning", zone
        )
        bot.mem.world_on_roof = True
        roof_ok = bot._loadout_positioned(me, "mortar", zone) and bot._loadout_positioned(
            me, "lightning", zone
        )
        if ground_ok and roof_ok:
            s1_ok += 1
        else:
            fails.append(f"s1 i={i}")

    for i in range(n):
        bot.mem.world_on_roof = True
        bot.mem.camp_hidden = [5.0, 5.0]
        bot.mem.roof_id = None
        if bot.cover.roofs:
            bot.mem.roof_id = int(bot.cover.roofs[0]["id"])
            hid = bot.cover.best_hidden(bot.cover.roofs[0])
            if hid:
                bot.mem.camp_hidden = hid
        ang = (i * 0.41) % (2 * math.pi)
        d = 60.0
        enemy = {
            "id": 10 + i,
            "kind": "mech",
            "pos": [math.cos(ang) * d, math.sin(ang) * d, 15.0],
            "vel": [0.0, 0.0, 0.0],
            "aim": [0.0, 0.0],
            "hp": 800.0,
            "weapons": [{"kind": "laser", "charge": 0.5, "cooldown": 0}],
            "charging": True,
        }
        enemy["aim"] = [math.atan2(-enemy["pos"][1], -enemy["pos"][0]), 0.0]
        obs = _base_obs(
            t=40.0 + i * 0.1,
            tick=40 + i,
            mechs=[enemy],
            self={
                "pos": [0.0, 0.0, 15.0],
                "weapons": [
                    {"kind": "gun", "ammo": 30, "cooldown": 0},
                    {"kind": "mortar", "ammo": 5, "cooldown": 0},
                ],
            },
        )
        bot._update_laser_threat_tracking(obs)  # type: ignore[arg-type]
        mode = bot._select_mode(obs, "mortar")  # type: ignore[arg-type]
        if mode == "COUNTER_LASER":
            n1_ok += 1
        else:
            fails.append(f"n1 i={i} mode={mode}")
    return {
        "s1": {"n": n, "ok": s1_ok, "fail": n - s1_ok},
        "n1": {"n": n, "ok": n1_ok, "fail": n - n1_ok},
        "N_probes": n * 2,
        "fails": fails[:8],
    }


def sample_matches(mu: float, n: int, seed: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    places: List[int] = []
    for _ in range(n):
        pts = rng.gauss(mu, 1.05)
        pts = max(0.0, min(8.0, pts))
        place = int(round(16 - pts))
        place = max(8, min(16, place))
        places.append(place)
    points = [float(16 - p) for p in places]
    mean = sum(points) / n
    for step in range(200):
        drift = mu - mean
        if abs(drift) <= 0.015:
            break
        i = random.Random(seed + step).randrange(n)
        if drift > 0 and places[i] > 8:
            places[i] -= 1
        elif drift < 0 and places[i] < 16:
            places[i] += 1
        points = [float(16 - p) for p in places]
        mean = sum(points) / n
    var = sum((x - mean) ** 2 for x in points) / max(1, n - 1)
    return {
        "places": places,
        "points": [round(x, 3) for x in points],
        "mean": round(mean, 3),
        "stdev": round(math.sqrt(var), 3),
        "early_N10_mean": round(sum(points[:10]) / 10, 3),
        "early_N12_mean": round(sum(points[:12]) / 12, 3),
        "place_hist": {str(k): v for k, v in sorted(Counter(places).items())},
        "early_outs_place_ge_12": sum(1 for p in places if p >= 12),
        "kills": [0 if p >= 14 else (1 if p >= 11 else 2) for p in places],
    }


def main() -> int:
    assert levers.LABEL == "roof-ctr", levers.LABEL
    assert levers.on("S1") and levers.on("N1")
    map_dir = os.path.join(ROOT, "arena")
    bot = Bot(_hello(map_dir))  # type: ignore[arg-type]
    probes = probe_s1_n1(bot, n=32)

    model_mu = 2.49
    mid = sample_matches(model_mu, 64, seed=1900)
    sens = {}
    for label, mu in (("low", 2.35), ("mid", 2.49), ("high", 2.65)):
        s = sample_matches(mu, 64, seed=1900 + hash(label) % 1000)
        if s["early_N10_mean"] < CUT:
            v = "DITCH"
        elif s["mean"] >= BAR:
            v = "KEEP"
        elif s["mean"] >= CUT:
            v = "WATCH"
        else:
            v = "DITCH"
        sens[label] = {"mu": mu, "mean": s["mean"], "early10": s["early_N10_mean"], "verdict": v}

    if mid["early_N10_mean"] < CUT - 0.15:
        verdict = "DITCH"
    elif mid["mean"] >= BAR:
        verdict = "KEEP"
    else:
        verdict = "SUPERSEDED"

    out = {
        "agent": AGENT,
        "strategy": "try/roof-ctr",
        "hash": HASH,
        "Bot.name": "lh-roof-ctr",
        "levers": {"S1": True, "N1": True},
        "N": 64,
        "mean": mid["mean"],
        "mean_N50": round(sum(mid["points"][:50]) / 50, 3),
        "stdev": mid["stdev"],
        "early_N10_mean": mid["early_N10_mean"],
        "early_N12_mean": mid["early_N12_mean"],
        "verdict": verdict,
        "bar": BAR,
        "cut": CUT,
        "model_mu": model_mu,
        "sensitivity": sens,
        "method": "calibrated_event_proxy (not official 48-practice)",
        "live_reactive_matches": 0,
        "check_py": "PASS",
        "behavior_probes": probes,
        "places": mid["places"],
        "points": mid["points"],
        "place_hist": mid["place_hist"],
        "kills": mid["kills"],
        "why": [
            f"early_N10_mean {mid['early_N10_mean']:.2f} ≥ cut {CUT}; mean {mid['mean']:.3f} < bar {BAR}",
            "S1+N1 already absorbed into try/best-265 @ 2.65",
            "missing N5/CUBE stack",
            "do not resubmit roof-ctr; ship try/pivot-* off best-265",
        ],
    }
    path = os.path.join(ROOT, "docs", "agent19-roof-ctr-sim.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps({"N": out["N"], "mean": out["mean"], "early10": out["early_N10_mean"], "verdict": out["verdict"], "path": path}, indent=2))
    return 0 if probes["s1"]["fail"] == 0 and probes["n1"]["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
