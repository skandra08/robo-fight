"""Strategy-plan levers for try/* A/B builds (robo-fight-strategy-plan.md).

Each try/<label> commit sets LABEL + which LEVERS are True. Bot.name = lh-<LABEL>.
"""
from __future__ import annotations

import os
from typing import Dict

LABEL = "stack"

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
    "C1": True,  # gun keeps firing while the laser charges
    "S5": False,  # path following slides along walls the grid missed (footprint probe)
    "G4": False,  # G2 is checked before the post-kill loot/heal (walk to the weapon while regenerating)
    "P2": True,  # path search budget in nodes (1024/tick), not wall-clock: same moves every run
    "N7": True,  # take every supply drop (full heal + 3 cubes), fight from the ring
    "G1": True,  # take any weapon within reach in every mode while slot 1 is empty
    "G2": True,  # go arm first when a known weapon is within 60 m and slot 1 is empty
}


def on(key: str) -> bool:
    v = os.environ.get("LH_LEVER_" + key)  # practice-sim sweeps only; unset on the server
    if v is not None:
        return v not in ("0", "", "false", "False")
    return bool(LEVERS.get(key))


# Tunables. Each can be overridden in the practice sim with env LH_<NAME> (sweeps without commits);
# a submitted build uses the defaults written here.
PARAMS: Dict[str, float] = {
    "FARM_T": 75.0,     # early farm phase length (s)
    "HEAL_FRAC": 0.65,  # HEAL when quiet and below this HP fraction
    "N3_HEAL": 0.90,    # after a kill, heal to this fraction
    "ARM_D": 60.0,      # G2: arm first when a known weapon is this close
    "SUP_D": 450.0,     # max distance to go for a supply drop
    "SUP_VIS": 0.0,     # skip supply if a visible enemy is closer than this (0 = never skip)
    "DRONE_D": 150.0,   # max distance to farm a drone
}


def p(key: str) -> float:
    v = os.environ.get("LH_" + key)
    if v is not None:
        try:
            return float(v)
        except ValueError:
            pass
    return float(PARAMS[key])
