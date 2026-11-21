# loadout-hunter (robo-fight)

Mech Royale practice bot: arm quietly (laser > mortar > lightning), set up roof camp, take advantaged fights; stay and fight (no DISENGAGE/THIRD in practice). R3 strategy levers in `levers.py` / `try/*` tags.

## Stance

- **Roof camp (S1):** every loadout climbs a roof after arming; mortar sound-lobs from the roof; lightning hides near climb points.
- **Laser counter (N1):** any loadout breaks LOS when a mech charges aimed at us; return on beam / charge+hold.
- **Edge-guard (N2):** with no target in view, hold 4–6 m inside the threat-edge and shoot climbers.
- **Post-kill (N3):** loot the drop, then heal to ≥90% while quiet.
- **No ambush (S2):** armed + undetected → set up first (no mid-range ambush FIGHT).
- **Quiet ARM (S3):** no boost inside the zone while looting.
- **Cube farm (N5):** `cubes_want = stat_cap`; farm drones from >45 m; scoop cubes to 25 m when quiet.
- **Drop 1 (N6):** contest the first supply drop only (≤120 m, HP>60%, no hunter).
- **ROTATE (S4):** next-circle time pressure only — gatekeep off in practice.
- **DISENGAGE / RESET / THIRD**: disabled for practice (R2); F1 re-enables DISENGAGE with safeguards when `mem.ffa`.
- **FFA (F1):** detector latches on unexplained alive drops / crossfire; survival = don't start fights, silent walk, full HP before shrinks, no contests.

## Version log

| Ver | Change | Notes |
| --- | --- | --- |
| v1.0 | First implementation of Rooftop Camper design | world + precomputed roofs/cover, state machine, gun/laser/mortar, ARM→RELOCATE→CAMP |
| v1.1 | Fix heal-under-fire, gun hold, laser release, climb, avoid | Never HEAL while shot; hold gun trigger when aimed; keep laser charged if aim drifts; climb with enemies visible; avoid skips FIGHT/climb; ground HEAL keeps moving |
| v1.2 | Arm/fight/nav/cover for practice scoring | No 150m ARM flee; loot memory + scan search; fight visible hunters (chase if no LOS); wider aim hold; side-waypoint nav; real cover.bin; camp always return-fires |
| v1.2b | shots_here / laser charge / climb idle | Count gun shots via ammo drop; only charge laser when ~on target; strafe while waiting for climb energy |
| v1.2c | Decision-time LOS/nav optimization | Per-tick LOS cache, coarser segment tests, single-pass target pick, fewer steer feelers; act ≪ 50ms |
| v1.3 | Loadout aggression | Ambush 1v1s; mortar far-ground / laser roof / lightning corner; aggressive ARM boost for loot |
| v1.4 | Fix stuck steer locking forever | Pass match time into `Navigator.steer`; stuck heading only applies while `t < stuck_until` (was stuck forever after first wall) |
| v1.5 | Climb through contact | Prefer RELOCATE over FIGHT mid-climb / near climb point; laser can still approach roof when hunter is farther than the climb |
| v1.6 | Roof avoid + camp rebind | Skip `_avoid` on roof / ESCAPE; ignore objects >4 m below (npc 50 / drop 40); clear camp_fire/hidden on roof change; arrive only on picked roof id; peek toward threat via `best_firing(toward_yaw)` until near fire_pt |
| v1.7 | ARM ghost / roof loot | Drop remembered loot inside `vision.near_range` when missing from pickups; skip elevated roof loot unless on that roof; take within `loot_r - 0.3` |
| v1.8 | Laser hold + gun aim | Keep laser trigger if charge mid-flight when target drops; don't fire gun on mortar aim; lead gun between laser shots via `aim_kind` |
| v1.9 | Practice modes | DISENGAGE / RESET / THIRD / ROTATE / LOOT_SWAP wired into `_select_mode`; FFA detector stubbed; supply contest only when `alive`≤5 |
| v1.10 | Practice survival hotfix | Gate THIRD (positioned + HP>0.7 + near-sound only); soften gun-only / unpositioned FIGHT; quieter ARM boost. Predicted: fewer place~14 early deaths vs shared-vision hunters; midpack practice score up from ~1.44 toward pre-aggression ~2.5 |
| v1.11 | Gun primary on clear shot (R1) | Mortar only no-LOS in-range; lightning only clear ≤range; else gun. Drop pitch-0.6 mortar fallback (#8). Predicted: restore gun DPS for mortar/lightning loadouts (v1.3+v1.8 silence) |
| v1.12 | Disable DISENGAGE/RESET/THIRD (R2) | Practice: stay in FIGHT (decision 5). Bodies kept for FFA. Predicted: finish 1v1s instead of looping DISENGAGE after ~400 HP lost |
| v1.13 | Loot memory LOS gate (R4) | Near-range ghost delete only with eye LOS (buildings block proximity vision). Predicted: stop forgetting wall-hidden loot mid-approach |
| v1.14 | Scope laser charge-hold (R5) | Skip hold in COUNTER_LASER / ESCAPE / climbing RELOCATE; release when no enemy within ~8° of aim. Predicted: stop half-speed charge while fleeing |
| v1.15 | Refresh threat bearing from sounds (#9) | Update `last_threat_bearing` from combat sounds each tick (damage bearing still wins for 0.3s). Predicted: better camp peek / chase toward active fights |
| v1.16 | Mortar refire from config | Replace hard-coded 4.0 s gap with `cfg.weapons.mortar.cooldown` (2.6). Live slot `cooldown` still gates. Predicted: ~35% more mortar shells when lobbing |
| v1.17 | Mortar low-arc + damped lead (#8) | Prefer low arc when lob clears; else high. Cap lead at 15 m. Drop pitch>0.25 fire gate (blocked low arc). Predicted: shells land on walking targets instead of 70 m ahead |
| v1.18 | Body centre from config | Aim/LOS CoM = `mech.height/2` × cube scale (was hard-coded +4.5). Predicted: neutral at default height; correct vs tall cube mechs |
| v1.19 | Firing-point yaw coverage (#10) | Precompute bins firing pts by 16 yaw sectors (≤3 each); hidden by hf. Regenerated `data/roofs.json`. Predicted: CAMP peeks toward any compass threat |
| v1.20 | Strategy plan S1–F1 (levers) | Roof camp all loadouts; laser counter; edge-guard; post-kill loot→heal; no ambush; quiet ARM; precharged peeks; cube/drone farm; contest drop 1; ROTATE gatekeep off; FFA detector+survival behind `levers.py`. Predicted: practice +0.5–2.0; FFA for qualifiers |
| S1 | Every loadout camps on a roof | Mortar/lightning use roof path; `_loadout_positioned` = on roof. Predicted: +0.2 to +0.5 |
| N1 | Laser counter all loadouts | Break LOS on charging aim≤8°; return on beam/hold; mortar drop only if no cover ~45 m. Predicted: +0.3 to +1.0 |
| N2 | Edge-guard climb | Hold 4–6 m inside threat edge; shoot z>roof−2; mortar wall-base. Predicted: +0.4 to +1.0 |
| N3 | Post-kill loot→heal≥90% | On `kill`, collect within 40 m then HEAL. Predicted: +0.3 to +0.7 |
| S2 | Remove 1v1 ambush | Keep armed+undetected→setup-first. Predicted: 0 to +0.2 |
| S3 | No ARM boost in zone | `boost = out_of_zone and efrac>0.55`. Predicted: 0 to +0.15 |
| N4 | Pre-charged laser peeks | Charge hidden, walk-out half speed, release ≤3°. Predicted: +0.2 to +0.6 |
| N5 | Cube snowball | `stat_cap` want; farm drones 45–80 m; cubes ≤25 m. Predicted: +0.2 to +0.6 |
| N6 | Contest supply drop 1 | First drop ≤120 m, HP>60%, no hunter. Predicted: +0.1 to +0.3 |
| S4 | ROTATE gatekeep off | Practice: time-into-next only. Predicted: ~0 |
| F1 | FFA detector + survival | Latch on unexplained alive drops / crossfire; silent / no start-fights. Predicted: 0 on practice (±0.15) |

## Local check

```sh
python3 tools/precompute.py   # once; needs numpy
python3 tools/test_strategy.py
python3 check/check.py -- python3 -u bot.py
docker build -t my-bot .
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" my-bot
```

## Submit

Public GitHub repo with this `Dockerfile` at the top. Tracker: joinbuilders.org/buildathon.

## Trying variants

A/B tags on `origin` (`git fetch --tags --force`). Checkout `try/<label>` and submit that tree. `Bot.name` = `lh-<label>` via `levers.LABEL`. Base: `b4d6e37` (v1.20 / r3-full).

| # | label | Bot.name | tag | full hash | tweak | try this if… |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | r3-base | lh-r3-base | `try/r3-base` | `3cbee64dd940d2ab0a0789611443083edc0497b7` | R3 scaffolding, all levers off | new control / ≈v1.19 behavior on plan tip |
| 1 | roof-all | lh-roof-all | `try/roof-all` | `9b820d14888fe6050429c98daff4871584cb3d9a` | **S1** all loadouts on roof | first R3 submit; mortar/lightning die on ground |
| 2 | laser-ctr | lh-laser-ctr | `try/laser-ctr` | `73821ee9b5e88678ee742c3a3b9b71d640368d2a` | **N1** laser counter any loadout | eating laser cook-offs / 70%+ laser damage |
| 3 | edge-guard | lh-edge-guard | `try/edge-guard` | `41b972ac54fb8c99eb45d5319a01e9996e08c693` | **N2** hold threat-edge vs climbers | dying to roof rushers one-by-one |
| 4 | post-kill | lh-post-kill | `try/post-kill` | `52335de017527588762821d0d23716ecd4c866cc` | **N3** loot then heal ≥90% | winning fights then dying under-healed |
| 5 | no-ambush | lh-no-ambush | `try/no-ambush` | `9065b8f3ded0ad85250479cfda439e938893a292` | **S2** no 1v1 ambush FIGHT | dying mid-setup to unaware hunters |
| 6 | arm-quiet | lh-arm-quiet | `try/arm-quiet` | `896375f111fa91425abfe5b7390db1c6f9ce6383` | **S3** no ARM boost in zone | hunted while looting / no climb energy |
| 7 | laser-peek | lh-laser-peek | `try/laser-peek` | `8a48f236f4f334663e7cb25736291eff9d68692a` | **N4** pre-charged peeks | laser peeks whiff / charge in open |
| 8 | cube-farm | lh-cube-farm | `try/cube-farm` | `8fbde1857cb73af8713efd832c8edac38c167283` | **N5** drones + cube snowball | losing long HP races / thin cubes |
| 9 | drop1 | lh-drop1 | `try/drop1` | `93bede5f5814e0f6688a11379673080b552b4b98` | **N6** contest first supply drop | need early cubes/repair, drop lands near |
| 10 | no-gate | lh-no-gate | `try/no-gate` | `c11cfdeaf0195e2584a4b0e4ffac4e2a18b62c8e` | **S4** ROTATE gatekeep off | gatekeep wastes time / dies on ring |
| 11 | ffa | lh-ffa | `try/ffa` | `450ebfc7de4762023ff99d4f6cb1c1a2d9bafb8f` | **F1** detector + survival only | qualifiers/final FFA; keep practice ±0.15 |
| 12 | r3-core | lh-r3-core | `try/r3-core` | `3737f2636dde5ec00e880ca0201142b1ed2c1f77` | S1+N1+N2+N3+S2+S3+S4+F1 | stacked core (skip uncertain N4/N5/N6) |
| 13 | r3-full | lh-r3-full | `try/r3-full` | `b4d6e37c727f7125bbf8c8087475b7a99fcaf910` | all S/N/F levers (= main) | full plan in one submit |
| 14 | locked-proc | lh-locked-proc | `try/locked-proc` | ``ab233a8a7f52617a2ba4984e975d268833d6d424`` | **S1+N1** + locked ARM→CUBE→DRONE→ROOF→FIGHT (sticky+killreach off best-265) | submit after best-265; see `docs/LOCKED_PROC.md` |


Offline proxy / careful play WS: `python3 tools/offline_proxy.py`; `python3 tools/play_ws_harness.py` (max 1–3; do not spam the shared lobby).

Prior A/B (still on origin): `try/camp-hold`, `try/arm-first`, `try/fight-ready`, `try/third-armed`, `try/no-third`.

Verify: `python3 tools/test_strategy.py` then `python3 check/check.py -- python3 -u bot.py`.
