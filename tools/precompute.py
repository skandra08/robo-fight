#!/usr/bin/env python3
"""Offline map precompute: data/roofs.json + data/cover.bin. Numpy allowed here."""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from world import World, _point_in_prism_xy  # noqa: E402


def _sample_ring_grid(prism: dict, step: float = 3.0):
    xs = np.arange(prism["minx"] + step * 0.5, prism["maxx"], step)
    ys = np.arange(prism["miny"] + step * 0.5, prism["maxy"], step)
    pts = []
    for x in xs:
        for y in ys:
            if _point_in_prism_xy(float(x), float(y), prism):
                pts.append((float(x), float(y)))
    return pts


def _hidden_frac(world: World, prism: dict, x: float, y: float, H: float) -> float:
    """Fast proxy + 8 LOS samples (4 dirs × 2 distances). Full 48-sample version is too slow offline."""
    ed = world.edge_distance(x, y, prism)
    base = min(1.0, ed / 12.0)
    our_c = H + 4.5
    blocked = 0
    total = 0
    for i in range(4):
        yaw = i * (math.pi / 2)
        c, s = math.cos(yaw), math.sin(yaw)
        for d in (80.0, 150.0):
            ox, oy = x + c * d, y + s * d
            oe = world.ground(ox, oy) + 8.0
            rid = world.roof_at(ox, oy)
            if rid is not None:
                rp = world.prisms[rid]
                if rp["top"] > H + 0.5:
                    oe = rp["top"] + 8.0
            total += 1
            if world.blocked_segment((ox, oy, oe), (x, y, our_c), step=4.0):
                blocked += 1
    return 0.5 * base + 0.5 * (blocked / max(1, total))


def build_roofs(world: World) -> list:
    roofs = []
    for prism in world.roofs:
        g_at_center = world.ground(
            (prism["minx"] + prism["maxx"]) * 0.5, (prism["miny"] + prism["maxy"]) * 0.5
        )
        climb_h = prism["top"] - g_at_center
        if climb_h > 55 or climb_h < 2.0:
            continue
        cells = _sample_ring_grid(prism, 3.0)
        if not cells:
            continue
        hidden_points = []
        firing_points = []
        for x, y in cells:
            ed = world.edge_distance(x, y, prism)
            if ed >= 3.0:
                hf = _hidden_frac(world, prism, x, y, prism["top"])
                hidden_points.append([round(x, 2), round(y, 2), round(hf, 3)])
            if ed <= 4.0:
                # firing directions: outward normals approximated by edge heading
                # use direction away from roof center
                cx = (prism["minx"] + prism["maxx"]) * 0.5
                cy = (prism["miny"] + prism["maxy"]) * 0.5
                yaw = math.atan2(y - cy, x - cx)
                # check open distance down
                open_ok = False
                for dist in (80.0, 120.0):
                    tx = x + math.cos(yaw) * dist
                    ty = y + math.sin(yaw) * dist
                    tg = world.ground(tx, ty)
                    if not world.blocked_segment(
                        (x, y, prism["top"] + 8), (tx, ty, tg + 4.5), step=4.0
                    ):
                        open_ok = True
                        break
                if open_ok or ed < 3.5:
                    firing_points.append([round(x, 2), round(y, 2), round(yaw, 3)])

        # climb points outside wall
        climb_points = []
        ring = prism["ring"]
        n = len(ring) // 2
        for i in range(0, n, max(1, n // 12)):
            x0, y0 = ring[2 * i], ring[2 * i + 1]
            x1, y1 = ring[2 * ((i + 1) % n)], ring[2 * ((i + 1) % n) + 1]
            mx, my = (x0 + x1) * 0.5, (y0 + y1) * 0.5
            ex, ey = x1 - x0, y1 - y0
            nx, ny = -ey, ex
            ln = math.hypot(nx, ny) or 1.0
            nx, ny = nx / ln, ny / ln
            # pick outward: point away from center
            cx = (prism["minx"] + prism["maxx"]) * 0.5
            cy = (prism["miny"] + prism["maxy"]) * 0.5
            if (mx - cx) * nx + (my - cy) * ny < 0:
                nx, ny = -nx, -ny
            for dist in (4.0, 5.5):
                px, py = mx + nx * dist, my + ny * dist
                if _point_in_prism_xy(px, py, prism):
                    continue
                climb_h = prism["top"] - world.ground(px, py)
                if 2.0 <= climb_h <= 55.0:
                    climb_points.append([round(px, 2), round(py, 2)])
                    break

        area = (prism["maxx"] - prism["minx"]) * (prism["maxy"] - prism["miny"])
        good_hidden = [h for h in hidden_points if h[2] >= 0.7]
        if len(good_hidden) < 1 or area < 150:
            continue
        # Bug #10: first-40 x-major scan left many roofs with ≤2 yaw quadrants.
        roofs.append(
            {
                "id": prism["id"],
                "top": round(prism["top"], 2),
                "center": [
                    round((prism["minx"] + prism["maxx"]) * 0.5, 2),
                    round((prism["miny"] + prism["maxy"]) * 0.5, 2),
                ],
                "hidden_points": sorted(good_hidden, key=lambda h: -h[2])[:40],
                "firing_points": _subsample_firing_by_yaw(firing_points, limit=40),
                "climb_points": climb_points[:16],
                "area": round(area, 1),
            }
        )
    return roofs


def _subsample_firing_by_yaw(
    pts: list, n_sectors: int = 16, per_sector: int = 3, limit: int = 40
) -> list:
    """Keep up to `per_sector` firing points per yaw sector for compass coverage."""
    if not pts:
        return []
    buckets: list = [[] for _ in range(n_sectors)]
    two_pi = 2 * math.pi
    for p in pts:
        yaw = float(p[2]) % two_pi
        if yaw < 0:
            yaw += two_pi
        i = int(yaw / two_pi * n_sectors) % n_sectors
        buckets[i].append(p)
    out: list = []
    for b in buckets:
        out.extend(b[:per_sector])
    return out[:limit]


def build_cover(world: World, out_path: str) -> None:
    """8 m grid for speed; still under 1 MB. Runtime treats missing fine cells as open."""
    step = 8.0
    minx, maxx = world.min_x + 8, world.min_x + world.nx * world.step - 8
    miny, maxy = world.min_y + 8, world.min_y + world.ny * world.step - 8
    xs = np.arange(minx, maxx, step)
    ys = np.arange(miny, maxy, step)
    nx, ny = len(xs), len(ys)
    cells = bytearray()
    # pre-bin prisms for near-wall flag
    for yi, y in enumerate(ys):
        if yi % 20 == 0:
            print(f"  cover row {yi}/{ny}")
        for x in xs:
            g = world.ground(float(x), float(y))
            eye = g + 8.0
            walkable = 0 if world.solid_at(float(x), float(y), g + 1.0) else 1
            near_wall = 0
            soft = 0
            opens = []
            for i in range(16):
                yaw = i * (2 * math.pi / 16)
                c, s = math.cos(yaw), math.sin(yaw)
                open_d = 200
                for d in (8, 16, 32, 48, 80, 120, 160, 200):
                    tx = float(x) + c * d
                    ty = float(y) + s * d
                    tg = world.ground(tx, ty)
                    if world.blocked_segment((float(x), float(y), eye), (tx, ty, tg + 8), step=6.0):
                        open_d = d
                        break
                opens.append(min(255, int(open_d)))
                if open_d < 12:
                    near_wall = 1
            flag = walkable | (near_wall << 1) | (soft << 2)
            cells.append(flag)
            cells.extend(opens)
    with open(out_path, "wb") as f:
        f.write(struct.pack("<ffffii", float(xs[0]), float(ys[0]), step, 0.0, nx, ny))
        f.write(cells)


def main():
    t0 = time.time()
    map_dir = os.path.join(ROOT, "arena")
    data_dir = os.path.join(ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    print("loading world…")
    world = World(map_dir)
    print(f"prisms={len(world.prisms)} roofs_candidates={len(world.roofs)}")
    print("building roofs.json…")
    roofs = build_roofs(world)
    roofs_path = os.path.join(data_dir, "roofs.json")
    with open(roofs_path, "w") as f:
        json.dump(roofs, f)
    print(f"wrote {len(roofs)} roofs -> {roofs_path}")
    print("building cover.bin (this takes a bit)…")
    cover_path = os.path.join(data_dir, "cover.bin")
    build_cover(world, cover_path)
    print(f"wrote {cover_path} ({os.path.getsize(cover_path)} bytes)")
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
