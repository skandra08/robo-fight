# best-350 — NEW BASELINE (official practice **3.5**)

**Status:** confirmed + tagged on origin  
**Repo:** `skandra08/robo-fight`  
**Branch (docs):** `cursor/best-350-58c4`  
**Scored commit (DO NOT MOVE TAG OFF THIS):** `6eaffccf8caa484f67c6dfb4191bdecb850edd3d`

| | |
| --- | --- |
| **Full hash** | `6eaffccf8caa484f67c6dfb4191bdecb850edd3d` |
| **Tags** | `try/best-350` (origin), `try/rw-path` (same tip) |
| **Bot.name** | `lh-rw-path` |
| **Levers** | **S1+N1** in `levers.py` (behaviorally **noroof**: `FARM_EARLY_S=1e9`) |
| **Score** | **3.5** (beats best-302 / bet-farm **3.02**) |
| **Parent tip** | `04583fbbdb77c122264ff4febd75a6246197d062` (`rw-farm`) ← rewrite stack on `481fed0` |
| **Identity** | **NOT** bet-farm / bet-sticky / bet-upgsus — this is **rewrite farm-fight-heal + bf-noavoid grid pathing + take every supply + drones 150 m**, with bet-farm’s 75 s ignore-undamaging-mechs |

## Plain English: +0.48 over bet-farm

Same early-farm idea as 3.02 (`FARM_FIGHT_S=75`), but the rewrite stops wasting tens of seconds stuck on buildings and starts banking free supply loot:

1. **`pathing.py` 4 m grid A\*** wired into `Navigator.steer` (ported from `try/bf-noavoid`, noted ~3.48 there). Long goals (far cubes, zone exits, supply rings) get a waypoint around buildings instead of local feelers pushing into walls.
2. **Take every reachable supply drop** (`SUPPLY` mode, `drop_avoid=0`). Full heal + energy + 3 cubes, ~3/match; practice squad rarely contests.
3. **Drone farm reach 150 m** (was 140 on `rw-farm`) while still in the cube-hungry farm loop.

So the +0.48 is **pathing that actually arrives + free supply cubes/HP + slightly longer drone farm**, not sticky or upgsus.

## Diff summary vs 3.02 (`d2674c3` / `lh-bet-farm`)

Huge rewrite delta (bot decision layer replaced). Conceptually vs bet-farm:

| area | bet-farm 3.02 | rw-path 3.5 |
| --- | --- | --- |
| architecture | mode soup (CUBE/RELOCATE/CAMP/…) | ESCAPE→ZONE→SUPPLY→DRONE→HEAL→FIGHT→FARM→ROOF |
| early farm | t&lt;75 ignore non-damaging mechs | same (`FARM_FIGHT_S=75`) |
| pathing | local steer only | `pathing.PathGrid` in `nav.steer` + `data/navmoves.bin` |
| supply | avoid drops (40 m) | hunt every reachable drop |
| drones | farm without N5 gate | farm to **150 m** in value/metre scorer |
| upgrades | armor→plating→nanites | same (not upgsus) |
| sticky | no | farm hysteresis only (not classic 2 s sticky) |

Files vs `d2674c3`: `bot.py`, `nav.py`, `levers.py`, **+`pathing.py`**, **+`data/navmoves.bin`**, Dockerfile, `tools/*`.

## Lineage from 2.65

```
b7b5c38  cubes-drones          2.65
fa3e282  v-greedy              2.75
481fed0  g-zone                2.81
 ├─ 2e8b45e gz-noroof         ~2.90
 │   └─ d2674c3 bet-farm       3.02   ← previous bar
 └─ d2ed0a1 try/rewrite …
     └─ 04583fb rw-farm        (bet-farm early phase on rewrite)
         └─ 6eaffcc rw-path    3.5    ← NEW BAR
              ↑ also ports bf-noavoid (ac6ad1f) pathing+supply ideas
```

## Working rule

**NEW BASELINE = this commit at 3.5.** Build future variants **off `6eaffcc`**, not off `d2674c3` / 3.02. Official practice is ground truth — no live WS grinding.

Queued off old bar (superseded as next submit):

- `97a111b…` `try/bet-sticky` — sticky on 3.02
- `b58dc68…` `try/bet-upgsus` — upgsus on 3.02

## Next submit (off THIS bar)

| Priority | Hash | Name | Delta |
| --- | --- | --- | --- |
| **SUBMIT NOW** | _(filled after push)_ | `lh-rw-sticky` / `try/rw-sticky` | sticky FARM 2 s on best-350 |
| Then | _(filled after push)_ | `lh-rw-upgsus` / `try/rw-upgsus` | nanites/plating/armor first on best-350 |

Laser-ARM skipped: rewrite already prefers laser via `WEAPON_RANK` + loot farm when unarmed; classic arm-first FIGHT gate is largely covered by `FARM_FIGHT_S=75`.

```sh
git fetch --tags --force
git checkout try/best-350          # baseline 3.5 / lh-rw-path
git checkout try/rw-sticky         # next official submit
```
