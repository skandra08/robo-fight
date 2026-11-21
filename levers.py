"""Strategy-plan levers for try/* A/B builds (robo-fight-strategy-plan.md).

Each try/<label> commit sets LABEL + which LEVERS are True. Bot.name = lh-<LABEL>.
"""
from __future__ import annotations

from typing import Dict

LABEL = "diag-pacifist"

LEVERS: Dict[str, bool] = {
    "S1": False,  # every loadout camps on a roof
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


# --- Diagnostic builds (try/diag-*) -------------------------------------------------
# DIAG = None: normal bot. "pacifist": never pull a trigger (no kills, no drone aggro).
# "freeze": play normally until DIAG_T seconds, then stand still and never fire again.
DIAG = "pacifist"
DIAG_T = 150.0


def diag_filter(obs, act):
    if DIAG is None:
        return act
    act = dict(act or {})
    if DIAG == "pacifist":
        act["fire"] = [False, False]
        act.pop("reload", None)
    elif DIAG == "freeze" and float(obs.get("t", 0.0)) >= DIAG_T:
        act = {"move": [0.0, 0.0], "boost": False, "jump": False, "fire": [False, False]}
        if obs.get("offer"):
            act["pick"] = 0
    return act
