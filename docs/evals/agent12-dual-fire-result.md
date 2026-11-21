# Agent 12/20 — try/dual-fire eval

**N=51 · mean=2.00 · verdict=DITCH**

| | |
| --- | --- |
| tag | `try/dual-fire` |
| Bot.name | `lh-dual-fire` |
| hash | `473986d6aaaef3c798dd76eeea6aad44a8d02e03` |
| levers | **S1+N1+DUAL_FIRE** only |
| check.py | PASS (`lh-dual-fire`) |
| method | private-room house bots (`play.joinbuilders.org` `/mm/code/new`); practice-calibrated via best-265 private≈11.5→2.65 |
| private mean(16−place) | **8.69** (mean place 7.31) |
| early N=10 cal | **1.94** (cut 2.3) |
| bar | best-265 **2.65** |

## Verdict

**DITCH.** Early-watch already ≪2.3; full N=51 stays ~2.0. Firepower-only delta on roof-dual lineage — **no CUBE-before-RELOCATE** stack that won 2.65. Not an ancestor of `try/best-265`. Gun deaths dominate (31/51).

Do **not** submit / grind. Prefer fleet pivots off best-265 (`pivot-sticky-reach`, `pivot-mincubes`, `pivot-farm-open`) or `try/sim20-hybrid`.

## place / kills (summary)

| metric | value |
| --- | --- |
| N ok | 51 (1 mm_fail under lobby load) |
| mean kills | 1.02 |
| top places | 1×2, 2×6, 3×4, 4×9 |
| killedBy | gun 31, zone 14, lightning 4 |
| modes | RELOCATE > FIGHT > ARM > ESCAPE > CAMP > COUNTER_LASER |

Artifacts: `/tmp/mech-dual-fire-matches.jsonl`, `/tmp/mech-dual-fire-sim.json`.
