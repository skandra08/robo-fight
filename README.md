# loadout-hunter (robo-fight)

Mech Royale practice bot: arm quietly (laser > mortar > lightning), set up loadout camp, take advantaged 1v1s; stay and fight (no DISENGAGE/THIRD in practice).

## Stance

- **Ambush**: if 1v1 and hunter has not locked you (or you flank), take the fight when armed / in contact.
- **Mortar**: relocate to far ground inside the zone; hold range and lob on mid/far sounds.
- **Laser**: climb a roof for vision; peek-shoot from the edge.
- **Lightning**: hold tight corners, stay out of sight, burst when close.
- **DISENGAGE / RESET / THIRD**: **disabled for practice** (R2) — latching DISENGAGE abandoned fights before the kill; THIRD crashed into shared-vision packs. Code kept for FFA (decision 6).
- **ROTATE**: enter next circle (not loadout RELOCATE); edge-gatekeep late rotators when loadout/position allows.
- **LOOT_SWAP**: nearby upgrades only; never mortar→lightning; laser threat → safe ground else drop mortar.
- **FFA**: stubbed (decision 6) — practice mid-pack path only for now.

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

## Local check

```sh
python3 tools/precompute.py   # once; needs numpy
python3 check/check.py -- python3 -u bot.py
docker build -t my-bot .
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" my-bot
```

## Submit

Public GitHub repo with this `Dockerfile` at the top. Tracker: joinbuilders.org/buildathon.
