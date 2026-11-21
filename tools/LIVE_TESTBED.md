# Live testbed: test the bot against the real server

This is how to run our Python bot in real matches on `play.joinbuilders.org`, many rooms at once, and read the results. No sign-in is needed. Sameer approved using the public play site's private rooms for this.

The two scripts are on branch `try/testbed`:
- `tools/lobby_harness.js` plays private rooms.
- `tools/watch_recorder.js` records the public stream.

Copies are also in `/mnt/project-files/reports/tools/`.

## What it is, and what it isn't

- **What it is.** `play.joinbuilders.org` runs the real game server, speaking the `mechfight/1` protocol. Its "Play with friends" private rooms fill every empty seat with real house bots.
- **What it isn't.** Private rooms are a 4-minute free-for-all with a faster zone (hold 30 s). The house bots there fight each other, and the lineup is "expert" plus "probe-*" bots. That is **not** the practice squad, where 15 bots hunt only us.
  - Use it to rank variants against each other, and to find bugs: deaths, drones, the zone, cubes.
  - Don't read its scores as practice scores. The 2.65 practice best scored about 11.5 here, as 16 minus place.

## 1. Open the page

- Open `https://play.joinbuilders.org/` in a normal browser tab.
- Everything below runs in that tab's DevTools console.
- The scripts need same-origin access to `/mm/code/new`, `/r/<room>/...` and `/arena/v2/*`, so they must run on that page.
- A headless container may be blocked: our cloud container got a 403 from `joinbuilders.org`.

## 2. Load the harness

Paste the whole of `tools/lobby_harness.js` into the console. It defines `window.H`. Then run:

```js
await H.loadPy();   // loads Pyodide 0.26.4 from cdn.jsdelivr.net and the map (/arena/v2/world.json, terrain.i16)
```

**How the bot runs.**
1. `H.install(commit)` fetches `mechfight.py bot.py world.py cover.py nav.py combat.py memory.py levers.py data/cover.bin data/roofs.json` from `raw.githubusercontent.com/skandra08/robo-fight/<commit>/` into Pyodide's in-memory filesystem.
2. `H.makeBot(commit, hello)` builds `bot.Bot(hello)` and returns an `act(obs_json) -> action_json` function.

Use **full 40-character hashes**, because raw.githubusercontent does not resolve short ones. Each room gets its own Bot instance, so different commits can play side by side.

## 3. How one match works (`H.run` / `H.one`)

1. **Get a room.** `GET /mm/code/new?sid=<32 hex>` returns `{code, room}`.
2. **Join as a player.** Open `wss://play.joinbuilders.org/r/<room>/play?token=&sid=<sid>&name=<name>&code=<code>`.
3. **Lobby.** On each `{type:"lobby"}` message, send `{type:"ready", name}`. As host, send `{type:"start"}`. Every empty seat becomes a house bot. You don't add them yourself.
4. **Hello.** On `{type:"hello"}` (same as protocol.md), build the bot and send `{type:"loaded"}`.
5. **Play.** On each `{type:"obs"}` (10 per second, real time), send `act(obs)`. The action must echo `tick`.
6. **End.** `{type:"end", place, kills}` and then `{type:"results"}` close the match.
7. **Spectate.** `H.watch(S)` also opens the room's spectator stream, `wss://play.joinbuilders.org/r/<room>/live?token=&code=<code>&sid=<any>`. It is `mechreplay/1`: every mech every 0.1 s, plus every shot, hit and death. This is what the hit-rate-by-distance tables came from.

Each run is kept in `H.runs`:
- `S.end` holds place and kills.
- `S.hpLog` takes one row a second: `[t, hp, alive, cubes, slot1 weapon, x, y, z, mode, in_zone]`.
- `S.ev` lists our events: `hit`, `damaged` (with weapon and attacker), `kill`, `took` and so on.
- `S.modes` counts decisions per bot mode.
- `S.lateMs` and `S.slow` record our think time. `slow` counts decisions over 45 ms, and the budget is 50 ms.

## 4. Many rooms at once

```js
H.batch({ base: '<full hash>', varA: '<full hash>', varB: '<full hash>' }, 10, 24);
// 10 matches per tag, 24 rooms at once, round-robin over the tags
H.cmp();    // per tag: n, kills, place, medAlive, cubes, dealtPerTaken, killedBy, modes
H.stop();   // start no new rooms; running matches finish on their own
```

- **How many rooms.** One laptop tab ran 28–33 rooms at once cleanly. Every room held 10 decisions a second, worst think time stayed under 10 ms, `slow` stayed at 0, and the heap stayed around 300 MB.
- **When to back off.** Stop adding rooms if the decision rate drops below 10/s, `slow` rises above 0, or `/mm/code/new` returns errors. It's a shared public server, so respect any refusal.
- **Measure the decision rate** like this:

```js
const a = H.runs.filter(S => !S.done).map(S => [S, S.ticks]);
await new Promise(r => setTimeout(r, 20000));
a.map(([S, t0]) => (S.ticks - t0) / 20);   // should be ~10 for every live room
```

- **Memory.** Per-frame spectator logs (`S.ff`) are large. `H.one` deletes them after each match unless `H.keepFrames = true`. Keep them only for `H.eng()` (hit rate by distance).
- **Branches.** Keep one tag on the current best commit as a control in every batch.
- **Scoring.** Score each variant as `16 - place` averaged over matches. Kills and cubes are steadier than place.

## 5. Read results

| Question | How to answer it |
| --- | --- |
| Score (16 − place), kills, cubes, time alive | `H.cmp()` (`score`, `kills`, `cubes`, `medAlive`) |
| What killed us | `H.cmp()[tag].killedBy`, the weapon with the most damage in our last 8 s: `gun`, `laser`, `lightning`, `mortar`, `npc` (drone) or `zone` |
| Damage by source in one match | `H.sum(S)`. `takenBy` lists `npc`, `zone`, and `m<id>:<weapon>` |
| Where the bot spent its time | `H.cmp()[tag].modes` (FIGHT, RELOCATE, CUBE, CAMP, ...) |
| Hit rate by distance, us and house bots | `H.keepFrames = true` before the batch, then `H.eng()` |

## 6. Watch how the top bots play (read-only)

1. Open `https://watch.joinbuilders.org/show`.
2. Paste `tools/watch_recorder.js` into its console. It records every match the stream airs into `REC.airings`: lobby games, house-bot games, and the hourly "Top 16 Showdown" between the top teams' own bots (each mech's `bot` field reads `docker:buildathon-entry-...`).
3. Run `AN(REC.airings[i])` for a per-mech table with these columns:
   - place, kills, death time
   - cubes at 30/60/90/120/180 s
   - weapons taken, upgrades picked
   - median height above ground and % of time on roofs
   - median speed, % of time still, % of time boosting
   - damage out and in, % of damage taken while 2+ mechs were hitting it
   - crate hits and the first one, drone hits
   - first mech hit, median engagement range
   - HP healed, cubes picked up
4. The feed is `wss://watch.joinbuilders.org/live`. Match state, the schedule and standings come from `wss://watch.joinbuilders.org/state`.

## 7. Making variants

- Branch off the current best: `git switch -c try/<name> <hash>`.
- Make one change. Set `LABEL` in `levers.py`.
- Run both checks:

```sh
python3 tools/test_strategy.py
python3 check/check.py -- python3 -u bot.py
```

- Push the branch, then pass its full hash to `H.batch`.
