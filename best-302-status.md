# best-302 — SUPERSEDED by best-350 (official practice **3.5**)

> **SUPERSEDED:** official practice now **3.5** at `6eaffcc…` (`try/best-350` / `lh-rw-path`). See `best-350-status.md`. Do not build new variants off 3.02.

**Status:** confirmed + tagged on origin  
**Repo:** `skandra08/robo-fight`  
**Branch (docs):** `cursor/best-302-6849`  
**Scored commit (DO NOT MOVE TAG OFF THIS):** `d2674c3e203a3c6de883de7a9e2d401beb5343cb`

| | |
| --- | --- |
| **Full hash** | `d2674c3e203a3c6de883de7a9e2d401beb5343cb` |
| **Tags** | `try/best-302` (origin), `try/bet-farm` (same tip) |
| **Bot.name** | `lh-bet-farm` |
| **Levers** | **N1 only** (S1 **off** — noroof) |
| **Score** | **3.02** (beats best-281 / g-zone **2.81**) |
| **Parent** | `2e8b45e8a31e3aa801470329b367a3cf2a9dcc6a` (`gz-noroof`, reported **2.90**) ← `481fed0` (2.81) |
| **Identity** | **NOT** gz-sticky / gz-upgsus — this is **g-zone + S1 off + early BET farm to 75 s** |

## Plain English: +0.21 over g-zone

Two stacked deltas off `481fed0` / `lh-g-zone`:

1. **`gz-noroof` (2.90):** flip **S1 off**. Stop roof-camping; stay on the greedy ground farm + zone-escape jet that already won 2.81. Intermediate score ~2.90.
2. **`bet-farm` (3.02):** until **t &lt; 75 s** and not recently damaged, **ignore mechs that are not hurting us** and farm cubes / crates / drones at any range (`_cube_goal(obs, [], 1e9)` + drone chase without N5 + crates reach **220 m** early). Mimics the showdown winner that farmed ~60 s before fighting.

So the +0.21 is **more early cubes/crates/drones + less time wasted on roof/unsolicited fights**, not sticky or upgsus.

## Diff summary vs 2.81 (`481fed0`)

| file | delta |
| --- | --- |
| `levers.py` | `LABEL` `g-zone`→`bet-farm`; **S1 True→False** |
| `bot.py` | + early 75 s farm block; drone chase without `N5` gate; crates 220 m while `t < 75` |

No sticky. No upgsus spend order. Laser-ARM / S3 not included.

## vs 2.65 stack (`b7b5c38` cubes-drones)

Same cube-before-RELOCATE + greedy reaches lineage, **plus**:

- `fa3e282` greedy reaches (2.75)
- `481fed0` zone-escape stuck-jet (2.81)
- `2e8b45e` S1 off / noroof (~2.90)
- `d2674c3` early BET farm to 75 s (3.02)

Levers flipped from **S1+N1** → **N1 only**.

## Working rule

**NEW BASELINE = this commit at 3.02.** Build future variants **off `d2674c3`**, not off `481fed0` / 2.81. Official practice is ground truth — no live WS grinding.

Queued off old bar (superseded as next submit):

- `8bd9295…` `try/gz-sticky` — sticky on 2.81
- `ce3e27c…` `try/gz-upgsus` — upgsus on 2.81

## Next submit (off THIS bar)

| Priority | Hash | Name | Delta |
| --- | --- | --- | --- |
| **SUBMIT NOW** | `97a111b936cc051c1e12c84bc0885d6e0d40f331` | `lh-bet-sticky` / `try/bet-sticky` | sticky CUBE 2s on best-302 |
| Then | `b58dc682400f97479d08ab5a6bf29da6d4fa7087` | `lh-bet-upgsus` / `try/bet-upgsus` | upgsus spend order on best-302 |

```sh
git fetch --tags --force
git checkout try/best-302          # baseline 3.02 / lh-bet-farm
git checkout try/bet-sticky        # next official submit
```
