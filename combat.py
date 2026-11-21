"""Targeting, lead aim, mortar ballistics, fire discipline."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from world import World


def _angdiff(a: float, b: float) -> float:
    return (a - b + math.pi) % (2 * math.pi) - math.pi


class Combat:
    def __init__(self, world: World, cfg: Dict[str, Any]):
        self.world = world
        self.cfg = cfg
        self.weapons = cfg.get("weapons") or {}
        self._los_cache: Dict[int, bool] = {}
        self._los_tick: Optional[float] = None

    def begin_tick(self, tick: float) -> None:
        if tick != self._los_tick:
            self._los_tick = tick
            self._los_cache.clear()

    def muzzle(self, me: Dict[str, Any]) -> List[float]:
        stats = me.get("stats") or {}
        mh = float(stats.get("muzzle_height", 7.0))
        x, y, z = me["pos"]
        return [x, y, z + mh]

    def eye(self, me: Dict[str, Any]) -> List[float]:
        stats = me.get("stats") or {}
        eh = float(stats.get("eye_height", 8.0))
        x, y, z = me["pos"]
        return [x, y, z + eh]

    def com_z(self, feet_z: float, cubes: Optional[int] = None) -> float:
        """Center-of-mass height from feet (cfg mech.height/2, cube-scaled)."""
        mech = self.cfg.get("mech") or {}
        h = float(mech.get("height", 9.0))
        spc = float((self.cfg.get("cubes") or {}).get("size_per_cube", 0.05))
        n = max(0, int(cubes or 0))
        return feet_z + (h * 0.5) * (1.0 + spc * n)

    def mortar_gap(self) -> float:
        """Min seconds between mortar shots; live weapon cooldown still gates fire."""
        return float((self.weapons.get("mortar") or {}).get("cooldown", 2.6))

    def clear_shot(
        self,
        me: Dict[str, Any],
        target_pos: Sequence[float],
        eid: Optional[int] = None,
        cubes: Optional[int] = None,
    ) -> bool:
        if eid is not None and eid in self._los_cache:
            return self._los_cache[eid]
        muzz = self.muzzle(me)
        center = [target_pos[0], target_pos[1], self.com_z(target_pos[2], cubes)]
        ok = not self.world.blocked_segment(muzz, center, step=3.5)
        if eid is not None:
            self._los_cache[eid] = ok
        return ok

    def pick_target(
        self,
        me: Dict[str, Any],
        visible: List[Dict[str, Any]],
        prefer_id: Optional[int],
        require_clear: bool = True,
    ) -> Optional[Dict[str, Any]]:
        cands = []
        for m in visible:
            if m.get("kind") != "mech":
                continue
            cubes = m.get("cubes") if isinstance(m.get("cubes"), int) else None
            if require_clear and not self.clear_shot(me, m["pos"], int(m["id"]), cubes):
                continue
            cands.append(m)
        if not cands:
            return None
        if prefer_id is not None:
            for m in cands:
                if int(m["id"]) == prefer_id:
                    return m

        def key(m):
            hp = m.get("hp", 1400)
            d = math.dist(m["pos"][:2], me["pos"][:2])
            return (hp, d)

        return min(cands, key=key)

    def pick_fight_targets(
        self,
        me: Dict[str, Any],
        visible: List[Dict[str, Any]],
        prefer_id: Optional[int],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """One pass: (best_clear_los, best_any). Avoids double LOS scans."""
        clear_cands: List[Dict[str, Any]] = []
        any_cands: List[Dict[str, Any]] = []
        for m in visible:
            if m.get("kind") != "mech":
                continue
            any_cands.append(m)
            cubes = m.get("cubes") if isinstance(m.get("cubes"), int) else None
            if self.clear_shot(me, m["pos"], int(m["id"]), cubes):
                clear_cands.append(m)

        def choose(cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not cands:
                return None
            if prefer_id is not None:
                for m in cands:
                    if int(m["id"]) == prefer_id:
                        return m
            return min(
                cands,
                key=lambda m: (m.get("hp", 1400), math.dist(m["pos"][:2], me["pos"][:2])),
            )

        return choose(clear_cands), choose(any_cands)

    def _gun_intercept_t(
        self,
        dx: float,
        dy: float,
        dz: float,
        vx: float,
        vy: float,
        vz: float,
        speed: float,
        spawn: float,
    ) -> float:
        """Smallest t>0 where |D + V t| = speed·t + spawn (shot leaves spawn m along aim)."""
        s = max(1.0, speed)
        a = vx * vx + vy * vy + vz * vz - s * s
        b = 2.0 * (dx * vx + dy * vy + dz * vz - s * spawn)
        c = dx * dx + dy * dy + dz * dz - spawn * spawn
        t: Optional[float] = None
        if abs(a) < 1e-8:
            if abs(b) > 1e-8:
                cand = -c / b
                if cand > 1e-3:
                    t = cand
        else:
            disc = b * b - 4.0 * a * c
            if disc >= 0.0:
                root = math.sqrt(disc)
                for cand in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)):
                    if cand > 1e-3 and (t is None or cand < t):
                        t = cand
        if t is None:
            dist = math.sqrt(max(0.0, dx * dx + dy * dy + dz * dz))
            t = max(0.0, dist - spawn) / s
        return t

    def aim_at(self, me: Dict[str, Any], target: Dict[str, Any], kind: str = "gun") -> List[float]:
        mx, my, mz = self.muzzle(me)
        tx, ty, tz_feet = target["pos"]
        tv = target.get("vel") or [0, 0, 0]
        cubes = target.get("cubes")
        tz = self.com_z(tz_feet, cubes if isinstance(cubes, int) else None)
        if kind == "gun":
            gun = self.weapons.get("gun") or {}
            speed = float(gun.get("speed", 252))
            rng = float(gun.get("range", 230))
            mech = self.cfg.get("mech") or {}
            # Protocol: shot leaves radius+0.5 along aim before free flight.
            spawn = float(mech.get("radius", 2.5)) + 0.5
            vx, vy, vz = float(tv[0]), float(tv[1]), float(tv[2])
            dx, dy, dz = tx - mx, ty - my, tz - mz
            t_max = rng / max(1.0, speed)
            t = min(self._gun_intercept_t(dx, dy, dz, vx, vy, vz, speed, spawn), t_max)
            px = tx + vx * t
            py = ty + vy * t
            pz = tz + vz * t
            # Refine once with the predicted aim point (numeric slip / spawn geometry).
            for _ in range(2):
                dist = math.dist([mx, my, mz], [px, py, pz])
                travel = max(0.5, dist - spawn)
                t = min(travel / max(1.0, speed), t_max)
                px = tx + vx * t
                py = ty + vy * t
                pz = tz + vz * t
            dx, dy, dz = px - mx, py - my, pz - mz
            horiz = math.hypot(dx, dy) or 1e-6
            yaw = math.atan2(dy, dx)
            pitch = math.atan2(dz, horiz)
            return [yaw, pitch]
        if kind == "mortar":
            ma = self.mortar_aim(me, [tx, ty, tz_feet], tv)
            if ma is not None:
                return ma
            # Bug #8: never fall back to pitch 0.6 (shell lands ~220 m away).
            dx, dy, dz = tx - mx, ty - my, tz - mz
            horiz = math.hypot(dx, dy) or 1e-6
            return [math.atan2(dy, dx), math.atan2(dz, horiz)]
        # laser / lightning / default: direct
        dx, dy, dz = tx - mx, ty - my, tz - mz
        horiz = math.hypot(dx, dy) or 1e-6
        return [math.atan2(dy, dx), math.atan2(dz, horiz)]

    def _mortar_arc_clear(
        self, mx: float, my: float, mz: float, px: float, py: float, pz: float, theta: float, v: float
    ) -> bool:
        """True if lob midpoints clear buildings (approx)."""
        R = math.hypot(px - mx, py - my) or 1e-6
        cth = math.cos(theta)
        if abs(cth) < 1e-6:
            return False
        t_flight = R / (v * cth)
        yaw = math.atan2(py - my, px - mx)
        g = float((self.weapons.get("mortar") or {}).get("gravity", 22))
        for frac in (0.35, 0.65):
            t = t_flight * frac
            x = mx + math.cos(yaw) * v * cth * t
            y = my + math.sin(yaw) * v * cth * t
            z = mz + v * math.sin(theta) * t - 0.5 * g * t * t
            if z > pz + 2.0 and self.world.solid_at(x, y, z):
                return False
        return True

    def mortar_aim(
        self, me: Dict[str, Any], target_feet: Sequence[float], vel: Sequence[float]
    ) -> Optional[List[float]]:
        w = self.weapons.get("mortar") or {}
        v = float(w.get("speed", 72))
        g = float(w.get("gravity", 22))
        # mortar tube is higher — use stats if present; protocol says height+0.5
        stats = me.get("stats") or {}
        mx, my = me["pos"][0], me["pos"][1]
        mz = me["pos"][2] + float(stats.get("height", 9)) + 0.5
        tx, ty = float(target_feet[0]), float(target_feet[1])
        tz = float(target_feet[2]) + 1.0
        vx, vy = float(vel[0]), float(vel[1])
        # iterate lead; damp long-flight lead so walking targets aren't aimed 70 m ahead
        lead_cap = 15.0
        px, py = tx, ty
        best: Optional[List[float]] = None
        for _ in range(3):
            R = math.hypot(px - mx, py - my)
            if R < 12.0 or R > (v * v / g) + 5:
                return None
            dz = tz - mz
            disc = v**4 - g * (g * R * R + 2 * dz * v * v)
            if disc < 0:
                return None
            root = math.sqrt(disc)
            # Prefer low arc when the lob clears; else high arc (#8).
            candidates = [
                math.atan((v * v - root) / (g * R)),  # low
                math.atan((v * v + root) / (g * R)),  # high
            ]
            theta = None
            for cand in candidates:
                if cand <= 0.02:
                    continue
                if cand == candidates[0] and not self._mortar_arc_clear(
                    mx, my, mz, px, py, tz, cand, v
                ):
                    continue
                theta = cand
                break
            if theta is None:
                return None
            t_flight = R / (v * math.cos(theta))
            lead_x, lead_y = vx * t_flight, vy * t_flight
            lead_d = math.hypot(lead_x, lead_y)
            if lead_d > lead_cap:
                s = lead_cap / lead_d
                lead_x *= s
                lead_y *= s
            px = tx + lead_x
            py = ty + lead_y
            best = [math.atan2(py - my, px - mx), theta]
        return best

    def aligned(self, me: Dict[str, Any], desired: Sequence[float], tol_deg: float = 2.0) -> bool:
        aim = me["aim"]
        return abs(_angdiff(aim[0], desired[0])) <= math.radians(tol_deg) and abs(
            aim[1] - desired[1]
        ) <= math.radians(tol_deg + 1)

    def fire_slots(
        self,
        me: Dict[str, Any],
        desired_aim: Sequence[float],
        target: Optional[Dict[str, Any]],
        t: float,
        mem: Any,
        aim_kind: Optional[str] = None,
    ) -> Tuple[List[bool], bool, Optional[float]]:
        """Returns fire[2], reload, optional drop_slot for COUNTER_LASER caller.

        aim_kind: when set, only fire weapons compatible with that aim.
        Gun requires gun lead aim (no skyfire on mortar lob / laser direct).
        Lightning may share laser/gun direct-ish aim.
        """
        fire = [False, False]
        reload = False
        weapons = me.get("weapons") or [None, None]
        if not target:
            gun = weapons[0]
            if gun and gun.get("kind") == "gun":
                ammo = gun.get("ammo", 12)
                if ammo is not None and ammo < 4 and gun.get("reload", 0) == 0:
                    reload = True
            return fire, reload, None

        # Slightly wider than 2° so torso slew still sustains gun DPS.
        aimed = self.aligned(me, desired_aim, 4.0)
        laser_close = self.aligned(me, desired_aim, 15.0)  # start/keep charge only when roughly on target
        laser_aimed = self.aligned(me, desired_aim, 4.0)

        for i, w in enumerate(weapons):
            if not w:
                continue
            kind = w["kind"]
            if aim_kind is not None:
                if kind == "gun" and aim_kind != "gun":
                    # Bug #7: don't dump the mag on mortar lob / laser direct aim.
                    continue
                if kind == "mortar" and aim_kind != "mortar":
                    continue
                if kind == "laser" and aim_kind != "laser":
                    continue
                if kind == "lightning" and aim_kind not in ("lightning", "laser", "gun"):
                    continue
            cd = float(w.get("cooldown") or 0)
            if kind == "laser":
                # Charging while way off-target telegraphs + risks hold_s auto-fire the wrong way.
                # Only pull the trigger when roughly aligned; if already charging, keep holding
                # until we can release on-target (releasing early also fires along current aim).
                charge = float(w.get("charge") or 0)
                need = float((self.weapons.get("laser") or {}).get("charge", 0.75))
                charging = charge > 0.02
                if charge >= need - 0.02 and laser_aimed:
                    fire[i] = False  # release on target
                elif charging or laser_close:
                    fire[i] = True
                else:
                    fire[i] = False
                continue
            if kind == "gun":
                # Hold the trigger whenever aimed: server fires at exact cooldown rate.
                ammo = w.get("ammo", 1)
                if aimed and (ammo is None or ammo > 0):
                    fire[i] = True
                    # Count real shots via ammo drop / cooldown edge — not every hold tick.
                    prev_ammo = getattr(mem, "_gun_ammo_seen", None)
                    if ammo is not None and prev_ammo is not None and ammo < prev_ammo:
                        mem.shots_here += int(prev_ammo - ammo)
                        mem.shots += int(prev_ammo - ammo)
                    elif ammo is None and cd <= 0 and not getattr(mem, "_gun_held_last", False):
                        mem.shots_here += 1
                        mem.shots += 1
                    mem._gun_ammo_seen = ammo
                    mem._gun_held_last = True
                else:
                    if ammo is not None:
                        mem._gun_ammo_seen = ammo
                    mem._gun_held_last = False
                    if aimed and ammo is not None and ammo <= 0 and w.get("reload", 0) == 0:
                        reload = True
            if kind == "lightning" and aimed and cd <= 0:
                rng = float((self.weapons.get("lightning") or {}).get("range", 45))
                cone = math.radians(float((self.weapons.get("lightning") or {}).get("cone_deg", 30)) / 2)
                d = math.dist(me["pos"][:2], target["pos"][:2])
                bearing = math.atan2(target["pos"][1] - me["pos"][1], target["pos"][0] - me["pos"][0])
                if d <= rng and abs(_angdiff(me["aim"][0], bearing)) <= cone:
                    fire[i] = True
            if kind == "mortar" and aimed and cd <= 0 and t - mem.last_mortar_t >= self.mortar_gap():
                # Fire whenever we have a mortar aim solution (low or high arc).
                # Old pitch>0.25 gate blocked legitimate low-arc shots under ~170 m.
                if desired_aim[1] > 0.02:
                    fire[i] = True
                    mem.last_mortar_t = t
                    mem.mortars_here += 1
                    mem.mortars += 1
        return fire, reload, None
