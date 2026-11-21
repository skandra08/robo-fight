# CURSOR_NOTES — fight-tactics swarm ranking

**Repo:** `skandra08/robo-fight`  
**BAR = 3.81** — `try/best-381` / `try/rewrite` = `f9eaf39685fec76442862288b13b1690eb6b3ce2` (`lh-rw-dual`)  
**Superseded bar:** `try/best-356` / `try/na-arm` = `8d5109ff0d252add3f45f0436d028a1df32d5d53` (`lh-na-arm`, **3.56**) — **historical only**  
**Aggregator branch:** `try/cursor-notes`  
**Deadline:** 11:00 AM America/New_York, 2026-11-21  
**Last scan:** 2026-11-21 03:25 EST

## NEW SWARM RULE (2026-11-21)

1. All **NEW** `try/cursor-*` fight experiments must base on **`f9eaf39`** (not `8d5109f`).
2. Still never push `main`.
3. Still **one change per branch**.
4. Still fight-tactics focus.
5. Still pass `tools/test_strategy.py` + `python3 check/check.py -- python3 -u bot.py`.
6. Older `8d5109f`-based sims / branches are **historical** — do not rank new work against them.

## Simulator

`try/sim` @ `5b3d022` (local worktree `/tmp/mech-sim-wt`).

```sh
python3 sim/run.py --seeds 96 --procs <cores> --params '{"track":true}' \
  --out out.json \
  f9eaf39685fec76442862288b13b1690eb6b3ce2 \
  <variant>
# compare per-seed wins vs f9eaf39 (3.81)
```

Example with 14 cores:

```sh
python3 sim/run.py --seeds 96 --procs 14 --params '{"track":true}' \
  --out /tmp/mech-cursor-<label>-vs-rw-dual.json \
  f9eaf39685fec76442862288b13b1690eb6b3ce2 \
  <candidate_sha>
```

**Ranking key:** per-seed **wins** vs `f9eaf39`, then mean Δ. Require **n≥48** for official rank. Never push `main`.

## Baseline (reference)

| Full hash | Branch / tag | Bot.name | Practice |
| --- | --- | --- | --- |
| `f9eaf39685fec76442862288b13b1690eb6b3ce2` | `try/rewrite` / `try/best-381` | `lh-rw-dual` | **3.81** official |
| `8d5109ff0d252add3f45f0436d028a1df32d5d53` | `try/na-arm` / `try/best-356` | `lh-na-arm` | 3.56 (historical) |
| `6eaffccf8caa484f67c6dfb4191bdecb850edd3d` | `try/rw-path` / `try/best-350` | `lh-rw-path` | 3.5 (ancestor of 3.81) |

**Identity of 3.81:** rewrite decision layer on `6eaffcc` (3.5) + arming tunables + grab-in-reach + **dual fire** (gun while laser charges) + deterministic 1024-node path budget. Label-only tip; real deltas in `550303f` / `44e4faf` / `3a20495`. **Dual-fire is already in the tip** — do not rebuild it.

## Next submit (off THIS bar)

| Priority | Full hash | Branch | Bot.name | Delta |
| --- | --- | --- | --- | --- |
| **SUBMIT NOW** | `dfb2931563b13d547b7ea042512f309dd2e05dc1` | `try/cursor-sticky` | `lh-cursor-sticky` | sticky FARM 2s on best-381 |
| Then | `0c11bda127ebab92e89700b3e2776e46fc3d2178` | `try/cursor-upgsus` | `lh-cursor-upgsus` | nanites/plating/armor first |
| Fight | `9698130906d023b877ba572ebac06f8403d30303` | `try/cursor-multi-dis-381` | `lh-cursor-multi-dis` | multi-attacker HEAL peel |
| Fight | `a6099596b742d03306c485048ae1bf5d6cf16985` | `try/cursor-lead-gun-381` | `lh-cursor-lead-gun` | quadratic gun intercept lead |

check.py: all four **PASS**.

## New pivots off 3.81 (rebuilt; dual-fire skipped — already in tip)

| Full hash | Branch | Change |
| --- | --- | --- |
| `dfb2931563b13d547b7ea042512f309dd2e05dc1` | `try/cursor-sticky` | sticky FARM 2s |
| `0c11bda127ebab92e89700b3e2776e46fc3d2178` | `try/cursor-upgsus` | nanites/plating/armor first |
| `9698130906d023b877ba572ebac06f8403d30303` | `try/cursor-multi-dis-381` | ≥2 attackers → HEAL peel ~2.5s |
| `a6099596b742d03306c485048ae1bf5d6cf16985` | `try/cursor-lead-gun-381` | exact gun intercept lead + spawn offset |

## Historical board (vs `8d5109f` / 3.56 — do not use for new ranking)

| Rank | Full hash (40) | Branch | vs `8d5109f` |
| --- | --- | --- | --- |
| 1 | `afc8f2fc37909560f67ec2c801b1d0dcb2db34d6` | `try/cursor-lead-gun` | **14W / 19L / 63T**, mean Δ **−0.031** — FLAT/DITCH |

All other pre-bar-update `try/cursor-*` tips based on `8d5109f` are historical awaiting archive; rebuild fight ideas off `f9eaf39` before ranking.

## Scan log

| When (EST) | Event |
| --- | --- |
| 03:11 | Bootstrap `try/cursor-notes`; fetched `try/sim` |
| 03:18 | lead-gun full n=96 ranked vs na-arm |
| 03:22 | Wave-controller batch-2 on 3.56 base (historical) |
| 03:25 | **BAR → 3.81** `f9eaf39` / `try/best-381`; tagged; rebuilt sticky/upgsus/multi-dis/lead off tip |

## Protocol

1. Land fight changes on `try/cursor-*` only (never `main`), **based on `f9eaf39`**.
2. Drop `/tmp/mech-cursor-<label>.md` + JSON with full hash and paired W/L/T vs **`f9eaf39`**.
3. Aggregator ranks by seed wins vs `f9eaf39`, then mean Δ; pushes `try/cursor-notes`.
