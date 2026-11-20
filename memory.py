"""Short-term memory: enemies, damage, sounds, camp counters."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class Memory:
    def __init__(self) -> None:
        self.enemies: Dict[int, Dict[str, Any]] = {}
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

    def seed(self, seed: int) -> None:
        self.rng_state = int(seed) & 0x7FFFFFFF or 1

    def rand(self) -> float:
        # LCG
        self.rng_state = (1103515245 * self.rng_state + 12345) & 0x7FFFFFFF
        return self.rng_state / 0x7FFFFFFF

    def update(self, obs: Dict[str, Any]) -> None:
        t = float(obs["t"])
        self.total_time = t
        me = obs["self"]
        if self.world_on_roof:
            self.time_on_roof += 0.1  # approx decide period; refined by caller

        # enemies
        seen = set()
        for m in obs.get("mechs") or []:
            if m.get("kind") != "mech":
                continue
            eid = int(m["id"])
            seen.add(eid)
            self.enemies[eid] = {
                "id": eid,
                "pos": list(m["pos"]),
                "vel": list(m.get("vel") or [0, 0, 0]),
                "hp": m.get("hp"),
                "max_hp": m.get("max_hp"),
                "weapons": list(m.get("weapons") or []),
                "aim": list(m.get("aim") or [0, 0]),
                "charging": bool(m.get("charging")),
                "last_seen_t": t,
            }
        # prune old
        for eid in list(self.enemies):
            if t - self.enemies[eid]["last_seen_t"] > 8.0:
                del self.enemies[eid]

        # events
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

        # sounds
        for s in obs.get("sounds") or []:
            self.sound_log.append({"t": t, **s})

        cutoff = t - 3.0
        self.damage_log = [d for d in self.damage_log if d["t"] >= cutoff]
        self.sound_log = [s for s in self.sound_log if s["t"] >= cutoff]

        weapons = me.get("weapons") or []
        for w in weapons:
            if w and w.get("kind") != "gun":
                self.second_weapon = w["kind"]

    # set by bot each tick
    world_on_roof: bool = False

    def set_mode(self, mode: str, t: float) -> None:
        if mode != self.mode:
            self.mode = mode
            self.mode_t = t

    def reset_camp_counters(self) -> None:
        self.shots_here = 0
        self.mortars_here = 0
