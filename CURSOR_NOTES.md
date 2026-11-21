# CURSOR_NOTES — fight-tactics swarm ranking

**Repo:** `skandra08/robo-fight`  
**Baseline:** `try/na-arm` / `try/best-356` = `8d5109ff0d252add3f45f0436d028a1df32d5d53` (`lh-na-arm`, official practice **3.56**)  
**Aggregator branch:** `try/cursor-notes`  
**Deadline:** 11:00 AM America/New_York, 2026-11-21  
**Last scan:** 2026-11-21 03:22 EST

## Simulator

`try/sim` @ `5b3d022` (local worktree `/tmp/mech-sim-wt`).

```sh
python3 sim/run.py --seeds 96 --procs 8 --seed0 1 \
  8d5109ff0d252add3f45f0436d028a1df32d5d53 \
  <candidate_sha> \
  --out /tmp/mech-cursor-<label>-vs-na-arm.json
# optional: --params '{"track":true}'
```

Smoke check used: `python3 sim/run.py --seeds 2 --procs 2 --seed0 1 8d5109ff0d252add3f45f0436d028a1df32d5d53` → mean 4.5 (`/tmp/mech-cursor-sim-smoke.txt`).

**Ranking key:** per-seed **wins** vs baseline (higher score on same seed), then mean Δ. Require **n≥48** for official rank; smokes (n=2) listed as preliminary only. Never push `main`.

## Ranked board (BEST FIRST) — n≥48 only

| Rank | Full hash (40) | Branch | One-sentence change | vs `8d5109f` |
| --- | --- | --- | --- | --- |
| 1 | `afc8f2fc37909560f67ec2c801b1d0dcb2db34d6` | `try/cursor-lead-gun` | Exact quadratic gun intercept lead + spawn offset in `combat.aim_at` | **14W / 19L / 63T**, mean Δ **−0.031** (cand 3.312 vs base 3.344, n=96) — FLAT/DITCH |

_Only one full paired panel finished so far; ~20+ sibling 96-seed sims still running on this machine._

### Baseline (reference)

| Full hash | Branch / tag | Change | Practice |
| --- | --- | --- | --- |
| `8d5109ff0d252add3f45f0436d028a1df32d5d53` | `try/na-arm` / `try/best-356` | G1 grab + G2 arm-first ≤60 m on bf-noavoid | **3.56** official |

## Pushed candidates awaiting full sim (alphabetical)

| Full hash | Branch | Change |
| --- | --- | --- |
| `7208dc2fe36394616cefa27aa6e2b889676e923d` | `try/cursor-aim-tight` | hold fire until aim within 2° (was 4°) |
| `aeae5045dcbc1ac5c112c3d5885e524b768f8825` | `try/cursor-burst-then-break` | after 8 shots, break LOS 1.2s then re-peek |
| `c478b1fe00a9f4db4feda3241571794ad157738e` | `try/cursor-chain-lightning-angle` | bias lightning yaw toward multi-enemy cluster |
| `36fddc6ea3288848ac3b3e8be6e4e90a90f446e1` | `try/cursor-cookoff-timer` | looser laser release + earlier mortar drop vs charged laser |
| `4fac9dee31460a9b08fb456a7a2c8f9316a42a03` | `try/cursor-cover-pre` | briefly take ground cover / break LOS before opening FIGHT |
| `772e6cd469fffface7a2227f1693518361a2f413` | `try/cursor-damage-source-focus` | when recently hurt, stick fight target on shooter id |
| `891366cc66dc30c6f8d1c8527561db22f686c567` | `try/cursor-elevation-aim` | bias gun/laser/ltn CoM for roof/ground elevation delta |
| `501c2653fa9f4e976a23b36ceef4d043e0077dcf` | `try/cursor-hp-gate` | no offensive FIGHT below 50% HP (heal/cover instead) |
| `d58f9e7b4fe3bcd87d69b511adb3927bb81c42f0` | `try/cursor-laser-interrupt` | prioritize charging-laser hunters; lightning short or break LOS |
| `3273230b57b59e36e3dcb17b148152a1c98f8843` | `try/cursor-lead-laser` | slew-lead laser aim; don't release early vs movers |
| `551da0ea0681721a7576169dbe373ed55d71300e` | `try/cursor-lead-laser-release` | 0.22s velocity lead on laser aim before release |
| `d0c6202119fd694376443747e88d35cbda9acb0f` | `try/cursor-mag-discipline` | tap/withhold gun when miss probability high |
| `d9f77c113e198d0aa8ef6d20a5ee3d823f39a52b` | `try/cursor-mag-dump-discipline` | save last 3 gun rounds unless tight aim; reload early |
| `bf7b8bae74681e052cc7a4cd49cb437d90c9d64a` | `try/cursor-multi-dis` | try/cursor-multi-dis — hard DISENGAGE on ≥2 mech attackers / multi-source dmg ~2.5s; forbid THIRD while multi |
| `dc090457141f7605399118fef6c3a02e9535c47b` | `try/cursor-peek-strafe` | flip strafe direction every 1s in close gun/laser fights |
| `15d257a804d95ed904db32f36707c67fb54711c2` | `try/cursor-prefight-heal` | heal to 90% between waves before re-engaging |
| `68fed573fdcd9a07583f213c5e60cd0db019370b` | `try/cursor-splash-mortar-predict` | raise mortar lead_cap 15->28 for splash on movers |
| `f09ba862b6c2888843950477699324a329e59fd5` | `try/cursor-stickycubes-fight-only` | sticky CUBE 2s only post-fight, not early farm |
| `88b17e2fa7f155e9f02620d25e0497a6fa72d432` | `try/cursor-strafe-aim` | half-strafe + hold fire when no clear shot |
| `672b143c5054f47d709d347549fdd64df24662a2` | `try/cursor-threat-tgt` | pick fight targets by threat not distance |
| `5f6ae9481acff1498ad462daf02126399ecae221` | `try/cursor-upg-armor` | nanites/plating/armor before gun/laser |
| `0b425caaca268658ec057b0ca30455b623b66675` | `try/cursor-gun-aim-widen` | widen gun fire align tolerance 4°→6° |
| `e33ce6b7b57f5400b1560303d1d0d60a7700811f` | `try/cursor-mortar-close-deny` | refuse mortar under 40 m; use gun |
| `b70531c0b773f27d247c7965aa38721e394bcbd6` | `try/cursor-flank-commit` | on flank/undetected crash to 35 m with boost |
| `8b51cae2bdda8a7753733c926c43c1bfbd7f6f7a` | `try/cursor-chase-range-cap` | no sprint chase beyond 90 m unless hurt by them |
| `2ea0985aa0da9a429a98a060f9918976287d462a` | `try/cursor-reload-before-push` | reload when ammo≤4 before long close commit |
| `64b3692d700710bdfc2801512b9b47d64b9b9c15` | `try/cursor-sound-retarget` | retarget fight to mech matching fresh combat sound |
| `3155fdf7442a14d35fa4b000803c27b67722aa87` | `try/cursor-jump-peek-fight` | hop every 1.4s while ADSing in gun range |
| `0d5f92088b7e150aa848071104b8a68c93bbd84b` | `try/cursor-energy-save-fight` | boost in fight only for long closes or low HP |
| `608dcaea28faa07e1897f5bf2c869d5b0bea0384` | `try/cursor-laser-keep-hold` | wider laser charge cone; tighter release aim |
| `7b338cfd61c884ebea86bf4eca889738ddb59dd9` | `try/cursor-dual-slot-prio` | between laser shots prefer lightning over gun |

## Local-only commits (not yet on origin)

| Full hash | Branch | Change |
| --- | --- | --- |
| `672b143c5054f47d709d347549fdd64df24662a2` | `heads/try/cursor-threat-tgt` | pick fight targets by threat not distance |
| `5f6ae9481acff1498ad462daf02126399ecae221` | `heads/try/cursor-upg-armor` | nanites/plating/armor before gun/laser |
| `77d1cd3ab215d68c951c28f28c1927d2fda81f78` | `try/cursor-burst-break` | after short burst, break LOS before re-peek |
| `43e676802d2221cf4a3146b69cd833811af75b64` | `try/cursor-dmg-focus` | focus the hunter who last damaged us |
| `6a5d280dfa7deb4eac3259929bc90db765e008f2` | `try/cursor-dual-fire` | gun+laser (and gun+lightning) simultaneous fire when aligned |
| `b7602355045b77ec18c8612d7b601b5e06c35be9` | `try/cursor-mortar-kite` | longer mortar standoff with kite vs cook-off |
| `205b34e02b7b4a285fc570fe8bca4e88b79967af` | `try/cursor-swap-rules` | mid-fight gun↔laser↔lightning↔mortar by range/HP |
| `f37c47b86abcd964903b97fa6f0354fc462e2d19` | `try/cursor-tgt-lowhp` | prefer lowest-HP hunter in sensible range |
| `0f0bc7403de6316b31f4167386e8278061a502a6` | `try/cursor-third-timing` | third only after brief near fight + isolate/HP |

## Preliminary smokes (n=2 only — do not rank)

| Branch | Hash | Rough W/L/T | note |
| --- | --- | --- | --- |
| `try/cursor-hp-gate` | `501c2653…` | 1/0/1 | smoke only |
| `try/cursor-mortar-kite` | `b7602355…` | 1/0/1 | smoke only |
| `try/cursor-lead-laser` | `3273230b…` | 0/0/2 | smoke only |
| `try/cursor-third-timing` | `0f0bc740…` | 0/0/2 | smoke only |
| `try/cursor-prefight-heal` | `15d257a8…` | 0/1/1 | smoke only |
| `try/cursor-multi-dis` | `bf7b8bae…` | 0/2/0 | smoke only |

## Scan log

| When (EST) | Event |
| --- | --- |
| 03:11 | Bootstrap `try/cursor-notes`; fetched `try/sim` |
| 03:12 | First in-flight local branches |
| 03:18 | 22 unique origin candidates; lead-gun full n=96 ranked; machine ~100+ `sim/run.py` workers — aggregator waiting, not spawning more sims |
| 03:22 | Wave-controller batch-2 pushed: gun-aim-widen, mortar-close-deny, flank-commit, chase-range-cap, reload-before-push, sound-retarget, jump-peek-fight, energy-save-fight, laser-keep-hold, dual-slot-prio (serial sim queue waiting on load) |

## Protocol

1. Land fight changes on `try/cursor-*` only (never `main`).
2. Drop `/tmp/mech-cursor-<label>.md` + JSON with full hash and paired W/L/T.
3. Aggregator ranks by seed wins vs `8d5109f`, then mean Δ; pushes `try/cursor-notes`.
