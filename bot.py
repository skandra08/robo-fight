"""Rooftop Camper v1 — state machine bot."""
from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Optional

import mechfight as mf
from combat import Combat
from cover import CoverBook
from memory import Memory
from nav import Navigator
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


class Bot:
    name = "rooftop-camper"

    def __init__(self, hello: mf.Hello):
        t0 = time.perf_counter()
        self.cfg = hello["config"]
        self.slot = int(hello["slot"])
        map_dir = hello["map"]["dir"]
        # data next to bot in image, or repo data/ when running locally
        here = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(here, "data")
        self.world = World(map_dir)
        self.cover = CoverBook(data_dir)
        self.mem = Memory()
        self.mem.seed(int(hello.get("seed") or 1))
        self.nav = Navigator(self.world, self.mem)
        self.combat = Combat(self.world, self.cfg)
        self.loot_r = float(self.cfg["loot"]["pickup_radius"])
        self.cube_r = float(self.cfg["cubes"]["pickup_radius"])
        self.npc_avoid = 50.0
        self.drop_avoid = 40.0
        elapsed = time.perf_counter() - t0
        mf.log(f"init {elapsed*1000:.0f}ms roofs={len(self.cover.roofs)} cover={self.cover.cover_ok}")

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
        self.mem.world_on_roof = self.world.on_roof(me["pos"])
        if self.mem.world_on_roof:
            self.mem.time_on_roof += 0.1
        self.mem.update(obs)

        act: Dict[str, Any] = {"move": [0.0, 0.0], "boost": False, "jump": False, "fire": [False, False]}

        # --- UPGRADE ---
        offer = obs.get("offer")
        if offer:
            choices = offer.get("choices") or []
            pick = 0
            best = 1e9
            for i, c in enumerate(choices):
                cid = c.get("id", "")
                try:
                    rank = UPGRADE_PRIORITY.index(cid)
                except ValueError:
                    rank = 100 + i
                if rank < best:
                    best = rank
                    pick = i
            act["pick"] = pick

        mode = self._select_mode(obs)
        self.mem.set_mode(mode, t)
        mf.draw.label(f"{mode} hp={me['hp']:.0f}")

        if mode == "ESCAPE_ZONE":
            self._do_escape(obs, act)
        elif mode == "COUNTER_LASER":
            self._do_counter_laser(obs, act)
        elif mode == "FIGHT":
            self._do_fight(obs, act)
        elif mode == "HEAL":
            self._do_heal(obs, act)
        elif mode == "ARM":
            self._do_arm(obs, act)
        elif mode == "RELOCATE":
            self._do_relocate(obs, act)
        else:  # CAMP
            self._do_camp(obs, act)

        # Avoid must not override fight or climb movement.
        climbing = bool(act.get("boost") or act.get("jump")) and mode == "RELOCATE"
        if mode not in ("FIGHT", "COUNTER_LASER") and not climbing:
            self._avoid(obs, act)

        ms = (time.perf_counter() - t_act0) * 1000
        self.mem.max_act_ms = max(self.mem.max_act_ms, ms)
        return act  # type: ignore[return-value]

    def _select_mode(self, obs: mf.Observation) -> str:
        me = obs["self"]
        t = float(obs["t"])
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        second = _has_second(me)

        if not me.get("in_zone", True):
            return "ESCAPE_ZONE"

        # COUNTER_LASER
        if _slot_of(me, "mortar") is not None:
            for m in obs.get("mechs") or []:
                if m.get("kind") != "mech" or not m.get("charging"):
                    continue
                aim = m.get("aim") or [0, 0]
                bearing_to_us = math.atan2(me["pos"][1] - m["pos"][1], me["pos"][0] - m["pos"][0])
                if abs(_angdiff(aim[0], bearing_to_us)) < math.radians(10):
                    return "COUNTER_LASER"

        recent_dmg = t - self.mem.last_took_weapon_damage_t < 1.5
        visible_enemies = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        loot = self.mem.best_loot(me["pos"], t)
        loot_d = math.dist(loot["pos"][:2], me["pos"][:2]) if loot else 1e9
        enemy_d = min(
            (math.dist(m["pos"][:2], me["pos"][:2]) for m in visible_enemies),
            default=1e9,
        )

        # Practice needs kills AND a second weapon. If loot is closer than the
        # nearest hunter, finish the grab; otherwise fight.
        if recent_dmg or visible_enemies:
            if second is None and loot is not None and loot_d + 15 < enemy_d and loot_d < 110:
                return "ARM"
            return "FIGHT"

        # Heal only when safe (no recent weapon hits / no enemies in view).
        safe_for_regen = (
            t - self.mem.last_took_weapon_damage_t >= 5.0
            and t - self.mem.last_dealt_damage_t >= 5.0
        )
        if safe_for_regen and hp_frac < 0.7:
            if self.mem.world_on_roof or hp_frac < 0.55:
                return "HEAL"

        # Keep arming until we have a second weapon (don't hard-stop at 50s).
        if second is None:
            return "ARM"

        # relocate triggers
        need_reloc = False
        if self.mem.mode == "ARM" and second is not None:
            need_reloc = True
        if self.mem.shots_here > 10 or self.mem.mortars_here >= 3:
            need_reloc = True
        if self.mem.roof_id is not None:
            roof = self.cover.roof(self.mem.roof_id)
            if roof:
                # zone will cover?
                z = obs["zone"]
                travel = math.hypot(roof["center"][0] - me["pos"][0], roof["center"][1] - me["pos"][1]) / 10.0
                # crude: if next circle leaves roof center out soon
                nc, nr = z["next_center"], float(z["next_radius"])
                if (roof["center"][0] - nc[0]) ** 2 + (roof["center"][1] - nc[1]) ** 2 > (0.8 * nr) ** 2:
                    if float(z["shrink_end"]) - t < travel + 15:
                        need_reloc = True
        if not self.mem.world_on_roof and second is not None:
            need_reloc = True
        if need_reloc and not self.mem.world_on_roof:
            return "RELOCATE"
        if need_reloc and self.mem.world_on_roof and self.mem.shots_here > 10:
            return "RELOCATE"

        if self.mem.world_on_roof:
            return "CAMP"
        if second is not None:
            return "RELOCATE"
        return "ARM"

    def _do_escape(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        goal = self.nav.zone_goal(obs["zone"], me["pos"], 0.65)
        move, yaw = self.nav.steer(me, goal, 1.0)
        act["move"] = move
        act["boost"] = True
        act["aim"] = [yaw, -0.05]
        self._try_fight_overlay(obs, act)

    def _do_counter_laser(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        slot = _slot_of(me, "mortar")
        if slot is not None:
            act["drop"] = slot
        # also break LOS
        if self.mem.camp_hidden:
            move, yaw = self.nav.steer(me, self.mem.camp_hidden, 1.0)
            act["move"] = move
            act["aim"] = [yaw, 0.0]
        else:
            act["move"] = [0.0, 0.0]

    def _do_fight(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        enemies = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        # Prefer clear LOS; else chase any visible / remembered hunter.
        target = self.combat.pick_target(me, enemies, self.mem.last_threat_id, require_clear=True)
        chase = target or self.combat.pick_target(
            me, enemies, self.mem.last_threat_id, require_clear=False
        )
        if chase is None and self.mem.last_threat_id in self.mem.enemies:
            chase = self.mem.enemies[self.mem.last_threat_id]
        if chase is None and self.mem.enemies:
            chase = min(
                self.mem.enemies.values(),
                key=lambda e: math.dist(e["pos"][:2], me["pos"][:2]),
            )

        if chase is None:
            # Move while scanning — never freeze under fire with no contact.
            bearing = self.mem.last_threat_bearing
            if bearing is None:
                for s in reversed(self.mem.sound_log):
                    if s.get("bearing") is not None:
                        bearing = float(s["bearing"])
                        break
            if bearing is None:
                bearing = me["aim"][0]
            act["aim"] = [bearing, -0.05]
            goal = [
                me["pos"][0] + math.cos(bearing) * 30.0,
                me["pos"][1] + math.sin(bearing) * 30.0,
            ]
            move, _ = self.nav.steer(me, goal, 0.9)
            act["move"] = move
            act["boost"] = me["energy"] / me["max_energy"] > 0.5
            act["fire"] = [True, False]  # suppress while closing if gun aimed enough
            return

        clear = self.combat.clear_shot(me, chase["pos"])
        kind = "gun"
        if _slot_of(me, "laser") is not None and clear:
            kind = "laser"
        elif _slot_of(me, "mortar") is not None and not clear:
            kind = "mortar"
        elif _slot_of(me, "laser") is not None:
            kind = "laser"
        aim = self.combat.aim_at(me, chase, kind)
        act["aim"] = aim
        if clear or kind == "mortar":
            fire, reload, _ = self.combat.fire_slots(me, aim, chase, t, self.mem)
            act["fire"] = fire
            act["reload"] = reload
        else:
            # Closing the gap: keep gun ready if roughly aimed.
            fire, reload, _ = self.combat.fire_slots(me, aim, chase, t, self.mem)
            act["fire"] = fire
            act["reload"] = reload
        mf.draw.line(
            self.combat.muzzle(me),
            [chase["pos"][0], chase["pos"][1], chase["pos"][2] + 4.5],
            "#ff5040",
        )

        bearing = math.atan2(chase["pos"][1] - me["pos"][1], chase["pos"][0] - me["pos"][0])
        if self.mem.world_on_roof:
            roof = self.cover.roof(self.mem.roof_id) if self.mem.roof_id is not None else None
            if roof is None:
                rid = self.world.roof_at(me["pos"][0], me["pos"][1])
                self.mem.roof_id = rid
                roof = self.cover.roof(rid) if rid is not None else None
            if roof:
                fp = self.cover.best_firing(roof, bearing)
                if fp:
                    move, _ = self.nav.steer(me, fp, 0.8)
                    act["move"] = move
                    return
            act["move"] = [0.0, 0.0]
            return

        # Ground: close distance if far / no LOS; strafe if trading at mid range.
        dist = math.dist(chase["pos"][:2], me["pos"][:2])
        if not clear or dist > 90:
            move, _ = self.nav.steer(me, chase["pos"], 1.0)
            act["move"] = move
            act["boost"] = dist > 60 and me["energy"] / me["max_energy"] > 0.4
        else:
            side = bearing + (math.pi / 2 if self.mem.rand() > 0.5 else -math.pi / 2)
            act["move"] = [math.cos(side) * 0.7, math.sin(side) * 0.7]
        self.nav.update_stuck(me, t, True)
        if self.mem.stuck_until > t:
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True

    def _do_heal(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        # don't fire (dealing damage resets regen)
        act["fire"] = [False, False]
        if self.mem.last_threat_bearing is not None:
            act["aim"] = [self.mem.last_threat_bearing, -0.05]
        if self.mem.world_on_roof:
            roof = self.cover.roof(self.mem.roof_id) if self.mem.roof_id is not None else None
            if roof is None:
                rid = self.world.roof_at(me["pos"][0], me["pos"][1])
                self.mem.roof_id = rid
                roof = self.cover.roof(rid) if rid is not None else None
            hid = self.cover.best_hidden(roof) if roof else None
            if hid:
                self.mem.camp_hidden = hid
                move, _ = self.nav.steer(me, hid, 0.6)
                act["move"] = move
            else:
                act["move"] = [0.0, 0.0]
        else:
            # cover.bin may be empty — never freeze in place.
            spot = self.cover.ground_spot(me["pos"], obs["zone"]["center"], float(obs["zone"]["radius"]))
            if spot is None:
                if self.mem.last_threat_bearing is not None:
                    # drift away from last threat toward zone interior
                    away = self.mem.last_threat_bearing + math.pi
                    spot = [
                        me["pos"][0] + math.cos(away) * 25.0,
                        me["pos"][1] + math.sin(away) * 25.0,
                    ]
                else:
                    spot = self.nav.zone_goal(obs["zone"], me["pos"], 0.5)
            move, yaw = self.nav.steer(me, spot, 0.6)
            act["move"] = move
            if "aim" not in act:
                act["aim"] = [yaw, -0.05]

    def _do_arm(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        # Do NOT abandon arming when enemies appear — fight while we loot.
        # (Old 150 m flee left us gun-only forever against hunter squads.)

        best = self.mem.best_loot(me["pos"], t)
        # Prefer currently visible ids for take
        visible = {int(p["id"]): p for p in (obs.get("pickups") or []) if p.get("kind") != "gun"}
        if best and int(best["id"]) in visible:
            best = {
                "id": best["id"],
                "kind": visible[int(best["id"])]["kind"],
                "pos": list(visible[int(best["id"])]["pos"]),
            }
        elif not best and visible:
            # rank visible only
            best = None
            best_score = -1e9
            for p in visible.values():
                d = math.dist(p["pos"][:2], me["pos"][:2])
                kind = p["kind"]
                score = {"laser": 300, "mortar": 200, "lightning": 100}.get(kind, 0) - d
                if score > best_score:
                    best_score = score
                    best = {"id": p["id"], "kind": kind, "pos": list(p["pos"])}

        cube = None
        for c in obs.get("cubes") or []:
            d = math.dist(c["pos"][:2], me["pos"][:2])
            if d < 8 and me["cubes"] < self.mem.cubes_want:
                cube = c
                break

        if best is not None:
            goal = best["pos"]
            self.mem.arm_goal = list(goal[:2])
            if math.dist(best["pos"][:2], me["pos"][:2]) <= self.loot_r + 0.5:
                if int(best["id"]) in visible:
                    act["take"] = best["id"]
        elif cube is not None:
            goal = cube["pos"]
            self.mem.arm_goal = list(goal[:2])
        else:
            # Search: weave around zone center while scanning with torso FOV.
            zc = self.nav.zone_goal(obs["zone"], me["pos"], 0.55)
            yaw = self.mem.scan_yaw
            goal = [zc[0] + math.cos(yaw) * 55.0, zc[1] + math.sin(yaw) * 55.0]
            self.mem.arm_goal = goal

        move, yaw = self.nav.steer(me, goal, 1.0)
        act["move"] = move
        # Face loot while moving; otherwise scan for pickups (FOV is yaw-based).
        if best is not None:
            act["aim"] = [math.atan2(best["pos"][1] - me["pos"][1], best["pos"][0] - me["pos"][0]), -0.05]
        else:
            act["aim"] = [self.mem.scan_yaw, -0.05]
        # Silent when possible — boost only outside zone.
        act["boost"] = not me.get("in_zone", True) and me["energy"] / me["max_energy"] > 0.55
        self.nav.update_stuck(me, t, True)
        if self.mem.stuck_until > t:
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True

        # Return fire while arming
        self._try_fight_overlay(obs, act)

    def _do_relocate(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        z = obs["zone"]
        # visible enemies? don't climb
        enemies = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        roof = self.cover.pick_roof(me["pos"], z["next_center"], float(z["next_radius"]))
        if roof is None:
            spot = self.cover.ground_spot(me["pos"], z["center"], float(z["radius"]))
            goal = spot or self.nav.zone_goal(z, me["pos"], 0.5)
            move, yaw = self.nav.steer(me, goal, 0.7)
            act["move"] = move
            act["aim"] = [yaw, -0.05]
            act["boost"] = False
            return

        self.mem.roof_id = int(roof["id"])
        climb = self.cover.nearest_climb(roof, me["pos"])
        if self.world.on_roof(me["pos"]):
            hid = self.cover.best_hidden(roof)
            self.mem.camp_hidden = hid
            self.mem.reset_camp_counters()
            self.mem.roofs_used.add(int(roof["id"]))
            if hid:
                move, yaw = self.nav.steer(me, hid, 0.6)
                act["move"] = move
                act["aim"] = [yaw, -0.05]
            return

        # Climb even with enemies visible — waiting at the base is free kills for hunters.
        # Overlay return fire when we have a clear shot.
        if climb:
            self.mem.climb_target = climb
            climb_act = self.nav.climb_action(me, roof, climb, t)
            act.update(climb_act)
        else:
            move, yaw = self.nav.steer(me, roof["center"], 0.8)
            act["move"] = move
            act["aim"] = [yaw, 0.15]
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True
        if enemies:
            self._try_fight_overlay(obs, act)

    def _do_camp(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        rid = self.mem.roof_id or self.world.roof_at(me["pos"][0], me["pos"][1])
        self.mem.roof_id = rid
        roof = self.cover.roof(rid) if rid is not None else None
        if roof is None:
            # fall back to relocate
            return self._do_relocate(obs, act)

        hid = self.mem.camp_hidden or self.cover.best_hidden(roof)
        self.mem.camp_hidden = hid
        fire_pt = self.mem.camp_fire or self.cover.best_firing(roof)
        self.mem.camp_fire = fire_pt

        # peek cadence
        if t >= self.mem.next_peek_t and self.mem.peek_phase == 0:
            self.mem.peek_phase = 1
            self.mem.peek_until = t + 1.0
            self.mem.next_peek_t = t + 3.0
        if self.mem.peek_phase == 1 and t >= self.mem.peek_until:
            self.mem.peek_phase = 0

        goal = fire_pt if self.mem.peek_phase == 1 and fire_pt else hid
        if goal:
            move, yaw = self.nav.steer(me, goal, 0.4)
            act["move"] = move
        else:
            act["move"] = [0.0, 0.0]
            yaw = me["aim"][0]

        # aim
        aim_yaw = yaw
        if self.mem.last_threat_bearing is not None:
            aim_yaw = self.mem.last_threat_bearing
        else:
            zc = obs["zone"]["center"]
            aim_yaw = math.atan2(zc[1] - me["pos"][1], zc[0] - me["pos"][0])
        act["aim"] = [aim_yaw, -0.05]

        # near step/boost/jet sounds
        for s in self.mem.sound_log:
            if s.get("dist") == "near" and s.get("kind") in ("step", "boost", "jet"):
                act["aim"] = [float(s["bearing"]), -0.05]
                break

        # mortar lob on mid/far gun/laser
        if _slot_of(me, "mortar") is not None and t - self.mem.last_mortar_t >= 4.0:
            for s in self.mem.sound_log:
                if s.get("kind") in ("gun", "laser", "laser_charge") and s.get("dist") in ("mid", "far"):
                    bearing = float(s["bearing"])
                    dist = 80.0 if s["dist"] == "mid" else 140.0
                    tx = me["pos"][0] + math.cos(bearing) * dist
                    ty = me["pos"][1] + math.sin(bearing) * dist
                    tz = self.world.ground(tx, ty)
                    aim = self.combat.mortar_aim(me, [tx, ty, tz], [0, 0, 0])
                    if aim:
                        act["aim"] = aim
                        if self.combat.aligned(me, aim, 4.0):
                            slot = _slot_of(me, "mortar")
                            fire = [False, False]
                            fire[slot] = True
                            act["fire"] = fire
                            self.mem.last_mortar_t = t
                            self.mem.mortars_here += 1
                            self.mem.mortars += 1
                    break

        # Always take fights from the roof when we can see someone.
        self._try_fight_overlay(obs, act)

    def _try_fight_overlay(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        enemies = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        target = self.combat.pick_target(me, enemies, self.mem.last_threat_id)
        if not target:
            return
        kind = "laser" if _slot_of(me, "laser") is not None else "gun"
        aim = self.combat.aim_at(me, target, kind)
        act["aim"] = aim
        fire, reload, _ = self.combat.fire_slots(me, aim, target, t, self.mem)
        act["fire"] = fire
        if reload:
            act["reload"] = True

    def _avoid(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        mx, my = me["pos"][0], me["pos"][1]
        push = [0.0, 0.0]
        for m in obs.get("mechs") or []:
            if m.get("kind") != "npc":
                continue
            d = math.dist(m["pos"][:2], (mx, my))
            if d < self.npc_avoid and d > 1e-3:
                ux = (mx - m["pos"][0]) / d
                uy = (my - m["pos"][1]) / d
                push[0] += ux
                push[1] += uy
        for d in obs.get("drops") or []:
            dist = math.dist(d["pos"][:2], (mx, my))
            if dist < self.drop_avoid and dist > 1e-3:
                ux = (mx - d["pos"][0]) / dist
                uy = (my - d["pos"][1]) / dist
                push[0] += ux
                push[1] += uy
        if push[0] or push[1]:
            pl = math.hypot(push[0], push[1]) or 1.0
            move = act.get("move") or [0.0, 0.0]
            act["move"] = [
                max(-1.0, min(1.0, move[0] * 0.5 + push[0] / pl * 0.7)),
                max(-1.0, min(1.0, move[1] * 0.5 + push[1] / pl * 0.7)),
            ]


if __name__ == "__main__":
    mf.run(Bot)
