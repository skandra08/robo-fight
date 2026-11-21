"""Strategy-plan levers for try/* A/B builds (robo-fight-strategy-plan.md).

Each try/<label> commit sets LABEL + which LEVERS are True. Bot.name = lh-<LABEL>.
"""
from __future__ import annotations

from typing import Dict

# try/r3-full — all approved rows
LABEL = "r3-full"

LEVERS: Dict[str, bool] = {
    "S1": True,  # every loadout camps on a roof
    "N1": True,  # laser counter for every loadout
    "N2": True,  # edge-guard hunters climbing our roof
    "N3": True,  # after kill: loot then heal ≥90%
    "S2": True,  # remove 1v1 ambush
    "S3": True,  # no ARM boost inside the zone
    "N4": True,  # pre-charged laser peeks
    "N5": True,  # cube snowball (drones + kill cubes)
    "N6": True,  # contest supply drop 1
    "S4": True,  # ROTATE gatekeep off in practice
    "F1": True,  # FFA detector + survival mode
}


def on(key: str) -> bool:
    return bool(LEVERS.get(key))
