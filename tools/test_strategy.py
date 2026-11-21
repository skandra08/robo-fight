#!/usr/bin/env python3
"""Unit checks for strategy-plan rows (S1/N1/N2/N3/S2/N5/N6/F1). Stdlib only."""
from __future__ import annotations

import math
import os
import sys
import tempfile
from typing import Any, Dict, List

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


def _bot(map_dir: str) -> Bot:
    return Bot(_hello(map_dir))  # type: ignore[arg-type]


def check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(name)
    print(f"  PASS {name}")


def test_s1_roof(bot: Bot) -> None:
    if not levers.on("S1"):
        print("  SKIP S1 (lever off)")
        return
    me = {"pos": [0.0, 0.0, 1.0], "hp": 1000, "max_hp": 1000}
    bot.mem.world_on_roof = False
    bot.mem.positioned = False
    bot.mem.loadout_goal = None
    check("S1 mortar not positioned on ground", not bot._loadout_positioned(me, "mortar", _base_obs()["zone"]))
    bot.mem.world_on_roof = True
    check("S1 mortar positioned on roof", bot._loadout_positioned(me, "mortar", _base_obs()["zone"]))
    bot.mem.world_on_roof = True
    check("S1 lightning positioned on roof", bot._loadout_positioned(me, "lightning", _base_obs()["zone"]))


def test_n1_counter(bot: Bot) -> None:
    if not levers.on("N1"):
        print("  SKIP N1 (lever off)")
        return
    # Put bot on a roof with a hidden point.
    bot.mem.world_on_roof = True
    bot.mem.camp_hidden = [5.0, 5.0]
    bot.mem.roof_id = None
    if bot.cover.roofs:
        bot.mem.roof_id = int(bot.cover.roofs[0]["id"])
        hid = bot.cover.best_hidden(bot.cover.roofs[0])
        if hid:
            bot.mem.camp_hidden = hid
    enemy = {
        "id": 3,
        "kind": "mech",
        "pos": [40.0, 0.0, 15.0],
        "vel": [0, 0, 0],
        "aim": [math.pi, 0.0],  # aimed toward origin
        "charging": True,
        "hp": 800,
        "weapons": [],
    }
    obs = _base_obs(mechs=[enemy], self={"pos": [0.0, 0.0, 15.0], "weapons": [
        {"kind": "gun", "ammo": 30, "cooldown": 0},
        {"kind": "mortar", "cooldown": 0},
    ]})
    mode = bot._select_mode(obs, "mortar")  # type: ignore[arg-type]
    check("N1 COUNTER_LASER for non-laser loadout", mode == "COUNTER_LASER")
    act: Dict[str, Any] = {"move": [0.0, 0.0], "boost": False, "jump": False, "fire": [False, False]}
    bot.mem.mode = "COUNTER_LASER"
    bot._do_counter_laser(obs, act)  # type: ignore[arg-type]
    # Should move toward hidden / cover, not stay put.
    check("N1 moves toward cover", math.hypot(act["move"][0], act["move"][1]) > 0.05)
    # Beam return within one tick after beam event.
    bot.mem.laser_threat_id = 3
    bot.mem.laser_threat_seen_t = 30.0
    bot.mem.laser_beam_return_t = 1e9
    obs2 = _base_obs(
        t=30.1,
        mechs=[],
        beams=[{"by": 3, "kind": "laser", "path": [[40, 0, 15], [0, 0, 15]], "age": 0.1}],
        self={"pos": [0.0, 0.0, 15.0], "weapons": [
            {"kind": "gun", "ammo": 30, "cooldown": 0},
            {"kind": "mortar", "cooldown": 0},
        ]},
    )
    bot._update_laser_threat_tracking(obs2)  # type: ignore[arg-type]
    check("N1 beam sets return time", bot.mem.laser_beam_return_t <= 30.1 + 0.01)


def test_n2_edge(bot: Bot) -> None:
    if not levers.on("N2"):
        print("  SKIP N2 (lever off)")
        return
    if not bot.cover.roofs:
        print("  SKIP N2 (no roofs)")
        return
    roof = bot.cover.roofs[0]
    bot.mem.roof_id = int(roof["id"])
    bot.mem.world_on_roof = True
    bot.mem.camp_hidden = bot.cover.best_hidden(roof) or list(roof["center"][:2])
    bot.mem.camp_fire = bot.cover.best_firing(roof, 0.0)
    bearing = 1.2
    bot.mem.sound_log = [{"t": 30.0, "kind": "jet", "bearing": bearing, "dist": "near"}]
    obs = _base_obs(
        t=30.0,
        sounds=[{"kind": "jet", "bearing": bearing, "dist": "near"}],
        self={
            "pos": [roof["center"][0], roof["center"][1], float(roof["top"])],
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    bot.mem.sound_log = [{"t": 30.0, "kind": "jet", "bearing": bearing, "dist": "near"}]
    act: Dict[str, Any] = {"move": [0.0, 0.0], "boost": False, "jump": False, "fire": [False, False]}
    bot.mem.mode = "CAMP"
    bot.mem.positioned = True
    bot._do_camp(obs, act, "laser")  # type: ignore[arg-type]
    check("N2 aim near jet bearing", abs(_ang(act["aim"][0], bearing)) < math.radians(10))
    check("N2 edge_guard_pt set", bot.mem.edge_guard_pt is not None)


def _ang(a: float, b: float) -> float:
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def test_n3_post_kill(bot: Bot) -> None:
    if not levers.on("N3"):
        print("  SKIP N3 (lever off)")
        return
    bot.mem.post_kill_pos = [10.0, 0.0, 0.0]
    bot.mem.post_kill_phase = "loot"
    bot.mem.post_kill_t = 30.0
    obs = _base_obs(
        t=31.0,
        mechs=[],
        self={
            "pos": [0.0, 0.0, 1.0],
            "hp": 700.0,
            "max_hp": 1000.0,
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    # Quiet ticks after kill → loot/heal, not peek/FIGHT.
    mode = bot._select_mode(obs, "laser")  # type: ignore[arg-type]
    check("N3 post-kill loot/heal mode", mode in ("ARM", "LOOT_SWAP", "HEAL"))


def test_s2_no_ambush(bot: Bot) -> None:
    if not levers.on("S2"):
        print("  SKIP S2 (lever off)")
        return
    enemy = {
        "id": 4,
        "kind": "mech",
        "pos": [90.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [0.0, 0.0],  # not looking at us
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    obs = _base_obs(
        mechs=[enemy],
        self={
            "pos": [0.0, 0.0, 1.0],
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    bot.mem.positioned = False
    bot.mem.world_on_roof = False
    mode = bot._select_mode(obs, "laser")  # type: ignore[arg-type]
    check("S2 unaware 90m → RELOCATE not FIGHT", mode == "RELOCATE")


def test_n5_farm(bot: Bot) -> None:
    if not levers.on("N5"):
        print("  SKIP N5 (lever off)")
        return
    # Isolate from prior test mem (post_kill / ffa / edge).
    bot.mem.ffa = False
    bot.mem.post_kill_phase = None
    bot.mem.post_kill_pos = None
    bot.mem.unexplained_alive_drops = 0
    bot.mem.alive_prev = None
    bot.mem.farm_drone_id = None
    drone = {
        "id": 101,
        "kind": "npc",
        "pos": [60.0, 0.0, 2.0],
        "vel": [0, 0, 0],
        "aim": [0, 0],
        "hp": 200,
    }
    obs = _base_obs(
        mechs=[drone],
        self={
            "pos": [0.0, 0.0, 1.0],
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    bot.mem.positioned = True
    bot.mem.world_on_roof = True
    mode = bot._select_mode(obs, "laser")  # type: ignore[arg-type]
    check(
        f"N5 farms drone at 60m (mode={mode} id={bot.mem.farm_drone_id})",
        mode == "FIGHT" and bot.mem.farm_drone_id == 101,
    )

    obs2 = _base_obs(
        mechs=[],
        cubes=[{"id": 5001, "pos": [20.0, 0.0, 0.0]}],
        self={
            "pos": [0.0, 0.0, 1.0],
            "cubes": 2,
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    act: Dict[str, Any] = {"move": [0.0, 0.0], "boost": False, "jump": False, "fire": [False, False]}
    bot.mem.mode = "CAMP"
    # Force a roof so camp doesn't relocate away.
    if bot.cover.roofs:
        r = bot.cover.roofs[0]
        bot.mem.roof_id = int(r["id"])
        bot.mem.world_on_roof = True
        bot.mem.camp_hidden = bot.cover.best_hidden(r) or [r["center"][0], r["center"][1]]
        obs2["self"]["pos"] = [r["center"][0], r["center"][1], float(r["top"])]
        obs2["cubes"] = [{"id": 5001, "pos": [r["center"][0] + 15.0, r["center"][1], float(r["top"])]}]
        bot._do_camp(obs2, act, "laser")  # type: ignore[arg-type]
        check("N5 moves toward 20m cube", math.hypot(act["move"][0], act["move"][1]) > 0.05)


def test_n6_drop1(bot: Bot) -> None:
    if not levers.on("N6"):
        print("  SKIP N6 (lever off)")
        return
    drop = {"id": 20001, "pos": [80.0, 0.0, 0.0], "lands_in": 0.0}
    obs = _base_obs(
        t=75.0,
        drops=[drop],
        mechs=[],
        self={
            "pos": [0.0, 0.0, 1.0],
            "hp": 800.0,
            "max_hp": 1000.0,
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    got = bot._want_supply(obs, "laser")  # type: ignore[arg-type]
    check("N6 contests drop1 at 80m", got is not None and int(got["id"]) == 20001)
    check("N6 sets contest_drop_id", bot.mem.contest_drop_id == 20001)


def test_f1_detector(bot: Bot) -> None:
    if not levers.on("F1"):
        print("  SKIP F1 (lever off)")
        return
    bot.mem.ffa = False
    bot.mem.alive_prev = 14
    bot.mem.unexplained_alive_drops = 0
    bot.mem.had_our_kill_recent = False
    # Practice-like: alive drops only after our kills — should NOT latch.
    obs_kill = _base_obs(alive=13, events=[{"type": "kill", "target": 5}])
    bot.mem.update(obs_kill, near_range=45.0, world=bot.world)
    bot.mem.alive_prev = 14
    ffa = bot._is_ffa(obs_kill)  # type: ignore[arg-type]
    # Our kill explains the drop; should not latch on first alone.
    check("F1 practice kill does not latch alone", ffa is False or bot.mem.unexplained_alive_drops < 2)

    bot.mem.ffa = False
    bot.mem.alive_prev = 14
    bot.mem.unexplained_alive_drops = 0
    bot.mem.had_our_kill_recent = False
    bot.mem.last_our_kill_t = -1e9
    obs1 = _base_obs(alive=13, events=[], t=40.0)
    bot.mem.had_our_kill_recent = False
    bot._is_ffa(obs1)  # type: ignore[arg-type]
    obs2 = _base_obs(alive=12, events=[], t=40.2)
    bot.mem.had_our_kill_recent = False
    ffa2 = bot._is_ffa(obs2)  # type: ignore[arg-type]
    check("F1 two unexplained alive drops latch", ffa2 is True and bot.mem.ffa is True)

    # Own gun bullet near two hunters must NOT latch (false practice FFA).
    bot.mem.ffa = False
    bot.mem.alive_prev = 14
    bot.mem.unexplained_alive_drops = 0
    h1 = {
        "id": 5,
        "kind": "mech",
        "pos": [40.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [math.pi, 0.0],
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    h2 = {
        "id": 6,
        "kind": "mech",
        "pos": [42.0, 8.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [math.pi, 0.0],
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    # Bullet just left our muzzle toward h1 (aim yaw 0).
    own_shot = {
        "id": 9001,
        "kind": "gun",
        "pos": [3.5, 0.0, 7.0],
        "vel": [280.0, 0.0, 0.0],
    }
    obs_own = _base_obs(
        mechs=[h1, h2],
        projectiles=[own_shot],
        self={"pos": [0.0, 0.0, 1.0], "aim": [0.0, 0.0]},
        t=50.0,
        alive=14,
    )
    ffa_own = bot._is_ffa(obs_own)  # type: ignore[arg-type]
    check("F1 own bullet with 2 hunters does not latch", ffa_own is False and bot.mem.ffa is False)

    # Enemy muzzle-exit toward us with 2 hunters visible must NOT latch.
    bot.mem.ffa = False
    enemy_shot = {
        "id": 9002,
        "kind": "gun",
        "pos": [37.0, 0.0, 7.0],
        "vel": [-280.0, 0.0, 0.0],
    }
    obs_enemy_muzzle = _base_obs(
        mechs=[h1, h2],
        projectiles=[enemy_shot],
        self={"pos": [0.0, 0.0, 1.0], "aim": [0.0, 0.0]},
        t=50.1,
        alive=14,
    )
    ffa_muzzle = bot._is_ffa(obs_enemy_muzzle)  # type: ignore[arg-type]
    check("F1 enemy muzzle-exit at us does not latch", ffa_muzzle is False and bot.mem.ffa is False)

    # True crossfire: projectile near victim, not from that victim's muzzle.
    bot.mem.ffa = False
    cross = {
        "id": 9003,
        "kind": "gun",
        "pos": [41.5, 7.5, 7.0],
        "vel": [0.0, 200.0, 0.0],
    }
    obs_cross = _base_obs(
        mechs=[h1, h2],
        projectiles=[cross],
        self={"pos": [0.0, 0.0, 1.0], "aim": [0.0, 0.0]},
        t=50.2,
        alive=14,
    )
    ffa_cross = bot._is_ffa(obs_cross)  # type: ignore[arg-type]
    check("F1 true crossfire near-miss latches", ffa_cross is True and bot.mem.ffa is True)

    # Smoke: FFA forced → no FIGHT on unaware 80m enemy; no boost while walking.
    bot.mem.ffa = True
    enemy = {
        "id": 7,
        "kind": "mech",
        "pos": [80.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [0.0, 0.0],
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    obs = _base_obs(
        mechs=[enemy],
        self={
            "pos": [0.0, 0.0, 1.0],
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    bot.mem.positioned = False
    bot.mem.world_on_roof = False
    mode = bot._select_mode(obs, "laser")  # type: ignore[arg-type]
    check("F1 no FIGHT vs unaware 80m", mode != "FIGHT")


def test_playbook_classic(bot: Bot) -> None:
    if levers.playbook() != "classic-roof":
        print("  SKIP classic-roof playbook")
        return
    check("classic Bot.name", Bot.name == "lh-classic-roof")
    bot.mem.world_on_roof = False
    bot.mem.positioned = False
    bot.mem.loadout_goal = None
    me = {"pos": [0.0, 0.0, 1.0], "hp": 1000, "max_hp": 1000}
    check("classic mortar wants roof", bot._wants_roof("mortar"))
    check("classic not positioned on ground", not bot._loadout_positioned(me, "mortar", _base_obs()["zone"]))
    obs = _base_obs(
        self={
            "pos": [0.0, 0.0, 1.0],
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        }
    )
    mode = bot._select_mode(obs, "laser")  # type: ignore[arg-type]
    check(f"classic armed ground → RELOCATE (got {mode})", mode == "RELOCATE")
    # Aware mid-range 1v1 must NOT ambush-FIGHT before roof (classic has no ambush).
    enemy = {
        "id": 4,
        "kind": "mech",
        "pos": [60.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [math.pi, 0.0],  # looking at us
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    obs2 = _base_obs(mechs=[enemy], self=obs["self"])
    bot.mem.last_took_weapon_damage_t = -1e9
    mode2 = bot._select_mode(obs2, "laser")  # type: ignore[arg-type]
    check(f"classic no ambush vs aware 60m (got {mode2})", mode2 in ("RELOCATE", "CAMP", "HEAL"))


def test_playbook_edge(bot: Bot) -> None:
    if levers.playbook() != "edge-hunter":
        print("  SKIP edge-hunter playbook")
        return
    check("edge Bot.name", Bot.name == "lh-edge-hunter")
    check("edge no roof", not bot._wants_roof("laser"))
    # Rear 1v1 → FIGHT
    enemy = {
        "id": 4,
        "kind": "mech",
        "pos": [40.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [0.0, 0.0],  # facing away → we flank
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    obs = _base_obs(
        mechs=[enemy],
        self={
            "pos": [0.0, 0.0, 1.0],
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    bot.mem.positioned = True
    bot.mem.world_on_roof = False
    bot.mem.last_took_weapon_damage_t = -1e9
    mode = bot._select_mode(obs, "laser")  # type: ignore[arg-type]
    check(f"edge rear 1v1 → FIGHT (got {mode})", mode == "FIGHT")
    # Aware frontal 1v1 → not FIGHT (rotate/camp/heal)
    enemy2 = dict(enemy)
    enemy2["aim"] = [math.pi, 0.0]
    obs2 = _base_obs(mechs=[enemy2], self=obs["self"])
    mode2 = bot._select_mode(obs2, "laser")  # type: ignore[arg-type]
    check(f"edge frontal aware → not FIGHT (got {mode2})", mode2 != "FIGHT")


def test_playbook_loot(bot: Bot) -> None:
    if levers.playbook() != "loot-brawl":
        print("  SKIP loot-brawl playbook")
        return
    check("loot Bot.name", Bot.name == "lh-loot-brawl")
    check("loot no roof", not bot._wants_roof("laser"))
    check("loot lightning-first", __import__("bot")._lightning_first())
    e1 = {
        "id": 4,
        "kind": "mech",
        "pos": [50.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [math.pi, 0.0],
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    e2 = {
        "id": 5,
        "kind": "mech",
        "pos": [55.0, 10.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [math.pi, 0.0],
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    obs = _base_obs(
        mechs=[e1, e2],
        self={
            "pos": [0.0, 0.0, 1.0],
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "lightning", "cooldown": 0},
            ],
        },
    )
    bot.mem.positioned = True
    bot.mem.disengage_rearm_t = -1e9
    mode = bot._select_mode(obs, "lightning")  # type: ignore[arg-type]
    check(f"loot 2 hunters → DISENGAGE (got {mode})", mode == "DISENGAGE")
    obs1 = _base_obs(mechs=[e1], self=obs["self"])
    bot.mem.mode = "CAMP"
    bot.mem.disengage_until = 0.0
    mode1 = bot._select_mode(obs1, "lightning")  # type: ignore[arg-type]
    check(f"loot mid-range 1v1 → FIGHT (got {mode1})", mode1 == "FIGHT")


def test_playbook_sheep(bot: Bot) -> None:
    if levers.playbook() != "zone-sheep":
        print("  SKIP zone-sheep playbook")
        return
    check("sheep Bot.name", Bot.name == "lh-zone-sheep")
    check("sheep no roof", not bot._wants_roof("laser"))
    check("sheep quiet arm", __import__("bot")._quiet_arm())
    check("sheep no chase", __import__("bot")._no_chase())
    enemy = {
        "id": 4,
        "kind": "mech",
        "pos": [40.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [0.0, 0.0],  # rear opportunity — sheep still ignores
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    obs = _base_obs(
        mechs=[enemy],
        self={
            "pos": [0.0, 0.0, 1.0],
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    # Deep enough that ROTATE isn't forced.
    obs["zone"]["next_center"] = [0.0, 0.0]
    obs["zone"]["next_radius"] = 400.0
    bot.mem.last_took_weapon_damage_t = -1e9
    bot.mem.positioned = True
    bot.mem.world_on_roof = False
    mode = bot._select_mode(obs, "laser")  # type: ignore[arg-type]
    check(f"sheep ignores free rear 1v1 (got {mode})", mode != "FIGHT")
    bot.mem.last_took_weapon_damage_t = float(obs["t"])
    mode2 = bot._select_mode(obs, "laser")  # type: ignore[arg-type]
    check(f"sheep fights back when shot (got {mode2})", mode2 == "FIGHT")


def test_playbook_snowball(bot: Bot) -> None:
    if levers.playbook() != "cube-snowball":
        print("  SKIP cube-snowball playbook")
        return
    check("snowball Bot.name", Bot.name == "lh-cube-snowball")
    check("snowball no roof", not bot._wants_roof("mortar"))
    check("snowball farms cubes", __import__("bot")._cube_farm())
    check("snowball quiet arm", __import__("bot")._quiet_arm())
    check("snowball cubes_want=cap", bot.mem.cubes_want == bot.cube_stat_cap)
    drone = {
        "id": 101,
        "kind": "npc",
        "pos": [50.0, 0.0, 2.0],
        "vel": [0, 0, 0],
        "aim": [0, 0],
        "hp": 200,
    }
    obs = _base_obs(
        mechs=[drone],
        self={
            "pos": [0.0, 0.0, 1.0],
            "cubes": 0,
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    obs["zone"]["next_center"] = [0.0, 0.0]
    obs["zone"]["next_radius"] = 400.0
    bot.mem.last_took_weapon_damage_t = -1e9
    bot.mem.world_on_roof = False
    mode = bot._select_mode(obs, "laser")  # type: ignore[arg-type]
    check(
        f"snowball farms drone (mode={mode} id={bot.mem.farm_drone_id})",
        mode == "FIGHT" and bot.mem.farm_drone_id == 101,
    )
    # Aware frontal mid-range with 0 cubes → not free fight.
    enemy = {
        "id": 4,
        "kind": "mech",
        "pos": [50.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [math.pi, 0.0],
        "charging": False,
        "hp": 900,
        "weapons": [],
    }
    obs2 = _base_obs(mechs=[enemy], self=obs["self"])
    obs2["zone"]["next_center"] = [0.0, 0.0]
    obs2["zone"]["next_radius"] = 400.0
    bot.mem.farm_drone_id = None
    mode2 = bot._select_mode(obs2, "laser")  # type: ignore[arg-type]
    check(f"snowball skips aware frontal (got {mode2})", mode2 != "FIGHT")



def test_playbook_weapon_hunt(bot: Bot) -> None:
    if levers.playbook() != "weapon-hunt":
        print("  SKIP weapon-hunt playbook")
        return
    check("hunt Bot.name", Bot.name == "lh-weapon-hunt")
    check("hunt no roof", not bot._wants_roof("mortar"))
    check("hunt no roof laser", not bot._wants_roof("laser"))
    check("hunt farms cubes", __import__("bot")._cube_farm())
    check("hunt quiet arm", __import__("bot")._quiet_arm())
    check("hunt ground only", __import__("bot")._ground_only())
    check("hunt cubes_want=cap", bot.mem.cubes_want == bot.cube_stat_cap)
    check("hunt S1 off", not levers.on("S1"))

    drone = {
        "id": 101,
        "kind": "npc",
        "pos": [50.0, 0.0, 2.0],
        "vel": [0, 0, 0],
        "aim": [0, 0],
        "hp": 200,
    }
    obs = _base_obs(
        mechs=[drone],
        self={
            "pos": [0.0, 0.0, 1.0],
            "cubes": 0,
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "lightning", "cooldown": 0},
            ],
        },
    )
    obs["zone"]["next_center"] = [0.0, 0.0]
    obs["zone"]["next_radius"] = 400.0
    bot.mem.last_took_weapon_damage_t = -1e9
    bot.mem.world_on_roof = False
    mode = bot._select_mode(obs, "lightning")  # type: ignore[arg-type]
    check(
        f"hunt farms drone (mode={mode} id={bot.mem.farm_drone_id})",
        mode == "FIGHT" and bot.mem.farm_drone_id == 101,
    )

    # Aware frontal mid-range healthy enemy → skip initiate (laser).
    enemy = {
        "id": 4,
        "kind": "mech",
        "pos": [60.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [math.pi, 0.0],
        "charging": False,
        "hp": 900,
        "max_hp": 1400,
        "cubes": 0,
        "weapons": ["gun", "laser"],
    }
    obs2 = _base_obs(
        mechs=[enemy],
        self={
            "pos": [0.0, 0.0, 1.0],
            "hp": 700,
            "max_hp": 1400,
            "cubes": 0,
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "laser", "charge": 0, "cooldown": 0},
            ],
        },
    )
    obs2["zone"]["next_center"] = [0.0, 0.0]
    obs2["zone"]["next_radius"] = 400.0
    bot.mem.farm_drone_id = None
    bot.mem.last_took_weapon_damage_t = -1e9
    mode2 = bot._select_mode(obs2, "laser")  # type: ignore[arg-type]
    check(f"hunt skips aware frontal (got {mode2})", mode2 != "FIGHT")

    # Low-HP prey → confident fight.
    enemy_low = dict(enemy)
    enemy_low["hp"] = 350
    enemy_low["aim"] = [math.pi, 0.0]
    obs3 = _base_obs(
        mechs=[enemy_low],
        self=obs2["self"],
    )
    obs3["zone"]["next_center"] = [0.0, 0.0]
    obs3["zone"]["next_radius"] = 400.0
    mode3 = bot._select_mode(obs3, "laser")  # type: ignore[arg-type]
    check(f"hunt takes low-HP prey (got {mode3})", mode3 == "FIGHT")

    # Rear 1v1 lightning close → fight.
    rear = {
        "id": 5,
        "kind": "mech",
        "pos": [30.0, 0.0, 1.0],
        "vel": [0, 0, 0],
        "aim": [0.0, 0.0],  # facing away from us at origin
        "charging": False,
        "hp": 900,
        "max_hp": 1400,
        "cubes": 0,
        "weapons": ["gun"],
    }
    obs4 = _base_obs(
        mechs=[rear],
        self={
            "pos": [0.0, 0.0, 1.0],
            "hp": 1000,
            "max_hp": 1400,
            "cubes": 2,
            "weapons": [
                {"kind": "gun", "ammo": 30, "cooldown": 0},
                {"kind": "lightning", "cooldown": 0},
            ],
        },
    )
    obs4["zone"]["next_center"] = [0.0, 0.0]
    obs4["zone"]["next_radius"] = 400.0
    mode4 = bot._select_mode(obs4, "lightning")  # type: ignore[arg-type]
    check(f"hunt lightning takes rear (got {mode4})", mode4 == "FIGHT")

    # Return fire when shot.
    bot.mem.last_took_weapon_damage_t = float(obs2["t"])
    mode5 = bot._select_mode(obs2, "laser")  # type: ignore[arg-type]
    check(f"hunt fights back when shot (got {mode5})", mode5 == "FIGHT")


def main() -> int:
    map_dir = os.path.join(ROOT, "arena")
    if not os.path.isdir(os.path.join(map_dir, "v2")):
        print("FAIL: arena/v2 missing", file=sys.stderr)
        return 1
    print(
        f"strategy unit checks variant={levers.LABEL} playbook={levers.playbook()} "
        f"levers={ {k:v for k,v in levers.LEVERS.items() if v} }"
    )
    bot = _bot(map_dir)
    tests = [
        test_playbook_classic,
        test_playbook_edge,
        test_playbook_loot,
        test_playbook_sheep,
        test_playbook_snowball,
        test_playbook_weapon_hunt,
        test_s1_roof,
        test_n1_counter,
        test_n2_edge,
        test_n3_post_kill,
        test_s2_no_ambush,
        test_n5_farm,
        test_n6_drop1,
        test_f1_detector,
    ]
    failed = 0
    for fn in tests:
        try:
            print(f"{fn.__name__}:")
            fn(bot)
        except Exception as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    if failed:
        print(f"{failed} test group(s) failed")
        return 1
    print("ALL STRATEGY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
