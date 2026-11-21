#!/usr/bin/env node
/**
 * Parallel play/observe harness for https://play.joinbuilders.org/
 *
 * WHAT THIS CAN DO
 * - Open N concurrent WebSocket play seats (public lobby or private code room)
 * - Ready up, optionally host-start a private match, wait for hello/obs/end
 * - Open N concurrent /live spectator streams and sample channel frames
 *
 * WHAT THIS CANNOT DO
 * - Attach a mechfight/1 Docker bot (stdin/stdout protocol) to the play site
 * - Drive skilled human input; idle seats coast / die to zone+bots
 * - Replace buildathon practice scoring (submit repo → 48 server-run matches)
 *
 * Usage:
 *   node tools/play_harness/parallel_play.mjs --mode play --n 4
 *   node tools/play_harness/parallel_play.mjs --mode play --n 2 --private
 *   node tools/play_harness/parallel_play.mjs --mode live --n 4
 *   node tools/play_harness/parallel_play.mjs --mode play --n 4 --timeout-ms 180000
 */

const BASE = process.env.PLAY_BASE || "https://play.joinbuilders.org";
const WS_BASE = BASE.replace(/^http/, "ws");

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  if (i < 0) return fallback;
  const v = process.argv[i + 1];
  if (v == null || v.startsWith("--")) return true;
  return v;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function getJson(path) {
  const r = await fetch(`${BASE}${path}`, { cache: "no-store" });
  const t = await r.text();
  try {
    return JSON.parse(t);
  } catch {
    return { error: "bad-json", raw: t.slice(0, 200), status: r.status };
  }
}

async function newPrivateCode(sid) {
  let last = null;
  for (let i = 0; i < 12; i++) {
    last = await getJson(`/mm/code/new?sid=${encodeURIComponent(`${sid}-${i}`)}`);
    if (last.room && last.code) return { ...last, sid: `${sid}-${i}` };
    const waitMs = Math.max(1000, Math.ceil(Number(last.retry_s) || 1) * 1000);
    await sleep(waitMs);
  }
  throw new Error(`mm/code/new failed: ${JSON.stringify(last)}`);
}

function connectPlay(url, name, { wantStart = false, timeoutMs = 180000 } = {}) {
  return new Promise((resolve) => {
    const out = {
      name,
      url,
      hello: null,
      end: null,
      results: false,
      obs: 0,
      lastLobby: null,
      error: null,
      types: [],
    };
    const ws = new WebSocket(url);
    let started = false;
    const timer = setTimeout(() => {
      out.error = out.error || "timeout";
      try {
        ws.close();
      } catch {}
      resolve(out);
    }, timeoutMs);

    ws.addEventListener("open", () => {
      ws.send(JSON.stringify({ type: "ready", name }));
    });

    ws.addEventListener("message", (ev) => {
      const text = typeof ev.data === "string" ? ev.data : Buffer.from(ev.data).toString("utf8");
      for (const line of text.split("\n").filter(Boolean)) {
        let j;
        try {
          j = JSON.parse(line);
        } catch {
          continue;
        }
        out.types.push(j.type);
        if (j.type === "lobby") {
          out.lastLobby = {
            phase: j.phase,
            match: j.match,
            you: j.you,
            count: j.count,
            next_at: j.next_at,
          };
          // Server picks the host; only that seat's `start` is honored.
          const amHost = Boolean(j.you?.host);
          if (wantStart && amHost && !started && (j.phase === "waiting" || j.phase === "intermission")) {
            started = true;
            setTimeout(() => ws.send(JSON.stringify({ type: "start" })), 400);
          }
        } else if (j.type === "hello") {
          out.hello = { slot: j.slot, seed: j.seed };
          ws.send(JSON.stringify({ type: "loaded" }));
        } else if (j.type === "obs") {
          out.obs += 1;
          // Idle: no input. Mech coasts until zone/bots end it.
        } else if (j.type === "end") {
          out.end = { place: j.place, kills: j.kills };
        } else if (j.type === "results") {
          out.results = true;
          clearTimeout(timer);
          try {
            ws.close();
          } catch {}
          resolve(out);
        }
      }
    });

    ws.addEventListener("error", () => {
      out.error = out.error || "ws-error";
    });
    ws.addEventListener("close", () => {
      clearTimeout(timer);
      resolve(out);
    });
  });
}

function connectLive(url, { timeoutMs = 20000, maxMsgs = 8 } = {}) {
  return new Promise((resolve) => {
    const out = { url, msgs: 0, first: null, error: null };
    const ws = new WebSocket(url);
    const timer = setTimeout(() => {
      out.error = out.error || "timeout";
      try {
        ws.close();
      } catch {}
      resolve(out);
    }, timeoutMs);

    ws.addEventListener("message", (ev) => {
      const text = typeof ev.data === "string" ? ev.data : Buffer.from(ev.data).toString("utf8");
      const line = text.split("\n").find(Boolean);
      if (!line) return;
      out.msgs += 1;
      if (!out.first) {
        try {
          const j = JSON.parse(line);
          out.first = { type: j.type, phase: j.phase, match: j.match };
        } catch {
          out.first = { raw: line.slice(0, 80) };
        }
      }
      if (out.msgs >= maxMsgs) {
        clearTimeout(timer);
        try {
          ws.close();
        } catch {}
        resolve(out);
      }
    });
    ws.addEventListener("error", () => {
      out.error = out.error || "ws-error";
    });
    ws.addEventListener("close", () => {
      clearTimeout(timer);
      resolve(out);
    });
  });
}

async function runPlay(n, { privateRoom, timeoutMs }) {
  let urls = [];
  if (privateRoom) {
    const code = await newPrivateCode(`harness-${Date.now()}`);
    console.error("private room", code);
    const base = `${WS_BASE}/r/${code.room}/play?code=${code.code}`;
    urls = Array.from({ length: n }, (_, i) => `${base}&sid=${encodeURIComponent(`${code.sid}-p${i}`)}`);
  } else {
    const pick = await getJson("/mm/pick");
    console.error("public pick", pick);
    const roomUrl = `${WS_BASE}/r/${pick.room}/play`;
    // Mix room + root /play (auto-assign) so we don't all stampede one queue slot path.
    urls = Array.from({ length: n }, (_, i) => (i % 2 === 0 ? roomUrl : `${WS_BASE}/play`));
  }

  const jobs = urls.map((url, i) =>
    connectPlay(url, `harness-${i}`, { wantStart: privateRoom, timeoutMs }),
  );
  const results = await Promise.all(jobs);
  return results.map((r) => ({
    name: r.name,
    hello: r.hello,
    obs: r.obs,
    end: r.end,
    results: r.results,
    error: r.error,
    lastLobby: r.lastLobby,
    types: [...new Set(r.types)],
  }));
}

async function runLive(n, timeoutMs) {
  const pick = await getJson("/mm/pick?watch=1");
  console.error("watch pick", pick);
  const rooms = await getJson("/rooms.json");
  const maxRoom = Math.max(1, Number(rooms.rooms) || 128);
  const jobs = [];
  for (let i = 0; i < n; i++) {
    const room = ((pick.room + i - 1) % maxRoom) + 1;
    jobs.push(connectLive(`${WS_BASE}/r/${room}/live`, { timeoutMs: Math.min(timeoutMs, 30000) }));
  }
  return Promise.all(jobs);
}

async function main() {
  const mode = String(arg("mode", "play"));
  const n = Math.max(1, Number(arg("n", "4")) || 4);
  const timeoutMs = Math.max(5000, Number(arg("timeout-ms", "180000")) || 180000);
  const privateRoom = Boolean(arg("private", false));

  console.error(`mode=${mode} n=${n} private=${privateRoom} timeoutMs=${timeoutMs}`);
  let out;
  if (mode === "live") out = await runLive(n, timeoutMs);
  else if (mode === "play") out = await runPlay(n, { privateRoom, timeoutMs });
  else throw new Error(`unknown --mode ${mode} (play|live)`);

  console.log(JSON.stringify({ mode, n, privateRoom, out }, null, 2));
  const failed = Array.isArray(out) && out.some((r) => r.error && !r.end && !r.first);
  process.exit(failed ? 2 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
