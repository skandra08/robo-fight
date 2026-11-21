# Simple placement variants (4.5 hunt)

Practice hunters share vision. Score = mean(`16 − place`). Leaders ~5.5, early 4.5 spike ⇒ **simple sharp placement**, not lever stacks. Our roof-all peak was ~2.29.

## Ideas evaluated

| # | idea | verdict |
| --- | --- | --- |
| 1 | Cube snowball | **ship** — tankiness from cubes; free fights only |
| 2 | Pure zone sheep | **ship** — placement over kills; quiet deep next-zone |
| 3 | Gun spray + cover | deferred — still a camp; sheep is cleaner |
| 4 | Supply drop addict | deferred — contested, loud, late |
| 5 | Dual alone on simple camp | deferred — still fights; complexity we already A/B'd |
| 6 | Fix loud boost / climb suicide / chase | **folded into both** — quiet arm, never climb, sheep holds |

## Shipped try tags (full 40-char hashes)

| # | tag | Bot.name | hash | idea |
| --- | --- | --- | --- | --- |
| 1 | `try/zone-sheep` | `lh-zone-sheep` | `156b8d8e1a1720ab80d0272d147faea65fa8aae6` | **submit first** — silent deep next-zone, heal hard, fight only when shot, no chase |
| 2 | `try/cube-snowball` | `lh-cube-snowball` | `5ac89093adc1f8af8cf0eeecbf8a3c5dc3c234ab` | farm NPCs/crates/cubes to `stat_cap`, free fights only, never climb |

```sh
git fetch --tags --force
git checkout try/zone-sheep
```

## Why sheep could be the 4.5 trick

1. Score is placement mean — not kills; dying 2–3 places later beats fancy DPS.
2. Shared-vision hunters punish loud boost + roof silhouettes; sheep deletes both.
3. Holding fire until shot keeps regen clock alive (45 HP/s after 5 s quiet).
4. Deep next-zone paths avoid edge scrapes that eat early places.
5. No chase ⇒ no tunnel vision into 2nd/3rd hunter while low.
