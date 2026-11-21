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

    def seed(self, seed: int) -> None:
        self.rng_state = int(seed) & 0x7FFFFFFF or 1
        self.scan_yaw = (seed % 360) * 0.017453292519943295

    def rand(self) -> float:
        self.rng_state = (1103515245 * self.rng_state + 12345) & 0x7FFFFFFF
        return self.rng_state / 0x7FFFFFFF

    def update(self, obs: Dict[str, Any]) -> None:
        t = float(obs["t"])
        self.total_time = t
        me = obs["self"]

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
        for pid in list(self.loot):
            if pid not in seen_loot and t - self.loot[pid]["last_seen_t"] > 45.0:
                del self.loot[pid]

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

        for s in obs.get("sounds") or []:
            self.sound_log.append({"t": t, **s})
            # sound bearings are useful hunt cues when we have no visual
            if s.get("kind") in ("gun", "laser", "laser_charge", "lightning", "mortar", "explosion"):
                if s.get("bearing") is not None and self.last_threat_bearing is None:
                    self.last_threat_bearing = float(s["bearing"])

        cutoff = t - 3.0
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

    def best_loot(self, pos: List[float], t: float) -> Optional[Dict[str, Any]]:
        best = None
        best_score = -1e9
        for p in self.loot.values():
            kind = p["kind"]
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
