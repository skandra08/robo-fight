"""Map geometry: terrain, prisms, LOS, roof lookup. Stdlib only."""
from __future__ import annotations

import array
import json
import math
import os
import sys
from typing import Dict, List, Optional, Sequence, Tuple

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]


def _point_in_ring(x: float, y: float, ring: Sequence[float]) -> bool:
    n = len(ring) // 2
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[2 * i], ring[2 * i + 1]
        xj, yj = ring[2 * j], ring[2 * j + 1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _point_in_prism_xy(x: float, y: float, prism: dict) -> bool:
    if not _point_in_ring(x, y, prism["ring"]):
        return False
    for hole in prism.get("holes") or []:
        if _point_in_ring(x, y, hole):
            return False
    return True


def _seg_dist2(ax: float, ay: float, bx: float, by: float, px: float, py: float) -> float:
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    ab2 = abx * abx + aby * aby
    if ab2 < 1e-12:
        return apx * apx + apy * apy
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab2))
    dx, dy = ax + t * abx - px, ay + t * aby - py
    return dx * dx + dy * dy


class World:
    def __init__(self, map_dir: str):
        world_path = os.path.join(map_dir, "v2", "world.json")
        with open(world_path) as f:
            raw = json.load(f)
        ter = raw["terrain"]
        self.min_x = float(ter["minX"])
        self.min_y = float(ter["minY"])
        self.step = float(ter["step"])
        self.nx = int(ter["nx"])
        self.ny = int(ter["ny"])
        terrain_path = os.path.join(map_dir, "v2", ter.get("file", "terrain.i16"))
        with open(terrain_path, "rb") as f:
            buf = f.read()
        self._h = array.array("h")
        self._h.frombytes(buf)
        if sys.byteorder == "big":
            self._h.byteswap()
        scale = float(ter.get("scale", 0.01))
        self._h_scale = scale

        self.prisms: List[dict] = []
        self.roofs: List[dict] = []  # building/stadium with top usable as roof
        self._grid: Dict[Tuple[int, int], List[int]] = {}
        self._cell = 20.0
        for i, p in enumerate(raw.get("prisms") or []):
            ring = p["ring"]
            xs = ring[0::2]
            ys = ring[1::2]
            meta = {
                "id": i,
                "kind": p.get("kind", "building"),
                "base": float(p["base"]),
                "top": float(p["top"]),
                "ring": ring,
                "holes": p.get("holes") or [],
                "minx": min(xs),
                "maxx": max(xs),
                "miny": min(ys),
                "maxy": max(ys),
            }
            self.prisms.append(meta)
            if meta["kind"] in ("building", "stadium"):
                self.roofs.append(meta)
            gx0 = int(math.floor(meta["minx"] / self._cell))
            gx1 = int(math.floor(meta["maxx"] / self._cell))
            gy0 = int(math.floor(meta["miny"] / self._cell))
            gy1 = int(math.floor(meta["maxy"] / self._cell))
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    self._grid.setdefault((gx, gy), []).append(i)

        self.rules = raw.get("rules") or {}
        self.max_step = float(self.rules.get("maxStep", 1.2))
        self.max_slope_deg = float(self.rules.get("maxSlopeDeg", 50))

    def ground(self, x: float, y: float) -> float:
        """Bilinear sample of terrain height (meters)."""
        u = (x - self.min_x) / self.step
        v = (y - self.min_y) / self.step
        if u < 0 or v < 0 or u >= self.nx - 1 or v >= self.ny - 1:
            # clamp to edge
            u = max(0.0, min(self.nx - 1.001, u))
            v = max(0.0, min(self.ny - 1.001, v))
        i0 = int(math.floor(u))
        j0 = int(math.floor(v))
        i1 = min(i0 + 1, self.nx - 1)
        j1 = min(j0 + 1, self.ny - 1)
        tx, ty = u - i0, v - j0
        h00 = self._h[j0 * self.nx + i0] * self._h_scale
        h10 = self._h[j0 * self.nx + i1] * self._h_scale
        h01 = self._h[j1 * self.nx + i0] * self._h_scale
        h11 = self._h[j1 * self.nx + i1] * self._h_scale
        return (h00 * (1 - tx) + h10 * tx) * (1 - ty) + (h01 * (1 - tx) + h11 * tx) * ty

    def _candidates(self, x: float, y: float) -> List[int]:
        gx = int(math.floor(x / self._cell))
        gy = int(math.floor(y / self._cell))
        out: List[int] = []
        seen = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for idx in self._grid.get((gx + dx, gy + dy), ()):
                    if idx not in seen:
                        seen.add(idx)
                        out.append(idx)
        return out

    def solid_at(self, x: float, y: float, z: float) -> bool:
        g = self.ground(x, y)
        if z < g - 0.05:
            return True
        for idx in self._candidates(x, y):
            p = self.prisms[idx]
            if z < p["base"] - 0.05 or z > p["top"] + 0.05:
                continue
            if _point_in_prism_xy(x, y, p):
                return True
        return False

    def blocked_segment(self, a: Sequence[float], b: Sequence[float], step: float = 3.0) -> bool:
        """True if the segment hits a prism or terrain (trees ignored — for shots).

        Uses ~3 m steps (fine enough for mech-scale LOS) and AABB rejects before
        polygon tests so combat clear_shot stays cheap under many enemies.
        """
        ax, ay, az = float(a[0]), float(a[1]), float(a[2])
        bx, by, bz = float(b[0]), float(b[1]), float(b[2])
        dx, dy, dz = bx - ax, by - ay, bz - az
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist < 1e-6:
            return self.solid_at(ax, ay, az)
        n = max(1, int(math.ceil(dist / step)))
        inv = 1.0 / n
        # Sample terrain every other step; prisms every step.
        for i in range(1, n + 1):
            t = i * inv
            x = ax + dx * t
            y = ay + dy * t
            z = az + dz * t
            if i == 1 or i == n or (i & 1):
                if z < self.ground(x, y) + 0.2:
                    return True
            for idx in self._candidates(x, y):
                p = self.prisms[idx]
                if z < p["base"] or z > p["top"]:
                    continue
                if x < p["minx"] or x > p["maxx"] or y < p["miny"] or y > p["maxy"]:
                    continue
                if _point_in_prism_xy(x, y, p):
                    return True
        return False

    def footprint_free(self, x: float, y: float, z: float, r: float = 2.6, h: float = 9.0) -> bool:
        """No prism occupies [z + step_up, z + h] at the centre or the 4 rim points (server-style
        collision probe). Used to slide along walls when the grid path pushes us into one."""
        for ox, oy in ((0.0, 0.0), (r, 0.0), (-r, 0.0), (0.0, r), (0.0, -r)):
            px, py = x + ox, y + oy
            for idx in self._candidates(px, py):
                p = self.prisms[idx]
                if p["top"] <= z + self.max_step or p["base"] >= z + h:
                    continue
                if px < p["minx"] or px > p["maxx"] or py < p["miny"] or py > p["maxy"]:
                    continue
                if _point_in_prism_xy(px, py, p):
                    return False
        return True

    def walkable_step(self, x: float, y: float, z: float, nx: float, ny: float, radius: float = 2.5) -> bool:
        """Can we move from (x,y) toward (nx,ny) on foot (rough)."""
        g0 = self.ground(x, y)
        g1 = self.ground(nx, ny)
        if abs(g1 - g0) > self.max_step + 0.05 and g1 > g0:
            # steep up — treat as wall unless already elevated
            if z < g0 + 1.5:
                return False
        # wall check at chest height
        mid_x, mid_y = (x + nx) * 0.5, (y + ny) * 0.5
        chest = max(z, g0) + 4.0
        for idx in self._candidates(mid_x, mid_y):
            p = self.prisms[idx]
            if chest < p["base"] or chest > p["top"]:
                continue
            if _point_in_prism_xy(mid_x, mid_y, p):
                # if we're already on top of this roof, ok
                if abs(z - p["top"]) < 1.5 and _point_in_prism_xy(x, y, p):
                    continue
                return False
        return True

    def roof_at(self, x: float, y: float) -> Optional[int]:
        best = None
        best_top = -1e9
        for p in self.roofs:
            if x < p["minx"] or x > p["maxx"] or y < p["miny"] or y > p["maxy"]:
                continue
            if _point_in_prism_xy(x, y, p) and p["top"] > best_top:
                best_top = p["top"]
                best = p["id"]
        return best

    def on_roof(self, pos: Sequence[float], tol: float = 1.0) -> bool:
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        rid = self.roof_at(x, y)
        if rid is None:
            return False
        p = self.prisms[rid]
        return abs(z - p["top"]) <= tol

    def edge_distance(self, x: float, y: float, prism: dict) -> float:
        ring = prism["ring"]
        n = len(ring) // 2
        best = 1e18
        for i in range(n):
            j = (i + 1) % n
            d2 = _seg_dist2(ring[2 * i], ring[2 * i + 1], ring[2 * j], ring[2 * j + 1], x, y)
            if d2 < best:
                best = d2
        return math.sqrt(best)

    def prism_by_id(self, pid: int) -> dict:
        return self.prisms[pid]
