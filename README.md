# loadout-hunter (robo-fight)

Mech Royale practice bot: arm fast (laser > mortar > lightning), take advantaged 1v1s, then camp by loadout.

## Stance

- **Ambush**: if 1v1 and hunter has not locked you (or you flank), take the fight when armed / in contact.
- **Mortar**: relocate to far ground inside the zone; hold range and lob on mid/far sounds.
- **Laser**: climb a roof for vision; peek-shoot from the edge.
- **Lightning**: hold tight corners, stay out of sight, burst when close.

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

## Local check

```sh
python3 tools/precompute.py   # once; needs numpy
python3 check/check.py -- python3 -u bot.py
docker build -t my-bot .
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" my-bot
```

## Submit

Public GitHub repo with this `Dockerfile` at the top. Tracker: joinbuilders.org/buildathon.
