#!/usr/bin/env python3
"""Write data/navmoves.bin (per-cell walkable-neighbour bits for pathing.PathGrid)."""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from world import World  # noqa: E402
import pathing  # noqa: E402

t = time.time()
w = World(os.path.join(ROOT, "arena"))
g = pathing.PathGrid(w, None)
with open(os.path.join(ROOT, "data", "navmoves.bin"), "wb") as f:
    f.write(bytes(g.moves))
print(f"navmoves.bin {len(g.moves)} cells in {time.time() - t:.1f}s")
