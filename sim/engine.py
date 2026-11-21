"""Headless practice-mode simulator for mechfight/1 (approximation, not the real server).

One bot under test (slot 0) against a 15-mech house squad (4 easy, 4 medium, 4 hard, 3 expert)
that shares vision, never fights itself, and hunts the bot in escalating waves.
Rules follow protocol.md and hello.config from check/stream.jsonl.gz. Simplifications:
  * mechs are vertical cylinders; walls are prisms; support = terrain or a prism top we are above
  * gun/NPC bullets are stepped projectiles; laser is hitscan; lightning nearest-in-cone; mortar ballistic
  * vision: near_range all round + 200 m / 120 deg wedge with prism/terrain LOS (no canopy)
  * sounds: kind + noisy bearing + dist band, for gun/laser/lightning/mortar/explosion/death/crate/step/boost
House-bot behaviour is a fitted policy (see housebot.py), not the real one.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import random
import sys
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from world import World, _point_in_prism_xy  # noqa: E402

DT = 0.05


def load_config() -> Dict[str, Any]:
    with gzip.open(os.path.join(REPO, "check", "stream.jsonl.gz"), "rt") as f:
        hello = json.loads(f.readline())
    return hello["config"]


def wrap(a: float) -> float:
    return math.atan2(math.sin(a), math.cos(a))


class Mech:
    def __init__(self, mid: int, pos, cfg, team: str, skill: str = ""):
        m = cfg["mech"]
        self.id = mid
        self.team = team
        self.skill = skill
        self.base = dict(m)
        self.stats = dict(m)
        self.pos = list(pos)
        self.vel = [0.0, 0.0, 0.0]
        self.aim = [random.uniform(-math.pi, math.pi), 0.0]
        self.cmd = {"move": [0.0, 0.0], "boost": False, "jump": False, "aim": list(self.aim), "fire": [False, False]}
        self.hp = float(m["hp"])
        self.max_hp = float(m["hp"])
        self.energy = float(m["energy"])
        self.max_energy = float(m["energy"])
        self.energy_t = -9.0
        self.grounded = True
        self.cubes = 0
        self.ups: List[str] = []
        self.upcount: Dict[str, int] = {}
        self.weapons: List[Optional[Dict[str, Any]]] = [new_weapon("gun", cfg), None]
        self.wstats_mul: Dict[str, Dict[str, Any]] = {}
        self.alive = True
        self.last_dmg_t = -99.0
        self.offers: List[Dict[str, Any]] = []
        self.offer_id = 0
        self.events: List[Dict[str, Any]] = []
        self.sounds: List[Dict[str, Any]] = []
        self.beams_seen: List[Dict[str, Any]] = []
        self.seen_until: Dict[int, float] = {}
        self.kills = 0
        self.step_acc = 0.0
        self.death_t = None
        self.place = None
        self.short_until = -1.0
        self.zone_dmg = 0.0
        self.dmg_taken: Dict[str, float] = {}

    @property
    def scale(self) -> float:
        return 1.0 + 0.05 * self.cubes

    def radius(self) -> float:
        return self.stats["radius"] * self.scale

    def height(self) -> float:
        return self.stats["height"] * self.scale

    def muzzle(self) -> List[float]:
        return [self.pos[0], self.pos[1], self.pos[2] + self.stats["muzzle_height"] * self.scale]

    def eye(self) -> List[float]:
        return [self.pos[0], self.pos[1], self.pos[2] + self.stats["eye_height"] * self.scale]

    def center(self) -> List[float]:
        return [self.pos[0], self.pos[1], self.pos[2] + self.height() * 0.5]

    def has(self, kind: str) -> Optional[int]:
        for i, w in enumerate(self.weapons):
            if w and w["kind"] == kind:
                return i
        return None


def new_weapon(kind: str, cfg) -> Dict[str, Any]:
    st = dict(cfg["weapons"][kind])
    w = {"kind": kind, "stats": st, "cooldown": 0.0, "equip": 0.0}
    if kind == "gun":
        w["ammo"] = int(st["mag"])
        w["reload"] = 0.0
    if kind == "laser":
        w["charge"] = 0.0
        w["held"] = 0.0
    return w


class Sim:
    def __init__(self, seed: int, bot_factory, house_factory, cfg=None, world=None, log=False):
        self.cfg = cfg or load_config()
        self.world = world or World(os.path.join(REPO, "arena"))
        self.rng = random.Random(seed)
        random.seed(seed * 7 + 1)
        self.seed = seed
        self.t = 0.0
        self.tick = 0
        self.log = log
        self.next_id = 0
        self.proj: List[Dict[str, Any]] = []
        self.crates: List[Dict[str, Any]] = []
        self.cubes: List[Dict[str, Any]] = []
        self.pickups: List[Dict[str, Any]] = []
        self.npcs: List[Dict[str, Any]] = []
        self.drops: List[Dict[str, Any]] = []
        self.sound_events: List[Dict[str, Any]] = []
        self.beams: List[Dict[str, Any]] = []
        self._pid = 0
        self._cube_id = 5000
        self._pick_id = 8000
        self._setup_zone()
        self.mechs: List[Mech] = []
        self._spawn_mechs()
        self._spawn_world()
        self.bot = bot_factory(self._hello(0))
        self.house = house_factory(self)
        self.place_counter = 16
        self.house_zone_immune = bool(getattr(self.house, "zone_immune", True))

    # ------------------------------------------------------------------ setup
    def _hello(self, slot: int) -> Dict[str, Any]:
        return {"type": "hello", "protocol": "mechfight/1", "slot": slot, "seed": self.seed,
                "map": {"dir": os.path.join(REPO, "arena"), "files": ["v2/world.json", "v2/terrain.i16"]},
                "config": self.cfg}

    def _setup_zone(self):
        z = self.cfg["zone"]
        c = list(z["start_center"])
        r = float(z["start_radius"])
        t = 0.0
        self.zone_phases = []
        for ph in z["phases"]:
            nr = float(ph["radius"])
            # next circle entirely inside the current one
            off = max(0.0, r - nr) * math.sqrt(self.rng.random()) * 0.9
            a = self.rng.uniform(-math.pi, math.pi)
            nc = [c[0] + math.cos(a) * off, c[1] + math.sin(a) * off]
            hs = t + float(ph["hold_s"])
            he = hs + float(ph["shrink_s"])
            self.zone_phases.append({"c0": c, "r0": r, "c1": nc, "r1": nr, "hold_start": t, "s0": hs, "s1": he, "dps": float(ph["dps"])})
            c, r, t = nc, nr, he

    def zone(self) -> Dict[str, Any]:
        for ph in self.zone_phases:
            if self.t < ph["s1"]:
                if self.t < ph["s0"]:
                    c, r = ph["c0"], ph["r0"]
                else:
                    f = (self.t - ph["s0"]) / max(1e-6, ph["s1"] - ph["s0"])
                    c = [ph["c0"][0] + (ph["c1"][0] - ph["c0"][0]) * f, ph["c0"][1] + (ph["c1"][1] - ph["c0"][1]) * f]
                    r = ph["r0"] + (ph["r1"] - ph["r0"]) * f
                return {"center": [round(c[0], 2), round(c[1], 2)], "radius": round(r, 2), "next_center": list(ph["c1"]),
                        "next_radius": ph["r1"], "shrink_start": ph["s0"], "shrink_end": ph["s1"], "dps": ph["dps"]}
        ph = self.zone_phases[-1]
        return {"center": list(ph["c1"]), "radius": 0.0, "next_center": list(ph["c1"]), "next_radius": 0.0,
                "shrink_start": ph["s0"], "shrink_end": ph["s1"], "dps": ph["dps"]}

    def support(self, x: float, y: float, z: float, step: float) -> float:
        """Highest surface under (x, y) we could stand on from height z (terrain or prism top)."""
        w = self.world
        g = w.ground(x, y)
        best = g
        for idx in w._candidates(x, y):
            p = w.prisms[idx]
            top = p["top"]
            if top <= best or top > z + step:
                continue
            if x < p["minx"] or x > p["maxx"] or y < p["miny"] or y > p["maxy"]:
                continue
            if _point_in_prism_xy(x, y, p):
                best = top
        return best

    def blocked_at(self, x: float, y: float, z: float, h: float, step: float) -> bool:
        """A prism occupies the column [z + step, z + h] at (x, y)."""
        w = self.world
        for idx in w._candidates(x, y):
            p = w.prisms[idx]
            if p["top"] <= z + step or p["base"] >= z + h:
                continue
            if x < p["minx"] or x > p["maxx"] or y < p["miny"] or y > p["maxy"]:
                continue
            if _point_in_prism_xy(x, y, p):
                return True
        return False

    def random_spot(self, roof_frac: float, inside_r: float = 520.0, center=None) -> List[float]:
        w = self.world
        center = center or self.cfg["zone"]["start_center"]
        for _ in range(400):
            if self.rng.random() < roof_frac and w.roofs:
                p = self.rng.choice(w.roofs)
                if p["kind"] != "building" or p["top"] - w.ground((p["minx"] + p["maxx"]) / 2, (p["miny"] + p["maxy"]) / 2) > 60:
                    continue
                x = self.rng.uniform(p["minx"], p["maxx"])
                y = self.rng.uniform(p["miny"], p["maxy"])
                if not _point_in_prism_xy(x, y, p):
                    continue
                return [x, y, p["top"]]
            a = self.rng.uniform(-math.pi, math.pi)
            r = inside_r * math.sqrt(self.rng.random())
            x = center[0] + math.cos(a) * r
            y = center[1] + math.sin(a) * r
            b = w.bounds if hasattr(w, "bounds") else None
            if not (-500 < x < 545 and -325 < y < 380):
                continue
            g = w.ground(x, y)
            if self.blocked_at(x, y, g, 9.0, 0.0):
                continue
            return [x, y, g]
        return [center[0], center[1], w.ground(center[0], center[1])]

    def _spawn_mechs(self):
        mc = self.cfg["match"]
        r = float(self.cfg["zone"]["start_radius"]) * float(mc["spawn_zone_fraction"])
        sep = float(mc["spawn_min_separation"])
        skills = ["easy"] * 4 + ["medium"] * 4 + ["hard"] * 4 + ["expert"] * 3
        pts: List[List[float]] = []
        while len(pts) < 16:
            p = self.random_spot(0.0, r)
            if all(math.dist(p[:2], q[:2]) >= sep for q in pts) or self.rng.random() < 0.02:
                pts.append(p)
        for i in range(16):
            team = "bot" if i == 0 else "house"
            self.mechs.append(Mech(i, pts[i], self.cfg, team, "" if i == 0 else skills[i - 1]))

    def _spawn_world(self):
        c = self.cfg
        for i in range(int(c["crates"]["count"])):
            p = self.random_spot(float(c["crates"]["roof_fraction"]))
            self.crates.append({"id": 1000 + i, "pos": p, "hp": float(c["crates"]["hp"])})
        kinds = ["mortar", "laser", "lightning"]
        for i in range(int(c["loot"]["floor_count"])):
            p = self.random_spot(float(c["loot"]["floor_roof_fraction"]))
            self.add_pickup(self.rng.choice(kinds), p)
        for i in range(int(c["npc"]["count"])):
            p = self.random_spot(0.0)
            self.npcs.append({"id": 100 + i, "pos": p, "home": list(p), "hp": float(c["npc"]["hp"]), "max_hp": float(c["npc"]["hp"]),
                              "target": None, "cd": 0.0, "vel": [0.0, 0.0, 0.0], "yaw": 0.0, "wander": list(p), "alive": True})
        self.drops = []
        for i, t in enumerate(c["drops"]["times"]):
            self.drops.append({"id": 20000 + i, "call": float(t), "land": float(t) + float(c["drops"]["fall_s"]), "pos": None,
                               "holder": None, "progress": 0.0, "taken": False})

    def add_pickup(self, kind: str, pos) -> Dict[str, Any]:
        p = {"id": self._pick_id, "kind": kind, "pos": list(pos)}
        self._pick_id += 1
        self.pickups.append(p)
        return p

    def add_cube(self, pos):
        a = self.rng.uniform(-math.pi, math.pi)
        r = self.rng.uniform(0, 2.0)
        x, y = pos[0] + math.cos(a) * r, pos[1] + math.sin(a) * r
        self.cubes.append({"id": self._cube_id, "pos": [x, y, pos[2]]})
        self._cube_id += 1

    # ------------------------------------------------------------------ helpers
    def los(self, a, b) -> bool:
        return not self.world.blocked_segment(a, b, step=4.0)

    def sees(self, m: Mech, target_center, target_top=None, near_bonus=0.0) -> bool:
        eye = m.eye()
        dx, dy = target_center[0] - eye[0], target_center[1] - eye[1]
        d = math.hypot(dx, dy)
        v = self.cfg["vision"]
        near = float(v["near_range"]) + m.stats.get("near_range_bonus", 0)
        rng = float(v["range"]) + m.stats.get("vision_bonus", 0)
        if d > rng:
            return False
        if d > near:
            if abs(wrap(math.atan2(dy, dx) - m.aim[0])) > math.radians(float(v["fov_deg"]) / 2):
                return False
        if self.los(eye, target_center):
            return True
        return target_top is not None and self.los(eye, target_top)

    def emit_sound(self, kind: str, pos, src: Optional[int]):
        self.sound_events.append({"kind": kind, "pos": list(pos), "t": self.t, "src": src})

    # ------------------------------------------------------------------ damage
    def damage(self, target: Mech, amount: float, weapon: str, src: Optional[Mech], from_pos=None, effect=None):
        if not target.alive or amount <= 0:
            return
        if src is not None and src is not target and src.team == target.team:
            return  # the squad never damages itself
        rear = False
        if src is not None:
            amount *= 1.0 + float(self.cfg["cubes"]["damage_per_cube"]) * min(src.cubes, int(self.cfg["cubes"]["stat_cap"]))
            fp = from_pos or src.pos
            b = math.atan2(fp[1] - target.pos[1], fp[0] - target.pos[0])
            if abs(wrap(b - target.aim[0])) > math.radians(target.stats["front_arc_deg"] / 2):
                rear = True
                amount *= target.stats["rear_mult"]
            amount *= max(0.0, 1.0 - target.stats.get("armor", 0.0))
            if src is target:
                amount *= target.stats["self_damage_mult"]
        target.hp -= amount
        target.last_dmg_t = self.t
        target.dmg_taken[weapon] = target.dmg_taken.get(weapon, 0.0) + amount
        bearing = None
        if from_pos is not None or src is not None:
            fp = from_pos or src.pos
            bearing = math.atan2(fp[1] - target.pos[1], fp[0] - target.pos[0])
        ev = {"type": "damaged", "amount": round(amount, 2), "weapon": weapon, "bearing": bearing, "by": src.id if src else None}
        if rear:
            ev["rear"] = True
        target.events.append(ev)
        if src is not None and src is not target:
            src.last_dmg_t = self.t
            hev = {"type": "hit", "target": target.id, "amount": round(amount, 2), "weapon": weapon}
            if rear:
                hev["rear"] = True
            if effect:
                hev["effect"] = effect
            src.events.append(hev)
            self.house.on_damage(target, src, amount, weapon)
        if target.hp <= 0:
            self.kill(target, src)

    def kill(self, m: Mech, src: Optional[Mech]):
        m.alive = False
        m.hp = 0
        m.death_t = self.t
        alive = sum(1 for x in self.mechs if x.alive)
        m.place = alive + 1
        m.killed_by = "bot" if (src is not None and src.id == 0) else ("zone" if src is None else "other")
        if src is not None and src is not m:
            src.kills += 1
            src.events.append({"type": "kill", "target": m.id})
        for _ in range(m.cubes + int(self.cfg["cubes"]["death_drop_extra"])):
            self.add_cube(m.pos)
        for w in m.weapons:
            if w and w["kind"] != "gun":
                self.add_pickup(w["kind"], m.pos)
        self.emit_sound("death", m.pos, m.id)
        self.house.on_death(m, src)

    def damage_npc(self, n, amount: float, src: Optional[Mech]):
        if not n["alive"]:
            return
        if src is not None:
            amount *= 1.0 + 0.04 * min(src.cubes, 10)
            src.events.append({"type": "hit", "target": n["id"], "amount": round(amount, 2), "weapon": "gun"})
            src.last_dmg_t = self.t
            n["target"] = src.id
        n["hp"] -= amount
        if n["hp"] <= 0:
            n["alive"] = False
            for _ in range(int(self.cfg["npc"]["cubes"])):
                self.add_cube(n["pos"])

    def damage_crate(self, c, amount: float, src: Optional[Mech], weapon="gun"):
        if c["hp"] <= 0:
            return
        if src is not None:
            amount *= 1.0 + 0.04 * min(src.cubes, 10)
            src.events.append({"type": "hit", "target": c["id"], "amount": round(amount, 2), "weapon": weapon})
        c["hp"] -= amount
        if c["hp"] <= 0:
            self.add_cube(c["pos"])
            if self.rng.random() < float(self.cfg["loot"]["crate_weapon_chance"]):
                self.add_pickup(self.rng.choice(["mortar", "laser", "lightning"]), c["pos"])
            self.emit_sound("crate", c["pos"], None)

    # ------------------------------------------------------------------ weapons
    def ray_hit(self, a, d, maxd, shooter: Optional[Mech], step=2.0):
        """First mech / npc / crate / wall along a ray. Returns (kind, obj, point)."""
        best = (None, None, None, maxd)
        for m in self.mechs:
            if not m.alive or m is shooter:
                continue
            t = self._ray_cyl(a, d, m.pos, m.radius(), m.height(), maxd)
            if t is not None and t < best[3]:
                best = ("mech", m, None, t)
        for n in self.npcs:
            if not n["alive"]:
                continue
            t = self._ray_cyl(a, d, n["pos"], 1.8, 3.5, maxd)
            if t is not None and t < best[3]:
                best = ("npc", n, None, t)
        for c in self.crates:
            if c["hp"] <= 0:
                continue
            t = self._ray_cyl(a, d, c["pos"], 1.4, 2.4, maxd)
            if t is not None and t < best[3]:
                best = ("crate", c, None, t)
        # wall
        tw = self._ray_wall(a, d, best[3], step)
        if tw is not None and tw < best[3]:
            return ("wall", None, [a[0] + d[0] * tw, a[1] + d[1] * tw, a[2] + d[2] * tw], tw)
        k, o, _, t = best
        return (k, o, [a[0] + d[0] * t, a[1] + d[1] * t, a[2] + d[2] * t], t)

    def _ray_cyl(self, a, d, base, r, h, maxd):
        ox, oy = a[0] - base[0], a[1] - base[1]
        dx, dy = d[0], d[1]
        A = dx * dx + dy * dy
        if A < 1e-9:
            return None
        B = 2 * (ox * dx + oy * dy)
        C = ox * ox + oy * oy - r * r
        disc = B * B - 4 * A * C
        if disc < 0:
            return None
        sq = math.sqrt(disc)
        for t in ((-B - sq) / (2 * A), (-B + sq) / (2 * A)):
            if 0 <= t <= maxd:
                z = a[2] + d[2] * t
                if base[2] <= z <= base[2] + h:
                    return t
        return None

    def _ray_wall(self, a, d, maxd, step):
        w = self.world
        n = int(maxd / step) + 1
        for i in range(1, n + 1):
            t = min(maxd, i * step)
            x, y, z = a[0] + d[0] * t, a[1] + d[1] * t, a[2] + d[2] * t
            if z < w.ground(x, y):
                return t
            for idx in w._candidates(x, y):
                p = w.prisms[idx]
                if z < p["base"] or z > p["top"]:
                    continue
                if x < p["minx"] or x > p["maxx"] or y < p["miny"] or y > p["maxy"]:
                    continue
                if _point_in_prism_xy(x, y, p):
                    return t
        return None

    def fire_gun(self, m: Mech, w):
        st = w["stats"]
        if w["reload"] > 0 or w["cooldown"] > 0 or w["equip"] > 0:
            return
        if w["ammo"] <= 0:
            w["reload"] = st["reload"]
            return
        sp = math.radians(st["spread_deg"])
        yaw = m.aim[0] + self.rng.gauss(0, sp)
        pit = m.aim[1] + self.rng.gauss(0, sp)
        d = [math.cos(pit) * math.cos(yaw), math.cos(pit) * math.sin(yaw), math.sin(pit)]
        mz = m.muzzle()
        self.proj.append({"id": self._pid, "kind": "gun", "pos": mz, "vel": [d[0] * st["speed"], d[1] * st["speed"], d[2] * st["speed"]],
                          "src": m.id, "dmg": st["damage"], "left": st["range"], "g": 0.0})
        self._pid += 1
        w["ammo"] -= 1
        w["cooldown"] = st["cooldown"]
        if w["ammo"] <= 0:
            w["reload"] = st["reload"]
            self.emit_sound("reload", m.pos, m.id)
        self.emit_sound("gun", mz, m.id)

    def fire_mortar(self, m: Mech, w):
        st = w["stats"]
        if w["cooldown"] > 0 or w["equip"] > 0:
            return
        yaw, pit = m.aim
        d = [math.cos(pit) * math.cos(yaw), math.cos(pit) * math.sin(yaw), math.sin(pit)]
        self.proj.append({"id": self._pid, "kind": "mortar", "pos": m.muzzle(), "vel": [x * st["speed"] for x in d], "src": m.id,
                          "dmg": st["damage"], "left": 1e9, "g": st["gravity"], "ttl": st["ttl"]})
        self._pid += 1
        w["cooldown"] = st["cooldown"]
        self.emit_sound("mortar", m.pos, m.id)

    def laser_tick(self, m: Mech, w, held: bool):
        st = w["stats"]
        if self.t < m.short_until:
            w["charge"] = 0.0
            return
        if w["cooldown"] > 0 or w["equip"] > 0:
            w["charge"] = 0.0
            return
        if held:
            if w["charge"] == 0.0:
                self.emit_sound("laser_charge", m.pos, m.id)
            if w["charge"] < st["charge"]:
                w["charge"] = min(st["charge"], w["charge"] + DT)
            else:
                w["held"] += DT
                if w["held"] >= st["hold_s"]:
                    self.fire_laser(m, w)
        elif w["charge"] > 0:
            if w["charge"] >= st["min_charge"]:
                self.fire_laser(m, w)

    def fire_laser(self, m: Mech, w):
        st = w["stats"]
        frac = st["min_frac"] + (1 - st["min_frac"]) * min(1.0, w["charge"] / st["charge"])
        dmg = st["damage"] * frac
        yaw, pit = m.aim
        d = [math.cos(pit) * math.cos(yaw), math.cos(pit) * math.sin(yaw), math.sin(pit)]
        a = m.muzzle()
        k, o, pt, t = self.ray_hit(a, d, st["range"], m)
        if k == "mech":
            eff = None
            if o.has("mortar") is not None:
                dmg *= 1 + st["cookoff"]
                eff = "cookoff"
            self.damage(o, dmg, "laser", m, from_pos=a, effect=eff)
        elif k == "npc":
            self.damage_npc(o, dmg, m)
        elif k == "crate":
            self.damage_crate(o, dmg, m, "laser")
        self.beams.append({"by": m.id, "kind": "laser", "path": [a, pt], "t": self.t})
        self.emit_sound("laser", a, m.id)
        w["charge"] = 0.0
        w["held"] = 0.0
        w["cooldown"] = st["cooldown"]

    def fire_lightning(self, m: Mech, w):
        st = w["stats"]
        if w["cooldown"] > 0 or w["equip"] > 0 or m.energy < st["energy"]:
            return
        m.energy -= st["energy"]
        m.energy_t = self.t
        w["cooldown"] = st["cooldown"]
        a = m.muzzle()
        cands = []
        for o in self.mechs:
            if o is m or not o.alive:
                continue
            cands.append(("mech", o, o.center()))
        for n in self.npcs:
            if n["alive"]:
                cands.append(("npc", n, [n["pos"][0], n["pos"][1], n["pos"][2] + 1.75]))
        for c in self.crates:
            if c["hp"] > 0:
                cands.append(("crate", c, [c["pos"][0], c["pos"][1], c["pos"][2] + 1.2]))
        best = None
        for k, o, p in cands:
            d = math.dist(a, p)
            if d > st["range"]:
                continue
            if abs(wrap(math.atan2(p[1] - a[1], p[0] - a[0]) - m.aim[0])) > math.radians(st["cone_deg"] / 2):
                continue
            if best is None or d < best[3]:
                if self.los(a, p):
                    best = (k, o, p, d)
        self.emit_sound("lightning", a, m.id)
        if best is None:
            return
        path = [a, best[2]]
        dmg = st["damage"]
        hitset = set()
        cur = best
        for j in range(int(st["chain"]) + 1):
            k, o, p, _ = cur
            hitset.add(id(o))
            if k == "mech":
                self.damage(o, dmg, "lightning", m, from_pos=path[-2])
                if o.has("laser") is not None:
                    o.short_until = self.t + st["short_s"]
            elif k == "npc":
                self.damage_npc(o, dmg, m)
            else:
                self.damage_crate(o, dmg, m, "lightning")
            dmg *= st["chain_falloff"]
            nxt = None
            for k2, o2, p2 in cands:
                if id(o2) in hitset:
                    continue
                d2 = math.dist(p, p2)
                if d2 <= st["chain_range"] and (nxt is None or d2 < nxt[3]):
                    nxt = (k2, o2, p2, d2)
            if nxt is None:
                break
            path.append(nxt[2])
            cur = nxt
        self.beams.append({"by": m.id, "kind": "lightning", "path": path, "t": self.t})

    def explode(self, pos, src: Optional[Mech], dmg_direct: float, direct=None):
        st = self.cfg["weapons"]["mortar"]
        if direct is not None:
            self.damage(direct, dmg_direct, "mortar", src, from_pos=pos)
        for m in self.mechs:
            if not m.alive:
                continue
            d = math.dist(pos, m.center())
            if d > st["splash_radius"] + m.radius():
                continue
            f = max(st["splash_edge"], 1 - (1 - st["splash_edge"]) * min(1.0, d / st["splash_radius"]))
            if not self.los(pos, m.center()):
                continue
            self.damage(m, st["splash"] * f, "mortar", src, from_pos=pos)
            away = math.atan2(m.pos[1] - pos[1], m.pos[0] - pos[0])
            m.vel[0] += math.cos(away) * st["knock"] * f
            m.vel[1] += math.sin(away) * st["knock"] * f
            m.vel[2] += st["knock_up"] * f
            m.energy = max(0.0, m.energy - st["drain"] * f)
            m.grounded = False
        for n in self.npcs:
            if n["alive"] and math.dist(pos, n["pos"]) < st["splash_radius"]:
                self.damage_npc(n, st["splash"] * 0.6, src)
        for c in self.crates:
            if c["hp"] > 0 and math.dist(pos, c["pos"]) < st["splash_radius"]:
                self.damage_crate(c, st["splash"] * 0.6, src, "mortar")
        self.emit_sound("explosion", pos, src.id if src else None)

    def step_projectiles(self):
        keep = []
        for p in self.proj:
            src = self.mechs[p["src"]] if isinstance(p["src"], int) and p["src"] < 16 else None
            v = p["vel"]
            if p["g"]:
                v[2] -= p["g"] * DT
            sp = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
            dist = sp * DT
            d = [v[0] / sp, v[1] / sp, v[2] / sp]
            k, o, pt, t = self.ray_hit(p["pos"], d, min(dist, p["left"]), src, step=2.0)
            if p["kind"] == "npc":
                # NPC bullets hit mechs only
                if k == "mech" and o.team == "bot":
                    self.damage(o, p["dmg"], "npc", None, from_pos=p["pos"])
                    o.events[-1]["by"] = p["owner"]
                    continue
                if k in ("wall",):
                    continue
                k = None
            if k is not None:
                if p["kind"] == "mortar":
                    self.explode(pt, src, p["dmg"], o if k == "mech" else None)
                    continue
                if k == "mech":
                    self.damage(o, p["dmg"], "gun", src, from_pos=p["pos"])
                elif k == "npc":
                    self.damage_npc(o, p["dmg"], src)
                elif k == "crate":
                    self.damage_crate(o, p["dmg"], src)
                continue
            p["pos"] = [p["pos"][0] + v[0] * DT, p["pos"][1] + v[1] * DT, p["pos"][2] + v[2] * DT]
            p["left"] -= dist
            if "ttl" in p:
                p["ttl"] -= DT
                if p["ttl"] <= 0:
                    continue
            if p["left"] <= 0:
                continue
            keep.append(p)
        self.proj = keep

    # ------------------------------------------------------------------ movement
    def step_mech(self, m: Mech):
        st = m.stats
        cmd = m.cmd
        # aim slew
        ty, tp = cmd["aim"]
        tp = max(st["min_pitch"], min(st["max_pitch"], tp))
        dy = wrap(ty - m.aim[0])
        mx = st["turn_rate"] * DT
        m.aim[0] = wrap(m.aim[0] + max(-mx, min(mx, dy)))
        mp = st["pitch_rate"] * DT
        m.aim[1] += max(-mp, min(mp, tp - m.aim[1]))
        mv = cmd["move"]
        L = math.hypot(mv[0], mv[1])
        if L > 1:
            mv = [mv[0] / L, mv[1] / L]
            L = 1.0
        charging = any(w and w["kind"] == "laser" and w.get("charge", 0) > 0 for w in m.weapons)
        boosting = False
        speed = st["walk_speed"]
        if cmd["boost"] and m.grounded and L > 0.1 and m.energy > 0:
            speed = st["boost_speed"]
            m.energy -= st["boost_drain"] * DT
            m.energy_t = self.t
            boosting = True
        if charging:
            speed *= st["charge_move_mult"]
        tvx, tvy = mv[0] * speed, mv[1] * speed
        acc = (st["ground_accel"] if m.grounded else st["air_accel"]) * DT
        for i, tv in ((0, tvx), (1, tvy)):
            dv = tv - m.vel[i]
            if m.grounded or L > 0.05:
                m.vel[i] += max(-acc, min(acc, dv))
        if cmd["jump"] and m.grounded:
            m.vel[2] = st["jump_speed"]
            m.grounded = False
        if cmd["boost"] and not m.grounded and m.energy > 0:
            m.vel[2] = min(st["max_rise_speed"], m.vel[2] + st["jet_accel"] * DT)
            m.energy -= st["jet_drain"] * DT
            m.energy_t = self.t
            boosting = True
            if self.rng.random() < 0.05:
                self.emit_sound("jet", m.pos, m.id)
        m.energy = max(0.0, m.energy)
        if self.t - m.energy_t > st["energy_regen_delay"]:
            m.energy = min(m.max_energy, m.energy + st["energy_regen"] * DT)
        m.vel[2] -= st["gravity"] * DT
        # horizontal move with wall slide
        x, y, z = m.pos
        h = m.height()
        step = st["step_up"]
        nx, ny = x + m.vel[0] * DT, y + m.vel[1] * DT
        nx = max(-510.0, min(553.0, nx))
        ny = max(-331.0, min(386.0, ny))
        r = m.radius()

        def free(px, py):
            for ox, oy in ((0, 0), (r, 0), (-r, 0), (0, r), (0, -r)):
                if self.blocked_at(px + ox, py + oy, z, h, step):
                    return False
            g = self.world.ground(px, py)
            if g > z + step and m.grounded:
                return False
            return True

        if not free(nx, ny):
            if free(nx, y):
                ny = y
                m.vel[1] = 0.0
            elif free(x, ny):
                nx = x
                m.vel[0] = 0.0
            else:
                nx, ny = x, y
                m.vel[0] = m.vel[1] = 0.0
        nz = z + m.vel[2] * DT
        sup = self.support(nx, ny, max(z, nz), step)
        if nz <= sup:
            nz = sup
            if m.vel[2] < 0:
                m.vel[2] = 0.0
            m.grounded = True
        else:
            m.grounded = nz - sup < 0.05
        m.pos = [nx, ny, nz]
        # footsteps
        hs = math.hypot(m.vel[0], m.vel[1])
        if m.grounded and hs > self.cfg["sound"]["step_speed"]:
            m.step_acc += DT
            if m.step_acc >= self.cfg["sound"]["step_every"]:
                m.step_acc = 0.0
                self.emit_sound("boost" if boosting else "step", m.pos, m.id)

    def fire_tick(self, m: Mech):
        for i, w in enumerate(m.weapons):
            if not w:
                continue
            w["cooldown"] = max(0.0, w["cooldown"] - DT)
            w["equip"] = max(0.0, w["equip"] - DT)
            if w["kind"] == "gun" and w["reload"] > 0:
                w["reload"] = max(0.0, w["reload"] - DT)
                if w["reload"] == 0:
                    w["ammo"] = int(w["stats"]["mag"])
            held = bool(m.cmd["fire"][i])
            k = w["kind"]
            if k == "gun":
                if m.cmd.get("reload") and w["ammo"] < w["stats"]["mag"] and w["reload"] == 0:
                    w["reload"] = w["stats"]["reload"]
                if held:
                    self.fire_gun(m, w)
            elif k == "laser":
                self.laser_tick(m, w, held)
            elif k == "lightning":
                if held:
                    self.fire_lightning(m, w)
            elif k == "mortar":
                if held:
                    self.fire_mortar(m, w)

    # ------------------------------------------------------------------ world systems
    def step_npcs(self):
        nc = self.cfg["npc"]
        for n in self.npcs:
            if not n["alive"]:
                continue
            tgt = None
            if n["target"] is not None:
                tm = self.mechs[n["target"]]
                if not tm.alive or math.dist(tm.pos[:2], n["pos"][:2]) > nc["deaggro_range"] or math.dist(n["pos"][:2], n["home"][:2]) > nc["chase_leash"]:
                    n["target"] = None
                else:
                    tgt = tm
            if tgt is None and self.tick % 10 == 0 and math.dist(n["pos"][:2], n["home"][:2]) <= nc["leash"]:
                best = None
                for m in self.mechs:
                    if not m.alive or m.team != "bot":
                        continue
                    d = math.dist(m.pos[:2], n["pos"][:2])
                    if d <= nc["aggro_range"] and (best is None or d < best[0]):
                        if self.los([n["pos"][0], n["pos"][1], n["pos"][2] + 3], m.center()):
                            best = (d, m)
                if best:
                    tgt = best[1]
                    n["target"] = tgt.id
            # move
            if tgt is not None:
                goal = tgt.pos
            else:
                if math.dist(n["pos"][:2], n["wander"][:2]) < 2 or self.rng.random() < 0.005:
                    a = self.rng.uniform(-math.pi, math.pi)
                    n["wander"] = [n["home"][0] + math.cos(a) * nc["leash"] * 0.8, n["home"][1] + math.sin(a) * nc["leash"] * 0.8]
                goal = n["wander"]
            dx, dy = goal[0] - n["pos"][0], goal[1] - n["pos"][1]
            d = math.hypot(dx, dy)
            if d > (12 if tgt else 1):
                vx, vy = dx / d * nc["speed"], dy / d * nc["speed"]
                nx, ny = n["pos"][0] + vx * DT, n["pos"][1] + vy * DT
                if not self.blocked_at(nx, ny, n["pos"][2], 3.5, 1.2):
                    g = self.support(nx, ny, n["pos"][2], 1.2)
                    n["pos"] = [nx, ny, g]
                    n["vel"] = [vx, vy, 0.0]
                n["yaw"] = math.atan2(dy, dx)
            else:
                n["vel"] = [0.0, 0.0, 0.0]
            n["cd"] = max(0.0, n["cd"] - DT)
            if tgt is not None and n["cd"] <= 0 and d < nc["deaggro_range"]:
                a = [n["pos"][0], n["pos"][1], n["pos"][2] + 3.0]
                c = tgt.center()
                if self.los(a, c):
                    dist = math.dist(a, c)
                    tt = dist / nc["projectile_speed"]
                    aimp = [c[0] + tgt.vel[0] * tt, c[1] + tgt.vel[1] * tt, c[2]]
                    yaw = math.atan2(aimp[1] - a[1], aimp[0] - a[0]) + self.rng.gauss(0, math.radians(nc["spread_deg"]))
                    pit = math.atan2(aimp[2] - a[2], math.hypot(aimp[0] - a[0], aimp[1] - a[1])) + self.rng.gauss(0, math.radians(nc["spread_deg"]))
                    v = nc["projectile_speed"]
                    self.proj.append({"id": self._pid, "kind": "npc", "pos": a, "vel": [math.cos(pit) * math.cos(yaw) * v, math.cos(pit) * math.sin(yaw) * v, math.sin(pit) * v],
                                      "src": None, "owner": n["id"], "dmg": nc["damage"], "left": 200.0, "g": 0.0})
                    self._pid += 1
                    n["cd"] = nc["cooldown"]
                    self.emit_sound("npc_gun", a, None)

    def step_pickups_cubes(self):
        cr = self.cfg["cubes"]
        keep = []
        for c in self.cubes:
            best = None
            for m in self.mechs:
                if not m.alive:
                    continue
                d = math.hypot(m.pos[0] - c["pos"][0], m.pos[1] - c["pos"][1])
                if d <= cr["pickup_radius"] and abs(m.pos[2] - c["pos"][2]) <= 4.0 and (best is None or d < best[0]):
                    best = (d, m)
            if best is None:
                keep.append(c)
                continue
            m = best[1]
            self.give_cube(m)
            m.events.append({"type": "pickup", "cubes": m.cubes})
        self.cubes = keep

    def give_cube(self, m: Mech, n: int = 1):
        cr = self.cfg["cubes"]
        for _ in range(n):
            m.cubes += 1
            if m.cubes <= cr["stat_cap"]:
                old = m.max_hp
                m.max_hp = m.stats["hp"] * (1 + cr["hp_per_cube"] * min(m.cubes, cr["stat_cap"]))
                m.hp += m.max_hp - old
            if m.cubes in cr["upgrade_thresholds"]:
                self.make_offer(m)

    def make_offer(self, m: Mech):
        ups = self.cfg["upgrades"]
        held = {w["kind"] for w in m.weapons if w}
        cands = [u for u in ups if m.upcount.get(u["id"], 0) < u["max"] and (not u.get("requires") or u["requires"] in held)]
        self.rng.shuffle(cands)
        ch = cands[:3]
        if not ch:
            return
        m.offer_id += 1
        m.offers.append({"id": m.offer_id, "expires": self.t + 5.0, "choices": [{"id": u["id"], "name": u["name"], "desc": u["desc"]} for u in ch], "_u": ch})

    def apply_upgrade(self, m: Mech, u):
        m.upcount[u["id"]] = m.upcount.get(u["id"], 0) + 1
        m.ups.append(u["id"])
        for e in u["effects"]:
            path = e["path"].split(".")
            if path[0] == "mech":
                k = path[1]
                if "mul" in e:
                    m.stats[k] = m.stats[k] * e["mul"]
                else:
                    m.stats[k] = m.stats[k] + e["add"]
                if k == "hp":
                    old = m.max_hp
                    m.max_hp = m.stats["hp"] * (1 + 0.04 * min(m.cubes, 10))
                    m.hp += m.max_hp - old
                if k == "energy":
                    m.max_energy = m.stats["energy"]
            elif path[0] == "weapons":
                kind, k = path[1], path[2]
                mul = m.wstats_mul.setdefault(kind, {})
                mul[k] = (mul.get(k, 1.0) * e["mul"]) if "mul" in e else (mul.get(k, 0.0) + e["add"])
                for w in m.weapons:
                    if w and w["kind"] == kind:
                        self._apply_wstats(m, w)
        m.events.append({"type": "upgrade", "id": u["id"]})

    def _apply_wstats(self, m: Mech, w):
        base = dict(self.cfg["weapons"][w["kind"]])
        for k, v in m.wstats_mul.get(w["kind"], {}).items():
            if k in ("mag", "chain", "pierce"):
                base[k] = base[k] + v
            else:
                base[k] = base[k] * v
        w["stats"] = base

    def handle_take(self, m: Mech, pid, drop_slot):
        for p in self.pickups:
            if p["id"] != pid:
                continue
            if math.hypot(p["pos"][0] - m.pos[0], p["pos"][1] - m.pos[1]) > self.cfg["loot"]["pickup_radius"] or abs(p["pos"][2] - m.pos[2]) > 4:
                m.events.append({"type": "take_failed", "id": pid, "reason": "range"})
                return
            if m.has(p["kind"]) is not None:
                m.events.append({"type": "take_failed", "id": pid, "reason": "have"})
                return
            slot = None
            if m.weapons[1] is None:
                slot = 1
            elif m.weapons[0] is None:
                slot = 0
            elif drop_slot in (0, 1):
                slot = drop_slot
                old = m.weapons[slot]
                np_ = self.add_pickup(old["kind"], m.pos)
                m.events.append({"type": "dropped", "id": np_["id"], "kind": old["kind"], "slot": slot})
            if slot is None:
                m.events.append({"type": "take_failed", "id": pid, "reason": "full"})
                return
            w = new_weapon(p["kind"], self.cfg)
            w["equip"] = max(self.cfg["loot"]["equip_s"], w["stats"]["cooldown"])
            self._apply_wstats(m, w)
            m.weapons[slot] = w
            self.pickups.remove(p)
            m.events.append({"type": "took", "id": pid, "kind": p["kind"], "slot": slot})
            return
        m.events.append({"type": "take_failed", "id": pid, "reason": "gone"})

    def step_zone_regen(self):
        z = self.zone()
        for m in self.mechs:
            if not m.alive:
                continue
            inz = math.hypot(m.pos[0] - z["center"][0], m.pos[1] - z["center"][1]) <= z["radius"]
            m.in_zone = inz
            if not inz and m.team == "house" and self.house_zone_immune:
                inz = True
            if not inz:
                m.hp -= z["dps"] * DT
                m.zone_dmg += z["dps"] * DT
                m.last_dmg_t = self.t
                if self.tick % 2 == 0:
                    m.events.append({"type": "damaged", "amount": round(z["dps"] * DT * 2, 2), "weapon": "zone", "bearing": None, "by": None})
                if m.hp <= 0:
                    self.kill(m, None)
            elif self.t - m.last_dmg_t >= m.stats["regen_delay"] and m.hp < m.max_hp:
                m.hp = min(m.max_hp, m.hp + m.stats["regen_per_s"] * DT)

    def step_drops(self):
        dc = self.cfg["drops"]
        for d in self.drops:
            if d["taken"] or self.t < d["call"]:
                continue
            if d["pos"] is None:
                z = self.zone()
                nc, nr = z["next_center"], z["next_radius"]
                d["pos"] = self.random_spot(0.0, max(5.0, nr * dc["spread"]), center=nc)
                self.emit_sound("drop", d["pos"], None)
            if self.t < d["land"]:
                continue
            inside = [m for m in self.mechs if m.alive and math.hypot(m.pos[0] - d["pos"][0], m.pos[1] - d["pos"][1]) <= dc["radius"]]
            if len(inside) == 1:
                m = inside[0]
                if d["holder"] != m.id:
                    d["holder"] = m.id
                    d["progress"] = 0.0
                d["progress"] += DT
                if d["progress"] >= dc["capture_s"]:
                    d["taken"] = True
                    self.give_cube(m, int(dc["cubes"]))
                    m.hp = m.max_hp
                    m.energy = m.max_energy
                    m.events.append({"type": "drop", "id": d["id"], "cubes": m.cubes})
            elif len(inside) == 0:
                d["holder"] = None
                d["progress"] = 0.0

    # ------------------------------------------------------------------ observation for slot 0
    def observe(self, m: Mech) -> Dict[str, Any]:
        t = self.t
        mechs = []
        for o in self.mechs:
            if o is m or not o.alive:
                continue
            vis = self.sees(m, o.center(), [o.pos[0], o.pos[1], o.pos[2] + o.height()])
            if vis:
                m.seen_until[o.id] = t + self.cfg["vision"]["memory_s"]
            if vis or m.seen_until.get(o.id, -1) > t:
                mechs.append({"id": o.id, "kind": "mech", "pos": [round(v, 2) for v in o.pos], "vel": [round(v, 2) for v in o.vel],
                              "aim": [round(o.aim[0], 3), round(o.aim[1], 3)], "hp": round(o.hp, 2), "max_hp": round(o.max_hp, 2),
                              "cubes": o.cubes, "weapons": [w["kind"] for w in o.weapons if w],
                              "charging": any(w and w["kind"] == "laser" and w.get("charge", 0) > 0 for w in o.weapons)})
        for n in self.npcs:
            if not n["alive"]:
                continue
            c = [n["pos"][0], n["pos"][1], n["pos"][2] + 1.75]
            vis = self.sees(m, c)
            if vis:
                m.seen_until[n["id"]] = t + 5
            if vis or m.seen_until.get(n["id"], -1) > t:
                mechs.append({"id": n["id"], "kind": "npc", "pos": [round(v, 2) for v in n["pos"]], "vel": list(n["vel"]), "aim": [n["yaw"], 0.0],
                              "hp": round(n["hp"], 2), "max_hp": n["max_hp"]})
        vis_static = self._vis_static(m)
        sounds = []
        hear = m.stats.get("hearing", 1.0)
        sr = self.cfg["sound"]
        for s in self.sound_events:
            if s["src"] == m.id or s["t"] <= t - 0.1 - 1e-6:
                continue
            d = math.hypot(s["pos"][0] - m.pos[0], s["pos"][1] - m.pos[1])
            if d > sr["range"].get(s["kind"], 0):
                continue
            b = math.atan2(s["pos"][1] - m.pos[1], s["pos"][0] - m.pos[0]) + self.rng.gauss(0, math.radians(sr["bearing_noise_deg"]) * hear)
            sounds.append({"kind": s["kind"], "bearing": round(wrap(b), 3), "dist": "near" if d < sr["near"] else "mid" if d < sr["mid"] else "far",
                           "age": round(t - s["t"], 2)})
        projs = []
        for p in self.proj:
            if p["src"] == m.id:
                continue
            if math.dist(p["pos"], m.pos) < 200:
                projs.append({"id": p["id"], "kind": p["kind"], "pos": [round(v, 2) for v in p["pos"]], "vel": [round(v, 2) for v in p["vel"]]})
        beams = [{"by": b["by"], "kind": b["kind"], "path": [[round(v, 2) for v in q] for q in b["path"]], "age": round(t - b["t"], 2)}
                 for b in self.beams if b["by"] != m.id and t - b["t"] <= 0.1 + 1e-6 and math.dist(b["path"][0], m.pos) < 200]
        z = self.zone()
        inz = math.hypot(m.pos[0] - z["center"][0], m.pos[1] - z["center"][1]) <= z["radius"]
        weapons = []
        for w in m.weapons:
            if not w:
                weapons.append(None)
                continue
            d = {"kind": w["kind"], "cooldown": round(max(w["cooldown"], w["equip"]), 3), "stats": dict(w["stats"])}
            if w["kind"] == "gun":
                d["ammo"] = w["ammo"]
                d["reload"] = round(w["reload"], 3)
            if w["kind"] == "laser":
                d["charge"] = round(w["charge"], 3)
            weapons.append(d)
        stats = dict(m.stats)
        stats["radius"] = m.radius()
        stats["height"] = m.height()
        stats["eye_height"] = m.stats["eye_height"] * m.scale
        stats["muzzle_height"] = m.stats["muzzle_height"] * m.scale
        drops = []
        for d in self.drops:
            if d["taken"] or t < d["call"] or d["pos"] is None:
                continue
            drops.append({"id": d["id"], "pos": [round(v, 2) for v in d["pos"]], "radius": self.cfg["drops"]["radius"], "lands_in": round(max(0.0, d["land"] - t), 2),
                          "capture_s": self.cfg["drops"]["capture_s"], "progress": round(d["progress"], 2), "holder": d["holder"]})
        offer = None
        if m.offers:
            o = m.offers[0]
            offer = {"id": o["id"], "expires": o["expires"], "choices": o["choices"]}
        obs = {"type": "obs", "tick": self.tick, "t": round(t, 2), "alive": sum(1 for x in self.mechs if x.alive),
               "self": {"id": m.id, "pos": [round(v, 2) for v in m.pos], "vel": [round(v, 2) for v in m.vel], "aim": [round(m.aim[0], 3), round(m.aim[1], 3)],
                        "hp": round(m.hp, 2), "max_hp": round(m.max_hp, 2), "energy": round(m.energy, 2), "max_energy": m.max_energy,
                        "grounded": m.grounded, "cubes": m.cubes, "upgrades": list(m.ups), "weapons": weapons, "in_zone": inz, "stats": stats},
               "mechs": mechs, "projectiles": projs, "crates": vis_static["crates"], "cubes": vis_static["cubes"], "pickups": vis_static["pickups"],
               "sounds": sounds, "beams": beams, "events": m.events, "zone": z, "offer": offer, "drops": drops}
        m.events = []
        return obs

    def _vis_static(self, m: Mech) -> Dict[str, List]:
        # Static things are re-checked every 0.5 s (vision cache) to keep LOS cost down.
        key = self.tick // 10
        cache = getattr(m, "_vcache", None)
        if cache is None or cache[0] != key or cache[3] != len(self.cubes) or cache[4] != len(self.pickups):
            eye = m.eye()
            v = self.cfg["vision"]
            near = v["near_range"] + m.stats.get("near_range_bonus", 0)
            rng = v["range"] + m.stats.get("vision_bonus", 0)
            half = math.radians(v["fov_deg"] / 2)

            def ok(p, hgt):
                d = math.hypot(p[0] - eye[0], p[1] - eye[1])
                if d > rng:
                    return False
                if d > near and abs(wrap(math.atan2(p[1] - eye[1], p[0] - eye[0]) - m.aim[0])) > half + 0.2:
                    return False
                return self.los(eye, [p[0], p[1], p[2] + hgt])

            cr = [c["id"] for c in self.crates if c["hp"] > 0 and ok(c["pos"], 2.0)]
            cu = [c["id"] for c in self.cubes if ok(c["pos"], 0.5)]
            pk = [p["id"] for p in self.pickups if ok(p["pos"], 0.5)]
            m._vcache = cache = (key, set(cr) | set(cu) | set(pk), None, len(self.cubes), len(self.pickups))
        ids = cache[1]
        return {"crates": [{"id": c["id"], "pos": [round(v, 2) for v in c["pos"]], "hp": round(c["hp"], 1)} for c in self.crates if c["hp"] > 0 and c["id"] in ids],
                "cubes": [{"id": c["id"], "pos": [round(v, 2) for v in c["pos"]]} for c in self.cubes if c["id"] in ids],
                "pickups": [{"id": p["id"], "kind": p["kind"], "pos": [round(v, 2) for v in p["pos"]]} for p in self.pickups if p["id"] in ids]}

    def apply_action(self, m: Mech, a: Dict[str, Any]):
        c = m.cmd
        c["move"] = list(a.get("move") or [0.0, 0.0])
        c["boost"] = bool(a.get("boost"))
        c["jump"] = bool(a.get("jump"))
        if a.get("aim") is not None:
            c["aim"] = list(a["aim"])
        f = a.get("fire") or [False, False]
        c["fire"] = [bool(f[0]), bool(f[1]) if len(f) > 1 else False]
        c["reload"] = bool(a.get("reload"))
        if a.get("pick") is not None and m.offers:
            o = m.offers.pop(0)
            i = int(a["pick"])
            if 0 <= i < len(o["_u"]):
                self.apply_upgrade(m, o["_u"][i])
        if a.get("take") is not None:
            self.handle_take(m, a["take"], a.get("drop"))
        elif a.get("drop") in (0, 1) and m.weapons[a["drop"]]:
            old = m.weapons[a["drop"]]
            m.weapons[a["drop"]] = None
            self.add_pickup(old["kind"], m.pos)

    # ------------------------------------------------------------------ main loop
    def run(self, max_t: Optional[float] = None) -> Dict[str, Any]:
        dur = float(self.cfg["match"]["duration_s"])
        if max_t is not None:
            dur = min(dur, max_t)
        me = self.mechs[0]
        bot_err = 0
        while self.t < dur and me.alive:
            if self.tick % 2 == 0:
                # offers time out
                for m in self.mechs:
                    if m.offers and self.t >= m.offers[0]["expires"]:
                        o = m.offers.pop(0)
                        self.apply_upgrade(m, o["_u"][0])
                obs = self.observe(me)
                try:
                    a = self.bot.act(obs) or {}
                except Exception:
                    bot_err += 1
                    a = {}
                self.apply_action(me, a)
                self.house.decide(self)
                self.sound_events = [s for s in self.sound_events if s["t"] > self.t - 0.15]
                self.beams = [b for b in self.beams if b["t"] > self.t - 0.15]
            for m in self.mechs:
                if m.alive:
                    self.step_mech(m)
                    self.fire_tick(m)
            self.step_projectiles()
            self.step_npcs()
            self.step_pickups_cubes()
            self.step_zone_regen()
            self.step_drops()
            self.tick += 1
            self.t = self.tick * DT
            alive = [m for m in self.mechs if m.alive]
            if len(alive) <= 1:
                break
        if me.alive:
            # clock ran out: rank survivors by HP
            alive = sorted([m for m in self.mechs if m.alive], key=lambda m: -m.hp)
            me.place = 1 + alive.index(me)
        return {"seed": self.seed, "place": me.place, "score": 16 - me.place, "kills": me.kills, "t": round(me.death_t or self.t, 1),
                "cubes": me.cubes, "ups": me.ups, "zone_dmg": round(me.zone_dmg), "dmg_taken": {k: round(v) for k, v in me.dmg_taken.items()},
                "bot_err": bot_err, "weapons": [w["kind"] for w in me.weapons if w],
                "house_dead": sum(1 for m in self.mechs[1:] if not m.alive),
                "house_dead_other": sum(1 for m in self.mechs[1:] if not m.alive and getattr(m, "killed_by", "") != "bot")}
