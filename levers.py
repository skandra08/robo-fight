"""Practice playbook selector for try/* builds (post A/B lever-loop pivot).

PLAYBOOK owns decisions. Legacy LEVERS stay False on pivot tags — bugfixes live
in bot/combat/nav regardless. Bot.name = lh-<LABEL>.

Mechanics-first (this pass):
  precise — thin ARM → zone → fight; nail low-level exploits (rear/regen/gun/laser/…)

Simple placement (prior):
  zone-sheep   — never start fights; deep next-zone; quiet heal
  cube-snowball — farm NPCs/crates/cubes ASAP; free fights only
"""
from __future__ import annotations

from typing import Dict


LABEL = "precise"
# classic-roof | edge-hunter | loot-brawl | zone-sheep | cube-snowball | precise
PLAYBOOK = "precise"

# Legacy S/N/F levers — off for pivot playbooks (kept for test_strategy skips).
LEVERS: Dict[str, bool] = {
    "S1": False,  # every loadout camps on a roof
    "N1": False,  # laser counter for every loadout
    "N2": False,  # edge-guard hunters climbing our roof
    "N3": False,  # after kill: loot then heal ≥90%
    "S2": False,  # remove 1v1 ambush
    "S3": False,  # no ARM boost inside the zone
    "N4": False,  # pre-charged laser peeks
    "N5": False,  # cube snowball (drones + kill cubes)
    "N6": False,  # contest supply drop 1
    "S4": False,  # ROTATE gatekeep off in practice
    "F1": False,  # FFA detector + survival mode
    "DUAL_FIRE": False,  # gun keeps firing on lead while laser/lightning charge/fire
    "HOLD_FIGHT": False,  # no chase in fight; hold roof / half-strafe; idle aim no fire
    "GROUND_ANCHOR": False,  # choke/pocket hold phases 0-2; roof fallback late
    "LIGHTNING_FIRST": False,  # loot lightning > laser > mortar; prefer pocket anchors
}


def on(key: str) -> bool:
    return bool(LEVERS.get(key))


def playbook() -> str:
    return PLAYBOOK
