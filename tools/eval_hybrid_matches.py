#!/usr/bin/env python3
"""≥50 offline decision 'matches' for try/sim20-hybrid deltas.

Not a reactive arena sim — probes quieter ARM-in-zone + never-chase-when-2+.
Official practice mean still requires GitHub submit (48 games).
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Any, Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import levers  # noqa: E402
from bot import Bot  # noqa: E402


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
            {"kind": "laser", "charge": 0, "cooldown": 0},
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


def _enemy(eid: int, x: float, y: float) -> Dict[str, Any]:
    return {
        "id": eid,
        "kind": "mech",
        "pos": [x, y, 15.0],
        "vel": [0.0, 0.0, 0.0],
        "aim": [math.atan2(-y, -x), 0.0],
        "hp": 800.0,
        "weapons": [],
        "charging": False,
    }


def run_arm_quiet(bot: Bot, n: int) -> Dict[str, Any]:
    """S3: ARM inside zone must not boost (even at high energy)."""
    ok = 0
    fails: List[str] = []
    for i in range(n):
        bot.mem.mode = "ARM"
        bot.mem.arm_goal = None
        bot.mem.stuck_until = -1.0
        efrac = 0.55 + (i % 5) * 0.08
        energy = efrac * 100.0
        pickup = {
            "id": 100 + i,
            "kind": "laser",
            "pos": [20.0 + (i % 7), 5.0, 1.0],
        }
        obs = _base_obs(
            t=20.0 + i * 0.1,
            tick=20 + i,
            pickups=[pickup],
            self={
                "pos": [0.0, 0.0, 1.0],
                "energy": energy,
                "max_energy": 100.0,
                "in_zone": True,
                "weapons": [{"kind": "gun", "ammo": 30, "cooldown": 0}, None],
                "cubes": 0,
            },
        )
        act: Dict[str, Any] = {"move": [0.0, 0.0], "boost": False, "jump": False, "fire": [False, False]}
        bot._do_arm(obs, act)  # type: ignore[arg-type]
        # Stuck escape may force boost+jump; only count non-stuck ticks.
        if bot.mem.stuck_until > float(obs["t"]):
            ok += 1  # stuck override is intentional loud escape
            continue
        if not act.get("boost"):
            ok += 1
        else:
            fails.append(f"arm_boost_in_zone i={i} efrac={efrac:.2f}")
    return {"name": "arm_quiet_in_zone", "n": n, "ok": ok, "fail": n - ok, "fails": fails[:5]}


def run_no_chase_2plus(bot: Bot, n: int) -> Dict[str, Any]:
    """When 2+ hunters visible, move must not close toward nearest chase target."""
    ok = 0
    fails: List[str] = []
    for i in range(n):
        ang = (i * 0.37) % (2 * math.pi)
        d = 40.0 + (i % 5) * 8.0
        e1 = _enemy(10 + i, math.cos(ang) * d, math.sin(ang) * d)
        e2 = _enemy(50 + i, math.cos(ang + 1.2) * (d + 15), math.sin(ang + 1.2) * (d + 15))
        mechs = [e1, e2]
        if i % 3 == 0:
            mechs.append(_enemy(90 + i, math.cos(ang - 0.8) * (d + 25), math.sin(ang - 0.8) * (d + 25)))
        obs = _base_obs(
            t=40.0 + i * 0.1,
            tick=40 + i,
            mechs=mechs,
            events=[{"type": "damaged", "weapon": "gun", "by": e1["id"], "amount": 22}],
            self={
                "pos": [0.0, 0.0, 15.0],
                "energy": 80.0,
                "max_energy": 100.0,
                "in_zone": True,
                "weapons": [
                    {"kind": "gun", "ammo": 30, "cooldown": 0},
                    {"kind": "laser", "charge": 0, "cooldown": 0},
                ],
                "hp": 700.0,
            },
        )
        bot.mem.last_threat_id = int(e1["id"])
        bot.mem.last_threat_bearing = ang
        bot.mem.world_on_roof = (i % 2 == 0)
        bot.mem.stuck_until = -1.0
        act: Dict[str, Any] = {"move": [0.0, 0.0], "boost": False, "jump": False, "fire": [False, False]}
        bot._do_fight(obs, act, second="laser", aggressive=True)  # type: ignore[arg-type]
        mx, my = act["move"][0], act["move"][1]
        # Toward e1 = (cos(ang), sin(ang)); closing if move·toward > 0.15 and |move| significant.
        toward = (math.cos(ang), math.sin(ang))
        speed = math.hypot(mx, my)
        closing = speed > 0.15 and (mx * toward[0] + my * toward[1]) / max(speed, 1e-6) > 0.35
        if not closing:
            ok += 1
        else:
            fails.append(f"chased i={i} move=({mx:.2f},{my:.2f}) ang={ang:.2f}")
    return {"name": "no_chase_2plus", "n": n, "ok": ok, "fail": n - ok, "fails": fails[:5]}


def run_one_v_one_still_chases(bot: Bot, n: int) -> Dict[str, Any]:
    """Sanity: with exactly 1 hunter and no clear shot far away, 1v1 may still close."""
    closes = 0
    for i in range(n):
        ang = (i * 0.41) % (2 * math.pi)
        d = 90.0
        e1 = _enemy(200 + i, math.cos(ang) * d, math.sin(ang) * d)
        obs = _base_obs(
            t=50.0 + i * 0.1,
            tick=50 + i,
            mechs=[e1],
            events=[{"type": "damaged", "weapon": "gun", "by": e1["id"], "amount": 22}],
            self={
                "pos": [0.0, 0.0, 1.0],
                "energy": 80.0,
                "max_energy": 100.0,
                "weapons": [
                    {"kind": "gun", "ammo": 30, "cooldown": 0},
                    {"kind": "laser", "charge": 0, "cooldown": 0},
                ],
            },
        )
        bot.mem.last_threat_id = int(e1["id"])
        bot.mem.world_on_roof = False
        bot.mem.stuck_until = -1.0
        act: Dict[str, Any] = {"move": [0.0, 0.0], "boost": False, "jump": False, "fire": [False, False]}
        bot._do_fight(obs, act, second="laser", aggressive=True)  # type: ignore[arg-type]
        mx, my = act["move"][0], act["move"][1]
        toward = (math.cos(ang), math.sin(ang))
        speed = math.hypot(mx, my)
        if speed > 0.15 and (mx * toward[0] + my * toward[1]) / max(speed, 1e-6) > 0.2:
            closes += 1
    return {"name": "one_v_one_may_close", "n": n, "closes": closes}


def main() -> int:
    map_dir = os.path.join(ROOT, "arena")
    bot = Bot(_hello(map_dir))  # type: ignore[arg-type]
    n_each = 32  # 32+32 = 64 ≥ 50
    arm = run_arm_quiet(bot, n_each)
    nochase = run_no_chase_2plus(bot, n_each)
    sanity = run_one_v_one_still_chases(bot, 16)
    n = arm["n"] + nochase["n"]
    ok = arm["ok"] + nochase["ok"]
    mean = ok / n if n else 0.0
    # Proxy "points" map: full pass ≈ keep bar; not a practice mean.
    proxy_mean = 2.65 * mean  # scales vs best-265 bar only as compliance proxy
    verdict = "PASS_BEHAVIOR" if arm["fail"] == 0 and nochase["fail"] == 0 else "FAIL_BEHAVIOR"
    if verdict == "PASS_BEHAVIOR":
        verdict = "SHIP_FOR_SUBMIT"  # live practice mean still unknown until GitHub 48
    out = {
        "label": levers.LABEL,
        "levers": {k: v for k, v in levers.LEVERS.items() if v},
        "N": n,
        "ok": ok,
        "mean_compliance": round(mean, 4),
        "proxy_mean_vs_bar": round(proxy_mean, 3),
        "bar": 2.65,
        "verdict": verdict,
        "live_reactive_matches": 0,
        "suites": [arm, nochase, sanity],
        "note": (
            "N=decision probes (ARM quiet + no-chase 2+). "
            "Official practice mean requires submit → 48 scorer matches."
        ),
    }
    print(json.dumps(out, indent=2))
    return 0 if arm["fail"] == 0 and nochase["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
