# CURSOR_NOTES — fight-tactics swarm ranking

**Repo:** `skandra08/robo-fight`  
**BAR = 3.81** — `try/best-381` / `try/rewrite` = `f9eaf39685fec76442862288b13b1690eb6b3ce2` (`lh-rw-dual`)  
**Superseded bar:** `try/best-356` / `try/na-arm` = `8d5109ff0d252add3f45f0436d028a1df32d5d53` (`lh-na-arm`, **3.56**) — historical only  
**Aggregator branch:** `try/cursor-notes`  
**Last scan:** 2026-11-21 03:46 EST

## STATUS — USAGE FREEZE

**Fight-swarm interrupted by worker disconnect.** Most fight agents killed mid-run.

- **Do NOT spawn more fight agents.**
- **Do NOT relaunch fight variants / new experiments.**
- Collect completed results only; official practice remains ground truth.
- Incomplete panels (`no-chase`, in-flight sims) are **not ranked**.

## Ranked top 5 (BEST FIRST) — Sameer action board

| Rank | Full hash | Branch / label | Why |
| --- | --- | --- | --- |
| **1** | `f9eaf39685fec76442862288b13b1690eb6b3ce2` | `try/best-381` / `lh-rw-dual` | **BAR** — official practice **3.81** |
| **2** | `dfb2931563b13d547b7ea042512f309dd2e05dc1` | `try/cursor-sticky` / `lh-cursor-sticky` | **Next submit** — best-381 + sticky FARM 2s |
| **3** | `0c11bda127ebab92e89700b3e2776e46fc3d2178` | `try/cursor-upgsus` | Off 3.81 — nanites/plating/armor first |
| **4** | `501c2653fa9f4e976a23b36ceef4d043e0077dcf` | `try/cursor-hp-gate` | Best completed fight sim vs old bar: **25W/20L/51T Δ+0.042 KEEP** (on `8d5109f`; rebuild on `f9eaf39` before new ranking) |
| **5** | `9698130906d023b877ba572ebac06f8403d30303` | `try/cursor-multi-dis-381` | Off 3.81 — multi-attacker HEAL peel (unevaluated on new bar; alt: `a609959…` lead-gun-381) |

### Also off 3.81 (queue, no new sims)

| Full hash | Branch | Delta |
| --- | --- | --- |
| `9698130906d023b877ba572ebac06f8403d30303` | `try/cursor-multi-dis-381` | ≥2 attackers → HEAL peel ~2.5s |
| `a6099596b742d03306c485048ae1bf5d6cf16985` | `try/cursor-lead-gun-381` | quadratic gun intercept lead |

check.py: sticky / upgsus / multi-dis-381 / lead-gun-381 **PASS**. Dual-fire already in 3.81 tip — do not rebuild.

## Baseline (reference)

| Full hash | Branch / tag | Bot.name | Practice |
| --- | --- | --- | --- |
| `f9eaf39685fec76442862288b13b1690eb6b3ce2` | `try/rewrite` / `try/best-381` | `lh-rw-dual` | **3.81** official |
| `8d5109ff0d252add3f45f0436d028a1df32d5d53` | `try/na-arm` / `try/best-356` | `lh-na-arm` | 3.56 (historical) |
| `6eaffccf8caa484f67c6dfb4191bdecb850edd3d` | `try/rw-path` / `try/best-350` | `lh-rw-path` | 3.5 (ancestor of 3.81) |

**Identity of 3.81:** rewrite plate on rw-path (3.5) + grab-in-reach + **dual fire** + det 1024-node path. Label-only tip `f9eaf39`.

## Simulator (when freeze lifts — not now)

`try/sim` @ `5b3d022`. New work compares vs **`f9eaf39`**, not `8d5109f`:

```sh
python3 sim/run.py --seeds 96 --procs <cores> --params '{"track":true}' \
  --out /tmp/mech-cursor-<label>-vs-rw-dual.json \
  f9eaf39685fec76442862288b13b1690eb6b3ce2 \
  <candidate_sha>
```

**Ranking key:** per-seed wins vs bar, then mean Δ. Require **n≥48**. Never push `main`.

## Historical board (vs `8d5109f` / 3.56) — completed n=96 only

Collected from `/tmp/mech-cursor-*-result.md`, `/tmp/*.json`, parent store, `results/`. Ranked by seed wins, then mean Δ.

| Rank | Full hash | Branch | vs `8d5109f` | Verdict |
| --- | --- | --- | --- | --- |
| 1 | `501c2653fa9f4e976a23b36ceef4d043e0077dcf` | `try/cursor-hp-gate` | **25W / 20L / 51T**, mean Δ **+0.042** (3.323 vs 3.281) | **KEEP** |
| 2 | `afc8f2fc37909560f67ec2c801b1d0dcb2db34d6` | `try/cursor-lead-gun` | 14W / 19L / 63T, Δ −0.031 | **DITCH** |
| 3 | `5f6ae9481acff1498ad462daf02126399ecae221` | `try/cursor-upg-armor` | 14W / 20L / 62T, Δ −0.031 | **DITCH** |
| 4 | `8f540e17376c951e676afa5b3a5cf192b6037de6` | `try/cursor-cookoff` | 13W / 18L / 65T, Δ −0.125 | **DITCH** |
| 5 | `b7602355045b77ec18c8612d7b601b5e06c35be9` | `try/cursor-mortar-kite` | 13W / 27L / 56T, Δ −0.219 | **DITCH** |
| 6 | `3273230b57b59e36e3dcb17b148152a1c98f8843` | `try/cursor-lead-laser` | 15W / 25L / 56T, Δ −0.208 | **DITCH** |
| 7 | `77d1cd3ab215d68c951c28f28c1927d2fda81f78` | `try/cursor-burst-break` | 25W / 52L / 19T, Δ **−1.167** | **DITCH** |
| 8 | `bf7b8bae74681e052cc7a4cd49cb437d90c9d64a` | `try/cursor-multi-dis` | 4W / 72L / 20T, Δ **−2.521** | **DITCH** |

### Explicit ditch list (Sameer / parent notes)

vs `8d5109f`: **lead-gun / upg-armor / mortar-kite / burst-break → DITCH.**  
hp-gate **501c2653 Δ+0.042 → KEEP** (only positive completed fight panel).

### Incomplete / interrupted (not ranked)

| Branch | Hash | Status |
| --- | --- | --- |
| `try/cursor-no-chase` | `65102827572e0e8740499b0892bbf7da2812965b` | result file still **SIM RUNNING**; smoke n=2 only |
| Many `try/cursor-*` / `try/cursor-381-*` | (pushed tips) | No completed n≥48 vs `f9eaf39`; swarm died on disconnect |

## Sources scanned

- `/tmp/mech-cursor-*-result.md` (hp-gate, lead-gun, upg-armor, mortar-kite, burst-break, no-chase incomplete)
- `/tmp/mech-cursor-*-vs-na-arm.json` + cookoff / lead-laser / lead-gun / upg-armor JSONs
- `results/CURSOR_NOTES.md` (workspace)
- Parent agent store: `bar-381-status.md`, `best-381-status.md`, prior `CURSOR_NOTES.md`
- Known hashes from freeze handoff (3.81 bar, sticky submit, off-381 queue)

## Scan log

| When (EST) | Event |
| --- | --- |
| 03:11 | Bootstrap notes; fetch `try/sim` |
| 03:18–03:31 | Historical panels vs `8d5109f`: hp-gate KEEP; lead-gun / upg-armor / mortar-kite / multi-dis / burst-break |
| 03:25 | BAR → **3.81** `f9eaf39`; sticky/upgsus/multi-dis/lead rebuilt off tip |
| 03:46 | **USAGE FREEZE** — worker disconnect killed fight swarm; notes refreshed; no new agents |

## Protocol

1. Never push `main`. Notes live on `try/cursor-notes` only.
2. While freeze holds: **no new fight experiments / agents.**
3. When freeze lifts: base new `try/cursor-*` on **`f9eaf39`**; drop `/tmp/mech-cursor-<label>.md` + JSON with W/L/T vs bar.
4. Aggregator ranks by seed wins vs bar, then mean Δ; pushes `try/cursor-notes`.
