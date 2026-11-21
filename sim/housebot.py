"""Fitted practice-squad policy for the house mechs (an approximation, not the real house bot).

Fitted to live replays (136 private-room matches): house bots shoot the nearest enemy, close to
~46 m (experts), lead their shots, and about half of them back off to heal when low.
Hit rate by range on the live server was <40 m 88%, 40-80 m 62%, 80-130 m 37%, 130-230 m 14%;
an aim error with sigma ~0.05 rad reproduces that for the mixed lineup.

Practice squad rules modelled here:
  * the 15 house mechs never shoot each other and share vision of the bot
  * hunters are released weakest first: 1 at the start, +1 per house death, more over time, all late
  * a house mech the bot damages, or that sees the bot up close, joins the hunt
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from engine import DT, Mech, wrap

SKILL = {
    #          aim sigma, lead quality, engage range, retreat chance, react s
    "easy":   dict(sigma=0.085, lead=0.4, rng=70.0, retreat=0.2, react=0.9),
    "medium": dict(sigma=0.065, lead=0.7, rng=60.0, retreat=0.4, react=0.6),
    "hard":   dict(sigma=0.052, lead=0.9, rng=50.0, retreat=0.5, react=0.4),
    "expert": dict(sigma=0.042, lead=1.0, rng=46.0, retreat=0.6, react=0.25),
}
ORDER = {"easy": 0, "medium": 1, "hard": 2, "expert": 3}


class HouseSquad:
    def __init__(self, sim, params: Optional[Dict] = None):
        self.sim = sim
        p = dict(base=1, per_death=1, t_steps=(90, 180, 270, 360), t_add=(1, 2, 3, 15), aim_mul=1.0, know_noise=25.0)
        if params:
            p.update(params)
        self.p = p
        rng = sim.rng
        self.state: Dict[int, Dict] = {}
        for m in sim.mechs[1:]:
            s = SKILL[m.skill]
            self.state[m.id] = dict(active=False, err=[0.0, 0.0], retreating=False, retreats=rng.random() < s["retreat"],
                                    seen_t=-99.0, strafe=1.0 if rng.random() < 0.5 else -1.0, strafe_t=0.0,
                                    stuck_t=0.0, last_pos=list(m.pos), detour=0.0, detour_until=-1.0,
                                    wander=list(m.pos), wander_t=-99.0)
        # release order: weakest first, ties by id
        self.order = sorted(sim.mechs[1:], key=lambda m: (ORDER[m.skill], rng.random()))
        self.known = None  # shared knowledge of the bot: [x, y, z]
        self.known_t = -99.0
        self.seen_now = False
        self.house_deaths = 0

    # ------------------------------------------------------------- engine hooks
    def on_damage(self, target: Mech, src: Mech, amount: float, weapon: str):
        if src.id == 0 and target.id in self.state:
            self.state[target.id]["active"] = True
            self.known = list(src.pos)
            self.known_t = self.sim.t

    def on_death(self, m: Mech, src):
        if m.id != 0:
            self.house_deaths += 1

    # ------------------------------------------------------------- policy
    def n_hunters(self) -> int:
        p = self.p
        n = p["base"] + p["per_death"] * self.house_deaths
        for ts, add in zip(p["t_steps"], p["t_add"]):
            if self.sim.t >= ts:
                n += add
        return n

    def decide(self, sim):
        bot = sim.mechs[0]
        if not bot.alive:
            return
        t = sim.t
        # release hunters
        want = self.n_hunters()
        alive = [m for m in self.order if m.alive]
        cnt = sum(1 for m in alive if self.state[m.id]["active"])
        for m in alive:
            if cnt >= want:
                break
            if not self.state[m.id]["active"]:
                self.state[m.id]["active"] = True
                cnt += 1
        # shared vision (every 0.2 s)
        if sim.tick % 4 == 0:
            self.seen_now = False
            bc = bot.center()
            top = [bot.pos[0], bot.pos[1], bot.pos[2] + bot.height()]
            for m in alive:
                d = math.dist(m.pos[:2], bot.pos[:2])
                if d > 210:
                    continue
                if sim.sees(m, bc, top):
                    self.seen_now = True
                    self.state[m.id]["seen_t"] = t
                    if d < 80:
                        self.state[m.id]["active"] = True
            if self.seen_now:
                self.known = list(bot.pos)
                self.known_t = t
            else:
                # loud bot weapons give away the position to the squad
                for s in sim.sound_events:
                    if s["src"] == 0 and s["kind"] in ("gun", "laser", "mortar", "lightning"):
                        nz = self.p["know_noise"]
                        self.known = [bot.pos[0] + sim.rng.gauss(0, nz), bot.pos[1] + sim.rng.gauss(0, nz), bot.pos[2]]
                        self.known_t = t
                        break
        zone = sim.zone()
        for m in alive:
            self.act(sim, m, bot, zone)

    def _in_zone_goal(self, zone, pos, frac=0.75):
        cx, cy = zone["center"]
        r = max(0.0, zone["radius"]) * frac
        dx, dy = pos[0] - cx, pos[1] - cy
        d = math.hypot(dx, dy) or 1.0
        if d <= r:
            return None
        return [cx + dx / d * r, cy + dy / d * r]

    def act(self, sim, m: Mech, bot: Mech, zone):
        st = self.state[m.id]
        sk = SKILL[m.skill]
        t = sim.t
        c = m.cmd
        c["fire"] = [False, False]
        c["jump"] = False
        c["boost"] = False
        c["reload"] = False
        # aim error: OU process, re-drawn smoothly
        sig = sk["sigma"] * self.p["aim_mul"]
        k = 0.25
        for i in (0, 1):
            st["err"][i] += -k * st["err"][i] + sim.rng.gauss(0, sig * math.sqrt(2 * k))
        hp_frac = m.hp / m.max_hp
        if st["retreats"]:
            if hp_frac < 0.35:
                st["retreating"] = True
            elif hp_frac > 0.85:
                st["retreating"] = False
        d_bot = math.dist(m.pos[:2], bot.pos[:2])
        visible = t - st["seen_t"] < 0.3 or (self.seen_now and d_bot < 120)
        goal = None
        speed = 1.0
        out = self._in_zone_goal(zone, m.pos, 0.9)
        if st["active"] and self.known is not None:
            tgt = bot.pos if visible else self.known
            d = math.dist(m.pos[:2], tgt[:2])
            if st["retreating"] and visible:
                ang = math.atan2(m.pos[1] - tgt[1], m.pos[0] - tgt[0])
                goal = [m.pos[0] + math.cos(ang) * 40, m.pos[1] + math.sin(ang) * 40]
            elif d > sk["rng"] or not visible:
                goal = tgt
            else:
                # strafe at engage range
                if t > st["strafe_t"]:
                    st["strafe"] = -st["strafe"]
                    st["strafe_t"] = t + sim.rng.uniform(1.5, 4.0)
                ang = math.atan2(tgt[1] - m.pos[1], tgt[0] - m.pos[0]) + st["strafe"] * math.pi / 2
                goal = [m.pos[0] + math.cos(ang) * 20, m.pos[1] + math.sin(ang) * 20]
                speed = 0.7
        else:
            # idle: drift inside the zone
            if t > st["wander_t"]:
                g = self._in_zone_goal(zone, m.pos, 0.6)
                st["wander"] = g or [m.pos[0] + sim.rng.uniform(-30, 30), m.pos[1] + sim.rng.uniform(-30, 30)]
                st["wander_t"] = t + sim.rng.uniform(4, 10)
            goal = st["wander"]
            speed = 0.5
        if out is not None and (not visible or zone["radius"] < 150):
            goal, speed = out, 1.0
        # aiming and firing
        if visible and (st["active"] or d_bot < 80):
            bc = bot.center()
            dist3 = math.dist(m.muzzle(), bc)
            tof = dist3 / 252.0
            lead = sk["lead"]
            px = bc[0] + bot.vel[0] * tof * lead
            py = bc[1] + bot.vel[1] * tof * lead
            pz = bc[2] + bot.vel[2] * tof * lead * 0.5
            mz = m.muzzle()
            yaw = math.atan2(py - mz[1], px - mz[0])
            pit = math.atan2(pz - mz[2], math.hypot(px - mz[0], py - mz[1]))
            c["aim"] = [yaw + st["err"][0], pit + st["err"][1]]
            if t - st["seen_t"] >= 0 and abs(wrap(yaw - m.aim[0])) < 0.15 and dist3 < 230:
                # reaction delay after first spotting
                if st.get("spot_t") is None:
                    st["spot_t"] = t
                if t - st["spot_t"] >= sk["react"]:
                    c["fire"][0] = True
        else:
            st["spot_t"] = None
            g = m.weapons[0]
            if g and g["kind"] == "gun" and g["ammo"] < g["stats"]["mag"] // 2:
                c["reload"] = True
        # movement
        if goal is None:
            c["move"] = [0.0, 0.0]
            return
        dx, dy = goal[0] - m.pos[0], goal[1] - m.pos[1]
        L = math.hypot(dx, dy)
        if L < 2.0:
            c["move"] = [0.0, 0.0]
            return
        ang = math.atan2(dy, dx)
        if t < st["detour_until"]:
            ang += st["detour"]
        c["move"] = [math.cos(ang) * speed, math.sin(ang) * speed]
        if not visible:
            c["aim"] = [ang, 0.0]
        # climb towards a target that is above us (roof), or get unstuck
        if st["active"] and visible and bot.pos[2] > m.pos[2] + 4 and d_bot < 30 and m.energy > 40:
            c["jump"] = m.grounded
            c["boost"] = True
        moved = math.dist(m.pos[:2], st["last_pos"][:2])
        if sim.tick % 10 == 0:
            if moved < 1.0 and speed > 0.4:
                st["stuck_t"] += 0.5
            else:
                st["stuck_t"] = 0.0
            st["last_pos"] = list(m.pos)
            if st["stuck_t"] >= 1.0:
                st["detour"] = sim.rng.choice([1, -1]) * sim.rng.uniform(0.9, 1.8)
                st["detour_until"] = t + 2.0
                if m.energy > 50:
                    c["jump"] = m.grounded
                    c["boost"] = True
                st["stuck_t"] = 0.0
