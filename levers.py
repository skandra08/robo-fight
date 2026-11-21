"""Strategy-plan levers for try/* A/B builds (robo-fight-strategy-plan.md).

Each try/<label> commit sets LABEL + which LEVERS are True. Bot.name = lh-<LABEL>.
"""
from __future__ import annotations

from typing import Dict

LABEL = "rw-heal-fight"

LEVERS: Dict[str, bool] = {
    "S1": True,  # every loadout camps on a roof
    "N1": True,  # laser counter for every loadout
    "N2": False,  # edge-guard hunters climbing our roof
    "N3": False,  # after kill: loot then heal ≥90%
    "S2": False,  # remove 1v1 ambush
    "S3": False,  # no ARM boost inside the zone
    "N4": False,  # pre-charged laser peeks
    "N5": False,  # cube snowball (drones + kill cubes)
    "N6": False,  # contest supply drop 1
    "S4": False,  # ROTATE gatekeep off in practice
    "F1": False,  # FFA detector + survival mode
}


def on(key: str) -> bool:
    return bool(LEVERS.get(key))
