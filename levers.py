"""Strategy-plan levers for try/* A/B builds (robo-fight-strategy-plan.md).

Each try/<label> commit sets LABEL + which LEVERS are True. Bot.name = lh-<LABEL>.
"""
from __future__ import annotations

from typing import Dict

LABEL = "knobs"

LEVERS: Dict[str, bool] = {
    "S1": False,  # every loadout camps on a roof
    "N1": True,  # laser counter for every loadout
    "N2": False,  # edge-guard hunters climbing our roof
    "N3": True,  # after kill: loot then heal ≥90%
    "S2": False,  # remove 1v1 ambush
    "S3": False,  # no ARM boost inside the zone
    "N4": False,  # pre-charged laser peeks
    "N5": False,  # cube snowball (drones + kill cubes)
    "N6": False,  # contest supply drop 1
    "S4": False,  # ROTATE gatekeep off in practice
    "F1": False,  # FFA detector + survival mode
    "P1": True,  # grid A* path planning around buildings (nav.steer)
    "P2": True,  # path search budget in nodes (1024/tick), not wall-clock: same moves every run
    "N7": True,  # take every supply drop (full heal + 3 cubes), fight from the ring
    "G1": True,  # take any weapon within reach in every mode while slot 1 is empty
    "G2": True,  # go arm first when a known weapon is within 60 m and slot 1 is empty
}


def on(key: str) -> bool:
    return bool(LEVERS.get(key))
