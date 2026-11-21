"""Short-term memory: enemies, loot, damage, sounds, camp counters."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class Memory:
    def __init__(self) -> None:
        self.enemies: Dict[int, Dict[str, Any]] = {}
        self.loot: Dict[int, Dict[str, Any]] = {}  # pickup id -> last known
        self.damage_log: List[Dict[str, Any]] = []
        self.sound_log: List[Dict[str, Any]] = []
        self.shots_here = 0
        self.mortars_here = 0
        self.last_dealt_damage_t = -1e9
        self.last_took_weapon_damage_t = -1e9
        self.last_threat_bearing: Optional[float] = None
        self.last_threat_id: Optional[int] = None
        self.mode = "ARM"
        self.mode_t = 0.0
        self.roof_id: Optional[int] = None
        self.climb_target: Optional[List[float]] = None
        self.camp_hidden: Optional[List[float]] = None
        self.camp_fire: Optional[List[float]] = None
        self.peek_phase = 0  # 0 hide, 1 peek
        self.peek_until = 0.0
        self.next_peek_t = 0.0
        self.last_mortar_t = -1e9
        self.stuck_since = -1e9
        self.stuck_heading: Optional[float] = None
        self.stuck_until = 0.0
        self.roofs_used: set = set()
        self.time_on_roof = 0.0
        self.total_time = 0.0
        self.shots = 0
        self.mortars = 0
        self.max_act_ms = 0.0
        self.hp_at_death = 0.0
        self.killer_weapon = None
        self.t_death = 0.0
        self.second_weapon = None
        self.cubes_want = 4
        self.rng_state = 1
        self.scan_yaw = 0.0
        self.arm_goal: Optional[List[float]] = None
        self._gun_ammo_seen: Optional[float] = None
        self._gun_held_last = False
        self.strafe_sign = 1.0
        self.positioned = False
        self.loadout_goal: Optional[List[float]] = None
        # Practice modes: fight → disengage / third / rotate tracking.
        self.fight_start_t = -1e9
        self.fight_start_hp = 0.0
        self.fight_target_id: Optional[int] = None
        self.disengage_goal: Optional[List[float]] = None
        self.disengage_until = 0.0
        self.combat_noise_since = -1e9
        self.third_bearing: Optional[float] = None
        self.third_commit = False
        self.rotate_goal: Optional[List[float]] = None
        self.gatekeep = False
        self.contest_drop_id: Optional[int] = None
        # Strategy plan (S/N/F) state
        self.ffa = False
        self.alive_prev: Optional[int] = None
        self.unexplained_alive_drops = 0
        self.had_our_kill_recent = False
        self.laser_threat_id: Optional[int] = None
        self.laser_threat_seen_t = -1e9
        self.laser_beam_return_t = -1e9
        self.threat_edge_bearing: Optional[float] = None
        self.edge_guard_pt: Optional[List[float]] = None
        self.post_kill_pos: Optional[List[float]] = None
        self.post_kill_t = -1e9
        self.post_kill_phase: Optional[str] = None  # "loot" | "heal"
        self.farm_drone_id: Optional[int] = None
        self.precharge_active = False
        self.disengage_rearm_t = -1e9
        self.last_our_kill_t = -1e9

    def seed(self, seed: int) -> None:
        self.rng_state = int(seed) & 0x7FFFFFFF or 1
        self.scan_yaw = (seed % 360) * 0.017453292519943295

    def rand(self) -> float:
        self.rng_state = (1103515245 * self.rng_state + 12345) & 0x7FFFFFFF
        return self.rng_state / 0x7FFFFFFF

    def update(self, obs: Dict[str, Any], near_range: float = 45.0, world: Any = None) -> None:
        t = float(obs["t"])
        self.total_time = t
        me = obs["self"]
        me_pos = me["pos"]

        for m in obs.get("mechs") or []:
            if m.get("kind") != "mech":
                continue
            eid = int(m["id"])
            self.enemies[eid] = {
                "id": eid,
                "kind": "mech",
                "pos": list(m["pos"]),
                "vel": list(m.get("vel") or [0, 0, 0]),
                "hp": m.get("hp"),
                "max_hp": m.get("max_hp"),
                "weapons": list(m.get("weapons") or []),
                "aim": list(m.get("aim") or [0, 0]),
                "charging": bool(m.get("charging")),
                "last_seen_t": t,
            }
        for eid in list(self.enemies):
            if t - self.enemies[eid]["last_seen_t"] > 8.0:
                del self.enemies[eid]

        # Remember weapon pickups while visible; drop if we took them or they're stale.
        seen_loot = set()
        for p in obs.get("pickups") or []:
            if p.get("kind") == "gun":
                continue
            pid = int(p["id"])
            seen_loot.add(pid)
            self.loot[pid] = {
                "id": pid,
                "kind": p["kind"],
                "pos": list(p["pos"]),
                "last_seen_t": t,
            }
        for e in obs.get("events") or []:
            if e.get("type") == "took" and e.get("id") is not None:
                self.loot.pop(int(e["id"]), None)
            if e.get("type") == "take_failed" and e.get("reason") == "gone" and e.get("id") is not None:
                self.loot.pop(int(e["id"]), None)
        # Bug #5 / R4: near-range vision is all-around, but buildings still block.
        # Only delete when we have eye LOS to the pickup (cap checks per tick).
        los_budget = 4
        stats = me.get("stats") or {}
        eh = float(stats.get("eye_height", 8.0))
        eye = [me_pos[0], me_pos[1], me_pos[2] + eh]
        for pid in list(self.loot):
            if pid in seen_loot:
                continue
            p = self.loot[pid]
            d_xy = ((p["pos"][0] - me_pos[0]) ** 2 + (p["pos"][1] - me_pos[1]) ** 2) ** 0.5
            if d_xy <= near_range:
                if world is None:
                    del self.loot[pid]
                    continue
                if los_budget <= 0:
                    continue  # defer; stale age still clears eventually
                los_budget -= 1
                px, py, pz = p["pos"]
                if not world.blocked_segment(eye, [px, py, pz + 0.5]):
                    del self.loot[pid]
            elif t - p["last_seen_t"] > 45.0:
                del self.loot[pid]

        our_kill_this_tick = False
        for e in obs.get("events") or []:
            et = e.get("type")
            if et == "damaged":
                self.damage_log.append({"t": t, **e})
                if e.get("weapon") not in (None, "zone"):
                    self.last_took_weapon_damage_t = t
                    if e.get("bearing") is not None:
                        self.last_threat_bearing = float(e["bearing"])
                    if e.get("by") is not None:
                        self.last_threat_id = int(e["by"])
                    self.killer_weapon = e.get("weapon")
                self.hp_at_death = me["hp"]
                self.t_death = t
            elif et == "hit":
                self.last_dealt_damage_t = t
            elif et == "took":
                self.second_weapon = e.get("kind")
            elif et == "kill":
                our_kill_this_tick = True
                self.last_our_kill_t = t
                tid = e.get("target")
                if tid is not None and int(tid) in self.enemies:
                    self.post_kill_pos = list(self.enemies[int(tid)]["pos"])
                    self.post_kill_t = t
                    self.post_kill_phase = "loot"
                elif tid is not None:
                    # Victim already dropped from enemies — keep last known if any.
                    self.post_kill_t = t
                    if self.post_kill_pos is None:
                        self.post_kill_phase = "heal"
        self.had_our_kill_recent = our_kill_this_tick or (t - self.last_our_kill_t < 0.25)

        combat_kinds = ("gun", "laser", "laser_charge", "lightning", "mortar", "explosion")
        heard_combat = False
        for s in obs.get("sounds") or []:
            self.sound_log.append({"t": t, **s})
            # sound bearings are useful hunt cues when we have no visual
            if s.get("kind") in combat_kinds:
                heard_combat = True
                # Bug #9: refresh from combat sounds (was once-only when None).
                # Damage events above win for ~0.3s after being hit.
                if s.get("bearing") is not None and t - self.last_took_weapon_damage_t > 0.3:
                    self.last_threat_bearing = float(s["bearing"])
        if heard_combat:
            if self.combat_noise_since < 0:
                self.combat_noise_since = t
        else:
            # Quiet tick — keep window if recent combat still in the log.
            if self.combat_noise_since >= 0 and not any(
                s.get("kind") in combat_kinds for s in self.sound_log if t - s["t"] < 1.2
            ):
                self.combat_noise_since = -1e9
                self.third_commit = False

        cutoff = t - 4.0
        self.damage_log = [d for d in self.damage_log if d["t"] >= cutoff]
        self.sound_log = [s for s in self.sound_log if s["t"] >= cutoff]

        for w in me.get("weapons") or []:
            if w and w.get("kind") != "gun":
                self.second_weapon = w["kind"]

        # slow scan for loot search
        self.scan_yaw = (self.scan_yaw + 0.35) % (2 * 3.141592653589793)

    world_on_roof: bool = False

    def set_mode(self, mode: str, t: float) -> None:
        if mode != self.mode:
            self.mode = mode
            self.mode_t = t

    def reset_camp_counters(self) -> None:
        self.shots_here = 0
        self.mortars_here = 0
        # Bug #3: stale camp_fire/camp_hidden walk us off the new roof after relocate.
        self.camp_fire = None
        self.camp_hidden = None
        self.peek_phase = 0
        self.peek_until = 0.0

    def best_loot(
        self,
        pos: List[float],
        t: float,
        world: Any = None,
        on_roof: bool = False,
        step_up: float = 1.2,
    ) -> Optional[Dict[str, Any]]:
        best = None
        best_score = -1e9
        my_rid = None
        if world is not None and on_roof:
            my_rid = world.roof_at(pos[0], pos[1])
        for p in self.loot.values():
            kind = p["kind"]
            # Bug #5: skip elevated roof loot unless we're on that same roof.
            if world is not None:
                gz = world.ground(p["pos"][0], p["pos"][1])
                if p["pos"][2] - gz > step_up + 3.0:
                    if not on_roof:
                        continue
                    loot_rid = world.roof_at(p["pos"][0], p["pos"][1])
                    if my_rid is None or loot_rid is None or int(my_rid) != int(loot_rid):
                        continue
            d = ((p["pos"][0] - pos[0]) ** 2 + (p["pos"][1] - pos[1]) ** 2) ** 0.5
            age = t - p["last_seen_t"]
            if kind == "laser" and d <= 160:
                score = 400 - d - age
            elif kind == "mortar" and d <= 120:
                score = 280 - d - age
            elif kind == "lightning" and d <= 60:
                score = 140 - d - age
            else:
                continue
            if score > best_score:
                best_score = score
                best = p
        return best
