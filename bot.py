"""Practice loadout bot: arm quietly, position, take advantaged fights, gated thirds."""
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


def _bearing_to(a: List[float], b: List[float]) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _enemy_aware(enemy: Dict[str, Any], me_pos: List[float]) -> bool:
    """True if their torso aim is roughly toward us (likely detected)."""
    aim = enemy.get("aim") or [0.0, 0.0]
    to_us = _bearing_to(enemy["pos"], me_pos)
    return abs(_angdiff(aim[0], to_us)) < math.radians(70)


def _we_flank(enemy: Dict[str, Any], me_pos: List[float]) -> bool:
    """True if we sit outside their front 180° arc (rear shot opportunity)."""
    aim = enemy.get("aim") or [0.0, 0.0]
    to_us = _bearing_to(enemy["pos"], me_pos)
    return abs(_angdiff(aim[0], to_us)) > math.radians(90)


class Bot:
    name = "lh-v119-safe"

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
        self.near_range = float((self.cfg.get("vision") or {}).get("near_range", 45.0))
        self.step_up = float((self.cfg.get("mech") or {}).get("step_up", 1.2))
        self.regen_delay = float((self.cfg.get("mech") or {}).get("regen_delay", 5.0))
        self.walk_speed = float((self.cfg.get("mech") or {}).get("walk_speed", 10.0))
        self.npc_avoid = 50.0
        self.drop_avoid = 40.0
        self.mem.strafe_sign = 1.0 if self.mem.rand() > 0.5 else -1.0
        self.mem.positioned = False
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
        self.combat.begin_tick(float(obs["tick"]))
        self.mem.world_on_roof = self.world.on_roof(me["pos"])
        if self.mem.world_on_roof:
            self.mem.time_on_roof += 0.1
        self.mem.update(obs, near_range=self.near_range, world=self.world)

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

        second = _has_second(me)
        mode = self._select_mode(obs, second)
        prev = self.mem.mode
        self.mem.set_mode(mode, t)
        if mode == "FIGHT" and prev != "FIGHT":
            self.mem.fight_start_t = t
            self.mem.fight_start_hp = float(me["hp"])
        if mode != "DISENGAGE" and prev == "DISENGAGE":
            self.mem.disengage_goal = None
        tag = second or "gun"
        mf.draw.label(f"{mode}/{tag} hp={me['hp']:.0f}")

        if mode == "ESCAPE_ZONE":
            self._do_escape(obs, act)
        elif mode == "COUNTER_LASER":
            self._do_counter_laser(obs, act)
        elif mode == "DISENGAGE":
            self._do_disengage(obs, act, second)
        elif mode == "FIGHT":
            self._do_fight(obs, act, second, aggressive=True)
        elif mode == "THIRD":
            self._do_third(obs, act, second)
        elif mode == "ROTATE":
            self._do_rotate(obs, act, second)
        elif mode == "LOOT_SWAP":
            self._do_loot_swap(obs, act, second)
        elif mode == "RESET":
            self._do_reset(obs, act)
        elif mode == "HEAL":
            self._do_heal(obs, act)
        elif mode == "ARM":
            self._do_arm(obs, act)
        elif mode == "RELOCATE":
            self._do_relocate(obs, act, second)
        else:  # CAMP
            self._do_camp(obs, act, second)

        climbing = bool(act.get("boost") or act.get("jump")) and mode in ("RELOCATE", "ROTATE")
        # Bug #4: avoid walks off roofs / can steer ESCAPE back out of the zone.
        if (
            mode not in ("FIGHT", "COUNTER_LASER", "ESCAPE_ZONE", "DISENGAGE", "THIRD")
            and not climbing
            and not self.mem.world_on_roof
        ):
            self._avoid(obs, act)

        # Bug #6: never drop a mid-charge laser blindly when the target leaves view.
        self._laser_charge_hold(obs, act)

        ms = (time.perf_counter() - t_act0) * 1000
        self.mem.max_act_ms = max(self.mem.max_act_ms, ms)
        # Design budget: typical <15ms, worst <30ms of the 50ms tick.
        if ms > 25:
            mf.log(f"slow act {ms:.1f}ms mode={self.mem.mode}")
        return act  # type: ignore[return-value]

    def _ambush_target(
        self, me: Dict[str, Any], enemies: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """1v1 where hunter hasn't locked us / we sit behind them."""
        if len(enemies) != 1:
            return None
        e = enemies[0]
        if _enemy_aware(e, me["pos"]) and not _we_flank(e, me["pos"]):
            return None
        return e

    def _loadout_positioned(self, me: Dict[str, Any], second: str, zone: Dict[str, Any]) -> bool:
        if self.mem.positioned and self.mem.loadout_goal:
            if math.dist(me["pos"][:2], self.mem.loadout_goal[:2]) < 18.0:
                return True
        if second == "laser":
            return bool(self.mem.world_on_roof)
        if second == "mortar":
            # Far from zone edge and not on a roof (ground mortar camp).
            zc, zr = zone["center"], float(zone["radius"])
            d_edge = zr - math.hypot(me["pos"][0] - zc[0], me["pos"][1] - zc[1])
            return d_edge > 0.35 * zr and not self.mem.world_on_roof
        if second == "lightning":
            return not self.mem.world_on_roof and self.mem.loadout_goal is not None and (
                math.dist(me["pos"][:2], self.mem.loadout_goal[:2]) < 22.0
            )
        return False

    def _zone_forces_reloc(self, me: Dict[str, Any], zone: Dict[str, Any], t: float) -> bool:
        goal = self.mem.loadout_goal
        if goal is None and self.mem.roof_id is not None:
            roof = self.cover.roof(self.mem.roof_id)
            if roof:
                goal = roof["center"]
        if goal is None:
            return False
        nc, nr = zone["next_center"], float(zone["next_radius"])
        if (goal[0] - nc[0]) ** 2 + (goal[1] - nc[1]) ** 2 <= (0.8 * nr) ** 2:
            return False
        walk = max(1.0, float((me.get("stats") or {}).get("walk_speed", self.walk_speed)))
        travel = math.hypot(goal[0] - me["pos"][0], goal[1] - me["pos"][1]) / walk
        return float(zone["shrink_end"]) - t < travel + 15

    def _is_ffa(self, obs: mf.Observation) -> bool:
        """Decision 6 stub: FFA detector not implemented. Practice mid-pack path only."""
        # TODO(FFA): detect free-for-all chaos and switch to survival play.
        _ = obs
        return False

    def _safe_cover_goal(self, me: Dict[str, Any], zone: Dict[str, Any], away_bearing: Optional[float]) -> List[float]:
        """Break LOS toward cover / zone-safe ground."""
        if self.mem.camp_hidden is not None:
            return list(self.mem.camp_hidden[:2])
        if self.mem.world_on_roof and self.mem.roof_id is not None:
            roof = self.cover.roof(self.mem.roof_id)
            hid = self.cover.best_hidden(roof) if roof else None
            if hid:
                return list(hid[:2])
        spot = self.cover.ground_spot(me["pos"], zone["center"], float(zone["radius"]))
        if spot is not None:
            return list(spot[:2])
        if away_bearing is not None:
            return [
                me["pos"][0] + math.cos(away_bearing + math.pi) * 35.0,
                me["pos"][1] + math.sin(away_bearing + math.pi) * 35.0,
            ]
        return list(self.nav.zone_goal(zone, me["pos"], 0.55)[:2])

    def _opponent_dies_soon(self, me: Dict[str, Any], enemies: List[Dict[str, Any]], t: float) -> bool:
        """True if the current 1v1 target looks like it will drop within a few seconds."""
        if len(enemies) != 1:
            return False
        e = enemies[0]
        hp = e.get("hp")
        if hp is None:
            # No HP shown — trust recent damage as a proxy.
            return t - self.mem.last_dealt_damage_t < 1.5
        if hp <= 280:
            return True
        if hp <= 450 and t - self.mem.last_dealt_damage_t < 2.0:
            return True
        return False

    def _should_disengage(self, me: Dict[str, Any], visible: List[Dict[str, Any]], t: float) -> bool:
        # R2 (practice): DISENGAGE latches and abandons fights before the kill.
        # Keep the body below for the FFA path (decision 6) once Sameer signs off.
        if True:  # practice: always stay and fight
            return False
        if self.mem.mode == "DISENGAGE" and t < self.mem.disengage_until:
            return True
        in_fight = self.mem.mode in ("FIGHT", "THIRD", "DISENGAGE") or (
            t - self.mem.last_took_weapon_damage_t < 2.5
        )
        if not in_fight and self.mem.mode not in ("FIGHT", "THIRD"):
            return False
        # Another hunter appears and current opponent won't die soon.
        if len(visible) >= 2 and not self._opponent_dies_soon(me, visible[:1], t):
            return True
        # Lost substantial HP (~400) since fight start.
        if self.mem.fight_start_t > 0 and (self.mem.fight_start_hp - me["hp"]) >= 400:
            return True
        # Fight dragged ~12s with no kill (no recent damage dealt).
        if (
            self.mem.fight_start_t > 0
            and t - self.mem.fight_start_t >= 12.0
            and t - self.mem.last_dealt_damage_t > 3.0
        ):
            return True
        return False

    def _want_third(self, me: Dict[str, Any], second: Optional[str], visible: List[Dict[str, Any]], t: float) -> bool:
        """THIRD disabled for practice (R2). Body kept for FFA (decision 6).

        Was practice-gated (v1.10): positioned + healthy + near sound only.
        Shared-vision house hunters punish mid/far crash-ins.
        """
        if True:  # practice: never crash into sound fights
            self.mem.third_commit = False
            return False
        if second is None:
            return False
        if visible:
            return False  # already in contact — FIGHT/DISENGAGE handle it
        # Get second weapon + loadout position before seeking thirds.
        if not self.mem.positioned:
            self.mem.third_commit = False
            return False
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        if hp_frac < 0.7:
            self.mem.third_commit = False
            return False
        if t - self.mem.last_took_weapon_damage_t < 4.0:
            self.mem.third_commit = False
            return False
        if self.mem.combat_noise_since < 0:
            self.mem.third_commit = False
            return False
        age = t - self.mem.combat_noise_since
        if age < 3.0:
            return False  # wait longer than v1.9 — don't crash at first exchange
        if age > 5.5 and not self.mem.third_commit:
            return False
        # Near combat only (single-contact estimate). Mid/far → pack ambush.
        combat_kinds = ("gun", "laser", "laser_charge", "mortar", "explosion", "lightning")
        bearing = None
        near_hits = 0
        for s in reversed(self.mem.sound_log):
            if s.get("kind") not in combat_kinds:
                continue
            if s.get("dist") == "near":
                near_hits += 1
                if bearing is None and s.get("bearing") is not None:
                    bearing = float(s["bearing"])
        if near_hits < 1 or bearing is None:
            self.mem.third_commit = False
            return False
        self.mem.third_bearing = bearing
        self.mem.third_commit = True
        return True

    def _need_rotate(self, me: Dict[str, Any], zone: Dict[str, Any], t: float, second: Optional[str]) -> bool:
        """Get inside next circle (distinct from loadout RELOCATE-to-camp)."""
        nc, nr = zone["next_center"], float(zone["next_radius"])
        dist = math.hypot(me["pos"][0] - nc[0], me["pos"][1] - nc[1])
        inside_next = dist <= 0.85 * nr
        walk = max(1.0, float((me.get("stats") or {}).get("walk_speed", self.walk_speed)))
        travel = max(0.0, dist - 0.7 * nr) / walk
        time_left = float(zone["shrink_end"]) - t
        # Must move before shrink closes us out.
        if not inside_next and time_left < travel + 18.0:
            self.mem.gatekeep = False
            return True
        # Already mid-ROTATE until inside.
        if self.mem.mode == "ROTATE" and not inside_next:
            return True
        # Edge gatekeep late rotators — contingent on weapon + position.
        if second is not None and inside_next and self._can_gatekeep(me, zone, second):
            # Only when shrink is imminent / ongoing and we're near the ring.
            edge_band = abs(dist - 0.9 * nr) < 40.0 or (0.75 * nr <= dist <= 0.98 * nr)
            if edge_band and time_left < 35.0:
                self.mem.gatekeep = True
                return True
        self.mem.gatekeep = False
        return False

    def _can_gatekeep(self, me: Dict[str, Any], zone: Dict[str, Any], second: str) -> bool:
        """Decision 6: mortar far-edge OK; laser roof sightlines OK; lightning only with cover."""
        nc, nr = zone["next_center"], float(zone["next_radius"])
        dist = math.hypot(me["pos"][0] - nc[0], me["pos"][1] - nc[1])
        if second == "mortar":
            # Far edge of next circle, ground.
            return not self.mem.world_on_roof and dist >= 0.55 * nr
        if second == "laser":
            return bool(self.mem.world_on_roof)
        if second == "lightning":
            # Need corner/cover on the edge path.
            if self.mem.world_on_roof:
                return False
            spot = self.cover.corner_spot(me["pos"], nc, nr)
            if spot is None:
                return False
            return math.dist(me["pos"][:2], spot[:2]) < 40.0
        return False

    def _loot_swap_target(
        self, me: Dict[str, Any], second: Optional[str], t: float
    ) -> Optional[Dict[str, Any]]:
        """Limited swaps: never mortar→lightning; no long camp abandon for speculative loot."""
        if second is None:
            return None
        if self.mem.mode == "DISENGAGE":
            return None
        loot = self.mem.best_loot(
            me["pos"], t, world=self.world, on_roof=self.mem.world_on_roof, step_up=self.step_up
        )
        if loot is None:
            return None
        d = math.dist(loot["pos"][:2], me["pos"][:2])
        # Don't abandon a good camp just to hunt a counter across the map.
        if self.mem.positioned and d > 55.0:
            return None
        if d > 90.0:
            return None
        kind = loot["kind"]
        # Prefer laser > mortar > lightning. Never drop mortar to grab lightning.
        if second == "mortar" and kind == "lightning":
            return None
        if second == "laser":
            return None  # already top tier
        if second == "mortar" and kind == "laser":
            return loot
        if second == "lightning" and kind in ("laser", "mortar"):
            return loot
        return None

    def _want_supply(self, obs: mf.Observation, second: Optional[str]) -> Optional[Dict[str, Any]]:
        """Contest drops only if few hunters left and we look capable."""
        me = obs["self"]
        alive = int(obs.get("alive") or 16)
        if alive > 5:
            self.mem.contest_drop_id = None
            return None
        if second is None:
            return None
        if self.mem.mode == "DISENGAGE":
            return None
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        if hp_frac < 0.55:
            return None
        best = None
        best_d = 1e9
        for d in obs.get("drops") or []:
            lands = float(d.get("lands_in") or 0)
            if lands > 25.0:
                continue
            dist = math.dist(d["pos"][:2], me["pos"][:2])
            if dist < best_d:
                best_d = dist
                best = d
        if best is None or best_d > 160.0:
            self.mem.contest_drop_id = None
            return None
        self.mem.contest_drop_id = int(best["id"])
        return best

    def _select_mode(self, obs: mf.Observation, second: Optional[str]) -> str:
        """Practice mid-pack path. Priority vs ARM/FIGHT/CAMP/RELOCATE/HEAL/ESCAPE/COUNTER_LASER.

        Decision 6 FFA is stubbed — do not invent FFA survival logic here.
        """
        me = obs["self"]
        t = float(obs["t"])
        hp_frac = me["hp"] / max(1.0, me["max_hp"])
        _ = self._is_ffa(obs)  # stub touch so the practice/FFA fork stays visible

        if not me.get("in_zone", True):
            return "ESCAPE_ZONE"

        # Laser charged at us: COUNTER_LASER (prefer safe ground; drop only if needed).
        laser_threat = False
        if _slot_of(me, "mortar") is not None:
            for m in obs.get("mechs") or []:
                if m.get("kind") != "mech" or not m.get("charging"):
                    continue
                aim = m.get("aim") or [0, 0]
                bearing_to_us = math.atan2(me["pos"][1] - m["pos"][1], me["pos"][0] - m["pos"][0])
                if abs(_angdiff(aim[0], bearing_to_us)) < math.radians(10):
                    laser_threat = True
                    break
        if laser_threat:
            return "COUNTER_LASER"

        recent_dmg = t - self.mem.last_took_weapon_damage_t < 1.5
        visible = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        loot = self.mem.best_loot(
            me["pos"], t, world=self.world, on_roof=self.mem.world_on_roof, step_up=self.step_up
        )
        loot_d = math.dist(loot["pos"][:2], me["pos"][:2]) if loot else 1e9
        enemy_d = min((math.dist(m["pos"][:2], me["pos"][:2]) for m in visible), default=1e9)

        # Stay in DISENGAGE until cover / timer. (R2 practice: _should_disengage
        # is False, so we only clear a stale DISENGAGE if somehow entered.)
        if self.mem.mode == "DISENGAGE" and t < self.mem.disengage_until:
            if not visible or enemy_d > 55:
                # Reached relative safety → fall through (RESET disabled in practice).
                pass
            else:
                return "DISENGAGE"

        if self._should_disengage(me, visible, t):
            self.mem.disengage_until = t + 4.0
            self.mem.positioned = False
            return "DISENGAGE"

        # Bug #2: keep RELOCATE through contact so mid-climb sightings don't drop us.
        if second is not None and not self.mem.world_on_roof:
            ct = self.mem.climb_target
            climb_d = math.dist(me["pos"][:2], ct[:2]) if ct is not None else 1e9
            near_climb = climb_d <= 10.0
            airborne = not me.get("grounded")
            if airborne and (self.mem.mode == "RELOCATE" or near_climb):
                return "RELOCATE"
            if self.mem.mode == "RELOCATE" and near_climb:
                return "RELOCATE"
            if second == "laser" and not recent_dmg and (
                climb_d + 8.0 < enemy_d or (not self.mem.positioned and enemy_d > 70.0)
            ):
                return "RELOCATE"

        # Ambush 1v1: armed OK; gun-only only when truly close + rear/undetected.
        ambush = self._ambush_target(me, visible)
        if ambush is not None:
            gun_only_close = second is None and enemy_d < 50 and _we_flank(ambush, me["pos"])
            if second is not None or gun_only_close:
                if not (second is None and loot is not None and loot_d + 20 < enemy_d and loot_d < 70):
                    return "FIGHT"

        # Damaged / multi-contact: don't duel packs gun-only at mid range.
        if recent_dmg or len(visible) >= 2:
            if second is None:
                if loot is not None and loot_d + 15 < enemy_d and loot_d < 110:
                    return "ARM"
                # Pack in view, not pressed close → keep arming instead of suicide push.
                if len(visible) >= 2 and enemy_d > 45 and not recent_dmg:
                    return "ARM"
            return "FIGHT"

        if visible and (second is not None or enemy_d < 120):
            aware = any(_enemy_aware(e, me["pos"]) for e in visible)
            if second is None:
                # Gun-only: fight only close/aware contact; else finish ARM.
                if enemy_d < 55 or (aware and enemy_d < 80) or recent_dmg:
                    if loot is not None and loot_d + 15 < enemy_d and loot_d < 90:
                        return "ARM"
                    return "FIGHT"
            else:
                # Armed: fight if spotted/damaged/already camped; else set up first.
                if aware or recent_dmg or self.mem.positioned or enemy_d < 70:
                    return "FIGHT"
                # Unpositioned + undetected mid-range → fall through to RELOCATE/CAMP.

        # THIRD: disabled for practice via _want_third (R2); body kept for FFA.
        if self._want_third(me, second, visible, t):
            return "THIRD"

        # ROTATE into next circle / edge gatekeep (before loadout RELOCATE).
        if second is not None and self._need_rotate(me, obs["zone"], t, second):
            return "ROTATE"

        # LOOT_SWAP: limited upgrades near us.
        if self._loot_swap_target(me, second, t) is not None:
            return "LOOT_SWAP"

        safe_for_regen = (
            t - self.mem.last_took_weapon_damage_t >= self.regen_delay
            and t - self.mem.last_dealt_damage_t >= self.regen_delay
            and not visible
        )
        # R2 (practice): RESET disabled — it paired with latching DISENGAGE.
        # Keep HEAL for critically low HP when safe. FFA can re-enable RESET.
        if False and safe_for_regen and (
            self.mem.mode in ("DISENGAGE", "RESET")
            or (hp_frac < 0.85 and t - self.mem.fight_start_t < 30 and self.mem.fight_start_t > 0)
        ):
            if hp_frac < 0.98:
                return "RESET"

        if safe_for_regen and hp_frac < 0.65:
            return "HEAL"

        if second is None:
            return "ARM"

        # Armed: set up loadout camp, then hold. Relocate when burnt / zone leaves camp.
        burnt = self.mem.shots_here > 12 or self.mem.mortars_here >= 3
        if burnt:
            self.mem.positioned = False
            self.mem.loadout_goal = None
            self.mem.reset_camp_counters()
            return "RELOCATE"
        if self._zone_forces_reloc(me, obs["zone"], t):
            # Zone left the camp — rotate into next circle first.
            return "ROTATE"

        if not self._loadout_positioned(me, second, obs["zone"]):
            return "RELOCATE"
        self.mem.positioned = True
        return "CAMP"

    def _do_disengage(self, obs: mf.Observation, act: Dict[str, Any], second: Optional[str] = None) -> None:
        """Break LOS, stop shooting when appropriate, path to cover / zone-safe."""
        me = obs["self"]
        t = float(obs["t"])
        visible = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        away = self.mem.last_threat_bearing
        if away is None and visible:
            away = math.atan2(visible[0]["pos"][1] - me["pos"][1], visible[0]["pos"][0] - me["pos"][0])
        if self.mem.disengage_goal is None:
            self.mem.disengage_goal = self._safe_cover_goal(me, obs["zone"], away)
        goal = self.mem.disengage_goal
        move, yaw = self.nav.steer(me, goal, 1.0, t)
        act["move"] = move
        act["boost"] = me["energy"] / max(1.0, me["max_energy"]) > 0.3
        act["aim"] = [away if away is not None else yaw, -0.05]
        # Stop shooting once LOS is broken / we put cover between us; peek-fire only if still pressed.
        still_pressed = False
        for e in visible:
            if self.combat.clear_shot(me, e["pos"], int(e["id"])):
                still_pressed = True
                break
        recent_hit = t - self.mem.last_took_weapon_damage_t < 1.0
        if still_pressed and recent_hit:
            self._try_fight_overlay(obs, act)
        else:
            act["fire"] = [False, False]
        self.nav.update_stuck(me, t, True)
        if self.mem.stuck_until > t:
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True
        _ = second

    def _do_reset(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        """Sit for regen (respect regen_delay), scan; only when safe."""
        me = obs["self"]
        t = float(obs["t"])
        act["fire"] = [False, False]
        act["boost"] = False
        act["jump"] = False
        # Hold cover if we have it; else freeze and scan.
        if self.mem.disengage_goal and math.dist(me["pos"][:2], self.mem.disengage_goal[:2]) > 6.0:
            move, yaw = self.nav.steer(me, self.mem.disengage_goal, 0.45, t)
            act["move"] = move
            act["aim"] = [yaw, -0.05]
        elif self.mem.camp_hidden and math.dist(me["pos"][:2], self.mem.camp_hidden[:2]) > 4.0:
            move, yaw = self.nav.steer(me, self.mem.camp_hidden, 0.4, t)
            act["move"] = move
            act["aim"] = [yaw, -0.05]
        else:
            act["move"] = [0.0, 0.0]
            act["aim"] = [self.mem.scan_yaw, -0.05]
        if self.mem.last_threat_bearing is not None:
            # Face last threat while regen clock ticks.
            quiet = (
                t - self.mem.last_took_weapon_damage_t >= self.regen_delay
                and t - self.mem.last_dealt_damage_t >= self.regen_delay
            )
            if not quiet:
                act["aim"] = [self.mem.last_threat_bearing, -0.05]

    def _do_third(self, obs: mf.Observation, act: Dict[str, Any], second: Optional[str] = None) -> None:
        """Sound-driven third-party: wait already done in selector; crash; abort if 2nd hunter."""
        me = obs["self"]
        t = float(obs["t"])
        visible = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        # Abort if a second hunter appears / approach looks bad.
        if len(visible) >= 2:
            self.mem.third_commit = False
            return self._do_disengage(obs, act, second)
        if me["hp"] / max(1.0, me["max_hp"]) < 0.35:
            self.mem.third_commit = False
            return self._do_disengage(obs, act, second)
        if visible:
            # One hunter in view — take the fight (crash arrived).
            return self._do_fight(obs, act, second, aggressive=True)
        bearing = self.mem.third_bearing
        if bearing is None:
            bearing = self.mem.last_threat_bearing or me["aim"][0]
        goal = [
            me["pos"][0] + math.cos(bearing) * 55.0,
            me["pos"][1] + math.sin(bearing) * 55.0,
        ]
        # Keep goal inside zone.
        zc, zr = obs["zone"]["center"], float(obs["zone"]["radius"])
        if (goal[0] - zc[0]) ** 2 + (goal[1] - zc[1]) ** 2 > (0.9 * zr) ** 2:
            goal = self.nav.zone_goal(obs["zone"], me["pos"], 0.7)
        move, yaw = self.nav.steer(me, goal, 1.0, t)
        act["move"] = move
        act["boost"] = me["energy"] / max(1.0, me["max_energy"]) > 0.4
        act["aim"] = [bearing, -0.05]
        self.nav.update_stuck(me, t, True)
        if self.mem.stuck_until > t:
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True

    def _do_rotate(self, obs: mf.Observation, act: Dict[str, Any], second: Optional[str] = None) -> None:
        """Move into next circle; optional edge gatekeep for late rotators."""
        me = obs["self"]
        t = float(obs["t"])
        z = obs["zone"]
        nc, nr = z["next_center"], float(z["next_radius"])
        if self.mem.gatekeep and second is not None:
            # Hold near the ring facing outward for late rotators.
            dist = math.hypot(me["pos"][0] - nc[0], me["pos"][1] - nc[1])
            if dist < 0.82 * nr:
                # Step out toward edge.
                ang = math.atan2(me["pos"][1] - nc[1], me["pos"][0] - nc[0])
                goal = [nc[0] + math.cos(ang) * 0.9 * nr, nc[1] + math.sin(ang) * 0.9 * nr]
            else:
                goal = list(me["pos"][:2])
            self.mem.rotate_goal = goal
            if math.dist(me["pos"][:2], goal[:2]) > 8.0:
                move, yaw = self.nav.steer(me, goal, 0.7, t)
                act["move"] = move
            else:
                act["move"] = [0.0, 0.0]
                yaw = math.atan2(me["pos"][1] - nc[1], me["pos"][0] - nc[0])
            act["aim"] = [yaw, -0.05]
            # Overlay if someone is closing from outside.
            self._try_fight_overlay(obs, act)
            return
        # Destination: deep-ish inside next circle (not loadout camp).
        if self.mem.rotate_goal is None:
            self.mem.rotate_goal = [nc[0], nc[1]]
            # Bias slightly toward current pos so we don't cross the whole map center needlessly.
            ang = math.atan2(me["pos"][1] - nc[1], me["pos"][0] - nc[0])
            self.mem.rotate_goal = [
                nc[0] + math.cos(ang) * 0.45 * nr,
                nc[1] + math.sin(ang) * 0.45 * nr,
            ]
        goal = self.mem.rotate_goal
        move, yaw = self.nav.steer(me, goal, 1.0, t)
        act["move"] = move
        act["boost"] = me["energy"] / max(1.0, me["max_energy"]) > 0.35
        act["aim"] = [yaw, -0.05]
        if math.hypot(me["pos"][0] - nc[0], me["pos"][1] - nc[1]) <= 0.8 * nr:
            self.mem.rotate_goal = None
        self._try_fight_overlay(obs, act)

    def _do_loot_swap(self, obs: mf.Observation, act: Dict[str, Any], second: Optional[str] = None) -> None:
        """Grab a nearby upgrade weapon under LOOT_SWAP rules."""
        me = obs["self"]
        t = float(obs["t"])
        target = self._loot_swap_target(me, second, t)
        if target is None:
            return self._do_arm(obs, act)
        visible = {int(p["id"]): p for p in (obs.get("pickups") or []) if p.get("kind") != "gun"}
        goal = target["pos"]
        if int(target["id"]) in visible:
            goal = visible[int(target["id"])]["pos"]
            if math.dist(goal[:2], me["pos"][:2]) <= self.loot_r - 0.3:
                act["take"] = target["id"]
        move, yaw = self.nav.steer(me, goal, 1.0, t)
        act["move"] = move
        act["aim"] = [math.atan2(goal[1] - me["pos"][1], goal[0] - me["pos"][0]), -0.05]
        act["boost"] = me["energy"] / max(1.0, me["max_energy"]) > 0.4
        self._try_fight_overlay(obs, act)

    def _do_escape(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        goal = self.nav.zone_goal(obs["zone"], me["pos"], 0.65)
        move, yaw = self.nav.steer(me, goal, 1.0, t)
        act["move"] = move
        act["boost"] = True
        act["aim"] = [yaw, -0.05]
        self._try_fight_overlay(obs, act)

    def _do_counter_laser(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        """Prefer break-LOS / safe ground vs laser; drop mortar only if we can't get safe."""
        me = obs["self"]
        t = float(obs["t"])
        away = self.mem.last_threat_bearing
        safe = self._safe_cover_goal(me, obs["zone"], away)
        d_safe = math.dist(me["pos"][:2], safe[:2])
        # Can we break toward cover quickly?
        can_safe = d_safe < 45.0 or self.mem.world_on_roof or self.mem.camp_hidden is not None
        slot = _slot_of(me, "mortar")
        if slot is not None and not can_safe:
            act["drop"] = slot  # existing cook-off counter when escape isn't available
        move, yaw = self.nav.steer(me, safe, 1.0, t)
        act["move"] = move
        act["boost"] = True
        act["aim"] = [away if away is not None else yaw, 0.0]
        act["fire"] = [False, False]

    def _do_fight(
        self,
        obs: mf.Observation,
        act: Dict[str, Any],
        second: Optional[str] = None,
        aggressive: bool = False,
    ) -> None:
        me = obs["self"]
        t = float(obs["t"])
        enemies = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        target, chase = self.combat.pick_fight_targets(me, enemies, self.mem.last_threat_id)
        chase = target or chase
        if chase is None and self.mem.last_threat_id in self.mem.enemies:
            chase = self.mem.enemies[self.mem.last_threat_id]
        if chase is None and self.mem.enemies:
            chase = min(
                self.mem.enemies.values(),
                key=lambda e: math.dist(e["pos"][:2], me["pos"][:2]),
            )

        if chase is None:
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
            move, _ = self.nav.steer(me, goal, 0.9, t)
            act["move"] = move
            act["boost"] = me["energy"] / me["max_energy"] > 0.45
            act["fire"] = [True, False]
            return

        clear = target is not None and int(target["id"]) == int(chase["id"])
        if not clear:
            clear = self.combat.clear_shot(me, chase["pos"], int(chase.get("id", -1)))

        flank = _we_flank(chase, me["pos"])
        undetected = not _enemy_aware(chase, me["pos"])
        push_hard = aggressive and (flank or undetected) and len(enemies) <= 1

        dist = math.dist(chase["pos"][:2], me["pos"][:2])
        # R1: gun is primary whenever it has a clear shot. Specials only when useful.
        kind = "gun"
        if second == "laser":
            kind = "laser" if clear else "gun"
        elif second == "mortar":
            mw = self.combat.weapons.get("mortar") or {}
            v = float(mw.get("speed", 72))
            g = float(mw.get("gravity", 22))
            mortar_max = (v * v / g) if g > 0 else 235.0
            if not clear and 12.0 < dist < mortar_max:
                kind = "mortar"
            else:
                kind = "gun"
        elif second == "lightning":
            lr = float((self.combat.weapons.get("lightning") or {}).get("range", 45))
            kind = "lightning" if clear and dist <= lr else "gun"
        # Bug #8: invalid mortar lob → gun (never pitch-0.6 skyfire).
        if kind == "mortar":
            feet = [chase["pos"][0], chase["pos"][1], chase["pos"][2]]
            if self.combat.mortar_aim(me, feet, chase.get("vel") or [0, 0, 0]) is None:
                kind = "gun"
        # Bug #7: gun lead between laser shots; never fire gun on mortar lob aim.
        kind, aim_kind = self._fight_aim_kind(me, kind)
        aim = self.combat.aim_at(me, chase, kind)
        act["aim"] = aim
        fire, reload, _ = self.combat.fire_slots(me, aim, chase, t, self.mem, aim_kind=aim_kind)
        act["fire"] = fire
        act["reload"] = reload
        mf.draw.line(
            self.combat.muzzle(me),
            [
                chase["pos"][0],
                chase["pos"][1],
                self.combat.com_z(chase["pos"][2], chase.get("cubes")),
            ],
            "#ff5040",
        )

        bearing = math.atan2(chase["pos"][1] - me["pos"][1], chase["pos"][0] - me["pos"][0])
        energy_ok = me["energy"] / me["max_energy"] > 0.35

        # Laser on roof: hold firing edge for vision.
        if second == "laser" and self.mem.world_on_roof:
            roof = self.cover.roof(self.mem.roof_id) if self.mem.roof_id is not None else None
            if roof is None:
                rid = self.world.roof_at(me["pos"][0], me["pos"][1])
                self.mem.roof_id = rid
                roof = self.cover.roof(rid) if rid is not None else None
            if roof:
                fp = self.cover.best_firing(roof, bearing)
                if fp:
                    move, _ = self.nav.steer(me, fp, 0.85, t)
                    act["move"] = move
                    return
            act["move"] = [0.0, 0.0]
            return

        # Mortar: keep range, don't rush into gun range unless flanking hard.
        if second == "mortar":
            prefer = 110.0
            if dist < prefer - 25 and not push_hard:
                away = bearing + math.pi
                act["move"] = [math.cos(away) * 0.85, math.sin(away) * 0.85]
                act["boost"] = energy_ok and dist < 70
            elif dist > prefer + 20 or (not clear and dist > 50):
                move, _ = self.nav.steer(me, chase["pos"], 0.7, t)
                act["move"] = move
            else:
                side = bearing + (math.pi / 2) * self.mem.strafe_sign
                act["move"] = [math.cos(side) * 0.55, math.sin(side) * 0.55]
            return

        # Lightning: close corners — close gap, hug cover, burst.
        if second == "lightning":
            if dist > 35 or not clear:
                move, _ = self.nav.steer(me, chase["pos"], 1.0, t)
                act["move"] = move
                act["boost"] = energy_ok and (dist > 40 or push_hard)
            else:
                side = bearing + (math.pi / 2) * self.mem.strafe_sign
                act["move"] = [math.cos(side) * 0.8, math.sin(side) * 0.8]
            self.nav.update_stuck(me, t, True)
            if self.mem.stuck_until > t:
                act["jump"] = bool(me.get("grounded"))
                act["boost"] = True
            return

        # Gun / laser ground / generic: take the fight. Ambush → commit.
        close_at = 55.0 if push_hard else 75.0
        if not clear or dist > close_at:
            move, _ = self.nav.steer(me, chase["pos"], 1.0, t)
            act["move"] = move
            act["boost"] = energy_ok and (dist > 50 or push_hard)
        else:
            side = bearing + (math.pi / 2) * self.mem.strafe_sign
            act["move"] = [math.cos(side) * 0.75, math.sin(side) * 0.75]
        self.nav.update_stuck(me, t, True)
        if self.mem.stuck_until > t:
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True

    def _do_heal(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
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
                move, _ = self.nav.steer(me, hid, 0.6, t)
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
            move, yaw = self.nav.steer(me, spot, 0.6, t)
            act["move"] = move
            if "aim" not in act:
                act["aim"] = [yaw, -0.05]

    def _do_arm(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        t = float(obs["t"])
        # Do NOT abandon arming when enemies appear — fight while we loot.
        # (Old 150 m flee left us gun-only forever against hunter squads.)

        best = self.mem.best_loot(
            me["pos"], t, world=self.world, on_roof=self.mem.world_on_roof, step_up=self.step_up
        )
        # Prefer currently visible ids for take
        visible = {int(p["id"]): p for p in (obs.get("pickups") or []) if p.get("kind") != "gun"}
        if best and int(best["id"]) in visible:
            best = {
                "id": best["id"],
                "kind": visible[int(best["id"])]["kind"],
                "pos": list(visible[int(best["id"])]["pos"]),
            }
        elif not best and visible:
            # rank visible only (still skip elevated roof loot from the ground)
            best = None
            best_score = -1e9
            for p in visible.values():
                if self._loot_is_elevated_roof(p["pos"]) and not self.mem.world_on_roof:
                    continue
                if self.mem.world_on_roof and not self._loot_on_our_roof(me["pos"], p["pos"]):
                    continue
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
            # Server take limit is loot_r horizontally; stay slightly inside to avoid range spam.
            if math.dist(best["pos"][:2], me["pos"][:2]) <= self.loot_r - 0.3:
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

        move, yaw = self.nav.steer(me, goal, 1.0, t)
        act["move"] = move
        # Face loot while moving; otherwise scan for pickups (FOV is yaw-based).
        if best is not None:
            act["aim"] = [math.atan2(best["pos"][1] - me["pos"][1], best["pos"][0] - me["pos"][0]), -0.05]
        else:
            act["aim"] = [self.mem.scan_yaw, -0.05]
        # Quieter early loot (v1.10): loud boosts pull shared-vision hunters onto ARM.
        # Out of zone always; otherwise only high energy (was efrac>0.35 while chasing).
        efrac = me["energy"] / max(1.0, me["max_energy"])
        act["boost"] = (not me.get("in_zone", True)) or efrac > 0.65
        self.nav.update_stuck(me, t, True)
        if self.mem.stuck_until > t:
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True

        # Return fire while arming
        self._try_fight_overlay(obs, act)

    def _do_relocate(self, obs: mf.Observation, act: Dict[str, Any], second: Optional[str] = None) -> None:
        me = obs["self"]
        t = float(obs["t"])
        z = obs["zone"]
        enemies = [m for m in (obs.get("mechs") or []) if m.get("kind") == "mech"]
        away = None
        if self.mem.last_threat_bearing is not None:
            away = [
                me["pos"][0] + math.cos(self.mem.last_threat_bearing) * 40.0,
                me["pos"][1] + math.sin(self.mem.last_threat_bearing) * 40.0,
            ]
        elif enemies:
            away = enemies[0]["pos"]

        # Mortar: deep ground camp — no climb.
        if second == "mortar":
            spot = self.mem.loadout_goal
            if spot is None:
                spot = self.cover.far_ground_spot(
                    me["pos"], z["next_center"], float(z["next_radius"]), away_from=away
                )
                if spot is None:
                    spot = self.nav.zone_goal(z, me["pos"], 0.55)
                self.mem.loadout_goal = list(spot[:2])
                self.mem.reset_camp_counters()
            move, yaw = self.nav.steer(me, self.mem.loadout_goal, 0.85, t)
            act["move"] = move
            act["aim"] = [yaw, -0.05]
            act["boost"] = me["energy"] / me["max_energy"] > 0.4
            act["jump"] = False
            if enemies:
                self._try_fight_overlay(obs, act)
            return

        # Lightning: tight corner — no climb.
        if second == "lightning":
            spot = self.mem.loadout_goal
            if spot is None:
                spot = self.cover.corner_spot(me["pos"], z["next_center"], float(z["next_radius"]))
                if spot is None:
                    spot = self.cover.ground_spot(me["pos"], z["center"], float(z["radius"]))
                if spot is None:
                    spot = self.nav.zone_goal(z, me["pos"], 0.5)
                self.mem.loadout_goal = list(spot[:2])
                self.mem.reset_camp_counters()
            move, yaw = self.nav.steer(me, self.mem.loadout_goal, 0.9, t)
            act["move"] = move
            act["aim"] = [yaw, -0.05]
            act["boost"] = me["energy"] / me["max_energy"] > 0.45
            act["jump"] = False
            if enemies:
                self._try_fight_overlay(obs, act)
            return

        # Laser (default): climb a roof for vision.
        roof = self.cover.pick_roof(me["pos"], z["next_center"], float(z["next_radius"]))
        if roof is None:
            spot = self.cover.ground_spot(me["pos"], z["center"], float(z["radius"]))
            goal = spot or self.nav.zone_goal(z, me["pos"], 0.5)
            self.mem.loadout_goal = list(goal[:2])
            move, yaw = self.nav.steer(me, goal, 0.7, t)
            act["move"] = move
            act["aim"] = [yaw, -0.05]
            act["boost"] = False
            return

        picked_id = int(roof["id"])
        if self.mem.roof_id != picked_id:
            self.mem.roof_id = picked_id
            self.mem.reset_camp_counters()
        climb = self.cover.nearest_climb(roof, me["pos"])
        # Bug #3: only "arrived" when on the picked roof id — not any roof.
        here_rid = self.world.roof_at(me["pos"][0], me["pos"][1])
        if here_rid is not None and int(here_rid) == picked_id:
            hid = self.cover.best_hidden(roof)
            self.mem.reset_camp_counters()
            self.mem.camp_hidden = hid
            self.mem.loadout_goal = list((hid or roof["center"])[:2])
            self.mem.roofs_used.add(picked_id)
            if hid:
                move, yaw = self.nav.steer(me, hid, 0.6, t)
                act["move"] = move
                act["aim"] = [yaw, -0.05]
            return

        # Climb even with enemies visible — waiting at the base is free kills for hunters.
        self.mem.loadout_goal = list(roof["center"][:2])
        if climb:
            self.mem.climb_target = climb
            climb_act = self.nav.climb_action(me, roof, climb, t)
            act.update(climb_act)
        else:
            move, yaw = self.nav.steer(me, roof["center"], 0.8, t)
            act["move"] = move
            act["aim"] = [yaw, 0.15]
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True
        if enemies:
            self._try_fight_overlay(obs, act)

    def _do_camp(self, obs: mf.Observation, act: Dict[str, Any], second: Optional[str] = None) -> None:
        me = obs["self"]
        t = float(obs["t"])
        # Supply drops: only contest when few hunters left and we look capable.
        drop = self._want_supply(obs, second)
        if drop is not None:
            goal = drop["pos"]
            if math.dist(me["pos"][:2], goal[:2]) > 6.0:
                move, yaw = self.nav.steer(me, goal, 0.85, t)
                act["move"] = move
                act["aim"] = [yaw, -0.05]
                act["boost"] = me["energy"] / max(1.0, me["max_energy"]) > 0.4
                self._try_fight_overlay(obs, act)
                return

        if second == "mortar":
            goal = self.mem.loadout_goal
            if goal is None:
                return self._do_relocate(obs, act, second)
            if math.dist(me["pos"][:2], goal[:2]) > 12.0:
                move, yaw = self.nav.steer(me, goal, 0.55, t)
                act["move"] = move
            else:
                act["move"] = [0.0, 0.0]
                yaw = me["aim"][0]
            aim_yaw = self.mem.last_threat_bearing if self.mem.last_threat_bearing is not None else yaw
            if self.mem.last_threat_bearing is None:
                zc = obs["zone"]["center"]
                aim_yaw = math.atan2(zc[1] - me["pos"][1], zc[0] - me["pos"][0])
            act["aim"] = [aim_yaw, -0.05]
            # Lob on mid/far combat sounds from far ground.
            if t - self.mem.last_mortar_t >= self.combat.mortar_gap():
                for s in self.mem.sound_log:
                    if s.get("kind") in ("gun", "laser", "laser_charge", "explosion") and s.get("dist") in (
                        "mid",
                        "far",
                    ):
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
                                if slot is not None:
                                    fire = [False, False]
                                    fire[slot] = True
                                    act["fire"] = fire
                                    self.mem.last_mortar_t = t
                                    self.mem.mortars_here += 1
                                    self.mem.mortars += 1
                        break
            self._try_fight_overlay(obs, act)
            return

        if second == "lightning":
            goal = self.mem.loadout_goal
            if goal is None:
                return self._do_relocate(obs, act, second)
            # Hold corner, stay low-profile (no boost/jump).
            if math.dist(me["pos"][:2], goal[:2]) > 8.0:
                move, yaw = self.nav.steer(me, goal, 0.5, t)
                act["move"] = move
            else:
                act["move"] = [0.0, 0.0]
                yaw = me["aim"][0]
            act["boost"] = False
            act["jump"] = False
            aim_yaw = self.mem.last_threat_bearing if self.mem.last_threat_bearing is not None else yaw
            for s in self.mem.sound_log:
                if s.get("dist") == "near" and s.get("kind") in ("step", "boost", "jet", "gun", "lightning"):
                    aim_yaw = float(s["bearing"])
                    break
            act["aim"] = [aim_yaw, -0.05]
            # Fight when someone is close / visible.
            near = False
            for m in obs.get("mechs") or []:
                if m.get("kind") == "mech" and math.dist(m["pos"][:2], me["pos"][:2]) < 55:
                    near = True
                    break
            if near or any(s.get("dist") == "near" for s in self.mem.sound_log):
                self._try_fight_overlay(obs, act)
            return

        # Laser / default: roof peek camp.
        # Prefer live roof under feet; never treat roof id 0 as missing via `or`.
        here_rid = self.world.roof_at(me["pos"][0], me["pos"][1])
        rid = here_rid if here_rid is not None else self.mem.roof_id
        if rid is not None and self.mem.roof_id != int(rid):
            self.mem.roof_id = int(rid)
            self.mem.reset_camp_counters()
        elif rid is not None:
            self.mem.roof_id = int(rid)
        roof = self.cover.roof(rid) if rid is not None else None
        if roof is None:
            return self._do_relocate(obs, act, second)

        toward = self.mem.last_threat_bearing
        if toward is None:
            zc = obs["zone"]["center"]
            toward = math.atan2(zc[1] - me["pos"][1], zc[0] - me["pos"][0])

        # Bug #3: rebind fire/hidden for this roof; peek toward threat bearing.
        if self.mem.camp_fire is None:
            self.mem.camp_fire = self.cover.best_firing(roof, toward)
        fire_pt = self.mem.camp_fire
        if self.mem.camp_hidden is None:
            hid_pts = roof.get("hidden_points") or []
            if fire_pt and hid_pts:
                # Prefer a hide spot near the chosen firing edge so peeks can reach it.
                best_h = min(
                    hid_pts,
                    key=lambda p: (p[0] - fire_pt[0]) ** 2 + (p[1] - fire_pt[1]) ** 2,
                )
                self.mem.camp_hidden = [best_h[0], best_h[1]]
            else:
                self.mem.camp_hidden = self.cover.best_hidden(roof)
        hid = self.mem.camp_hidden
        if hid is not None:
            self.mem.loadout_goal = list(hid[:2])

        # peek cadence: hold peek until near fire_pt (timeout ~2.5 s)
        if t >= self.mem.next_peek_t and self.mem.peek_phase == 0:
            self.mem.peek_phase = 1
            self.mem.peek_until = t + 2.5
            self.mem.next_peek_t = t + 4.0
            self.mem.camp_fire = self.cover.best_firing(roof, toward)
            fire_pt = self.mem.camp_fire
        if self.mem.peek_phase == 1:
            near_fire = (
                fire_pt is not None and math.dist(me["pos"][:2], fire_pt[:2]) <= 2.0
            )
            if near_fire or t >= self.mem.peek_until:
                self.mem.peek_phase = 0

        goal = fire_pt if self.mem.peek_phase == 1 and fire_pt else hid
        if goal:
            move, yaw = self.nav.steer(me, goal, 0.4, t)
            act["move"] = move
        else:
            act["move"] = [0.0, 0.0]
            yaw = me["aim"][0]

        # aim
        aim_yaw = toward if self.mem.last_threat_bearing is not None else yaw
        if self.mem.last_threat_bearing is None:
            zc = obs["zone"]["center"]
            aim_yaw = math.atan2(zc[1] - me["pos"][1], zc[0] - me["pos"][0])
        act["aim"] = [aim_yaw, -0.05]

        # near step/boost/jet sounds
        for s in self.mem.sound_log:
            if s.get("dist") == "near" and s.get("kind") in ("step", "boost", "jet"):
                act["aim"] = [float(s["bearing"]), -0.05]
                break

        # mortar lob on mid/far gun/laser (if somehow dual-wielding / leftover)
        if _slot_of(me, "mortar") is not None and t - self.mem.last_mortar_t >= self.combat.mortar_gap():
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
        kind, aim_kind = self._fight_aim_kind(me, kind)
        aim = self.combat.aim_at(me, target, kind)
        act["aim"] = aim
        fire, reload, _ = self.combat.fire_slots(me, aim, target, t, self.mem, aim_kind=aim_kind)
        act["fire"] = fire
        if reload:
            act["reload"] = True

    def _fight_aim_kind(self, me: Dict[str, Any], kind: str) -> tuple[str, str]:
        """Pick aim weapon + fire_slots aim_kind (bug #7)."""
        if kind == "mortar":
            return "mortar", "mortar"
        if kind == "laser":
            slot = _slot_of(me, "laser")
            if slot is not None:
                w = (me.get("weapons") or [])[slot]
                charge = float((w or {}).get("charge") or 0)
                cd = float((w or {}).get("cooldown") or 0)
                # Between laser shots (cooling, not charging): lead with the gun.
                if charge <= 0.02 and cd > 0 and _slot_of(me, "gun") is not None:
                    return "gun", "gun"
            return "laser", "laser"
        if kind == "lightning":
            return "lightning", "lightning"
        return "gun", "gun"

    def _laser_charge_hold(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        """Final pass: keep / release a laser that was charging when the target vanished."""
        me = obs["self"]
        t = float(obs["t"])
        mode = self.mem.mode
        # R5: modes that deliberately set fire=False must not be overridden.
        climbing = bool(act.get("boost") or act.get("jump")) and mode in ("RELOCATE", "ROTATE")
        if mode in ("COUNTER_LASER", "ESCAPE_ZONE") or (mode == "RELOCATE" and climbing):
            return
        weapons = me.get("weapons") or []
        fire = list(act.get("fire") or [False, False])
        while len(fire) < 2:
            fire.append(False)
        memory_s = float((self.cfg.get("vision") or {}).get("memory_s", 5.0))
        changed = False
        for i, w in enumerate(weapons):
            if not w or w.get("kind") != "laser":
                continue
            charge = float(w.get("charge") or 0)
            if charge <= 0.02:
                continue
            if fire[i]:
                continue
            # Target lost / mode didn't hold this slot — decide explicitly.
            best = None
            best_ang = 1e9
            for e in self.mem.enemies.values():
                if t - float(e.get("last_seen_t", -1e9)) > memory_s:
                    continue
                bearing = math.atan2(e["pos"][1] - me["pos"][1], e["pos"][0] - me["pos"][0])
                ang = abs(_angdiff(me["aim"][0], bearing))
                if ang < best_ang:
                    best_ang = ang
                    best = e
            if best is not None and best_ang <= math.radians(8.0):
                fire[i] = True
                act["aim"] = self.combat.aim_at(me, best, "laser")
                changed = True
            else:
                # R5: no enemy near aim → release (don't half-speed hold to auto-fire).
                fire[i] = False
                changed = True
        if changed or fire != list(act.get("fire") or [False, False]):
            act["fire"] = fire

    def _loot_is_elevated_roof(self, pos: List[float]) -> bool:
        gz = self.world.ground(pos[0], pos[1])
        return pos[2] - gz > self.step_up + 3.0

    def _loot_on_our_roof(self, me_pos: List[float], loot_pos: List[float]) -> bool:
        my_rid = self.world.roof_at(me_pos[0], me_pos[1])
        loot_rid = self.world.roof_at(loot_pos[0], loot_pos[1])
        return my_rid is not None and loot_rid is not None and int(my_rid) == int(loot_rid)

    def _avoid(self, obs: mf.Observation, act: Dict[str, Any]) -> None:
        me = obs["self"]
        mx, my, mz = me["pos"][0], me["pos"][1], me["pos"][2]
        push = [0.0, 0.0]
        # Ignore objects well below us (ground NPCs/drops under a roof ledge).
        below_slack = 4.0
        for m in obs.get("mechs") or []:
            if m.get("kind") != "npc":
                continue
            if mz - m["pos"][2] > below_slack:
                continue
            d = math.dist(m["pos"][:2], (mx, my))
            if d < self.npc_avoid and d > 1e-3:
                ux = (mx - m["pos"][0]) / d
                uy = (my - m["pos"][1]) / d
                push[0] += ux
                push[1] += uy
        for d in obs.get("drops") or []:
            if self.mem.contest_drop_id is not None and int(d.get("id", -1)) == self.mem.contest_drop_id:
                continue  # actively contesting this drop
            if mz - d["pos"][2] > below_slack:
                continue
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
