"""Load precomputed roof/cover data and pick camp spots."""
from __future__ import annotations

import json
import math
import os
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple


class CoverBook:
    def __init__(self, data_dir: str):
        self.roofs: List[Dict[str, Any]] = []
        roofs_path = os.path.join(data_dir, "roofs.json")
        if os.path.isfile(roofs_path):
            with open(roofs_path) as f:
                self.roofs = json.load(f)
        self._by_id = {int(r["id"]): r for r in self.roofs}

        self.choke_sites: List[Dict[str, Any]] = []
        choke_path = os.path.join(data_dir, "choke_sites.json")
        if os.path.isfile(choke_path):
            try:
                with open(choke_path) as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    self.choke_sites = raw
            except (OSError, json.JSONDecodeError, ValueError):
                self.choke_sites = []

        self.cover_ok = False
        self.minx = self.miny = self.step = 0.0
        self.nx = self.ny = 0
        self._cells: bytes = b""
        cover_path = os.path.join(data_dir, "cover.bin")
        hdr_size = struct.calcsize("<ffffii")
        if os.path.isfile(cover_path):
            try:
                with open(cover_path, "rb") as f:
                    header = f.read(hdr_size)
                    if len(header) == hdr_size:
                        self.minx, self.miny, self.step, _, self.nx, self.ny = struct.unpack(
                            "<ffffii", header
                        )
                        self._cells = f.read()
                        need = max(0, self.nx * self.ny * 17)
                        self.cover_ok = self.nx > 0 and self.ny > 0 and len(self._cells) >= need
            except (struct.error, OSError, ValueError):
                self.cover_ok = False

    def roof(self, rid: int) -> Optional[Dict[str, Any]]:
        return self._by_id.get(int(rid))

    def best_hidden(self, roof: Dict[str, Any]) -> Optional[List[float]]:
        pts = roof.get("hidden_points") or []
        if not pts:
            return None
        best = max(pts, key=lambda p: p[2])
        return [best[0], best[1]]

    def best_firing(self, roof: Dict[str, Any], toward_yaw: Optional[float] = None) -> Optional[List[float]]:
        pts = roof.get("firing_points") or []
        if not pts:
            # fall back to edge-ish hidden
            hid = roof.get("hidden_points") or []
            return [hid[0][0], hid[0][1]] if hid else None
        if toward_yaw is None:
            return [pts[0][0], pts[0][1]]
        best = min(pts, key=lambda p: abs(_angdiff(p[2], toward_yaw)))
        return [best[0], best[1]]

    def nearest_climb(self, roof: Dict[str, Any], pos: Sequence[float]) -> Optional[List[float]]:
        pts = roof.get("climb_points") or []
        if not pts:
            return None
        return min(pts, key=lambda p: (p[0] - pos[0]) ** 2 + (p[1] - pos[1]) ** 2)

    def score_roof(
        self,
        roof: Dict[str, Any],
        pos: Sequence[float],
        next_center: Sequence[float],
        next_radius: float,
        taller_penalty: float = 0.0,
    ) -> float:
        hid = roof.get("hidden_points") or []
        if not hid:
            return -1e9
        # require some hidden point inside 80% of next zone
        rlim = 0.8 * next_radius
        cx, cy = next_center[0], next_center[1]
        inside = [h for h in hid if (h[0] - cx) ** 2 + (h[1] - cy) ** 2 <= rlim * rlim]
        if not inside:
            return -1e9
        best_hf = max(h[2] for h in inside)
        travel = math.hypot(roof["center"][0] - pos[0], roof["center"][1] - pos[1])
        return best_hf - 0.015 * travel - taller_penalty

    def pick_roof(
        self,
        pos: Sequence[float],
        next_center: Sequence[float],
        next_radius: float,
        world_tops: Optional[Dict[int, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        best = None
        best_s = -1e9
        for r in self.roofs:
            pen = 0.0
            if world_tops:
                for oid, top in world_tops.items():
                    if oid == r["id"]:
                        continue
                    if top > r["top"] + 1.0:
                        oc = self._by_id.get(oid)
                        # approximate: if any other roof center within 150m and taller
                        d = math.hypot(r["center"][0] - (oc["center"][0] if oc else 0), r["center"][1] - (oc["center"][1] if oc else 0)) if oc else 999
                        if d < 150:
                            pen += 0.05
            s = self.score_roof(r, pos, next_center, next_radius, pen)
            if s > best_s:
                best_s = s
                best = r
        return best if best_s > -1e8 else None

    def _cell(self, ix: int, iy: int) -> Optional[Tuple[int, List[int]]]:
        if not self.cover_ok or ix < 0 or iy < 0 or ix >= self.nx or iy >= self.ny:
            return None
        off = (iy * self.nx + ix) * 17
        chunk = self._cells[off : off + 17]
        if len(chunk) < 17:
            return None
        return chunk[0], list(chunk[1:17])

    def pick_choke(
        self,
        pos: Sequence[float],
        next_center: Sequence[float],
        next_radius: float,
        prefer_kind: Optional[str] = None,
        prefer_min_sight: float = 0.0,
        max_travel: float = 200.0,
    ) -> Optional[Dict[str, Any]]:
        """Nearest foot-reachable choke/pocket inside 0.8×next zone, within max_travel."""
        if not self.choke_sites:
            return None
        rlim = 0.8 * next_radius
        cx, cy = next_center[0], next_center[1]
        best = None
        best_s = -1e9
        for s in self.choke_sites:
            x, y = float(s["x"]), float(s["y"])
            if (x - cx) ** 2 + (y - cy) ** 2 > rlim * rlim:
                continue
            travel = math.hypot(x - pos[0], y - pos[1])
            if travel > max_travel:
                continue
            sight = float(s.get("max_sight_m") or 0)
            kind = s.get("kind") or "choke"
            # Prefer requested kind (pocket) and sight floor (laser wants 80+).
            kind_bonus = 40.0 if prefer_kind and kind == prefer_kind else 0.0
            sight_bonus = 0.0
            if prefer_min_sight > 0:
                if sight >= prefer_min_sight:
                    sight_bonus = 25.0 + 0.05 * sight
                else:
                    sight_bonus = 0.02 * sight
            elif kind == "pocket":
                sight_bonus = 10.0
            else:
                sight_bonus = 0.05 * sight
            score = kind_bonus + sight_bonus - 0.05 * travel
            if score > best_s:
                best_s = score
                best = s
        return best

    def ground_spot(self, pos: Sequence[float], zone_c: Sequence[float], zone_r: float) -> Optional[List[float]]:
        if not self.cover_ok:
            return None
        best = None
        best_s = -1e9
        # search nearby cells
        ix0 = int((pos[0] - self.minx) / self.step)
        iy0 = int((pos[1] - self.miny) / self.step)
        for dy in range(-12, 13):
            for dx in range(-12, 13):
                cell = self._cell(ix0 + dx, iy0 + dy)
                if cell is None:
                    continue
                flag, opens = cell
                if not (flag & 1):
                    continue
                blocked_close = sum(1 for d in opens if d < 12)
                open_lanes = 0
                i = 0
                while i < 16:
                    if opens[i] > 40:
                        open_lanes += 1
                        while i < 16 and opens[i] > 40:
                            i += 1
                    else:
                        i += 1
                if blocked_close < 6 or not (1 <= open_lanes <= 2):
                    continue
                x = self.minx + (ix0 + dx) * self.step
                y = self.miny + (iy0 + dy) * self.step
                if (x - zone_c[0]) ** 2 + (y - zone_c[1]) ** 2 > (0.8 * zone_r) ** 2:
                    continue
                exposure = sum(opens)
                travel = math.hypot(x - pos[0], y - pos[1])
                s = blocked_close * 10 - 0.01 * exposure - 0.02 * travel
                if s > best_s:
                    best_s = s
                    best = [x, y]
        return best

    def far_ground_spot(
        self,
        pos: Sequence[float],
        zone_c: Sequence[float],
        zone_r: float,
        away_from: Optional[Sequence[float]] = None,
    ) -> Optional[List[float]]:
        """Mortar camp: deep inside the zone, far from threats / current pos."""
        if not self.cover_ok:
            # geometric fallback: 0.55 * radius opposite away_from
            if away_from is None:
                away_from = pos
            dx, dy = pos[0] - away_from[0], pos[1] - away_from[1]
            if dx * dx + dy * dy < 1:
                dx, dy = 1.0, 0.0
            ln = math.hypot(dx, dy) or 1.0
            r = 0.55 * zone_r
            return [zone_c[0] + dx / ln * r, zone_c[1] + dy / ln * r]
        best = None
        best_s = -1e9
        ix0 = int((zone_c[0] - self.minx) / self.step)
        iy0 = int((zone_c[1] - self.miny) / self.step)
        span = max(8, int(0.7 * zone_r / self.step))
        for dy in range(-span, span + 1, 2):
            for dx in range(-span, span + 1, 2):
                cell = self._cell(ix0 + dx, iy0 + dy)
                if cell is None:
                    continue
                flag, opens = cell
                if not (flag & 1):
                    continue
                x = self.minx + (ix0 + dx) * self.step
                y = self.miny + (iy0 + dy) * self.step
                if (x - zone_c[0]) ** 2 + (y - zone_c[1]) ** 2 > (0.7 * zone_r) ** 2:
                    continue
                dist_me = math.hypot(x - pos[0], y - pos[1])
                dist_threat = 0.0
                if away_from is not None:
                    dist_threat = math.hypot(x - away_from[0], y - away_from[1])
                blocked = sum(1 for d in opens if d < 20)
                s = dist_threat * 0.4 + dist_me * 0.15 + blocked * 2.0
                if s > best_s:
                    best_s = s
                    best = [x, y]
        return best

    def corner_spot(self, pos: Sequence[float], zone_c: Sequence[float], zone_r: float) -> Optional[List[float]]:
        """Lightning: tight cover, many blocked close rays, still in zone."""
        if not self.cover_ok:
            return self.ground_spot(pos, zone_c, zone_r)
        best = None
        best_s = -1e9
        ix0 = int((pos[0] - self.minx) / self.step)
        iy0 = int((pos[1] - self.miny) / self.step)
        for dy in range(-16, 17):
            for dx in range(-16, 17):
                cell = self._cell(ix0 + dx, iy0 + dy)
                if cell is None:
                    continue
                flag, opens = cell
                if not (flag & 1):
                    continue
                blocked_close = sum(1 for d in opens if d < 12)
                if blocked_close < 8:
                    continue
                x = self.minx + (ix0 + dx) * self.step
                y = self.miny + (iy0 + dy) * self.step
                if (x - zone_c[0]) ** 2 + (y - zone_c[1]) ** 2 > (0.85 * zone_r) ** 2:
                    continue
                travel = math.hypot(x - pos[0], y - pos[1])
                s = blocked_close * 12 - 0.05 * travel
                if s > best_s:
                    best_s = s
                    best = [x, y]
        return best or self.ground_spot(pos, zone_c, zone_r)


def _angdiff(a: float, b: float) -> float:
    d = (a - b + math.pi) % (2 * math.pi) - math.pi
    return d
