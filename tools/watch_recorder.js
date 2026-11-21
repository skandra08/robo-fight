// Record matches from the public stream page and summarize how each mech played.
// Paste into a tab open on https://watch.joinbuilders.org/show (read-only, no sign-in).
//   REC.airings            // one entry per match the stream airs: {hdr, chan, frames, ev}
//   AN(REC.airings[i])     // per-mech table, best place first
// The feed (wss://watch.joinbuilders.org/live) is the same mechreplay/1 stream the viewer uses.
// Frames: [tick, m[], n[], z, d, p] with m = [id,x,y,z,aim_yaw,aim_pitch,hp,energy,flags,cubes,max_hp,slot0,slot1]
// (flags 1 grounded, 2 boosting, 4 laser charging). Events: fire, hit{src,dst,amt,w}, death{id,by},
// crate, cube, pickup{id,by}, weapon{op,kind,by}, upgrade{id,up}, charge, laser, zap, boom, short, cookoff.
// Ids: mechs 0-15, drones 100+, crates 1000+, cubes 5000+.
(async function () {
  const w = await fetch("/arena/v2/world.json").then((r) => r.json());
  const h = new Int16Array(await fetch("/arena/v2/terrain.i16").then((r) => r.arrayBuffer()));
  const T = w.terrain, sc = T.scale || 0.01;
  window.GROUND = (x, y) => {
    let u = (x - T.minX) / T.step, v = (y - T.minY) / T.step;
    u = Math.max(0, Math.min(T.nx - 1.001, u)); v = Math.max(0, Math.min(T.ny - 1.001, v));
    const i = Math.floor(u), j = Math.floor(v), tx = u - i, ty = v - j, g = (a, b) => h[b * T.nx + a] * sc;
    return (g(i, j) * (1 - tx) + g(i + 1, j) * tx) * (1 - ty) + (g(i, j + 1) * (1 - tx) + g(i + 1, j + 1) * tx) * ty;
  };

  window.REC = window.REC || { airings: [], cur: null };
  function start() {
    const ws = new WebSocket(`wss://${location.host}/live`);
    ws.onmessage = (e) => {
      for (const line of String(e.data).split("\n")) {
        if (!line) continue; let d; try { d = JSON.parse(line); } catch { continue; }
        if (d.type === "channel") REC.lastChan = d;
        else if (d.type === "header") { REC.cur = { hdr: d, chan: REC.lastChan && { title: REC.lastChan.title, match: REC.lastChan.match }, frames: [], ev: [] }; REC.airings.push(REC.cur); }
        else if (d.t !== undefined && REC.cur) { REC.cur.frames.push([d.t, d.m, d.n, d.z, d.d, d.p]); if (d.ev) for (const x of d.ev) REC.cur.ev.push(x); }
      }
    };
    ws.onclose = () => setTimeout(start, 2000);
  }
  start();

  window.AN = function (a) {
    const N = a.hdr.mechs.length;
    const S = a.hdr.mechs.map((m, i) => ({ name: m.name, kills: 0, deathT: null, cubes: {}, weap: {}, ups: [], z: [], spd: [], still: 0, n: 0, boost: 0, heal: 0,
      dmgOut: 0, dmgIn: 0, multiIn: 0, crateHits: 0, firstCrate: null, droneHits: 0, firstMechHit: null, range: [], pickups: 0 }));
    const pos = {}; let prev = {};
    for (const f of a.frames) {
      const cur = {}; for (const m of f[1]) cur[m[0]] = m; pos[f[0]] = cur;
      if (f[0] % 10) continue;
      for (const id in cur) {
        const m = cur[id], s = S[id]; s.n++; s.z.push(m[3] - GROUND(m[1], m[2])); if (m[8] & 2) s.boost++;
        const p = prev[id]; if (p) { const sp = Math.hypot(m[1] - p[1], m[2] - p[2]) / 0.5; s.spd.push(sp); if (sp < 1) s.still++; if (m[6] > p[6] + 5) s.heal += m[6] - p[6]; }
      }
      for (const t of [30, 60, 90, 120, 180]) if (f[0] === t * 20) for (const id in cur) S[id].cubes[t] = cur[id][9];
      prev = cur;
    }
    const at = (t, id) => { for (let k = 0; k < 6; k++) { const c = pos[t - k] || pos[t + k]; if (c && c[id]) return c[id]; } return null; };
    const att = {};
    for (const x of a.ev) {
      const t = x.t / 20;
      if (x.e === "death" && x.id < N) { S[x.id].deathT = t; if (x.by != null && x.by < N) S[x.by].kills++; }
      if (x.e === "hit") {
        if (x.src < N) {
          const s = S[x.src];
          if (x.dst < N) { s.dmgOut += x.amt; if (s.firstMechHit === null) s.firstMechHit = t; const p = at(x.t, x.src), q = at(x.t, x.dst); if (p && q) s.range.push(Math.hypot(p[1] - q[1], p[2] - q[2])); }
          else if (x.dst >= 1000 && x.dst < 5000) { s.crateHits++; if (s.firstCrate === null) s.firstCrate = t; }
          else if (x.dst >= 100) s.droneHits++;
        }
        if (x.dst < N) { S[x.dst].dmgIn += x.amt; const r = att[x.dst] || (att[x.dst] = {}); if (x.src < N) r[x.src] = t; if (Object.values(r).filter((u) => t - u < 3).length >= 2) S[x.dst].multiIn += x.amt; }
      }
      if (x.e === "upgrade" && x.id < N) S[x.id].ups.push(x.up);
      if (x.e === "pickup" && x.by < N) S[x.by].pickups++;
      if (x.e === "weapon" && x.op === "take" && x.by < N) S[x.by].weap[x.kind] = (S[x.by].weap[x.kind] || 0) + 1;
    }
    const order = S.map((s, i) => [i, s.deathT == null ? 1e9 : s.deathT]).sort((p, q) => q[1] - p[1]);
    order.forEach(([i], k) => (S[i].place = k + 1));
    const med = (v) => { if (!v.length) return null; const s = [...v].sort((x, y) => x - y); return Math.round(s[Math.floor(s.length / 2)] * 10) / 10; };
    const pct = (x, n) => Math.round((100 * x) / Math.max(1, n));
    return S.map((s) => ({ name: s.name, place: s.place, kills: s.kills, deathT: s.deathT, cubes: s.cubes, weap: s.weap, ups: s.ups,
      medHeight: med(s.z), roofPct: pct(s.z.filter((z) => z > 4).length, s.z.length), medSpeed: med(s.spd), stillPct: pct(s.still, s.n), boostPct: pct(s.boost, s.n),
      dmgOut: Math.round(s.dmgOut), dmgIn: Math.round(s.dmgIn), multiAttackerPct: pct(s.multiIn, s.dmgIn), crateHits: s.crateHits, firstCrate: s.firstCrate,
      droneHits: s.droneHits, firstMechHit: s.firstMechHit, medRange: med(s.range), healed: Math.round(s.heal), cubePickups: s.pickups }))
      .sort((p, q) => p.place - q.place);
  };
})();
