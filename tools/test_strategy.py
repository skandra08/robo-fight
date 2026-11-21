#!/usr/bin/env python3
"""Unit checks for the farm-fight-heal loop (try/rewrite). Stdlib only."""
from __future__ import annotations

import copy
import math
import os
import random
import sys
import time
from typing import Any, Dict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import levers  # noqa: E402
from bot import Bot  # noqa: E402

# Open ground near the start-zone centre (checked against arena/v2): clear lines of sight
# from ME to WEST (80 m) and NORTH (80 m).
ME = [30.0, -60.0, 1.53]
WEST = [-50.0, -60.0]
NORTH = [30.0, 20.0, 1.25]


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
            "mech": {"step_up": 1.2, "regen_delay": 5.0, "walk_speed": 11.7, "height": 9.0, "eye_height": 8.0},
            "weapons": {
                "gun": {"damage": 45, "cooldown": 0.24, "speed": 252, "range": 230},
                "laser": {"damage": 315, "charge": 0.75, "min_charge": 0.15, "hold_s": 2.0, "cooldown": 1.65, "range": 280},
                "mortar": {"damage": 200, "cooldown": 2.6, "speed": 72, "gravity": 22},
                "lightning": {"damage": 60, "range": 45, "cooldown": 0.25, "cone_deg": 30},
            },
            "npc": {"height": 3.5, "aggro_range": 45},
            "drops": {"times": [70, 140, 210], "radius": 8.0},
            "sound": {"step_speed": 5.0},
            "debug": {"hold_s": 0.5},
        },
    }


def _obs(**kw: Any) -> Dict[str, Any]:
    me = {
        "id": 0,
        "pos": list(ME),
        "vel": [0.0, 0.0, 0.0],
        "aim": [0.0, -0.05],
        "hp": 1400.0,
        "max_hp": 1400.0,
        "energy": 100.0,
        "max_energy": 100.0,
        "cubes": 0,
        "weapons": [{"kind": "gun", "ammo": 12, "cooldown": 0, "reload": 0}, None],
        "grounded": True,
        "in_zone": True,
        "stats": {"walk_speed": 11.7, "eye_height": 8.0, "muzzle_height": 7.0},
    }
    obs: Dict[str, Any] = {
        "type": "obs", "tick": 10, "t": 30.0, "alive": 16, "self": me,
        "mechs": [], "projectiles": [], "crates": [], "cubes": [], "pickups": [],
        "sounds": [], "beams": [], "events": [], "drops": [], "offer": None,
        "zone": {"center": [41.3, -72.8], "radius": 560.0, "next_center": [30.0, -60.0],
                 "next_radius": 380.0, "shrink_start": 60.0, "shrink_end": 110.0, "dps": 20},
    }
    for k, v in kw.items():
        if k == "self":
            obs["self"].update(v)
        else:
            obs[k] = v
    return obs


def _mech(mid: int, xy, hp: float = 1400.0, aim: float = 0.0) -> Dict[str, Any]:
    from_ground = NORTH[2] if list(xy[:2]) == NORTH[:2] else 1.5
    return {"id": mid, "kind": "mech", "pos": [xy[0], xy[1], from_ground], "vel": [0, 0, 0],
            "aim": [aim, 0.0], "hp": hp, "max_hp": 1400, "cubes": 0, "weapons": ["gun"], "charging": False}


def check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(name)
    print(f"  PASS {name}")


def fresh(map_dir: str) -> Bot:
    return Bot(_hello(map_dir))  # type: ignore[arg-type]


def mode_of(bot: Bot, obs: Dict[str, Any]) -> str:
    bot.act(obs)  # type: ignore[arg-type]
    return bot.mode


def test_upgrades(md: str) -> None:
    bot = fresh(md)
    offer = {"id": 1, "expires": 40, "choices": [{"id": "sensors"}, {"id": "nanites"}, {"id": "armor"}]}
    check("greedy order picks armor first", bot._pick_upgrade(offer) == 2)


def test_zone(md: str) -> None:
    bot = fresh(md)
    check("out of zone -> ESCAPE", mode_of(bot, _obs(self={"in_zone": False})) == "ESCAPE")
    bot = fresh(md)
    z = {"center": [41.3, -72.8], "radius": 560.0, "next_center": [400.0, -60.0], "next_radius": 140.0,
         "shrink_start": 20.0, "shrink_end": 40.0, "dps": 20}
    check("next circle closing far away -> ZONE", mode_of(bot, _obs(zone=z)) == "ZONE")


def test_farm(md: str) -> None:
    bot = fresh(md)
    cube = {"id": 5001, "pos": [30.0, -20.0, 1.3]}
    check("visible cube -> FARM", mode_of(bot, _obs(cubes=[cube])) == "FARM")
    check("FARM target is the cube", bot._farm is not None and bot._farm["kind"] == "cube")
    a = bot.act(_obs(cubes=[cube], tick=12, t=30.1))  # type: ignore[arg-type]
    check("walks toward the cube", a["move"][1] > 0.3)

    bot = fresh(md)
    crate = {"id": 1001, "pos": [-50.0, -60.0, 1.5], "hp": 300}
    m = mode_of(bot, _obs(crates=[crate]))
    check("visible crate with clear shot -> FARM crate", m == "FARM" and bot._farm and bot._farm["kind"] == "crate")

    bot = fresh(md)
    drone = {"id": 104, "kind": "npc", "pos": [-50.0, -60.0, 1.5], "vel": [0, 0, 0], "aim": [0, 0], "hp": 350, "max_hp": 350}
    m = mode_of(bot, _obs(mechs=[drone]))
    check("drone at 80 m -> FARM drone", m == "FARM" and bot._farm and bot._farm["kind"] == "drone")

    bot = fresh(md)
    lz = {"id": 8001, "kind": "laser", "pos": [30.0, -40.0, 1.4]}
    m = mode_of(bot, _obs(pickups=[lz]))
    check("laser pickup with no second weapon -> FARM loot", m == "FARM" and bot._farm and bot._farm["kind"] == "loot")

    bot = fresh(md)
    check("nothing early -> FARM search", mode_of(bot, _obs()) == "FARM")
    bot = fresh(md)
    check("nothing later -> FARM search, no roof camping", mode_of(bot, _obs(t=150.0, tick=3000)) == "FARM")


def test_supply(md: str) -> None:
    bot = fresh(md)
    drop = {"id": 20000, "pos": [30.0, -20.0, 1.3], "radius": 8, "lands_in": 2.0, "capture_s": 4, "progress": 0, "holder": None}
    check("reachable supply drop -> SUPPLY", mode_of(bot, _obs(drops=[drop])) == "SUPPLY")
    far = dict(drop, lands_in=25.0)
    bot = fresh(md)
    check("drop landing much later than we'd arrive -> not yet", mode_of(bot, _obs(drops=[far])) != "SUPPLY")


def test_fight(md: str) -> None:
    bot = fresh(md)
    e = _mech(5, WEST, aim=0.0)
    check("early: far mech that isn't hitting us -> keep farming", mode_of(bot, _obs(mechs=[e])) != "FIGHT")
    bot = fresh(md)
    check("mech in clear view at 80 m -> FIGHT", mode_of(bot, _obs(mechs=[e], t=90.0, tick=1800)) == "FIGHT")

    bot = fresh(md)
    near, far = _mech(5, NORTH), _mech(6, WEST)
    far["pos"] = [-20.0, -60.0, 1.5]  # 50 m
    bot.act(_obs(mechs=[near, far], t=90.0, tick=1800))  # type: ignore[arg-type]
    check("targets the nearest mech", bot._target_id == 6)

    bot = fresh(md)
    e = _mech(5, WEST)
    e["pos"] = [10.0, -60.0, 1.6]  # 20 m: inside the band
    a = bot.act(_obs(mechs=[e], t=90.0, tick=1800))  # type: ignore[arg-type]
    check("backs off when inside the fight band", a["move"][0] > 0.2)

    bot = fresh(md)
    lowhp = {"hp": 400.0}
    check("low HP with mech in view -> HEAL", mode_of(bot, _obs(self=lowhp, mechs=[_mech(5, WEST)], t=90.0, tick=1800)) == "HEAL")
    bot = fresh(md)
    check("low HP but target nearly dead -> FIGHT",
          mode_of(bot, _obs(self=lowhp, mechs=[_mech(5, WEST, hp=150.0)], t=90.0, tick=1800)) == "FIGHT")


def test_heal(md: str) -> None:
    bot = fresh(md)
    check("hurt, nobody in view -> HEAL (rest)", mode_of(bot, _obs(self={"hp": 800.0})) == "HEAL")
    a = bot.act(_obs(self={"hp": 800.0}, tick=12, t=30.1))  # type: ignore[arg-type]
    check("resting holds fire", not any(a["fire"]))
    crate = {"id": 1001, "pos": [-50.0, -60.0, 1.5], "hp": 300}
    m = mode_of(bot, _obs(self={"hp": 600.0}, crates=[crate], tick=14, t=30.2))
    check("resting at low HP does not shoot crates", m == "HEAL")
    m = mode_of(bot, _obs(self={"hp": 850.0}, crates=[crate], tick=15, t=30.25))
    check("hurt but above half HP keeps farming crates", m == "FARM")
    m = mode_of(bot, _obs(self={"hp": 1300.0}, tick=16, t=30.3))
    check("healed -> leaves HEAL", m != "HEAL")


def test_drone(md: str) -> None:
    bot = fresh(md)
    drone = {"id": 104, "kind": "npc", "pos": [30.0, -30.0, 1.5], "vel": [0, 0, 0], "aim": [0, 0], "hp": 350, "max_hp": 350}
    ev = [{"type": "damaged", "amount": 25, "weapon": "npc", "bearing": math.pi / 2, "by": 104}]
    check("drone shooting us -> DRONE", mode_of(bot, _obs(mechs=[drone], events=ev)) == "DRONE")


def test_multi_disengage(md: str) -> None:
    """Hard DISENGAGE when ≥2 mech attackers / multi-source damage within ~2.5s."""
    bot = fresh(md)
    a = _mech(5, WEST)
    b = _mech(6, NORTH)
    # Two distinct mech damage sources in one window → DISENGAGE.
    ev = [
        {"type": "damaged", "amount": 45, "weapon": "gun", "bearing": math.pi, "by": 5},
        {"type": "damaged", "amount": 45, "weapon": "gun", "bearing": math.pi / 2, "by": 6},
    ]
    m = mode_of(bot, _obs(mechs=[a, b], events=ev, t=90.0, tick=1800))
    check("two mech damage sources -> DISENGAGE", m == "DISENGAGE")
    check("multi latch set", bot.mem.multi_disengage and bot.mem.multi)

    # While latched with two visible aggressors, stay peeled (no fire, boost).
    a2 = bot.act(_obs(mechs=[a, b], t=90.2, tick=1804, self={"hp": 900.0}))  # type: ignore[arg-type]
    check("multi peel holds fire", not any(a2["fire"]))
    check("multi peel boosts", bool(a2.get("boost")))

    # Single attacker + healthy: no multi DISENGAGE.
    bot = fresh(md)
    one = [
        {"type": "damaged", "amount": 45, "weapon": "gun", "bearing": math.pi, "by": 5},
    ]
    m = mode_of(bot, _obs(mechs=[a], events=one, t=90.0, tick=1800))
    check("single attacker stays FIGHT", m == "FIGHT")
    check("single attacker no multi latch", not bot.mem.multi_disengage)

    # Damage spike >250/2s from one source also trips multi pressure.
    bot = fresh(md)
    spike = [
        {"type": "damaged", "amount": 130, "weapon": "laser", "bearing": math.pi, "by": 5},
        {"type": "damaged", "amount": 130, "weapon": "laser", "bearing": math.pi, "by": 5},
    ]
    check(
        "dmg spike >250/2s -> DISENGAGE",
        mode_of(bot, _obs(mechs=[a], events=spike, t=90.0, tick=1800)) == "DISENGAGE",
    )

    # Clear: ≤1 aggressor and HP≥45% → leave DISENGAGE.
    bot = fresh(md)
    mode_of(bot, _obs(mechs=[a, b], events=ev, t=90.0, tick=1800))
    bot.mem.damage_log = []
    bot.mem.multi_until = -1e9
    bot.mem.last_took_weapon_damage_t = -1e9
    m = mode_of(bot, _obs(mechs=[a], t=95.0, tick=1900, self={"hp": 900.0}))
    check("cleared multi + HP≥45% leaves DISENGAGE", m != "DISENGAGE")
    check("multi latch cleared", not bot.mem.multi_disengage)


def test_timing(md: str) -> None:
    bot = fresh(md)
    rng = random.Random(3)
    worst = 0.0
    total = 0.0
    n = 400
    for i in range(n):
        o = _obs(tick=10 + 2 * i, t=20.0 + 0.1 * i)
        o["self"]["pos"] = [ME[0] + rng.uniform(-150, 150), ME[1] + rng.uniform(-150, 150), 1.5]
        o["self"]["pos"][2] = bot.world.ground(o["self"]["pos"][0], o["self"]["pos"][1])
        o["self"]["hp"] = rng.choice([1400.0, 900.0, 400.0])
        o["mechs"] = [_mech(5 + k, [o["self"]["pos"][0] + rng.uniform(-120, 120), o["self"]["pos"][1] + rng.uniform(-120, 120)]) for k in range(rng.randint(0, 3))]
        o["mechs"] += [{"id": 100 + k, "kind": "npc", "pos": [o["self"]["pos"][0] + rng.uniform(-100, 100), o["self"]["pos"][1] + rng.uniform(-100, 100), 1.5], "vel": [0, 0, 0], "aim": [0, 0], "hp": 350, "max_hp": 350} for k in range(rng.randint(0, 2))]
        o["crates"] = [{"id": 1000 + k, "pos": [o["self"]["pos"][0] + rng.uniform(-150, 150), o["self"]["pos"][1] + rng.uniform(-150, 150), 1.5], "hp": 300} for k in range(rng.randint(0, 4))]
        if rng.random() < 0.2:
            o["events"] = [{"type": "damaged", "amount": 45, "weapon": "gun", "bearing": 0.0, "by": 5}]
        t0 = time.perf_counter()
        bot.act(copy.deepcopy(o))  # type: ignore[arg-type]
        ms = (time.perf_counter() - t0) * 1000
        worst = max(worst, ms)
        total += ms
    print(f"  act mean {total / n:.2f} ms, worst {worst:.2f} ms over {n} random decisions")
    check("act mean under 15 ms", total / n < 15.0)
    check("act worst under 40 ms", worst < 40.0)


def main() -> int:
    map_dir = os.path.join(ROOT, "arena")
    if not os.path.isdir(os.path.join(map_dir, "v2")):
        print("FAIL: arena/v2 missing", file=sys.stderr)
        return 1
    print(f"strategy unit checks variant={levers.LABEL}")
    tests = [
        test_upgrades,
        test_zone,
        test_farm,
        test_supply,
        test_fight,
        test_heal,
        test_drone,
        test_multi_disengage,
        test_timing,
    ]
    failed = 0
    for fn in tests:
        try:
            print(f"{fn.__name__}:")
            fn(map_dir)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {fn.__name__}: {e!r}")
    if failed:
        print(f"{failed} test group(s) failed")
        return 1
    print("ALL STRATEGY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
