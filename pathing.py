"""Coarse ground path planner: 4 m occupancy grid built from world.json at init, A* on demand.

Navigator.steer is local (feelers + one side waypoint), so long goals behind buildings
(supply drops, zone escapes, far cubes, climb points) got the bot stuck pushing into the
same wall for tens of seconds. This plans around buildings and hands steer a near waypoint.
"""
from __future__ import annotations

import heapq
import math
import os
import time
from typing import List, Optional, Sequence, Tuple

CELL = 4.0
HEAD = 9.0
STEP_UP = 1.2
DIRS = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
        (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414))


def build_moves(grid, world) -> bytearray:
    """Walk 1 m samples of the terrain along each cell-centre to neighbour-centre segment; a
    rise above STEP_UP between consecutive samples (or a slope over 50 deg) blocks that move."""
    nx, ny = grid.nx, grid.ny
    out = bytearray(nx * ny)
    gr = world.ground
    for j in range(ny):
        for i in range(nx):
            k = j * nx + i
            if grid.blocked[k]:
                continue
            cx, cy = grid.center(i, j)
            m = 0
            for bit, (di, dj, dc) in enumerate(DIRS):
                ii, jj = i + di, j + dj
                if ii < 0 or jj < 0 or ii >= nx or jj >= ny or grid.blocked[jj * nx + ii]:
                    continue
                steps = int(CELL * dc)
                prev = gr(cx, cy)
                ok = True
                for s in range(1, steps + 1):
                    f = s / steps
                    h = gr(cx + di * CELL * f, cy + dj * CELL * f)
                    if h - prev > STEP_UP:
                        ok = False
                        break
                    prev = h
                if ok:
                    m |= 1 << bit
            out[k] = m
    return out


def _pip(x: float, y: float, ring: Sequence[float]) -> bool:
    n = len(ring) // 2
    c = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[2 * i], ring[2 * i + 1]
        xj, yj = ring[2 * j], ring[2 * j + 1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


class PathGrid:
    def __init__(self, world, data_dir: Optional[str] = None) -> None:
        self.w = world
        self.x0 = world.min_x
        self.y0 = world.min_y
        self.nx = int(world.nx * world.step / CELL)
        self.ny = int(world.ny * world.step / CELL)
        nx, ny = self.nx, self.ny
        self.g = [0.0] * (nx * ny)
        blocked = bytearray(nx * ny)
        for j in range(ny):
            cy = self.y0 + (j + 0.5) * CELL
            for i in range(nx):
                self.g[j * nx + i] = world.ground(self.x0 + (i + 0.5) * CELL, cy)
        for p in world.prisms:
            i0 = max(0, int((p["minx"] - self.x0) / CELL))
            i1 = min(nx - 1, int((p["maxx"] - self.x0) / CELL))
            j0 = max(0, int((p["miny"] - self.y0) / CELL))
            j1 = min(ny - 1, int((p["maxy"] - self.y0) / CELL))
            ring, holes = p["ring"], p["holes"]
            for j in range(j0, j1 + 1):
                cy = self.y0 + (j + 0.5) * CELL
                for i in range(i0, i1 + 1):
                    k = j * nx + i
                    if blocked[k]:
                        continue
                    cx = self.x0 + (i + 0.5) * CELL
                    gz = self.g[k]
                    if p["top"] <= gz + 1.2 or p["base"] >= gz + HEAD:
                        continue
                    if _pip(cx, cy, ring) and not any(_pip(cx, cy, h) for h in holes):
                        blocked[k] = 1
        # Inflate by one cell (mech radius 2.5 m).
        infl = bytearray(blocked)
        for j in range(ny):
            for i in range(nx):
                if blocked[j * nx + i]:
                    for dj in (-1, 0, 1):
                        for di in (-1, 0, 1):
                            ii, jj = i + di, j + dj
                            if 0 <= ii < nx and 0 <= jj < ny:
                                infl[jj * nx + ii] = 1
        self.raw = blocked
        self.blocked = infl
        self.max_rise = CELL * math.tan(math.radians(50.0))
        self.moves = self._load_moves(world, data_dir)

    def _load_moves(self, world, data_dir):
        """Per cell, a bit per neighbour (D order) that is walkable without a ledge > step_up.
        Precomputed into data/navmoves.bin by tools/precompute_nav.py (computed here if absent)."""
        n = self.nx * self.ny
        if data_dir:
            p = os.path.join(data_dir, "navmoves.bin")
            try:
                with open(p, "rb") as f:
                    buf = f.read()
                if len(buf) == n:
                    return bytearray(buf)
            except OSError:
                pass
        return build_moves(self, world)

    def cell(self, x: float, y: float) -> Tuple[int, int]:
        i = min(self.nx - 1, max(0, int((x - self.x0) / CELL)))
        j = min(self.ny - 1, max(0, int((y - self.y0) / CELL)))
        return i, j

    def center(self, i: int, j: int) -> List[float]:
        return [self.x0 + (i + 0.5) * CELL, self.y0 + (j + 0.5) * CELL]

    def _free_near(self, i: int, j: int, grid: bytearray) -> Optional[Tuple[int, int]]:
        nx, ny = self.nx, self.ny
        for r in range(0, 6):
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    if max(abs(di), abs(dj)) != r:
                        continue
                    ii, jj = i + di, j + dj
                    if 0 <= ii < nx and 0 <= jj < ny and not grid[jj * nx + ii]:
                        return ii, jj
        return None

    def plan(self, a: Sequence[float], b: Sequence[float], budget_s: float = 0.012,
             max_nodes: int = 9000) -> Optional[List[List[float]]]:
        """A* from a to b in one go (tests/tools). Returns waypoints or None."""
        gen = self.search(a, b, max_nodes)
        next(gen)
        try:
            gen.send(time.perf_counter() + budget_s)
        except StopIteration as e:
            return e.value
        gen.close()
        return None  # out of budget

    def search(self, a: Sequence[float], b: Sequence[float], max_nodes: int = 30000):
        """Resumable A*: send() a perf_counter deadline; yields "more" when it ran out of time,
        returns the waypoint list (or None) via StopIteration."""
        deadline = yield "more"
        # An int is a node budget (deterministic: sim reruns match); a float a perf_counter deadline.
        stop_n = deadline if isinstance(deadline, int) else None
        grid = self.blocked
        nx = self.nx
        s = self._free_near(*self.cell(a[0], a[1]), grid)
        g = self._free_near(*self.cell(b[0], b[1]), grid)
        if s is None or g is None:
            return None
        si, sj = s
        gi, gj = g
        start, goal = sj * nx + si, gj * nx + gi
        if start == goal:
            return [list(b[:2])]
        hts = self.g
        rise = self.max_rise
        openh = [(0.0, start)]
        came = {start: -1}
        cost = {start: 0.0}
        n = 0
        D = DIRS
        moves = self.moves
        found = False
        while openh:
            _, k = heapq.heappop(openh)
            if k == goal:
                found = True
                break
            n += 1
            if n > max_nodes:
                break
            if stop_n is not None:
                if n >= stop_n:
                    deadline = yield "more"
                    stop_n = n + deadline if isinstance(deadline, int) else None
            elif n & 127 == 0 and time.perf_counter() > deadline:
                deadline = yield "more"
                stop_n = n + deadline if isinstance(deadline, int) else None
            ki, kj = k % nx, k // nx
            ck = cost[k]
            hk = hts[k]
            mk = moves[k]
            for bit, (di, dj, dc) in enumerate(D):
                if not (mk >> bit) & 1:
                    continue
                ii, jj = ki + di, kj + dj
                if ii < 0 or jj < 0 or ii >= nx or jj >= self.ny:
                    continue
                q = jj * nx + ii
                if grid[q] or hts[q] - hk > rise * dc:
                    continue
                if di and dj and (grid[kj * nx + ii] or grid[jj * nx + ki]):
                    continue
                c = ck + dc
                if c < cost.get(q, 1e18):
                    cost[q] = c
                    came[q] = k
                    h = 1.6 * math.hypot(ii - gi, jj - gj)
                    heapq.heappush(openh, (c + h, q))
        if not found:
            return None
        path = []
        k = goal
        while k != -1:
            path.append(self.center(k % nx, k // nx))
            k = came[k]
        path.reverse()
        path[-1] = list(b[:2])
        return path

    def clear_line(self, a: Sequence[float], b: Sequence[float]) -> bool:
        d = math.dist(a[:2], b[:2])
        n = max(1, int(d / (CELL * 0.5)))
        grid, nx = self.blocked, self.nx
        for s in range(n + 1):
            f = s / n
            i, j = self.cell(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            if grid[j * nx + i]:
                return False
        return True
