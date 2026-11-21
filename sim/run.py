"""Run the practice simulator for one or more commits.

  python3 sim/run.py --seeds 48 --procs 4 fa3e282 b7b5c38 ...
  python3 sim/run.py --seeds 4 --procs 1 --max-t 120 fa3e282      # smoke test

Each commit's bot files are extracted with `git show` into a temp dir and imported in a worker.
Prints per-commit mean score (16 - place), kills, cubes, time alive.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import statistics
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FILES = ["mechfight.py", "bot.py", "world.py", "cover.py", "nav.py", "combat.py", "memory.py", "levers.py",
         "data/cover.bin", "data/roofs.json", "pathing.py", "data/navmoves.bin"]
MODS = ["mechfight", "bot", "world", "cover", "nav", "combat", "memory", "levers", "pathing"]
CACHE = os.path.join(tempfile.gettempdir(), "simbots")


def install(commit: str) -> str:
    full = subprocess.check_output(["git", "-C", REPO, "rev-parse", commit], text=True).strip()
    d = os.path.join(CACHE, full[:12])
    if os.path.exists(os.path.join(d, ".ok")):
        return d
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    for f in FILES:
        try:
            blob = subprocess.check_output(["git", "-C", REPO, "show", f"{full}:{f}"], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            continue
        with open(os.path.join(d, f), "wb") as fh:
            fh.write(blob)
    open(os.path.join(d, ".ok"), "w").close()
    return d


_loaded = {"dir": None, "mod": None}


def load_bot(d: str):
    if _loaded["dir"] == d:
        return _loaded["mod"]
    for m in MODS:
        sys.modules.pop(m, None)
    sys.path[:] = [p for p in sys.path if not p.startswith(CACHE)]
    sys.path.insert(0, d)
    import bot as botmod  # noqa
    _loaded.update(dir=d, mod=botmod)
    return botmod


class BotWrap:
    def __init__(self, botmod, hello):
        try:
            import mechfight as mf
            mf.draw.caps = hello.get("config", {}).get("debug", {})
            self.mf = mf
        except Exception:
            self.mf = None
        self.b = botmod.Bot(hello)
        self.last = {}
        self.slow = 0
        self.worst = 0.0
        self.tr = []

    def act(self, obs):
        if self.mf is not None:
            try:
                self.mf.draw.clear()
            except Exception:
                pass
        t0 = time.perf_counter()
        try:
            a = dict(self.b.act(obs) or {})
            self.last = {k: a[k] for k in ("move", "boost", "aim") if k in a}
        except Exception:
            a = dict(self.last)
        dt = time.perf_counter() - t0
        self.worst = max(self.worst, dt)
        mode = ""
        if self.mf is not None:
            try:
                d = self.mf.draw.take() or {}
                mode = (d.get("label") or "").split(" ")[0]
            except Exception:
                pass
        me = obs["self"]
        vis = sum(1 for m in obs.get("mechs") or [] if m.get("kind") == "mech")
        w1 = me["weapons"][1]["kind"] if len(me.get("weapons") or []) > 1 and me["weapons"][1] else "-"
        self.tr.append((obs["t"], mode, round(me["hp"]), round(me["energy"]), round(math.hypot(me["vel"][0], me["vel"][1]), 1),
                        vis, bool((a.get("fire") or [False])[0]), me["cubes"], w1, bool(a.get("boost")), [round(v) for v in me["pos"]]))
        return a


_world = {}
TRACE = os.environ.get("SIM_TRACE") == "1"


def one(job):
    commit, d, seed, max_t, params = job[:5]
    knobs = job[5] if len(job) > 5 else None
    tag = job[6] if len(job) > 6 else commit
    sys.path.insert(0, HERE)
    import engine
    import housebot
    try:
        if "w" not in _world:
            _world["w"] = engine.World(os.path.join(REPO, "arena"))
            _world["cfg"] = engine.load_config()
        botmod = load_bot(d)
        # module-level tunables (rewrite line: RW_TUNE-style globals); restore defaults each job
        g0 = botmod.__dict__.setdefault("_G0", {})
        for k, v in g0.items():
            setattr(botmod, k, v)
        if knobs and not hasattr(botmod, "K"):
            for k, v in knobs.items():
                if k not in g0:
                    g0[k] = getattr(botmod, k)
                setattr(botmod, k, v)
        if hasattr(botmod, "K"):
            if not hasattr(botmod, "_K0"):
                botmod._K0 = dict(botmod.K)
            botmod.K.clear()
            botmod.K.update(botmod._K0)
            if knobs:
                botmod.K.update(knobs)
        holder = {}

        def bf(hello):
            holder["b"] = BotWrap(botmod, hello)
            return holder["b"]

        t0 = time.time()
        sim = engine.Sim(seed, bf, lambda s: housebot.HouseSquad(s, params), cfg=_world["cfg"], world=_world["w"])
        r = sim.run(max_t)
        r["wall"] = round(time.time() - t0, 1)
        r["worst_ms"] = round(holder["b"].worst * 1000, 1)
        r["commit"] = tag
        r["sha"] = commit
        r["tr"] = holder["b"].tr if TRACE else None
        return r
    except Exception:
        return {"commit": tag, "seed": seed, "error": traceback.format_exc()[-1500:]}


def summarize(rows):
    out = {}
    for c in dict.fromkeys(r["commit"] for r in rows):
        rs = [r for r in rows if r["commit"] == c and "error" not in r]
        errs = [r for r in rows if r["commit"] == c and "error" in r]
        if not rs:
            out[c] = {"n": 0, "errors": len(errs), "err": errs[0]["error"] if errs else None}
            continue
        mean = lambda k: round(statistics.mean(r[k] for r in rs), 3)
        out[c] = {"n": len(rs), "score": mean("score"), "kills": mean("kills"), "cubes": mean("cubes"), "t": mean("t"),
                  "zone": mean("zone_dmg"), "errors": len(errs), "bot_err": sum(r["bot_err"] for r in rs)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("commits", nargs="*")
    ap.add_argument("--variants", default=None, help="JSON file: [[tag, commit, knobs], ...]")
    ap.add_argument("--seeds", type=int, default=48)
    ap.add_argument("--seed0", type=int, default=1)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--max-t", type=float, default=None)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    params = json.loads(a.params)
    vs = [[c, c, None] for c in a.commits]
    if a.variants:
        vs += json.load(open(a.variants))
    dirs = {v[1]: install(v[1]) for v in vs}
    # seed-major order so partial results stay paired across variants
    jobs = [(v[1], dirs[v[1]], a.seed0 + s, a.max_t, params, v[2], v[0]) for s in range(a.seeds) for v in vs]
    t0 = time.time()
    rows = []
    ctx = mp.get_context("fork")
    with ctx.Pool(a.procs, maxtasksperchild=None) as pool:
        for r in pool.imap_unordered(one, jobs, chunksize=1):
            rows.append(r)
            if "error" in r:
                print("ERR", r["commit"], r["seed"], r["error"][-400:], flush=True)
    print(f"{len(rows)} matches in {time.time() - t0:.0f}s", flush=True)
    s = summarize(rows)
    for c, v in s.items():
        print(c, json.dumps(v), flush=True)
    if a.out:
        with open(a.out, "w") as f:
            json.dump({"rows": rows, "summary": s, "params": params}, f)


if __name__ == "__main__":
    main()
