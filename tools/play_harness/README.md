# Play-site parallel harness

Probe / drive concurrent seats on [play.joinbuilders.org](https://play.joinbuilders.org/).

## Verdict (Sameer)

| Question | Answer |
| --- | --- |
| Can we run multiple browsers/clients at once? | **Yes** — WebSocket clients work; Playwright Chromium also launches. |
| Concurrent safe (this machine)? | **~4–8 WS play seats** or **many `/live` spectators** is fine. Full browser tabs are heavier (WebGL campus load); prefer WS. |
| Attach our Docker `mechfight/1` bot via the play site? | **No.** Play seats speak a browser lobby/input protocol (`ready` / `loaded` / pointer-lock actions). Kit bots speak stdin/stdout JSONL inside Docker with **no network**. |
| Bulk (hundreds) of scored bot games? | **Submit the GitHub repo** on the Mech Royale track (buildathon). Server builds the image and runs **48 practice matches** against built-in bots. Re-submit variants / tags for more batches. Do not scrape the play site for bot eval. |

## Match flow (play site)

1. Matchmaking HTTP (no login required for public play):
   - `GET /mm/pick` → `{room, wait, ...}`
   - `GET /mm/code/new?sid=...` → private `{code, room}`
   - `GET /rooms.json` → `{rooms: N}`
2. Play WebSocket: `wss://play.joinbuilders.org/play` or `wss://…/r/{room}/play`
   - Client: `{type:"ready", name}` → optional `{type:"start"}` (host) → `{type:"loaded"}` after `hello`
   - Server: `lobby` → `hello` → `obs`… → `end` → `results`
   - Empty seats filled with **built-in bots** when the match starts
3. Spectator WebSocket: `wss://…/r/{room}/live` (channel / frame stream)
4. Human UI: `/` (play, pointer lock) or `/game.html?watch` (spectator). Playwright can open these, but WS is enough to observe outcomes.

## Run

Needs Node 22+ (global `WebSocket`) and network egress to `play.joinbuilders.org`.

```sh
# 4 idle public seats (may queue; wait for seating)
node tools/play_harness/parallel_play.mjs --mode play --n 4 --timeout-ms 180000

# 2-seat private room (host starts; bots fill the rest) — good smoke test
node tools/play_harness/parallel_play.mjs --mode play --n 2 --private --timeout-ms 180000

# 4 spectator streams
node tools/play_harness/parallel_play.mjs --mode live --n 4
```

Proven smoke (this agent): 2 parallel private-room seats completed a match and returned `end.place` / `end.kills` while idle (no keyboard input).
