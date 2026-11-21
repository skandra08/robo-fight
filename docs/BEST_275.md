# NEW BASELINE — best-275 (official practice 2.75)

| | |
| --- | --- |
| **Full hash** | `fa3e2828e3c1b1e1edd37c257a5b6e4ec8d1380d` |
| **Tags** | `try/best-275`, `try/v-greedy` |
| **Bot.name** | `lh-v-greedy` |
| **Levers** | **S1+N1 only** |
| **Score** | **2.75** (beats best-265 / cubes-drones at 2.65) |
| **Parent** | `b7b5c38367dbf208f836f77d8f8a1ee4dd2658f4` (`try/best-265` / `try/cubes-drones`) |

## What +0.10 came from (ONLY change vs 2.65)

One-file numeric greed in `_cube_goal` (LABEL rename only in `levers.py`):

1. **Cube walk reach:** quiet `100 → 160`; with hunter `min(60, 0.4·d) → min(80, 0.5·d)`
2. **Post-kill site:** `170 → 250` m; hunter slack `d+80 → d+50` (scoop after kills more often)
3. **Crate break gate:** `enemy_d > 130 → > 90` (break crates with nearer mechs)

State machine order **unchanged** from best-265: CUBE still checked **before** RELOCATE/roof. No sticky, no locked-proc, no new levers.

## Freeze

- Do **not** build future variants off `b7b5c38` / 2.65.
- Do **not** re-submit precise / roof-all / pre-greedy cube stacks as the base.
- Official 48 is ground truth; do not grind live WS for scoring.

## Next A/B (off this commit)

| # | tag | Bot.name | hash | delta |
| --- | --- | --- | --- | --- |
| 1 | `try/g-sticky` | `lh-g-sticky` | `cd664e522c3d7858fee61ff676a9c985fd6faeaa` | sticky CUBE 2s (keep greedy reaches) |
| 2 | `try/g-proc` | `lh-g-proc` | `907f9f38a4a01742eb086b36e966db1f63b83275` | sticky + post-kill reach 190 |
| 3 | `try/g-edge` | `lh-g-edge` | `b9b02bab75cd0e1aaa315215d73c16302fb82afd` | N2 edge-guard |

Already pushed earlier off greedy (score unknown): `try/g-dronefarm`, `try/g-greedier`, `try/g-zone`, `try/g-upgsus`.

Submit order: **g-sticky first**, then g-proc if sticky helps; g-edge only if roof deaths from climbers show up.
