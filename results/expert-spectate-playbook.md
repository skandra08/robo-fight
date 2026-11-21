# Expert/house bot spectate playbook

**N=4 games** watched (1 private smoke + 2 public `/live` rooms + 1 `watch.joinbuilders.org` airing). Baseline to beat: practice **2.65** @ `b7b5c383…`.

Roster in these rooms: `house:expert` + probes (`probe-red-best`/`red`, `probe-red-honest`/`crimson`, `probe-astra-finalist`/`astra`, `probe-astra-skirmish`/`skirmish`). FFA ≠ practice scoring.

## Class snapshot

| class | n | meanPlace | top4% | roof% | firstWeaponT | firstWeapon | engageRange | multi% | cubes30 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| expert | 12 | 7.67 | 25.0 | 38.1 | 5.2 | {'laser': 5, 'mortar': 2, 'lightning': 2} | 56.97 | 19.9 | 0.42 |
| probe_red_best | 12 | 7.83 | 25.0 | 33.3 | 9.7 | {'laser': 4, 'mortar': 0, 'lightning': 2} | 83.42 | 9.0 | 0 |
| probe_astra_skirmish | 11 | 8.73 | 27.3 | 28.8 | 3.95 | {'laser': 1, 'mortar': 2, 'lightning': 5} | 52.97 | 17.4 | 2 |
| probe_astra_finalist | 11 | 9.64 | 9.1 | 27.2 | 4.25 | {'laser': 1, 'mortar': 2, 'lightning': 5} | 60.72 | 32.8 | 1.56 |
| probe_red_honest | 12 | 11.33 | 8.3 | 24.5 | 27.6 | {'laser': 4, 'mortar': 1, 'lightning': 2} | 63.34 | 21.9 | 0.25 |

## Ranked tactics (small diffs on 2.65)

### 1. `laser-first-arm-under-15s` — Take laser within ~8–15s; fight only after armed

**Change first:** Hard-prefer laser in ARM loot ranking; exit ARM immediately on laser take.

- expert medFirstWeaponT=5.2 firstWeapon={'laser': 5, 'mortar': 2, 'lightning': 2}
- probe-red-best medFirstWeaponT=9.7 firstWeapon={'laser': 4, 'mortar': 0, 'lightning': 2}
- Spawn → nearest laser loot; lightning only if laser >~80m.
- Exit ARM on laser take; allow crate/drone gun poke before secondary.

### 2. `brief-roof-then-mobile-midrange` — Roof as short staging (≈10–25% time), laser peek 50–70m, then relocate

**Change first:** Add CAMP peek-timeout → RELOCATE after laser cycle with no target.

- expert meanRoofPct=38.1 roofAfterArm=0.0 firstRoofT=11.25
- engage range med≈56.97m; boost≈28.2%
- After arm: climb ≤15s, one laser cycle, leave if no isolate / after ~8s empty.
- Winners keep inZone≈100 and stay mobile — not AFK roof camps.

### 3. `disengage-multi-attacker` — Hard DISENGAGE when 2+ mechs hit within ~3s

**Change first:** Lower multi-source DISENGAGE threshold; forbid THIRD while multi flag set.

- expert meanMulti=19.9; top places often multi≪30%
- Trigger on ≥2 mech damage sources in 2.5s OR dmgIn spike >250/2s.
- Boost perpendicular + break LOS; no greed laser finish.
- Re-enter FIGHT only if ≤1 aggressor and HP≥45%.

### 4. `cube-upgrade-snowball-like-astra` — Early cube/crate/drone path + spend upgrades (astra-finalist pattern)

**Change first:** Keep/enable N5; earlier armor+gun upgrades; short crate detour during ARM.

- astra cubes30=1.56 cubes60=8.5 ups=1.75 drones=2.5
- expert cubes30=0.42 ups=1.22
- On ARM/RELOCATE: crate ≤40m, scoop cubes, 1–2 drones before long rotate.
- Spend promptly: armor/plating → gun_damage → laser_damage/charge.

### 5. `zone-hug-skip-early-third` — Always hug zone; delay thirds until armed+healthy; skip skirmish early brawls

**Change first:** Tighten THIRD preconditions; never fail ESCAPE_ZONE; no FIGHT before arm complete.

- Top inZonePct≈99.1
- Never leave ring for loot after t>45s.
- THIRD only if armed, HP≥55%, target already fighting, path stays in zone.
- skirmish meanPlace=8.73 firstHit=7.45 — early brawl places worse

## What to change first on our bot

1. **Laser-first ARM** — hard-prefer laser loot; exit ARM on take (experts/red-best).
2. **Multi-attacker DISENGAGE** — widest survival lever vs mid-pack deaths.
3. **CAMP peek-timeout** — roof staging not eternal camp; keep S1 for practice hunters but leave after empty laser cycle.

## Match evidence

- **0** (private_room_smoke): frames=1298 events=3521
  - P1 crimson/probe_red_honest: arm=lightning@80.4 roofT=1.0 roof%=12.2 range=58.5 multi=4.0 drones=0 cubes30=0
  - P2 red/probe_red_best: arm=laser@7.7 roofT=9.5 roof%=15.1 range=68.81 multi=22.3 drones=6 cubes30=0
  - P3 astra/probe_astra_finalist: arm=lightning@3.6 roofT=11.0 roof%=10.0 range=42.23 multi=59.1 drones=5 cubes30=1
  - P4 red/probe_red_best: arm=None@None roofT=35.5 roof%=8.7 range=80.46 multi=0.0 drones=0 cubes30=0
  - P5 expert/expert: arm=laser@4.2 roofT=12.5 roof%=26.0 range=52.49 multi=10.5 drones=8 cubes30=0
- **pub-0** (public_live_room_2): frames=1247 events=3527
  - P1 expert/expert: arm=laser@2.6 roofT=47.0 roof%=68.7 range=61.48 multi=23.1 drones=0 cubes30=2
  - P3 red/probe_red_best: arm=laser@88.8 roofT=27.5 roof%=49.5 range=130.08 multi=0.0 drones=25 cubes30=0
  - P4 skirmish/probe_astra_skirmish: arm=lightning@4.6 roofT=0.0 roof%=100.0 range=39.03 multi=22.4 drones=0 cubes30=5
  - P5 crimson/probe_red_honest: arm=laser@87.3 roofT=46.0 roof%=40.9 range=63.23 multi=2.3 drones=0 cubes30=0
  - P6 red/probe_red_best: arm=None@None roofT=20.5 roof%=15.2 range=30.06 multi=59.9 drones=8 cubes30=0
- **pub-1** (public_live_room_3): frames=363 events=1492
  - P3 expert/expert: arm=laser@3.3 roofT=23.5 roof%=6.5 range=None multi=0.0 drones=8 cubes30=0
  - P4 skirmish/probe_astra_skirmish: arm=None@None roofT=None roof%=0.0 range=62.02 multi=58.3 drones=1 cubes30=0
  - P5 astra/probe_astra_finalist: arm=mortar@3.4 roofT=1.0 roof%=79.2 range=54.95 multi=0.0 drones=1 cubes30=1
  - P6 red/probe_red_best: arm=laser@5.0 roofT=0.0 roof%=71.4 range=114.41 multi=0.0 drones=0 cubes30=0
  - P7 expert/expert: arm=None@None roofT=10.0 roof%=9.1 range=61.79 multi=35.7 drones=0 cubes30=0
- **pub-2** (watch): frames=1251 events=3979
  - P1 Skirmish/probe_astra_skirmish: arm=mortar@3.3 roofT=12.5 roof%=13.0 range=62.01 multi=33.5 drones=8 cubes30=3
  - P2 Expert 2/expert: arm=mortar@10.7 roofT=0.0 roof%=89.8 range=61.04 multi=0.0 drones=8 cubes30=2
  - P5 Astra/probe_astra_finalist: arm=lightning@4.9 roofT=0.5 roof%=37.4 range=56.94 multi=59.4 drones=0 cubes30=3
  - P6 Crimson/probe_red_honest: arm=laser@39.1 roofT=2.0 roof%=15.3 range=63.45 multi=20.8 drones=0 cubes30=1
  - P7 Red 3/probe_red_best: arm=laser@65.9 roofT=15.0 roof%=33.2 range=128.26 multi=3.9 drones=0 cubes30=0
