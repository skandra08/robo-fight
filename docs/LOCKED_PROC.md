# Locked procedure (`try/locked-proc` / `try/pivot-sticky-reach`)

Off **best-265** (`b7b5c383…`, cubes-drones, practice **2.65**). Levers stay **S1+N1**.

## Sameer early-ditch rule (all sims)

After **~8–12 games**: if mean points are clearly below **~2.3** (or places are terrible), **STOP**. Do not grind 48–50 on a loser. Immediately invent/checkout a **new** small delta off best-265, tag `try/pivot-<name>`, and continue only on the replacement. Prefer pivots that keep **roof + CUBE**. Live board: `/tmp/mech-sim-leaderboard.md`. Harness: `/tmp/mech-sim-harness-notes.txt`.

## Why no 100+ local sims

| Path | Reality |
| --- | --- |
| Kit `check/check.py` | Protocol conformance only — recorded obs, **non-reactive** |
| Kit `arena/` | Map files only — **no match server / physics binary** |
| Official scoring | GitHub submit → scorer runs **48** practice matches (4 submits/hour) |
| `play.joinbuilders.org` | Human lobby over `wss://…/play` (real-time). Bulk automation would DDoS shared rooms |

Offline proxy used instead: public house-bot replay + mode-decision audit (`tools/offline_proxy.py`). Careful human-seat driver: `tools/play_ws_harness.py` (never spam).

## Locked steps (exact)

1. **ARM** — take laser > mortar > lightning; stay quiet in-zone (no ARM boost for volume).
2. **CUBE** — if no recent mech damage and not mid-climb:
   - scoop visible cubes (reach 100 m quiet / 130 m for 25 s after a kill; 60 m capped when a hunter is in view)
   - walk kill-sites up to 200 m when quiet / enemy > 90 m
   - shoot LOS crates when enemy > 130 m (100 m quiet post-kill), range ≤ 150 m
   - **sticky 2 s** so goal flicker cannot hand the tick to RELOCATE mid-scoop
   - **before** RELOCATE / CAMP (best-265 priority)
3. **DRONE** — if an NPC gun hit us in the last 2.5 s and no mech hit in 2.0 s → turn and kill the drone.
4. **ROOF (S1)** — once armed and cubes clear, RELOCATE to a roof and CAMP; keep climb through contact.
5. **FIGHT** — return fire when damaged; finish 1v1s (no DISENGAGE / THIRD in practice); **N1** laser counter on charge aimed at us.
6. **HEAL / ROTATE** — heal when safe and HP low; rotate only for next-circle time pressure.

## Offline proxy findings (house replay `mechanics-v2-16`)

- Winner: `house:brawler` lightning, **16 cubes**, 4 kills, low roof fraction.
- Cubes ↔ place: top finishes had high `cubes_max`; early outs often gun-only + 0–2 cubes.
- Reinforces locking cube scoop ahead of roof camp, not discarding the roof+laser stack.
