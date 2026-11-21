# Strategy pivot (away from lever A/B)

## Why the old loop failed

Roof-all peaked at **~2.29**. Stacking S1+N1 with dual-fire / hold-fight / ground-anchor / lightning-first all landed **~2.15**. Same decision skeleton + lever soup does not move practice score — it only reshuffles noise around a local max.

## What these three test

Fresh playbooks on the modern bugfix base (stuck-steer, climb-through-contact, roof avoid, ghost loot, laser hold, gun/mortar aim, FFA own-bullet). Legacy `LEVERS` stay **off**.

| # | tag | Bot.name | idea |
| --- | --- | --- | --- |
| 1 | `try/classic-roof` | `lh-classic-roof` | Replay historical ARM→roof→CAMP peek (`5e969f1` era). No ambush / THIRD / dual / hold / ground-anchor. Goal: recover old peak with fixed bugs. |
| 2 | `try/edge-hunter` | `lh-edge-hunter` | Quiet arm, zone-edge rotate, **only** rear/undetected 1v1s. THIRD only after sustained near sounds when armed+healed. No roof. |
| 3 | `try/loot-brawl` | `lh-loot-brawl` | Stay low, lightning-prefer second weapon, mid-range pocket trades, DISENGAGE on 2nd hunter, heal hard between waves. Never climb. |

## Submit order

1. **`try/classic-roof` first** — closest to the known historical high; validates “old playbook + bugfixes” vs roof-all 2.29.
2. **`try/edge-hunter`** — if classic dies early to shared-vision / roof contests.
3. **`try/loot-brawl`** — if edge/classic starve kills; tests aggressive ground DPS.

```sh
git fetch --tags --force
git checkout try/classic-roof   # then submit that tree
```
