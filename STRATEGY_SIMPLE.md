# Mechanics-first + simple placement variants

Sameer philosophy: **don't encode fat high-level strategy**. If the bot is precise
on low-level decisions, it should be good. Exploit beneficial game features.

Practice hunters share vision. Score = mean(`16 - place`). Leaders ~5.5; roof-all peak ~2.29.

## Shipped try tags (full 40-char hashes)

| # | tag | Bot.name | hash | idea |
| --- | --- | --- | --- | --- |
| 0 | `try/precise` | `lh-precise` | `f32106a26b4747f2f497162fa2105ecd274e7871` | **mechanics-first** — thin ARM→zone→fight; rear/regen/gun/laser/lightning/quiet/LOS/cubes/zone |
| 1 | `try/zone-sheep` | `lh-zone-sheep` | `156b8d8e1a1720ab80d0272d147faea65fa8aae6` | silent deep next-zone, heal hard, fight only when shot, no chase |
| 2 | `try/cube-snowball` | `lh-cube-snowball` | `5ac89093adc1f8af8cf0eeecbf8a3c5dc3c234ab` | farm NPCs/crates/cubes to `stat_cap`, free fights only, never climb |

`weapon-hunt` (fat loadout trees on snowball) **deprioritized** — scrap / don't submit over precise.

```sh
git fetch --tags --force
git checkout try/precise
```

## Precise mechanics exploited

1. **Rear 1.5x** — orbit behind enemy aim; face threat so we don't give rear
2. **Regen** — stop firing with no LOS / HEAL dumps laser into dirt; don't reset 5s for nothing
3. **Gun** — hold trigger when aimed; lead; dual-aim with laser (no mortar skyfire)
4. **Laser** — charge only on target; release on target; no telegraph miss
5. **Lightning** — close to cone range; chain when NPCs nearby
6. **Quiet** — no boost in zone unless escaping; walk under step_speed
7. **LOS** — don't chase; strafe/hold for clear shot; spray sound through canopy (trees != walls)
8. **Cubes** — scoop when walking by (<=8 m); no farm campaign
9. **Zone** — next-center bias; don't die to storm

Fight rule: 1 visible + (flank/rear OR HP edge) → take; 2+ → cover; if shot → return fire.
