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

    def clear_shot(self, me: Dict[str, Any], target_pos: Sequence[float]) -> bool:
        muzz = self.muzzle(me)
        center = [target_pos[0], target_pos[1], target_pos[2] + 4.5]
        return not self.world.blocked_segment(muzz, center, step=2.5)

    def pick_target(
        self,
        me: Dict[str, Any],
        visible: List[Dict[str, Any]],
        prefer_id: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        cands = []
        for m in visible:
            if m.get("kind") != "mech":
                continue
            if not self.clear_shot(me, m["pos"]):
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

    def aim_at(self, me: Dict[str, Any], target: Dict[str, Any], kind: str = "gun") -> List[float]:
        mx, my, mz = self.muzzle(me)
        tx, ty, tz = target["pos"]
        tv = target.get("vel") or [0, 0, 0]
        # aim at center of mass
        tz = tz + 4.5
        if kind == "gun":
            speed = float((self.weapons.get("gun") or {}).get("speed", 252))
            px, py, pz = tx, ty, tz
            for _ in range(2):
                dist = math.dist([mx, my, mz], [px, py, pz])
                t = dist / max(1.0, speed)
                px = tx + tv[0] * t
                py = ty + tv[1] * t
                pz = tz + tv[2] * t
            dx, dy, dz = px - mx, py - my, pz - mz
            horiz = math.hypot(dx, dy) or 1e-6
            yaw = math.atan2(dy, dx)
            pitch = math.atan2(dz, horiz)
            return [yaw, pitch]
        if kind == "mortar":
            return self.mortar_aim(me, [tx, ty, tz - 4.5], tv) or [
                math.atan2(ty - my, tx - mx),
                0.6,
            ]
        # laser / lightning / default: direct
        dx, dy, dz = tx - mx, ty - my, tz - mz
        horiz = math.hypot(dx, dy) or 1e-6
        return [math.atan2(dy, dx), math.atan2(dz, horiz)]

    def mortar_aim(
        self, me: Dict[str, Any], target_feet: Sequence[float], vel: Sequence[float]
    ) -> Optional[List[float]]:
        w = self.weapons.get("mortar") or {}
        v = float(w.get("speed", 72))
        g = float(w.get("gravity", 22))
        mx, my, mz = self.muzzle(me)
        # mortar tube is higher — use stats if present; protocol says height+0.5
        stats = me.get("stats") or {}
        mz = me["pos"][2] + float(stats.get("height", 9)) + 0.5
        tx, ty = float(target_feet[0]), float(target_feet[1])
        tz = float(target_feet[2]) + 1.0
        # iterate lead
        px, py = tx, ty
        theta = None
        for _ in range(3):
            R = math.hypot(px - mx, py - my)
            if R < 12.0 or R > (v * v / g) + 5:
                return None
            dz = tz - mz
            disc = v**4 - g * (g * R * R + 2 * dz * v * v)
            if disc < 0:
                return None
            # high arc
            tan_th = (v * v + math.sqrt(disc)) / (g * R)
            theta = math.atan(tan_th)
            t_flight = R / (v * math.cos(theta))
            px = tx + vel[0] * t_flight
            py = ty + vel[1] * t_flight
        if theta is None:
            return None
        yaw = math.atan2(py - my, px - mx)
        return [yaw, theta]

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
    ) -> Tuple[List[bool], bool, Optional[float]]:
        """Returns fire[2], reload, optional drop_slot for COUNTER_LASER caller."""
        fire = [False, False]
        reload = False
        weapons = me.get("weapons") or [None, None]
        if not target:
            # early reload gun
            gun = weapons[0]
            if gun and gun.get("kind") == "gun":
                ammo = gun.get("ammo", 12)
                if ammo is not None and ammo < 4 and gun.get("reload", 0) == 0:
                    reload = True
            return fire, reload, None

        if not self.aligned(me, desired_aim, 2.0):
            return fire, reload, None

        # prefer laser in either slot
        for i, w in enumerate(weapons):
            if not w:
                continue
            kind = w["kind"]
            cd = float(w.get("cooldown") or 0)
            if kind == "laser":
                charge = float(w.get("charge") or 0)
                need = float((self.weapons.get("laser") or {}).get("charge", 0.75))
                # hold trigger to charge; release when full by not firing next — but we only get
                # binary fire per decision. Hold fire True while charging; when full and aligned,
                # set False for one tick... Protocol: hold to charge, let go to fire.
                # So: fire True until charge >= need, then fire False once.
                if charge >= need - 0.02 and self.aligned(me, desired_aim, 3.0):
                    fire[i] = False  # release
                else:
                    fire[i] = True  # charge / keep
                continue
            if kind == "gun" and cd <= 0:
                ammo = w.get("ammo", 1)
                if ammo is None or ammo > 0:
                    fire[i] = True
                    mem.shots_here += 1
                    mem.shots += 1
                elif w.get("reload", 0) == 0:
                    reload = True
            if kind == "lightning" and cd <= 0:
                rng = float((self.weapons.get("lightning") or {}).get("range", 45))
                cone = math.radians(float((self.weapons.get("lightning") or {}).get("cone_deg", 30)) / 2)
                d = math.dist(me["pos"][:2], target["pos"][:2])
                bearing = math.atan2(target["pos"][1] - me["pos"][1], target["pos"][0] - me["pos"][0])
                if d <= rng and abs(_angdiff(me["aim"][0], bearing)) <= cone:
                    fire[i] = True
            if kind == "mortar" and cd <= 0 and t - mem.last_mortar_t >= 4.0:
                # only if aim looks like mortar pitch
                if desired_aim[1] > 0.25:
                    fire[i] = True
                    mem.last_mortar_t = t
                    mem.mortars_here += 1
                    mem.mortars += 1
        return fire, reload, None
