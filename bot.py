"""Farm-fight-heal bot (try/rewrite).

One simple loop, in priority order each decision:

  ESCAPE  out of the zone: get back in (jets over whatever traps us).
  ZONE    the next circle will close on us: walk into it, shooting what we see.
  DRONE   a drone is shooting us and no mech is: kill it (350 HP, 2 cubes).
  HEAL    low HP: break line of sight, face the threat, stop shooting once safe, regen.
  FIGHT   a mech we can shoot (or one hitting us): fight the nearest, from a roof if on one.
  FARM    cubes, kill sites, drones, crates, weapons: the best value per metre.
  ROOF    nothing to farm: climb a roof inside the next circle and hold it (peek camp).

What it carries over on purpose (all from real data):
  * cubes are the main lever (+4% HP and damage each, upgrades at 1/3/6/10/15/...);
    farm greedily, drones included, and loot kill sites;
  * house bots shoot the nearest mech and hit badly past ~80 m: fight the nearest target
    and hold 55-125 m instead of closing to their 46 m median;
  * the winner healed ~7k HP a match vs our ~660: back off to heal when low, and rest
    (no shooting, which resets regen) when hurt and nobody is in view;
  * roofs give a better exchange than the ground: camp roofs when idle, and fight from
    the roof instead of jumping down to chase;
  * zone was 18% of damage taken: keep the stuck-proof zone escape and move early;
  * greedy upgrade order (armor first) beat sustain-first;
  * no FFA detector, no disengage/third/gatekeep/ambush/laser-dodge modes.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Optional

import mechfight as mf
from combat import Combat
from cover import CoverBook
import levers
from memory import Memory
from nav import GridPlanner, Navigator
from world import World

UPGRADE_PRIORITY = [
    "armor",
    "plating",
    "nanites",
    "laser_damage",
    "laser_charge",
    "mortar_reload",
    "gun_damage",
    "gun_rate",
    "jets",
    "capacitor",
    "sensors",
]

WEAPON_RANK = {"laser": 3, "mortar": 2, "lightning": 1}

# Tunables (one place, so variants are one-line changes).
FARM_EARLY_S = 90.0  # before this, search the map for farm targets instead of camping
CUBE_GOAL = 45  # last upgrade threshold; keep collecting until here
RETREAT_HP = 0.40  # back off to heal below this (in a fight)
REST_HP = 0.70  # rest (stop shooting) below this when nobody is in view
HEAL_DONE_HP = 0.90
BAND_LO = 55.0  # fight band: back off inside this
BAND_HI = 125.0  # ...and close in beyond this
CHASE_NO_LOS = 100.0  # chase a mech we can't shoot only this close
ENGAGE_MAX = 230.0  # gun range

# Local experiments only: RW_TUNE='{"RETREAT_HP": 0.3}' overrides the tunables above.
if os.environ.get("RW_TUNE"):
    import json as _json

    globals().update(_json.loads(os.environ["RW_TUNE"]))


def _angdiff(a: float, b: float) -> float:
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def _has_second(me: Dict[str, Any]) -> Optional[str]:
    for w in me.get("weapons") or []:
        if w and w.get("kind") in ("laser", "mortar", "lightning"):
            return w["kind"]
    return None


def _slot_of(me: Dict[str, Any], kind: str) -> Optional[int]:
    for i, w in enumerate(me.get("weapons") or []):
        if w and w.get("kind") == kind:
            return i
    return None


def _bearing_to(a: List[float], b: List[float]) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _d2(a: List[float], b: List[float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Bot:
    name = f"lh-{levers.LABEL}"

    def __init__(self, hello: mf.Hello):
        t0 = time.perf_counter()
        self.cfg = hello["config"]
        self.slot = int(hello["slot"])
        here = os.path.dirname(os.path.abspath(__file__))
        self.world = World(hello["map"]["dir"])
        self.cover = CoverBook(os.path.join(here, "data"))
        self.mem = Memory()
        self.mem.seed(int(hello.get("seed") or 1))
        self.nav = Navigator(self.world, self.mem)
        self.planner = GridPlanner(self.world)
        self._path: Optional[List[List[float]]] = None
        self._path_goal: Optional[List[float]] = None
        self._path_until = -1.0
        self._prog_goal: Optional[List[float]] = None
        self._prog_t = -1.0
        self._prog_d = 0.0
        self._prog_last = -99.0
        self.combat = Combat(self.world, self.cfg)
        cfg = self.cfg
        self.loot_r = float(cfg["loot"]["pickup_radius"])
        self.cube_r = float(cfg["cubes"]["pickup_radius"])
        self.near_range = float((cfg.get("vision") or {}).get("near_range", 45.0))
        self.step_up = float((cfg.get("mech") or {}).get("step_up", 1.2))
        self.walk_speed = float((cfg.get("mech") or {}).get("walk_speed", 11.7))
        self.memory_s = float((cfg.get("vision") or {}).get("memory_s", 5.0))
        lc = (cfg.get("weapons") or {}).get("laser") or {}
        self.laser_charge_s = float(lc.get("charge", 0.75))
        self.lightning_range = float(((cfg.get("weapons") or {}).get("lightning") or {}).get("range", 45.0))
        mc = (cfg.get("weapons") or {}).get("mortar") or {}
        v, g = float(mc.get("speed", 72)), float(mc.get("gravity", 22))
        self.mortar_max = (v * v / g) if g > 0 else 235.0
        self.npc_h = float((cfg.get("npc") or {}).get("height", 3.5))
        self.mech_h = float((cfg.get("mech") or {}).get("height", 9.0))
        self.npc_aggro = float((cfg.get("npc") or {}).get("aggro_range", 45.0))
        self.drop_avoid = 40.0
        self.mem.strafe_sign = 1.0 if self.mem.rand() > 0.5 else -1.0
        self.mode = "FARM"
        self.mode_t = 0.0
        # drones that hit us, by id -> last time
        self._npc_hit_t: Dict[int, float] = {}
        self._npc_hit_last_t = -1e9
        self._npc_hit_bearing: Optional[float] = None
        self._mech_hit_last_t = -1e9
        # remembered crates: id -> {pos, last_seen_t}
        self.crates: Dict[int, Dict[str, Any]] = {}
        # farm target hysteresis / give-up blacklist
        self._farm: Optional[Dict[str, Any]] = None
        self._farm_key: Any = None
        self._farm_since = 0.0
        self._farm_bl: Dict[Any, float] = {}
        self._search_wp: Optional[List[float]] = None
        self._search_until = -1.0
        # fight target stickiness
        self._target_id: Optional[int] = None
        # heal cover cache
        self._cover_pt: Optional[List[float]] = None
        self._cover_t = -1e9
        # zone escape progress tracking (481fed0)
        self._esc_ref_t = -1.0
        self._esc_ref_d = 0.0
        self._esc_jet_until = -1.0
        self._esc_last_t = -99.0
        mf.log(
            f"init {(time.perf_counter() - t0) * 1000:.0f}ms roofs={len(self.cover.roofs)} "
            f"cover={self.cover.cover_ok} variant={levers.LABEL}"
        )

    # ------------------------------------------------------------------ entry
    def act(self, obs: mf.Observation) -> mf.Action:
        t_act0 = time.perf_counter()
        try:
            return self._act(obs, t_act0)
        except Exception:
            mf.log(f"act error:\n{__import__('traceback').format_exc()}")
            aim = obs["self"]["aim"]
            if self.mem.last_threat_bearing is not None:
                aim = [self.mem.last_threat_bearing, aim[1]]
            return {"move": [0.0, 0.0], "aim": aim, "fire": [True, False], "boost": False}

    def _act(self, obs: mf.Observation, t_act0: float) -> mf.Action:
        me = obs["self"]
        t = float(obs["t"])
        self.combat.begin_tick(float(obs["tick"]))
        self.mem.world_on_roof = self.world.on_roof(me["pos"])
        self.mem.update(obs, near_range=self.near_range, world=self.world)
        self._track(obs, t)

        act: Dict[str, Any] = {"move": [0.0, 0.0], "boost": False, "jump": False, "fire": [False, False]}
        pick = self._pick_upgrade(obs.get("offer"))
        if pick is not None:
            act["pick"] = pick

        mode = self._select_mode(obs)
        if mode != self.mode:
            self.mode, self.mode_t = mode, t
        self.mem.set_mode(mode, t)
        mf.draw.label(f"{mode}/{_has_second(me) or 'gun'} hp={me['hp']:.0f} c={me.get('cubes', 0)}")

        if mode == "ESCAPE":
            self._do_escape(obs, act)
        elif mode == "ZONE":
            self._do_zone(obs, act)
        elif mode == "DRONE":
            self._do_drone(obs, act)
        elif mode == "HEAL":
            self._do_heal(obs, act)
        elif mode == "FIGHT":
            self._do_fight(obs, act)
        elif mode == "FARM":
            self._do_farm(obs, act)
        else:
            self._do_roof(obs, act)

        if mode in ("FARM", "ROOF", "HEAL") and not self.mem.world_on_roof and not act.get("jump"):
            self._avoid(obs, act)
        self._laser_charge_hold(obs, act)

        ms = (time.perf_counter() - t_act0) * 1000
        self.mem.max_act_ms = max(self.mem.max_act_ms, ms)
        if ms > 25:
            mf.log(f"slow act {ms:.1f}ms mode={mode}")
        return act  # type: ignore[return-value]

    # ------------------------------------------------------------- bookkeeping
    def _track(self, obs: mf.Observation, t: float) -> None:
        for e in obs.get("events") or []:
            if e.get("type") != "damaged":
                continue
            w = e.get("weapon")
            if w == "npc":
                self._npc_hit_last_t = t
                self._npc_hit_bearing = e.get("bearing")
                if e.get("by") is not None:
                    self._npc_hit_t[int(e["by"])] = t
            elif w not in (None, "zone"):
                self._mech_hit_last_t = t
        me_pos = obs["self"]["pos"]
        seen = set()
        for c in obs.get("crates") or []:
            cid = int(c["id"])
            seen.add(cid)
            self.crates[cid] = {"id": cid, "pos": list(c["pos"]), "last_seen_t": t}
        for cid in list(self.crates):
            if cid in seen:
                continue
            c = self.crates[cid]
            if _d2(c["pos"], me_pos) < 35.0 or t - c["last_seen_t"] > 120.0:
                del self.crates[cid]

    def _pick_upgrade(self, offer: Optional[Dict[str, Any]]) -> Optional[int]:
        if not offer:
            return None
        pick, best = 0, 1e9
        for i, c in enumerate(offer.get("choices") or []):
            try:
                rank = UPGRADE_PRIORITY.index(c.get("id", ""))
            except ValueError:
                rank = 100 + i
            if rank < best:
                best, pick = rank, i
        return pick

    # ---------------------------------------------------------------- deciding
    def _select_mode(self, obs: mf.Observation) -> str:
        me = obs["self"]
        t = float(obs["t"])
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        zone = obs["zone"]

        if not me.get("in_zone", True):
            return "ESCAPE"
        airborne_climb = self.mode == "ROOF" and not me.get("grounded") and not self.mem.world_on_roof

        mechs = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        hit_by_mech = t - self._mech_hit_last_t < 1.5
        target = self._fight_target(me, mechs, t)

        urgency = self._zone_urgency(me, zone, t)
        if urgency < 5.0:
            return "ZONE"
        busy = hit_by_mech or (target is not None and _d2(target["pos"], me["pos"]) < 90.0)
        if urgency < 20.0 and not busy:
            return "ZONE"

        # A drone shooting us while no mech is: kill it.
        if t - self._npc_hit_last_t < 2.5 and t - self._mech_hit_last_t > 2.0:
            return "DRONE"

        # Back off to heal when low, unless the target is about to die.
        if mechs or hit_by_mech:
            finishing = target is not None and self._nearly_dead(target)
            if self.mode == "HEAL" and hp_frac < HEAL_DONE_HP * 0.85 and not finishing:
                return "HEAL"
            if hp_frac < RETREAT_HP and not finishing:
                return "HEAL"
            if target is not None:
                return "FIGHT"
        else:
            # Nobody in view: rest when hurt (no shooting, so regen runs).
            if self.mode == "HEAL" and hp_frac < HEAL_DONE_HP:
                return "HEAL"
            if hp_frac < REST_HP and t - self.mem.last_took_weapon_damage_t > 1.0:
                return "HEAL"

        if airborne_climb:
            return "ROOF"
        if self._farm_goal(obs, mechs, t) is not None:
            return "FARM"
        if t < FARM_EARLY_S and not self.mem.world_on_roof:
            return "FARM"  # search the map for crates/drones/cubes early
        return "ROOF"

    def _nearly_dead(self, m: Dict[str, Any]) -> bool:
        hp = m.get("hp")
        if hp is None:
            return False
        return float(hp) <= 260.0 or float(hp) < 0.2 * float(m.get("max_hp") or 1400)

    def _fight_target(self, me: Dict[str, Any], mechs: List[Dict[str, Any]], t: float) -> Optional[Dict[str, Any]]:
        """Nearest mech we can shoot; keep the current one unless another is much nearer.

        Also returns a no-LOS mech that is close (chase) or that is hitting us.
        """
        best, best_d = None, 1e9
        prev = None
        hit_recent = t - self._mech_hit_last_t < 1.5
        for m in mechs:
            d = _d2(m["pos"], me["pos"])
            if d > ENGAGE_MAX:
                continue
            cubes = m.get("cubes") if isinstance(m.get("cubes"), int) else None
            clear = self.combat.clear_shot(me, m["pos"], int(m["id"]), cubes)
            if not clear:
                hitter = hit_recent and self.mem.last_threat_id == int(m["id"])
                if not (d < CHASE_NO_LOS or hitter):
                    continue
                d += 40.0  # prefer something we can actually shoot
            if self._nearly_dead(m):
                d -= 30.0
            if self._target_id is not None and int(m["id"]) == self._target_id:
                prev = (m, d)
            if d < best_d:
                best, best_d = m, d
        if prev is not None and prev[1] < best_d * 1.25 + 10.0:
            best = prev[0]
        if best is None and hit_recent and self.mem.last_threat_id in self.mem.enemies:
            e = self.mem.enemies[self.mem.last_threat_id]
            if t - float(e.get("last_seen_t", -1e9)) < self.memory_s:
                best = e
        self._target_id = int(best["id"]) if best is not None else None
        return best

    def _zone_urgency(self, me: Dict[str, Any], zone: Dict[str, Any], t: float) -> float:
        """Seconds of slack before the next circle closes on us (1e9 when safely inside)."""
        nc, nr = zone["next_center"], float(zone["next_radius"])
        dist = math.hypot(me["pos"][0] - nc[0], me["pos"][1] - nc[1])
        inside = 0.75 * nr if self.mode == "ZONE" else 0.85 * nr
        if dist <= inside:
            return 1e9
        walk = max(1.0, float((me.get("stats") or {}).get("walk_speed", self.walk_speed)))
        travel = max(0.0, dist - 0.7 * nr) / walk
        return float(zone["shrink_end"]) - t - travel

    # ----------------------------------------------------------------- farming
    def _farm_goal(self, obs: mf.Observation, mechs: List[Dict[str, Any]], t: float) -> Optional[Dict[str, Any]]:
        """Best farm target by value per distance. None when nothing worth it."""
        me = obs["self"]
        mx, my, mz = me["pos"]
        zone = obs["zone"]
        zc, zr = zone["center"], float(zone["radius"])
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        resting = self.mode == "HEAL"
        enemy_d = min((_d2(m["pos"], me["pos"]) for m in mechs), default=1e9)
        cubes_n = int(me.get("cubes") or 0)
        second = _has_second(me)
        cands: List[Dict[str, Any]] = []

        def inzone(p: List[float], margin: float = 10.0) -> bool:
            return math.hypot(p[0] - zc[0], p[1] - zc[1]) < zr - margin

        if cubes_n < CUBE_GOAL:
            reach = 200.0 if not mechs else min(100.0, enemy_d * 0.6)
            for c in obs.get("cubes") or []:
                d = _d2(c["pos"], me["pos"])
                if c["pos"][2] - mz > 3.0 or d > reach or not inzone(c["pos"], 5.0):
                    continue
                cands.append({"kind": "cube", "pos": list(c["pos"]), "key": ("cube", c["id"]), "val": 1.0, "d": d})
            pk = self.mem.post_kill_pos
            if pk is not None:
                d = _d2(pk, me["pos"])
                fresh = t - self.mem.post_kill_t < 30.0
                if not fresh or d <= self.cube_r:
                    self.mem.post_kill_pos = None
                elif d < 250.0 and pk[2] - mz < 3.0 and (not mechs or enemy_d > d + 50.0) and inzone(pk):
                    cands.append({"kind": "site", "pos": list(pk), "key": ("site", round(pk[0]), round(pk[1])), "val": 3.0, "d": d})

        # Weapons: get a second weapon, or upgrade to a better one, when it's close.
        if not mechs or enemy_d > 90.0:
            loot = self.mem.best_loot(me["pos"], t, world=self.world, on_roof=self.mem.world_on_roof, step_up=self.step_up)
            if loot is not None and inzone(loot["pos"]):
                d = _d2(loot["pos"], me["pos"])
                have = WEAPON_RANK.get(second or "", 0)
                gain = WEAPON_RANK.get(loot["kind"], 0) - have
                if gain > 0 and (second is None or d < 60.0):
                    val = 3.0 if second is None else 1.2
                    cands.append({"kind": "loot", "pos": list(loot["pos"]), "id": loot["id"], "key": ("loot", loot["id"]), "val": val, "d": d})

        # Shooting crates and drones deals damage, which stops regen: not while resting.
        shoot_ok = not resting and (not mechs or enemy_d > 90.0) and cubes_n < CUBE_GOAL
        if shoot_ok:
            muzz = self.combat.muzzle(me)
            for c in obs.get("crates") or []:
                d = _d2(c["pos"], me["pos"])
                if d > 160.0 or d < 1.0 or not inzone(c["pos"]):
                    continue
                center = [c["pos"][0], c["pos"][1], c["pos"][2] + 1.2]
                clear = not self.world.blocked_segment(muzz, center, step=2.5)
                if not clear and (c["pos"][2] - self.world.ground(c["pos"][0], c["pos"][1]) > self.step_up + 3.0):
                    continue  # roof crate we can't see the top of
                dd = d * 0.35 if clear else d  # shooting from here costs little time
                cands.append({"kind": "crate", "pos": center, "id": c["id"], "key": ("crate", c["id"]), "val": 1.0, "d": dd, "clear": clear})
            for cid, c in self.crates.items():
                if c["last_seen_t"] >= t:
                    continue  # visible: handled above
                d = _d2(c["pos"], me["pos"])
                if d > 160.0 or not inzone(c["pos"]):
                    continue
                if c["pos"][2] - self.world.ground(c["pos"][0], c["pos"][1]) > self.step_up + 3.0:
                    continue
                center = [c["pos"][0], c["pos"][1], c["pos"][2] + 1.2]
                cands.append({"kind": "crate", "pos": center, "id": cid, "key": ("crate", cid), "val": 0.9, "d": d, "clear": False})
            if hp_frac > 0.45:
                for m in obs.get("mechs") or []:
                    if m.get("kind") != "npc":
                        continue
                    d = _d2(m["pos"], me["pos"])
                    if d > 140.0 or not inzone(m["pos"], 0.0):
                        continue
                    cands.append({"kind": "drone", "pos": list(m["pos"]), "id": int(m["id"]), "key": ("drone", int(m["id"])), "val": 2.0, "d": d * 0.6 + 25.0})

        best, best_s = None, 0.0
        cur = None
        for c in cands:
            if self._farm_bl.get(c["key"], -1e9) > t:
                continue
            s = c["val"] / (c["d"] + 20.0)
            if c["key"] == self._farm_key:
                cur = (c, s)
            if s > best_s:
                best, best_s = c, s
        if cur is not None and cur[1] * 1.3 >= best_s:
            best = cur[0]
        if best is None:
            self._farm = None
            self._farm_key = None
            return None
        if best["key"] != self._farm_key:
            self._farm_key = best["key"]
            self._farm_since = t
        limit = {"crate": 8.0, "drone": 15.0, "cube": 18.0, "site": 20.0, "loot": 20.0}[best["kind"]]
        if best["kind"] == "crate" and not best.get("clear"):
            limit = 20.0
        if t - self._farm_since > limit:
            self._farm_bl[best["key"]] = t + 45.0
            if best["kind"] == "site":
                self.mem.post_kill_pos = None
            self._farm = None
            self._farm_key = None
            return None
        self._farm = best
        return best

    def _do_farm(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        goal = self._farm
        efrac = me["energy"] / max(1.0, me["max_energy"])
        if goal is None:
            # Early search: walk to waypoints inside the next circle, scanning with the torso.
            z = obs["zone"]
            dest = self._search_wp
            if dest is None or _d2(dest, me["pos"]) < 15.0 or t > self._search_until:
                nc, nr = z["next_center"], float(z["next_radius"])
                ang = self.mem.rand() * 2 * math.pi
                rr = math.sqrt(self.mem.rand()) * 0.6 * nr
                # bias toward our side of the circle so we don't cross the whole map
                bx = 0.5 * (me["pos"][0] - nc[0])
                by = 0.5 * (me["pos"][1] - nc[1])
                dest = [nc[0] + bx * 0.5 + math.cos(ang) * rr, nc[1] + by * 0.5 + math.sin(ang) * rr]
                self._search_wp, self._search_until = dest, t + 30.0
            move, _ = self._go(me, dest, 1.0, t)
            act["move"] = move
            act["aim"] = [self.mem.scan_yaw, -0.05]
            act["boost"] = efrac > 0.7
            self._unstick(me, act, t)
            return
        kind = goal["kind"]
        if kind == "crate" and goal.get("clear"):
            mx, my, mz = self.combat.muzzle(me)
            gx, gy, gz = goal["pos"]
            yaw = math.atan2(gy - my, gx - mx)
            pitch = math.atan2(gz - mz, math.hypot(gx - mx, gy - my) or 1e-6)
            act["aim"] = [yaw, pitch]
            if self.combat.aligned(me, [yaw, pitch], tol_deg=3.0):
                act["fire"] = [True, False]
            gun = (me.get("weapons") or [None])[0]
            if gun and gun.get("kind") == "gun" and (gun.get("ammo") or 0) == 0 and not gun.get("reload"):
                act["reload"] = True
            return
        if kind == "drone":
            drone = None
            for m in obs.get("mechs") or []:
                if m.get("kind") == "npc" and int(m["id"]) == goal["id"]:
                    drone = m
                    break
            if drone is not None:
                d = _d2(drone["pos"], me["pos"])
                tgt = self._drone_aim_target(drone)
                clear = self.combat.clear_shot(me, tgt["pos"], None)
                if clear and d <= 95.0:
                    self._shoot_drone(obs, act, me, drone, t)
                    return
                move, yaw = self._go(me, drone["pos"], 1.0, t)
                act["move"] = move
                act["aim"] = self.combat.aim_at(me, tgt, "gun")
                act["boost"] = efrac > 0.6 and d > 60.0
                self._unstick(me, act, t)
                return
        # walk to it (cube, site, loot, unseen crate, drone out of view)
        move, yaw = self._go(me, goal["pos"], 1.0, t)
        act["move"] = move
        act["aim"] = [_bearing_to(me["pos"], goal["pos"]), -0.05]
        d = _d2(goal["pos"], me["pos"])
        act["boost"] = efrac > 0.5 and d > 15.0
        if kind == "loot" and d <= self.loot_r - 0.3:
            vis = {int(p["id"]) for p in (obs.get("pickups") or [])}
            if int(goal["id"]) in vis:
                act["take"] = goal["id"]
                second = _has_second(me)
                if second is not None:
                    act["drop"] = _slot_of(me, second)
        self._unstick(me, act, t)

    # ----------------------------------------------------------------- fighting
    def _do_fight(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        second = _has_second(me)
        chase = None
        if self._target_id is not None:
            for m in obs.get("mechs") or []:
                if m.get("kind") == "mech" and int(m["id"]) == self._target_id:
                    chase = m
                    break
            if chase is None:
                chase = self.mem.enemies.get(self._target_id)
        if chase is None:
            return self._do_roof(obs, act)

        # A drone shooting us while we fight: kill it first unless the mech is nearly dead.
        drone = self._hostile_drone(obs, me, t)
        if drone is not None and not self._nearly_dead(chase):
            self._shoot_drone(obs, act, me, drone, t)
            return

        cubes = chase.get("cubes") if isinstance(chase.get("cubes"), int) else None
        clear = self.combat.clear_shot(me, chase["pos"], int(chase["id"]), cubes)
        dist = _d2(chase["pos"], me["pos"])

        kind = "gun"
        if second == "laser":
            kind = "laser" if clear else "gun"
        elif second == "mortar":
            if not clear and 12.0 < dist < self.mortar_max:
                kind = "mortar"
        elif second == "lightning":
            kind = "lightning" if clear and dist <= self.lightning_range else "gun"
        if kind == "mortar" and self.combat.mortar_aim(me, chase["pos"], chase.get("vel") or [0, 0, 0]) is None:
            kind = "gun"
        kind, aim_kind = self._fight_aim_kind(me, kind)
        aim = self.combat.aim_at(me, chase, kind)
        act["aim"] = aim
        fire, reload, _ = self.combat.fire_slots(me, aim, chase, t, self.mem, aim_kind=aim_kind)
        if kind == "gun" and not clear:
            fire = [False, False]  # don't empty the mag into a wall
        act["fire"] = fire
        act["reload"] = reload

        bearing = _bearing_to(me["pos"], chase["pos"])
        efrac = me["energy"] / max(1.0, me["max_energy"])
        finishing = self._nearly_dead(chase)

        # On a roof: hold it. Move to the firing edge toward them; never jump down to chase
        # unless they're nearly dead.
        if self.mem.world_on_roof and not (finishing and not clear and dist < 80.0):
            roof = self._roof_here(me)
            fp = self.cover.best_firing(roof, bearing) if roof else None
            if fp and (not clear or dist > BAND_LO):
                move, _ = self.nav.steer(me, fp, 0.85, t)
                act["move"] = move
            else:
                side = bearing + (math.pi / 2) * self.mem.strafe_sign
                act["move"] = [math.cos(side) * 0.4, math.sin(side) * 0.4]
            return

        lo, hi = BAND_LO, BAND_HI
        if second == "lightning" and _slot_of(me, "lightning") is not None:
            lo, hi = 20.0, 40.0
        if finishing:
            lo = 25.0
        if not clear:
            move, _ = self.nav.steer(me, chase["pos"], 1.0, t)
            act["move"] = move
            act["boost"] = efrac > 0.45 and dist > 40.0
        elif dist > hi:
            move, _ = self.nav.steer(me, chase["pos"], 1.0, t)
            act["move"] = move
            act["boost"] = efrac > 0.5 and dist > hi + 40.0
        elif dist < lo:
            away = bearing + math.pi + 0.5 * self.mem.strafe_sign
            dest = [me["pos"][0] + math.cos(away) * 25.0, me["pos"][1] + math.sin(away) * 25.0]
            move, _ = self.nav.steer(me, dest, 1.0, t)
            act["move"] = move
        else:
            # flip strafe direction every few seconds so we're not trivially led
            if int(t / 2.7) % 2 == 0:
                sgn = self.mem.strafe_sign
            else:
                sgn = -self.mem.strafe_sign
            side = bearing + (math.pi / 2) * sgn
            dest = [me["pos"][0] + math.cos(side) * 15.0, me["pos"][1] + math.sin(side) * 15.0]
            move, _ = self.nav.steer(me, dest, 0.75, t)
            act["move"] = move
        self._unstick(me, act, t)

    # ------------------------------------------------------------------ healing
    def _do_heal(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        """Break LOS, face the threat (front armor), fire back only while still being hit."""
        me = obs["self"]
        t = float(obs["t"])
        mechs = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        threat = None
        if mechs:
            threat = min(mechs, key=lambda m: _d2(m["pos"], me["pos"]))
        tb = _bearing_to(me["pos"], threat["pos"]) if threat else self.mem.last_threat_bearing
        if tb is not None:
            act["aim"] = [tb, -0.05]

        # Still being hit and they're in our sights: shoot back while we move.
        if threat is not None and t - self.mem.last_took_weapon_damage_t < 1.5:
            cubes = threat.get("cubes") if isinstance(threat.get("cubes"), int) else None
            if self.combat.clear_shot(me, threat["pos"], int(threat["id"]), cubes):
                kind = "laser" if _slot_of(me, "laser") is not None else "gun"
                kind, aim_kind = self._fight_aim_kind(me, kind)
                aim = self.combat.aim_at(me, threat, kind)
                act["aim"] = aim
                fire, reload, _ = self.combat.fire_slots(me, aim, threat, t, self.mem, aim_kind=aim_kind)
                act["fire"] = fire
                act["reload"] = reload

        # Grab cubes right next to us (no damage involved).
        for c in obs.get("cubes") or []:
            if _d2(c["pos"], me["pos"]) < 20.0 and c["pos"][2] - me["pos"][2] < 3.0 and not mechs:
                move, _ = self.nav.steer(me, c["pos"], 0.4, t)
                act["move"] = move
                return

        if self.mem.world_on_roof:
            roof = self._roof_here(me)
            hid = self._roof_hide(roof, tb) if roof else None
            if hid is not None and _d2(hid, me["pos"]) > 1.5:
                move, _ = self.nav.steer(me, hid, 0.6, t)
                act["move"] = move
            return

        if tb is None:
            # Nothing known: stand still (silent) unless the zone wants us to move.
            return
        goal = self._cover_point(obs, me, tb, t)
        if goal is not None and _d2(goal, me["pos"]) > 2.0:
            fast = threat is not None
            move, _ = self.nav.steer(me, goal, 1.0 if fast else 0.4, t)
            act["move"] = move
            efrac = me["energy"] / max(1.0, me["max_energy"])
            act["boost"] = fast and efrac > 0.3 and t - self.mem.last_took_weapon_damage_t < 2.0
            self._unstick(me, act, t)

    def _cover_point(self, obs: mf.Observation, me: Dict[str, Any], threat_bearing: float, t: float) -> Optional[List[float]]:
        """A nearby spot with a wall between us and the threat, inside the zone (cached 1 s)."""
        if self._cover_pt is not None and t - self._cover_t < 1.0:
            return self._cover_pt
        zone = obs["zone"]
        zc, zr = zone["center"], float(zone["radius"])
        x, y, z = me["pos"]
        eh = float((me.get("stats") or {}).get("eye_height", 8.0))
        thr = [x + math.cos(threat_bearing) * 60.0, y + math.sin(threat_bearing) * 60.0]
        thr_eye = [thr[0], thr[1], self.world.ground(thr[0], thr[1]) + 8.0]
        best, best_s = None, -1e9
        for k in range(12):
            ang = threat_bearing + math.pi + (k - 5.5) * (math.pi / 6.0)
            for r in (14.0, 26.0):
                cx, cy = x + math.cos(ang) * r, y + math.sin(ang) * r
                if math.hypot(cx - zc[0], cy - zc[1]) > zr - 15.0:
                    continue
                gz = self.world.ground(cx, cy)
                if abs(gz - z) > 3.0 or self.world.solid_at(cx, cy, gz + 2.0):
                    continue
                if not self.world.blocked_segment(thr_eye, [cx, cy, gz + eh], step=3.0):
                    continue
                away = math.cos(_angdiff(ang, threat_bearing + math.pi))
                s = away * 10.0 - r * 0.5
                if s > best_s:
                    best, best_s = [cx, cy], s
        if best is None:
            # No cover found: back away from the threat, toward the zone interior.
            away = threat_bearing + math.pi
            bx, by = x + math.cos(away) * 30.0, y + math.sin(away) * 30.0
            if math.hypot(bx - zc[0], by - zc[1]) > zr - 15.0:
                best = self.nav.zone_goal(zone, me["pos"], 0.5)
            else:
                best = [bx, by]
        self._cover_pt, self._cover_t = best, t
        return best

    # --------------------------------------------------------------- roof camp
    def _roof_here(self, me: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rid = self.world.roof_at(me["pos"][0], me["pos"][1])
        if rid is None:
            rid = self.mem.roof_id
        if rid is None:
            return None
        if self.mem.roof_id != int(rid):
            self.mem.roof_id = int(rid)
            self.mem.reset_camp_counters()
        return self.cover.roof(int(rid))

    def _roof_hide(self, roof: Dict[str, Any], threat_bearing: Optional[float]) -> Optional[List[float]]:
        pts = roof.get("hidden_points") or []
        if not pts:
            return None
        if threat_bearing is None:
            return self.cover.best_hidden(roof)
        c = roof["center"]

        # hidden point well rated and on the far side from the threat
        def score(p: List[float]) -> float:
            side = -math.cos(_angdiff(math.atan2(p[1] - c[1], p[0] - c[0]), threat_bearing))
            return float(p[2]) + 0.5 * side

        p = max(pts, key=score)
        return [p[0], p[1]]

    def _do_roof(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        z = obs["zone"]
        here = self.world.roof_at(me["pos"][0], me["pos"][1])
        roof = self.cover.roof(int(here)) if here is not None else None
        # stay on the roof we're on if it's still inside the next circle
        if roof is not None and self.cover.score_roof(roof, me["pos"], z["next_center"], float(z["next_radius"])) > -1e8:
            return self._do_camp(obs, act, roof)
        roof = self.cover.pick_roof(me["pos"], z["next_center"], float(z["next_radius"]))
        if roof is None:
            goal = self.nav.zone_goal(z, me["pos"], 0.5)
            move, yaw = self.nav.steer(me, goal, 0.7, t)
            act["move"] = move
            act["aim"] = [yaw, -0.05]
            return
        if self.mem.roof_id != int(roof["id"]):
            self.mem.roof_id = int(roof["id"])
            self.mem.reset_camp_counters()
        climb = self.cover.nearest_climb(roof, me["pos"])
        if climb and _d2(climb, me["pos"]) > 20.0 and me.get("grounded"):
            self.mem.climb_target = climb
            move, yaw = self._go(me, climb, 1.0, t)
            act["move"] = move
            act["aim"] = [yaw, -0.05]
            act["boost"] = me["energy"] / max(1.0, me["max_energy"]) > 0.8
        elif climb:
            self.mem.climb_target = climb
            act.update(self.nav.climb_action(me, roof, climb, t))
        else:
            move, yaw = self.nav.steer(me, roof["center"], 0.8, t)
            act["move"] = move
            act["aim"] = [yaw, 0.15]
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True
        if me.get("grounded"):
            self._unstick(me, act, t)
        self._fire_overlay(obs, act)

    def _do_camp(self, obs: mf.Observation, act: Dict[str, Any], roof: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        if self.mem.roof_id != int(roof["id"]):
            self.mem.roof_id = int(roof["id"])
            self.mem.reset_camp_counters()
        toward = self.mem.last_threat_bearing
        if toward is None:
            zc = obs["zone"]["center"]
            toward = _bearing_to(me["pos"], [zc[0], zc[1]])
        if self.mem.camp_hidden is None:
            self.mem.camp_hidden = self._roof_hide(roof, self.mem.last_threat_bearing) or list(roof["center"][:2])
        # peek cadence: 2.5 s out at the firing edge toward the threat, every 4 s
        if t >= self.mem.next_peek_t and self.mem.peek_phase == 0:
            self.mem.peek_phase = 1
            self.mem.peek_until = t + 2.5
            self.mem.next_peek_t = t + 4.0
            self.mem.camp_fire = self.cover.best_firing(roof, toward)
        fire_pt = self.mem.camp_fire
        if self.mem.peek_phase == 1:
            if (fire_pt is not None and _d2(fire_pt, me["pos"]) <= 2.0) or t >= self.mem.peek_until:
                self.mem.peek_phase = 0
        goal = fire_pt if self.mem.peek_phase == 1 and fire_pt else self.mem.camp_hidden
        if goal is not None and _d2(goal, me["pos"]) > 1.0:
            move, _ = self.nav.steer(me, goal, 0.4, t)
            act["move"] = move
        act["aim"] = [toward, -0.05]
        for s in self.mem.sound_log:
            if s.get("dist") == "near" and s.get("kind") in ("step", "boost", "jet"):
                act["aim"] = [float(s["bearing"]), -0.05]
                break
        # mortar: lob at mid/far gunfire
        slot = _slot_of(me, "mortar")
        if slot is not None and t - self.mem.last_mortar_t >= self.combat.mortar_gap():
            for s in self.mem.sound_log:
                if s.get("kind") in ("gun", "laser", "laser_charge") and s.get("dist") in ("mid", "far"):
                    b = float(s["bearing"])
                    dist = 80.0 if s["dist"] == "mid" else 140.0
                    tx, ty = me["pos"][0] + math.cos(b) * dist, me["pos"][1] + math.sin(b) * dist
                    aim = self.combat.mortar_aim(me, [tx, ty, self.world.ground(tx, ty)], [0, 0, 0])
                    if aim:
                        act["aim"] = aim
                        if self.combat.aligned(me, aim, 4.0):
                            fire = [False, False]
                            fire[slot] = True
                            act["fire"] = fire
                            self.mem.last_mortar_t = t
                    break
        self._fire_overlay(obs, act)

    def _fire_overlay(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        """Shoot a visible mech with a clear shot while doing something else."""
        me = obs["self"]
        t = float(obs["t"])
        mechs = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech" and _d2(m["pos"], me["pos"]) < ENGAGE_MAX]
        if not mechs:
            return
        mechs.sort(key=lambda m: _d2(m["pos"], me["pos"]))
        target = self.combat.pick_target(me, mechs[:3], self._target_id)
        if not target:
            return
        kind = "laser" if _slot_of(me, "laser") is not None else "gun"
        kind, aim_kind = self._fight_aim_kind(me, kind)
        aim = self.combat.aim_at(me, target, kind)
        act["aim"] = aim
        fire, reload, _ = self.combat.fire_slots(me, aim, target, t, self.mem, aim_kind=aim_kind)
        act["fire"] = fire
        if reload:
            act["reload"] = True

    # ------------------------------------------------------------- zone (481fed0)
    def _do_escape(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        goal = self.nav.zone_goal(obs["zone"], me["pos"], 0.65)
        move, yaw = self._go(me, goal, 1.0, t)
        act["move"] = move
        act["aim"] = [yaw, -0.05]
        efrac = float(me["energy"]) / max(1.0, float(me["max_energy"]))
        if self._path:
            act["boost"] = efrac > 0.4 and bool(me.get("grounded"))
            self._unstick(me, act, t)
            self._fire_overlay(obs, act)
            return
        # Local steering gets trapped (stadium bowl, courtyards, wall pockets). Track progress
        # toward the circle; if it stalls for 1.5 s, jet straight at the goal over whatever is
        # in the way. Keep energy for that: ground boost only while energy is above half.
        zc = obs["zone"]["center"]
        d_c = math.hypot(me["pos"][0] - zc[0], me["pos"][1] - zc[1])
        fresh = t - self._esc_last_t > 0.5
        self._esc_last_t = t
        if fresh:
            self._esc_ref_t = t
            self._esc_ref_d = d_c
        elif t - self._esc_ref_t > 1.5:
            if self._esc_ref_d - d_c < 3.0:
                self._esc_jet_until = t + 3.0
            self._esc_ref_t = t
            self._esc_ref_d = d_c
        if t < self._esc_jet_until and (efrac > 0.12 or not me.get("grounded")):
            direct = math.atan2(goal[1] - me["pos"][1], goal[0] - me["pos"][0])
            act["move"] = [math.cos(direct), math.sin(direct)]
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True
            act["aim"] = [direct, -0.05]
        else:
            act["boost"] = efrac > 0.5 and bool(me.get("grounded"))
        self._fire_overlay(obs, act)

    def _do_zone(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        z = obs["zone"]
        nz = {"center": z["next_center"], "radius": z["next_radius"]}
        goal = self.nav.zone_goal(nz, me["pos"], 0.6)
        move, yaw = self._go(me, goal, 1.0, t)
        act["move"] = move
        act["aim"] = [yaw, -0.05]
        efrac = me["energy"] / max(1.0, me["max_energy"])
        late = float(z["shrink_end"]) - t < 12.0
        act["boost"] = efrac > (0.3 if late else 0.6) and bool(me.get("grounded"))
        self._unstick(me, act, t)
        self._fire_overlay(obs, act)

    # ------------------------------------------------------------------ drones
    def _hostile_drone(self, obs: mf.Observation, me: Dict[str, Any], t: float) -> Optional[Dict[str, Any]]:
        best, best_d = None, 1e9
        for m in obs.get("mechs") or []:
            if m.get("kind") != "npc":
                continue
            if t - self._npc_hit_t.get(int(m["id"]), -99.0) > 3.0:
                continue
            d = _d2(m["pos"], me["pos"])
            if d > 110.0 or d >= best_d:
                continue
            if not self.combat.clear_shot(me, self._drone_aim_target(m)["pos"], None):
                continue
            best, best_d = m, d
        return best

    def _drone_aim_target(self, m: Dict[str, Any]) -> Dict[str, Any]:
        """combat.aim_at aims at a mech's centre (feet + height/2); shift a drone so it aims at its centre."""
        x, y, z = m["pos"]
        return {"id": m["id"], "kind": "npc", "pos": [x, y, z + self.npc_h * 0.5 - self.mech_h * 0.5], "vel": m.get("vel") or [0, 0, 0]}

    def _shoot_drone(self, obs: mf.Observation, act: Dict[str, Any], me: Dict[str, Any], drone: Dict[str, Any], t: float) -> None:
        tgt = self._drone_aim_target(drone)
        aim = self.combat.aim_at(me, tgt, "gun")
        act["aim"] = aim
        fire, reload, _ = self.combat.fire_slots(me, aim, tgt, t, self.mem, aim_kind="gun")
        act["fire"] = [fire[0], False]
        act["reload"] = reload
        bearing = _bearing_to(me["pos"], drone["pos"])
        side = bearing + (math.pi / 2) * self.mem.strafe_sign
        act["move"] = [math.cos(side) * 0.6, math.sin(side) * 0.6]

    def _do_drone(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        drone = self._hostile_drone(obs, me, t)
        if drone is None:
            npcs = [m for m in (obs.get("mechs") or []) if m.get("kind") == "npc" and _d2(m["pos"], me["pos"]) < 110.0]
            if npcs:
                drone = min(npcs, key=lambda m: _d2(m["pos"], me["pos"]))
        if drone is not None:
            self._shoot_drone(obs, act, me, drone, t)
            return
        b = self._npc_hit_bearing if self._npc_hit_bearing is not None else me["aim"][0]
        act["aim"] = [float(b), -0.15]
        side = float(b) + (math.pi / 2) * self.mem.strafe_sign
        act["move"] = [math.cos(side) * 0.5, math.sin(side) * 0.5]

    # ------------------------------------------------------------------ shared
    def _go(self, me: Dict[str, Any], goal: List[float], speed: float, t: float) -> tuple:
        """steer() toward goal; if we stop making progress for 2.5 s, plan a grid path around."""
        d = _d2(goal, me["pos"])
        if self._path and t < self._path_until and self._path_goal is not None and _d2(self._path_goal, goal) < 25.0:
            path = self._path
            while len(path) > 1 and _d2(path[0], me["pos"]) < 6.0:
                path.pop(0)
            if len(path) == 1 and _d2(path[0], me["pos"]) < 4.0:
                self._path = None
            else:
                mf.draw.line(me["pos"], [path[0][0], path[0][1], me["pos"][2]], "#40c0ff")
                return self.nav.steer(me, path[0], speed, t)
        else:
            self._path = None
        if (
            self._prog_goal is None
            or _d2(self._prog_goal, goal) > 25.0
            or t - self._prog_last > 0.5
        ):
            self._prog_goal, self._prog_t, self._prog_d = list(goal[:2]), t, d
        elif t - self._prog_t > 2.5:
            if self._prog_d - d < 5.0 and d > 12.0 and me.get("grounded"):
                path = self.planner.plan(me["pos"], goal)
                if path:
                    self._path, self._path_goal, self._path_until = path, list(goal[:2]), t + 30.0
            self._prog_t, self._prog_d = t, d
        self._prog_last = t
        return self.nav.steer(me, goal, speed, t)

    def _unstick(self, me: Dict[str, Any], act: Dict[str, Any], t: float) -> None:
        mv = act.get("move") or [0.0, 0.0]
        self.nav.update_stuck(me, t, math.hypot(mv[0], mv[1]) > 0.3)
        if self.mem.stuck_until > t:
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True

    def _fight_aim_kind(self, me: Dict[str, Any], kind: str) -> tuple[str, str]:
        """Pick aim weapon + fire_slots aim_kind (gun leads between laser shots)."""
        if kind == "mortar":
            return "mortar", "mortar"
        if kind == "laser":
            slot = _slot_of(me, "laser")
            if slot is not None:
                w = (me.get("weapons") or [])[slot]
                charge = float((w or {}).get("charge") or 0)
                cd = float((w or {}).get("cooldown") or 0)
                if charge <= 0.02 and cd > 0 and _slot_of(me, "gun") is not None:
                    return "gun", "gun"
            return "laser", "laser"
        if kind == "lightning":
            return "lightning", "lightning"
        return "gun", "gun"

    def _laser_charge_hold(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        """Final pass: keep / release a laser that was charging when the target vanished."""
        if self.mode in ("ESCAPE",) or (self.mode == "ROOF" and (act.get("boost") or act.get("jump"))):
            return
        me = obs["self"]
        t = float(obs["t"])
        fire = list(act.get("fire") or [False, False])
        while len(fire) < 2:
            fire.append(False)
        changed = False
        for i, w in enumerate(me.get("weapons") or []):
            if not w or w.get("kind") != "laser":
                continue
            if float(w.get("charge") or 0) <= 0.02 or fire[i]:
                continue
            best, best_ang = None, 1e9
            for e in self.mem.enemies.values():
                if t - float(e.get("last_seen_t", -1e9)) > self.memory_s:
                    continue
                ang = abs(_angdiff(me["aim"][0], _bearing_to(me["pos"], e["pos"])))
                if ang < best_ang:
                    best, best_ang = e, ang
            if best is not None and best_ang <= math.radians(8.0):
                fire[i] = True
                act["aim"] = self.combat.aim_at(me, best, "laser")
            else:
                fire[i] = False
            changed = True
        if changed:
            act["fire"] = fire

    def _avoid(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        """Steer clear of supply drops (hunters converge) and, when hurt, of drones."""
        me = obs["self"]
        mx, my, mz = me["pos"]
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        farm_drone = self._farm["id"] if self._farm and self._farm.get("kind") == "drone" else None
        push = [0.0, 0.0]
        if hp_frac < 0.5 or self.mode == "HEAL":
            for m in obs.get("mechs") or []:
                if m.get("kind") != "npc" or (farm_drone is not None and int(m["id"]) == farm_drone):
                    continue
                if mz - m["pos"][2] > 4.0:
                    continue
                d = _d2(m["pos"], me["pos"])
                if 1e-3 < d < self.npc_aggro + 5.0:
                    push[0] += (mx - m["pos"][0]) / d
                    push[1] += (my - m["pos"][1]) / d
        for d in obs.get("drops") or []:
            if mz - d["pos"][2] > 4.0:
                continue
            dist = _d2(d["pos"], me["pos"])
            if 1e-3 < dist < self.drop_avoid:
                push[0] += (mx - d["pos"][0]) / dist
                push[1] += (my - d["pos"][1]) / dist
        if push[0] or push[1]:
            pl = math.hypot(push[0], push[1]) or 1.0
            move = act.get("move") or [0.0, 0.0]
            act["move"] = [
                max(-1.0, min(1.0, move[0] * 0.5 + push[0] / pl * 0.7)),
                max(-1.0, min(1.0, move[1] * 0.5 + push[1] / pl * 0.7)),
            ]


if __name__ == "__main__":
    mf.run(Bot)
