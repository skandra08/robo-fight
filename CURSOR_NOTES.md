# CURSOR_NOTES — fight-tactics swarm ranking

**Repo:** `skandra08/robo-fight`  
**Baseline:** `try/na-arm` / `try/best-356` = `8d5109ff0d252add3f45f0436d028a1df32d5d53` (`lh-na-arm`, official practice **3.56**)  
**Aggregator branch:** `try/cursor-notes` @ `d9ca296652e7118da1dc4d1e0d6ea49d3c3f2e36`  
**Deadline:** 11:00 AM America/New_York, 2026-11-21  
**Last scan:** 2026-11-21 03:12 EST

## Simulator

`try/sim` fetched locally (worktree `/tmp/mech-sim-wt` @ `5b3d022`).

Exact command used for head-to-head vs baseline:

```sh
git fetch origin try/sim try/na-arm
# from a checkout that has sim/ (e.g. worktree of origin/try/sim):
python3 sim/run.py --seeds 48 --procs 4 --seed0 1 \
  8d5109ff0d252add3f45f0436d028a1df32d5d53 \
  <candidate_full_or_abbrev_sha> \
  --out /tmp/mech-cursor-<label>-vs-na-arm.json
```

Smoke (2 seeds on baseline): mean score **4.5** / 2 matches / 5s — log `/tmp/mech-cursor-sim-smoke.txt`.

**Ranking key:** per-seed win count vs baseline (candidate score > baseline on same seed), then mean Δscore. Never push `main`.

## Ranked board (BEST FIRST)

_No scored `try/cursor-*` fight changes yet (tips still = baseline or notes-only)._

| Rank | Full hash (40) | Branch | One-sentence change | vs `8d5109f` |
| --- | --- | --- | --- | --- |
| — | — | — | awaiting sibling commits + sim dumps | — |

### Baseline (reference, not ranked)

| Full hash | Branch / tag | Change | Practice |
| --- | --- | --- | --- |
| `8d5109ff0d252add3f45f0436d028a1df32d5d53` | `try/na-arm` / `try/best-356` | G1 grab + G2 arm-first ≤60 m on bf-noavoid plate | **3.56** official |

### In-flight (local tips still == baseline)

| Branch | Tip hash | Expected tweak (from name) | Sim / `/tmp/mech-cursor-*.md` |
| --- | --- | --- | --- |
| `try/cursor-isolate-1v1` | `8d5109ff0d252add3f45f0436d028a1df32d5d53` | isolate / prefer clean 1v1s | pending |
| `try/cursor-lead-gun` | `8d5109ff0d252add3f45f0436d028a1df32d5d53` | gun lead / aim lead | pending |
| `try/cursor-ltn-brawl` | `8d5109ff0d252add3f45f0436d028a1df32d5d53` | lightning brawl aggression | pending |
| `try/cursor-mortar-kite` | `8d5109ff0d252add3f45f0436d028a1df32d5d53` | mortar kite spacing | pending |
| `try/cursor-upg-armor` | `8d5109ff0d252add3f45f0436d028a1df32d5d53` | armor-first upgrades | pending |

### Queued off-bar (not cursor swarm; context)

| Full hash | Branch | Change | Status |
| --- | --- | --- | --- |
| `02ca46051c9067f977ed2f5fbb82df9437eb59b0` | `try/na-sticky` | sticky CUBE 2 s on best-356 | check.py PASS |
| `d73e3984f65139bba9ccaa0febd7ade00c3af300` | `try/na-upgsus` | nanites/plating/armor first on best-356 | check.py PASS |

## Scan log

| When (EST) | Event |
| --- | --- |
| 03:11 | Bootstrap `try/cursor-notes`; fetched `try/sim`; sim smoke OK |
| 03:12 | Local swarm branches seen: isolate-1v1, lead-gun, ltn-brawl, mortar-kite, upg-armor (all @ baseline); no result md yet |

## Protocol (swarm)

1. Experiments land on `try/cursor-*` (never `main`).
2. Drop `/tmp/mech-cursor-<label>.md` and/or `results/` with full 40-char hash + sim summary (seed wins/losses/ties + mean Δ).
3. Aggregator re-ranks by **seed wins vs `8d5109f`**, then mean Δ, pushes this file on `try/cursor-notes`.
