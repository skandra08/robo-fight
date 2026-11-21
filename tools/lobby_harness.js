// Live testbed for robo-fight: run the repo's Python bot (via Pyodide) in a private room on
// play.joinbuilders.org against real house bots, and record the spectator replay.
// Paste this whole file into the JS console (or a javascript tool) of a play.joinbuilders.org tab.
//   await H.loadPy();
//   H.loop('<full commit hash>', 6, 'mytag');   // 6 matches in a row, in real time
//   H.batch({base:'<hash>', test:'<hash>'}, 10, 20);  // 10 matches each, 20 rooms at once
//   H.cmp();    // per-tag kills, place, time alive, cubes, damage ratio, cause of death, modes
//   H.stop();   // no new rooms; running ones finish
//   H.table();  // per-tag placement / kills / damage taken by source (npc, zone, ...)
//   H.eng();    // per-tag gun accuracy: house bots on us, and ours, with median distance
// Private-room caveats: 4-minute free-for-all, faster zone, "expert"/"probe-*" house bots that also
// fight each other. Use it for shot-level and bug evidence, not as a practice-score predictor.
(function () {
  const RAW = "https://raw.githubusercontent.com/skandra08/robo-fight/";
  const FILES = ["mechfight.py", "bot.py", "world.py", "cover.py", "nav.py", "combat.py", "memory.py", "levers.py"];
  const DATA = ["data/cover.bin", "data/roofs.json"];
  const H = (window.H = window.H || { runs: [] });

  H.loadPy = async function () {
    if (H.py) return H.py;
    if (!window.loadPyodide) {
      await new Promise((res, rej) => {
        const s = document.createElement("script");
        s.src = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js";
        s.onload = res; s.onerror = rej; document.head.appendChild(s);
      });
    }
    H.py = await loadPyodide();
    H.py.FS.mkdirTree("/arena/v2");
    H.py.FS.writeFile("/arena/v2/world.json", await (await fetch("/arena/v2/world.json")).text());
    H.py.FS.writeFile("/arena/v2/terrain.i16", new Uint8Array(await (await fetch("/arena/v2/terrain.i16")).arrayBuffer()));
    H.py.runPython(`
import sys, json
def MAKE(bot_dir, hello_json):
    for m in ["mechfight","bot","world","cover","nav","combat","memory","levers"]:
        sys.modules.pop(m, None)
    sys.path[:] = [p for p in sys.path if not p.startswith("/bots/")]
    sys.path.insert(0, bot_dir)
    import mechfight as mf, bot as botmod
    hello = json.loads(hello_json)
    hello.setdefault("map", {})["dir"] = "/arena"
    mf.draw.caps = hello.get("config", {}).get("debug", {})
    b = botmod.Bot(hello)
    last = {}
    def act(obs_json):
        obs = json.loads(obs_json)
        mf.draw.clear()
        try:
            a = dict(b.act(obs) or {})
            last.clear(); last.update({k: a[k] for k in ("move","boost","aim") if k in a})
        except Exception:
            import traceback; print(traceback.format_exc()[-600:])
            a = dict(last)
        d = mf.draw.take() or {}
        a.pop("debug", None)
        a["tick"] = obs["tick"]
        a["_m"] = (d.get("label") or "")[:20]   # mode label, ignored by the server
        return json.dumps(a)
    return act
`);
    return H.py;
  };

  H.install = async function (commit) {
    const py = await H.loadPy();
    const dir = "/bots/" + commit;
    if (!py.FS.analyzePath(dir).exists) {
      py.FS.mkdirTree(dir + "/data");
      for (const f of FILES.concat(DATA)) {
        const r = await fetch(RAW + commit + "/" + f);
        if (!r.ok) { if (f === "levers.py") continue; throw new Error(f + " " + r.status); }
        py.FS.writeFile(dir + "/" + f, new Uint8Array(await r.arrayBuffer()));
      }
    }
    return dir;
  };

  H.makeBot = async function (commit, hello) {
    const dir = await H.install(commit);
    return H.py.globals.get("MAKE")(dir, JSON.stringify(hello));
  };

  H.run = async function (commit, opts = {}) {
    const sid = [...crypto.getRandomValues(new Uint8Array(16))].map((e) => e.toString(16).padStart(2, "0")).join("");
    const name = opts.name || "probe";
    const room = await (await fetch(`/mm/code/new?sid=${sid}`, { cache: "no-store" })).json();
    if (!room.code) throw new Error("no room: " + JSON.stringify(room));
    const url = `wss://${location.host}/r/${room.room}/play?token=&sid=${sid}&name=${encodeURIComponent(name)}&code=${room.code}`;
    const S = { commit, tag: opts.tag, name, code: room.code, room: room.room, started: Date.now(), ticks: 0, hpLog: [], ev: [], end: null, lateMs: 0, slow: 0, hello: null, modes: {} };
    H.runs.push(S);
    let act = null;
    await new Promise((resolve) => {
      const ws = new WebSocket(url); let started = false;
      ws.onmessage = async (m) => {
        let d; try { d = JSON.parse(String(m.data)); } catch { return; }
        if (d.type === "lobby") {
          if (!d.you.ready) ws.send(JSON.stringify({ type: "ready", name }));
          if (!started && d.you.host && d.phase !== "running") { started = true; setTimeout(() => ws.send(JSON.stringify({ type: "start" })), 500); }
        } else if (d.type === "hello") {
          S.hello = { slot: d.slot, seed: d.seed }; S.zoneCfg = d.config.zone;
          try { act = await H.makeBot(commit, d); } catch (e) { S.err = String(e); }
          ws.send(JSON.stringify({ type: "loaded" }));
        } else if (d.type === "obs") {
          if (!act) return;
          const t0 = performance.now(); const out = act(JSON.stringify(d)); const dt = performance.now() - t0;
          if (dt > 45) S.slow++; S.lateMs = Math.max(S.lateMs, dt);
          ws.send(out); S.ticks++;
          const me = d.self; let mode = ""; try { mode = JSON.parse(out)._m.split("/")[0]; } catch {}
          S.modes[mode] = (S.modes[mode] || 0) + 1;
          if (S.ticks % 10 === 0) S.hpLog.push([d.t, Math.round(me.hp), d.alive, me.cubes, (me.weapons[1] || {}).kind || "-", Math.round(me.pos[0]), Math.round(me.pos[1]), Math.round(me.pos[2]), mode, me.in_zone ? 1 : 0]);
          for (const e of d.events) if (e.type !== "pickup") S.ev.push([d.t, e.type, e.amount ? Math.round(e.amount) : "", e.weapon || e.kind || "", e.by ?? e.target ?? "", e.rear ? "R" : ""]);
          S.last = { t: d.t, alive: d.alive };
        } else if (d.type === "end") { S.end = d; S.endT = S.last ? S.last.t : null;
        } else if (d.type === "results") { ws.close(); resolve(); }
      };
      ws.onclose = (e) => { S.closeCode = e.code + " " + e.reason; resolve(); };
      if (opts.timeoutMs) setTimeout(() => { try { ws.close(); } catch {} resolve(); }, opts.timeoutMs);
    });
    S.done = Date.now();
    return S;
  };

  // Spectator stream of the same private room: every mech every 0.1 s, every shot and hit.
  H.watch = function (S) {
    const url = `wss://${location.host}/r/${S.room}/live?token=&code=${S.code}&sid=watch${Math.random().toString(16).slice(2)}`;
    S.liveEv = []; S.fires = []; S.ff = [];
    const ws = new WebSocket(url); S.livews = ws;
    ws.onmessage = (e) => {
      for (const line of String(e.data).split("\n")) {
        if (!line) continue; let d; try { d = JSON.parse(line); } catch { continue; }
        if (d.type === "header") { S.header = { bots: d.bots, mechs: d.mechs.map((m) => [m.id, m.name]) }; S.liveEv = []; S.fires = []; S.ff = []; }
        else if (d.t !== undefined) {
          if (d.ev) for (const x of d.ev) {
            if (x.e === "death") S.liveEv.push([d.t / 20, "death", x.id, x.by, x.place]);
            else if (x.e === "hit") S.liveEv.push([d.t / 20, "hit", x.src, x.dst, Math.round(x.amt), x.w]);
            else if (x.e === "fire") S.fires.push([d.t / 20, x.id, x.w]);
          }
          S.ff.push([d.t, d.m.map((m) => [m[0], +m[1].toFixed(1), +m[2].toFixed(1), +m[3].toFixed(1), +m[4].toFixed(3), +m[5].toFixed(3), Math.round(m[6])])]);
        }
      }
    };
  };

  H.loop = async function (commit, n, tag) {
    for (let i = 0; i < n; i++) {
      await H.one(commit, tag);
    }
  };

  // One match: open a room, play it, record its spectator stream, free the big frame log after.
  H.one = async function (commit, tag) {
    let S = null;
    const p = H.run(commit, { name: "rf-" + tag, tag, timeoutMs: 9.5 * 60 * 1000 });
    await new Promise((r) => setTimeout(r, 1500));
    S = H.runs.find((x) => x.tag === tag && !x.done && !x.livews && x.room);
    if (S) H.watch(S);
    const out = await p; try { out.livews && out.livews.close(); } catch {}
    if (!H.keepFrames) delete out.ff;   // per-0.1 s frames are large; keep only if you need H.eng()
    return out;
  };

  // Parallel batch: H.batch({tagA: 'hashA', tagB: 'hashB'}, matchesPerTag, rooms)
  // Runs `rooms` private rooms at once, round-robin over the tags. 20-28 ran cleanly on one laptop tab.
  H.batch = function (commits, perTag, rooms) {
    H.Q = []; for (let i = 0; i < perTag; i++) for (const tag in commits) H.Q.push(tag);
    H.C = commits; H.stopAll = false;
    const worker = async (w) => { while (H.Q.length && !H.stopAll) { const tag = H.Q.shift(); try { await H.one(H.C[tag], tag); } catch (e) { console.log("room", w, e); await new Promise((r) => setTimeout(r, 5000)); } } };
    return Promise.all([...Array(rooms)].map((_, i) => new Promise((r) => setTimeout(r, i * 2500)).then(() => worker(i))));
  };
  H.stop = () => { H.stopAll = true; H.Q = []; };   // running matches finish on their own

  // Per-tag summary: kills, time alive, cubes, damage ratio, cause of death (last 8 s of damage).
  H.cmp = function () {
    const g = {}; const med = (a) => { a = a.filter((x) => x != null).sort((x, y) => x - y); return a.length ? a[Math.floor(a.length / 2)] : null; };
    for (const S of H.runs) {
      if (!S.end || !S.hpLog.length || !S.tag) continue;
      const o = g[S.tag] || (g[S.tag] = { n: 0, kills: 0, place: 0, alive: [], dealt: 0, taken: 0, cubes: 0, killedBy: {}, modes: {} });
      const lt = S.hpLog[S.hpLog.length - 1][0]; o.n++; o.kills += S.end.kills; o.place += S.end.place; o.alive.push(lt);
      o.cubes += Math.max(...S.hpLog.map((h) => h[3] || 0));
      const tail = {};
      for (const e of S.ev) {
        if (e[1] === "hit" && !(+e[4] >= 100)) o.dealt += +e[2] || 0;
        if (e[1] === "damaged") { if (e[3] !== "zone") o.taken += +e[2] || 0; if (e[0] > lt - 8) tail[e[3]] = (tail[e[3]] || 0) + (+e[2] || 0); }
      }
      const k = Object.entries(tail).sort((a, b) => b[1] - a[1])[0]; if (k) o.killedBy[k[0]] = (o.killedBy[k[0]] || 0) + 1;
      for (const m in S.modes) o.modes[m] = (o.modes[m] || 0) + S.modes[m];
    }
    const out = {};
    for (const t in g) { const o = g[t]; const tot = Object.values(o.modes).reduce((a, b) => a + b, 0) || 1;
      out[t] = { n: o.n, kills: +(o.kills / o.n).toFixed(2), place: +(o.place / o.n).toFixed(1), medAlive: med(o.alive), cubes: +(o.cubes / o.n).toFixed(1), dealtPerTaken: +(o.dealt / Math.max(1, o.taken)).toFixed(2), killedBy: o.killedBy,
        modes: Object.fromEntries(Object.entries(o.modes).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([m, v]) => [m, Math.round(100 * v / tot) + "%"])) }; }
    return out;
  };

  H.sum = function (S) {
    let dealt = 0, taken = 0; const takenBy = {};
    for (const e of S.ev) {
      if (e[1] === "hit" && e[4] < 16) dealt += e[2];
      if (e[1] === "damaged") { taken += e[2]; const k = e[3] === "npc" ? "npc" : e[3] === "zone" ? "zone" : "m" + e[4] + ":" + e[3]; takenBy[k] = (takenBy[k] || 0) + e[2]; }
    }
    return { tag: S.tag, place: S.end && S.end.place, kills: S.end && S.end.kills, t: S.endT, dealt, taken, takenBy };
  };

  // For every gun shot: which mech it was aimed at (nearest to the shooter's aim yaw), the distance,
  // and whether a hit on that mech followed within the flight time.
  H.aim = function (S, shooterFilter) {
    const F = S.ff; if (!F || F.length < 3) return null;
    const idx = new Map(); F.forEach((f, i) => idx.set(f[0], i));
    const hits = (S.liveEv || []).filter((e) => e[1] === "hit" && e[5] === "gun");
    const wrap = (a) => Math.atan2(Math.sin(a), Math.cos(a)); const rows = [];
    for (const [tf, sid, w] of S.fires) {
      if (w !== "gun" || (shooterFilter && !shooterFilter(sid))) continue;
      const tk = Math.round(tf * 20); let i = idx.get(tk); if (i === undefined) i = idx.get(tk - 1);
      if (i === undefined || i < 1) continue;
      const f = F[i]; const sh = f[1].find((m) => m[0] === sid); if (!sh) continue;
      let best = null;
      for (const m of f[1]) {
        if (m[0] === sid || m[6] <= 0) continue;
        const dx = m[1] - sh[1], dy = m[2] - sh[2], d = Math.hypot(dx, dy); if (d < 5 || d > 230) continue;
        const b = Math.atan2(dy, dx), da = Math.abs(wrap(sh[4] - b));
        if (da < 0.2 && (!best || da < best.da)) best = { m, d, da };
      }
      if (!best) continue;
      const T = best.d / 252;
      const hit = hits.some((h) => h[2] === sid && h[3] === best.m[0] && h[0] >= tf - 0.01 && h[0] <= tf + T + 0.25);
      rows.push({ sid, tid: best.m[0], d: best.d, hit });
    }
    return rows;
  };

  H.table = function () {
    const g = {};
    for (const S of H.runs) {
      if (!S.tag || !S.end) continue; const x = H.sum(S);
      const o = g[S.tag] || (g[S.tag] = { n: 0, place: 0, kills: 0, t: 0, taken: 0, npc: 0, zone: 0 });
      o.n++; o.place += x.place; o.kills += x.kills; o.t += x.t; o.taken += x.taken; o.npc += x.takenBy.npc || 0; o.zone += x.takenBy.zone || 0;
    }
    for (const k in g) for (const f of ["place", "kills", "t", "taken", "npc", "zone"]) g[k][f] = +(g[k][f] / g[k].n).toFixed(1);
    return g;
  };

  H.eng = function () {
    const g = {};
    for (const S of H.runs) {
      if (!S.tag || !S.ff || !S.hello) continue; const me = S.hello.slot;
      const o = g[S.tag] || (g[S.tag] = { on: [], mine: [] });
      o.on.push(...(H.aim(S, (s) => s !== me) || []).filter((q) => q.tid === me));
      o.mine.push(...(H.aim(S, (s) => s === me) || []));
    }
    const f = (rows) => {
      if (!rows.length) return null; const ds = rows.map((q) => q.d).sort((a, b) => a - b);
      return { n: rows.length, hit: +(rows.filter((q) => q.hit).length / rows.length).toFixed(2), medD: Math.round(ds[Math.floor(ds.length / 2)]) };
    };
    const out = {}; for (const k in g) out[k] = { houseOnUs: f(g[k].on), ours: f(g[k].mine) }; return out;
  };
})();
