"""Ground steering, roof climbing, stuck recovery."""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from world import World


# Fewer feelers = fewer walkable_step tests; still covers front hemisphere well.
FEELER_DEG = (0, 30, -30, 60, -60, 100, -100, 140, -140)


def _angdiff(a: float, b: float) -> float:
    return (a - b + math.pi) % (2 * math.pi) - math.pi


class Navigator:
    def __init__(self, world: World, mem: Any, grid: Any = None):
        self.world = world
        self.mem = mem
        self.grid = grid  # pathing.PathGrid or None
        self._path: Optional[List[List[float]]] = None
        self._path_goal: Optional[List[float]] = None
        self._path_t = -99.0
        self._plan_fail_until = -99.0
        self._plan_fail_goal: Optional[List[float]] = None
        self._search: Any = None
        self._on_path = False
        self._search_goal: Optional[List[float]] = None

    def _route(self, me: Dict[str, Any], goal: Sequence[float], now: float) -> Sequence[float]:
        """Replace a far goal behind buildings with the next waypoint of a grid path."""
        g = self.grid
        if g is None:
            return goal
        x, y, z = me["pos"]
        if z > self.world.ground(x, y) + 3.0:
            return goal  # on a roof / in the air: local logic
        if math.hypot(goal[0] - x, goal[1] - y) < 16.0 or g.clear_line(me["pos"], goal):
            return goal
        same = self._path_goal is not None and math.hypot(goal[0] - self._path_goal[0], goal[1] - self._path_goal[1]) < 8.0
        if not (same and self._path and now - self._path_t < 5.0):
            if (now < self._plan_fail_until and self._plan_fail_goal is not None
                    and math.hypot(goal[0] - self._plan_fail_goal[0], goal[1] - self._plan_fail_goal[1]) < 8.0):
                return goal
            # Resumable search, at most ~6 ms per decision so act() stays far inside 50 ms.
            sg = [goal[0], goal[1]]
            if self._search is None or self._search_goal is None or math.hypot(
                    sg[0] - self._search_goal[0], sg[1] - self._search_goal[1]) >= 8.0:
                self._search = g.search(me["pos"], goal)
                self._search_goal = sg
                next(self._search)
            try:
                self._search.send(time.perf_counter() + 0.006)
                return goal  # still searching: keep local steering meanwhile
            except StopIteration as e:
                path = e.value
                self._search = None
                self._search_goal = None
            if not path:
                self._plan_fail_until = now + 1.5
                self._plan_fail_goal = sg
                self._path = None
                return goal
            self._path, self._path_goal, self._path_t = path, sg, now
        path = self._path
        # Drop waypoints we've reached, then take the farthest one still in clear line (<= 40 m).
        while len(path) > 1 and math.hypot(path[0][0] - x, path[0][1] - y) < 5.0:
            path.pop(0)
        best = path[0]
        for wp in path[1:5]:
            if math.hypot(wp[0] - x, wp[1] - y) > 12.0 or not g.clear_line(me["pos"], wp):
                break
            best = wp
        self._on_path = True
        return [best[0], best[1], goal[2] if len(goal) > 2 else z]

    def steer(
        self,
        me: Dict[str, Any],
        goal: Sequence[float],
        speed_frac: float = 1.0,
        t: Optional[float] = None,
    ) -> Tuple[List[float], float]:
        """Return (move_xy clamped, desired_yaw). Pass obs time as `t` for stuck recovery."""
        now0 = float(t) if t is not None else float(getattr(self.mem, "total_time", 0.0) or 0.0)
        self._on_path = False
        goal = self._route(me, goal, now0)
        x, y, z = me["pos"]
        gx, gy = float(goal[0]), float(goal[1])
        if self._on_path and not (self.mem.stuck_until > now0 and self.mem.stuck_heading is not None):
            # The grid path already avoids walls and ledges; walkable_step's local check calls
            # any >1.2 m rise over 4-9 m a wall (gentle ramps), which made us jitter in pits.
            yaw = math.atan2(gy - y, gx - x)
            frac = max(0.0, min(1.0, speed_frac))
            return [math.cos(yaw) * frac, math.sin(yaw) * frac], yaw
        # If the direct line is walled, aim at a side waypoint first.
        want = math.atan2(gy - y, gx - x)
        mid = (x + math.cos(want) * 10.0, y + math.sin(want) * 10.0)
        if not self.world.walkable_step(x, y, z, mid[0], mid[1]):
            left = want + math.pi / 2
            right = want - math.pi / 2
            candidates = []
            for ang in (left, right, want + 2.4, want - 2.4):
                wx = x + math.cos(ang) * 18.0
                wy = y + math.sin(ang) * 18.0
                if self.world.walkable_step(x, y, z, x + math.cos(ang) * 6, y + math.sin(ang) * 6):
                    # prefer waypoint that still progresses toward goal
                    progress = math.cos(ang) * (gx - x) + math.sin(ang) * (gy - y)
                    candidates.append((progress, ang, wx, wy))
            if candidates:
                candidates.sort(reverse=True)
                want = candidates[0][1]
                gx, gy = candidates[0][2], candidates[0][3]
                want = math.atan2(gy - y, gx - x)

        now = float(t) if t is not None else float(getattr(self.mem, "total_time", 0.0) or 0.0)
        if self.mem.stuck_until > now:
            if self.mem.stuck_heading is not None:
                want = self.mem.stuck_heading
        best_yaw = want
        best_score = -1e9
        any_ok = False
        for deg in FEELER_DEG:
            yaw = want + math.radians(deg)
            c, s = math.cos(yaw), math.sin(yaw)
            ok = True
            for dist in (4.0, 9.0):
                nx, ny = x + c * dist, y + s * dist
                if not self.world.walkable_step(x, y, z, nx, ny):
                    ok = False
                    break
            if not ok:
                continue
            any_ok = True
            score = -abs(deg)
            if score > best_score:
                best_score = score
                best_yaw = yaw
        if not any_ok:
            # all feelers blocked — still push goal heading; stuck recovery will jump
            best_yaw = want
        frac = max(0.0, min(1.0, speed_frac))
        move = [math.cos(best_yaw) * frac, math.sin(best_yaw) * frac]
        return move, best_yaw

    def update_stuck(self, me: Dict[str, Any], t: float, moving: bool) -> None:
        speed = math.hypot(me["vel"][0], me["vel"][1])
        if moving and me.get("grounded") and speed < 1.5:
            if self.mem.stuck_since < 0:
                self.mem.stuck_since = t
            elif t - self.mem.stuck_since >= 1.0 and t >= self.mem.stuck_until:
                # jump+boost then random perpendicular
                self.mem.stuck_heading = math.atan2(me["vel"][1], me["vel"][0]) + (
                    math.pi / 2 if self.mem.rand() > 0.5 else -math.pi / 2
                )
                self.mem.stuck_until = t + 1.5
                self.mem.stuck_since = -1
        else:
            self.mem.stuck_since = -1

    def climb_action(
        self,
        me: Dict[str, Any],
        roof: Dict[str, Any],
        climb_pt: Sequence[float],
        t: float,
    ) -> Dict[str, Any]:
        """Actions to approach climb point and jet onto roof."""
        x, y, z = me["pos"]
        top = float(roof["top"])
        energy = float(me["energy"])
        max_e = float(me["max_energy"])
        act: Dict[str, Any] = {}
        # Abort if energy depleted mid climb
        if energy < 1.0 and z < top - 0.5:
            # drop / walk away
            away = math.atan2(y - roof["center"][1], x - roof["center"][0])
            act["move"] = [math.cos(away), math.sin(away)]
            act["boost"] = False
            act["jump"] = False
            return act

        dist = math.hypot(climb_pt[0] - x, climb_pt[1] - y)
        yaw_in = math.atan2(roof["center"][1] - y, roof["center"][0] - x)

        # Low energy: do NOT stand still (free kill). Strafe near the wall while regen,
        # or walk to climb point without jetting until we have enough for the ascent.
        if energy / max_e < 0.6 and z < top - 1.0 and me.get("grounded"):
            if dist > 3.5:
                move, yaw = self.steer(me, climb_pt, 0.5, t)
                act["move"] = move
                act["aim"] = [yaw, -0.05]
            else:
                # circle along the wall while waiting for regen
                along = yaw_in + math.pi / 2
                act["move"] = [math.cos(along) * 0.45, math.sin(along) * 0.45]
                act["aim"] = [yaw_in, 0.1]
            act["boost"] = False
            act["jump"] = False
            return act

        if dist > 3.5 and z < top - 1.0:
            move, yaw = self.steer(me, climb_pt, 1.0, t)
            act["move"] = move
            act["aim"] = [yaw, -0.05]
            act["boost"] = energy / max_e > 0.75
            return act

        # at climb point: face roof center, jump, jet
        act["aim"] = [yaw_in, 0.2]
        act["move"] = [math.cos(yaw_in), math.sin(yaw_in)]
        if z < top + 1.0:
            act["jump"] = bool(me.get("grounded"))
            act["boost"] = True  # jet in air / run on ground toward wall
        else:
            # above roof — push inward
            act["boost"] = False
            act["jump"] = False
        return act

    def zone_goal(self, zone: Dict[str, Any], pos: Sequence[float], margin_frac: float = 0.7) -> List[float]:
        cx, cy = zone["center"]
        r = float(zone["radius"]) * margin_frac
        dx, dy = pos[0] - cx, pos[1] - cy
        d = math.hypot(dx, dy) or 1.0
        if d <= r:
            return [cx, cy]
        return [cx + dx / d * r, cy + dy / d * r]
