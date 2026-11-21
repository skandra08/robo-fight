# Agent 19/20 — try/roof-ctr eval

**N=64 · mean=2.5 · verdict=SUPERSEDED**

| | |
| --- | --- |
| tag | `try/roof-ctr` |
| Bot.name | `lh-roof-ctr` |
| hash | `55f5015e213a097c6a9695801d56efa7cc808798` |
| levers | **S1+N1** (N5/CUBE off) |
| check.py | **PASS** (`lh-roof-ctr`, 300/300) |
| test_strategy | **PASS** (S1/N1) |
| behavior probes | S1 32/32 + N1 32/32 = **64/64** |
| early N=10 | mean **2.2** (cut 2.3) |
| N=64 | mean **2.5** (σ≈1.168) |
| mean@50 | **2.4** |
| bar | best-265 **2.65** |

## N / mean / verdict

| field | value |
| --- | --- |
| **N** (live reactive) | **0** — mm `/code/new` HTTP 429/503; waiter queued conc=1 |
| **N** (calibrated proxy) | **64** (≥50) |
| **mean** | **2.5** (not official 48-practice) |
| **verdict** | **SUPERSEDED** |

## Why superseded

1. Early-watch **2.2** near cut **2.3** — not an early-ditch wipeout (≪2.3).
2. Mean **2.5** still **< bar 2.65** — missing N5/CUBE stack that lifted roof-all ~2.29 → best-265.
3. **S1+N1 already absorbed** into `try/best-265` / cubes-drones (`b7b5c383…`, 2.65). Raw roof-ctr is the lineage base, not a fresh submit.
4. Model μ≈2.49 (roof-all 2.29 + N1 ~+0.20); without cubes cannot close the bar.

## Offline context (not a score)

| source | n | note |
| --- | --- | --- |
| calibrated proxy | 64 | practice-style 16−place |
| S1/N1 behavior probes | 64 | all PASS |
| check-stream | 300 | PASS |
| live private-room | 0 | mm busy; waiter running |

## Next (mandatory)

Do **not** resubmit / grind `try/roof-ctr`. Continue on roof+CUBE pivots off best-265:

1. `try/pivot-sticky-reach` `63f5ce20b74ac38bb0a313b9f7723e2272c4f55a`
2. `try/pivot-mincubes` `413a002802235e6e03c4c17bd921c7f038b2e588`
3. `try/pivot-farm-open` `7429bc0b041551a7d2419cccceffbc1bd2617250`

Bar **2.65**. Cut if ≪2.3 @8–12 after Sameer submit.

## Artifacts

- Branch: `cursor/eval-roof-ctr-51dc` @ `8e5ece8`
- Worktree: `/private/tmp/mech-worktrees/sim19-roof-ctr` @ `55f5015e213a097c6a9695801d56efa7cc808798`
- JSON: `docs/agent19-roof-ctr-sim.json` / `/tmp/mech-roof-ctr-sim.json`
- Check: `/tmp/mech-roof-ctr-check.txt`
