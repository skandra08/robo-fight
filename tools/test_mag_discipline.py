#!/usr/bin/env python3
"""Unit checks for gun mag discipline (hold vs tap vs withhold). Stdlib only."""
from __future__ import annotations

import math
import os
import sys
from typing import Any, Dict, List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from combat import Combat  # noqa: E402
from world import World  # noqa: E402


class _Mem:
    def __init__(self) -> None:
        self.shots_here = 0
        self.shots = 0
        self.last_mortar_t = -1e9
        self.mortars_here = 0
        self.mortars = 0


def _cfg() -> Dict[str, Any]:
    return {
        "mech": {"radius": 2.5, "height": 9.0, "muzzle_height": 7.0, "eye_height": 8.0},
        "cubes": {"size_per_cube": 0.05},
        "weapons": {
            "gun": {
                "damage": 45,
                "cooldown": 0.24,
                "speed": 252,
                "range": 230,
                "spread_deg": 0.6,
                "mag": 12,
                "reload": 2.4,
            },
            "laser": {"damage": 315, "charge": 0.75, "range": 280},
            "mortar": {"damage": 200, "cooldown": 2.6, "speed": 72, "gravity": 22},
            "lightning": {"damage": 60, "range": 45, "cooldown": 0.25, "cone_deg": 30},
        },
    }


def _me(pos: List[float], aim: List[float], ammo: int = 12, cd: float = 0.0) -> Dict[str, Any]:
    return {
        "pos": list(pos),
        "vel": [0.0, 0.0, 0.0],
        "aim": list(aim),
        "cubes": 0,
        "weapons": [
            {
                "kind": "gun",
                "ammo": ammo,
                "cooldown": cd,
                "reload": 0,
                "stats": {
                    "damage": 45,
                    "cooldown": 0.24,
                    "speed": 252,
                    "range": 230,
                    "spread_deg": 0.6,
                    "mag": 12,
                    "reload": 2.4,
                },
            },
            None,
        ],
        "stats": {"muzzle_height": 7.0, "eye_height": 8.0, "height": 9.0},
    }


def _tgt(pos: List[float], vel: List[float] | None = None, cubes: int = 0) -> Dict[str, Any]:
    return {
        "id": 5,
        "kind": "mech",
        "pos": list(pos),
        "vel": list(vel or [0.0, 0.0, 0.0]),
        "aim": [0.0, 0.0],
        "hp": 1400,
        "cubes": cubes,
    }


def check(name: str, cond: bool) -> None:
    if not cond:
        raise AssertionError(name)
    print(f"  PASS {name}")


def main() -> int:
    map_dir = os.path.join(ROOT, "arena")
    if not os.path.isdir(os.path.join(map_dir, "v2")):
        print("FAIL: arena/v2 missing", file=sys.stderr)
        return 1
    world = World(map_dir)
    combat = Combat(world, _cfg())

    # Close, stationary, aimed: high hit chance → hold trigger.
    me = _me([0.0, 0.0, 1.5], [0.0, 0.0])
    tgt = _tgt([40.0, 0.0, 1.5])
    aim = combat.aim_at(me, tgt, "gun")
    me["aim"] = list(aim)
    p_close = combat.gun_hit_prob(me, tgt, aim, me["weapons"][0])
    check(f"close hit_p high ({p_close:.2f})", p_close >= 0.40)
    mem = _Mem()
    fire, _, _ = combat.fire_slots(me, aim, tgt, 10.0, mem, aim_kind="gun")
    check("close hold fire", fire[0] is True)

    # Far + aim error: low hit chance → withhold (don't dump mag).
    me_far = _me([0.0, 0.0, 1.5], [0.15, 0.0])  # ~8.6° yaw error
    tgt_far = _tgt([200.0, 0.0, 1.5])
    aim_far = combat.aim_at(me_far, tgt_far, "gun")
    # Keep bad aim (do not snap to desired).
    p_far = combat.gun_hit_prob(me_far, tgt_far, aim_far, me_far["weapons"][0])
    check(f"far+bad aim hit_p low ({p_far:.2f})", p_far < 0.16)
    mem2 = _Mem()
    fire2, _, _ = combat.fire_slots(me_far, aim_far, tgt_far, 10.0, mem2, aim_kind="gun")
    check("far+bad aim withholds", fire2[0] is False)

    # Mid range with ~2° slew error: tap band — one shot then release.
    me_mid = _me([0.0, 0.0, 1.5], [0.0, 0.0], cd=0.0)
    tgt_mid = _tgt([120.0, 0.0, 1.5])
    aim_mid = combat.aim_at(me_mid, tgt_mid, "gun")
    me_mid["aim"] = [aim_mid[0] + math.radians(2.0), aim_mid[1]]
    p_mid = combat.gun_hit_prob(me_mid, tgt_mid, aim_mid, me_mid["weapons"][0])
    check(f"mid+2deg hit_p in tap band ({p_mid:.2f})", 0.16 <= p_mid < 0.40)
    mem3 = _Mem()
    fire3, _, _ = combat.fire_slots(me_mid, aim_mid, tgt_mid, 20.0, mem3, aim_kind="gun")
    check("mid tap first shot", fire3[0] is True)
    me_mid["weapons"][0]["cooldown"] = 0.2
    fire4, _, _ = combat.fire_slots(me_mid, aim_mid, tgt_mid, 20.05, mem3, aim_kind="gun")
    check("mid tap releases between shots", fire4[0] is False)

    # Aimed empty mag still requests reload.
    me_empty = _me([0.0, 0.0, 1.5], [0.0, 0.0], ammo=0)
    tgt_e = _tgt([30.0, 0.0, 1.5])
    aim_e = combat.aim_at(me_empty, tgt_e, "gun")
    me_empty["aim"] = list(aim_e)
    mem4 = _Mem()
    fire5, reload, _ = combat.fire_slots(me_empty, aim_e, tgt_e, 30.0, mem4, aim_kind="gun")
    check("empty mag no fire", fire5[0] is False)
    check("empty mag reload", reload is True)

    print("ALL MAG DISCIPLINE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
