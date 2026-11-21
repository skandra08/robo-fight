# rooftop-camper (robo-fight)

Mech Royale bot: arm (laser > mortar > lightning), climb a roof inside the zone, peek-shoot, heal out of sight.

## Version log

| Ver | Change | Notes |
| --- | --- | --- |
| v1.0 | First implementation of Rooftop Camper design | world + precomputed roofs/cover, state machine, gun/laser/mortar, ARM→RELOCATE→CAMP |
| v1.1 | Fix heal-under-fire, gun hold, laser release, climb, avoid | Never HEAL while shot; hold gun trigger when aimed; keep laser charged if aim drifts; climb with enemies visible; avoid skips FIGHT/climb; ground HEAL keeps moving |

## Local check

```sh
python3 tools/precompute.py   # once; needs numpy
python3 check/check.py -- python3 -u bot.py
docker build -t my-bot .
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" my-bot
```

## Submit

Public GitHub repo with this `Dockerfile` at the top. Tracker: joinbuilders.org/buildathon.
