"""Routability gate: global routing of every open connection with negotiated congestion (PathFinder), in seconds.

    global_route.py BOARD [--tile 1.0] [--iters 60] [--png OUT.png] [--json OUT.json] [--keep-routed] [--quiet]

Connections: KiCad's unconnected items on a refilled copy with the unlocked tracks and vias stripped (the gate
judges the placement plus the locked critical copper; --keep-routed keeps everything). Layers: config
"signal_layers". Widths and clearances: each net's netclass in the .kicad_pro (run sizing.py first). Via:
sizing.vias.signal.

Capacity: the board is rasterised at 0.1 mm; every pad, track, via, zone fill and track keep-out is grown by the
default clearance + half the default width. Zones named in freerouting.drop_zones (by name, or "NET@LAYER") are pours that fill around
tracks and do not block. Plane zones (config "planes") block tracks on their layer but not vias. A tile's track
capacity on a layer is its free area / tile size (mm of free width); a route uses its net's pitch (width +
clearance) in every tile it crosses; a via uses one via site of its tile (free area for a via on all layers / via
pitch squared) and half a via pitch on every routable layer. The tiles under a connection's own end pads are open
to it (pin access).

PathFinder: first pass routes everything, later passes rip up only routes through overflowing tiles; A* on
(layer, tile), cost = length + via cost, times (1 + history) x (1 + present overflow penalty). Routes may cross
fixed copper at 30x cost, so a connection with no legal way still gets a path and shows where it wants to go. The
best iteration is reported.

Reading it: overflow is in mm of track width over capacity, summed over tiles, at the given tile size. It is a
comparison and a locator, not a proof: compare placements at the same --tile (1.0 mm is the standard), act on the
hotspots (where, which nets, blocked by what). 0 at 1.0 mm with no fixed-copper crossings is the gate for detailed
routing; the detailed route is the proof. Exit 1 otherwise. --png: one panel per signal layer, blocked copper grey,
used capacity blue, overflow red, routes through fixed copper magenta."""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from klib import load_config
from g4 import Model

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--tile", type=float, default=1.0); ap.add_argument("--iters", type=int, default=60)
ap.add_argument("--png"); ap.add_argument("--json"); ap.add_argument("--quiet", action="store_true")
ap.add_argument("--via-cost", type=float, default=1.5, help="via cost in mm of track")
ap.add_argument("--keep-routed", action="store_true")
ap.add_argument("--fine", type=float, default=0.1, help="raster step, mm")
ap.add_argument("--restarts", type=int, default=3, help="net orders tried (best kept; the spread is printed)")
a = ap.parse_args()
m = Model(a.board, load_config(a.board), tile=a.tile, keep_routed=a.keep_routed, via_cost=a.via_cost, fine=a.fine)
import random
order0, runs, best = list(m.conns), [], None
for k in range(a.restarts):
    m.conns = list(order0)
    if k:
        random.Random(k).shuffle(m.conns)
    m.routes = [None] * len(m.conns)
    m.reset_usage()                                              # fresh usage for each order
    t = m.solve(iters=a.iters, quiet=a.quiet)
    runs.append(round(t, 2))
    if best is None or t < best[0]:
        best = (t, list(m.conns), list(m.routes), [dict(c) for c in m.conns])
tot = best[0]
m.reset_usage()
m.conns, m.routes = best[1], best[2]
for c, r in zip(m.conns, m.routes):
    c.pop("applied", None)
    if r:
        m._apply(r, c, +1)
fixed = m.fixed_crossings()
unrouted = [c for c, r in zip(m.conns, m.routes) if not r]
print(("" if a.keep_routed else f"unlocked tracks/vias stripped: {m.stripped}; ")
      + f"connections {len(m.conns)} (plane-net ends over their plane, left to plane_fanout: {m.plane_skipped}), layers {'/'.join(m.LAYERS)}, tile {m.T} mm, iterations {len(m.curve)}")
tr, vo = m.overflow_split()
print(f"overflow {tot:.2f} mm (tracks {tr:.2f}, vias {vo:.2f}); crossing fixed copper: {len(fixed)} connections; no path: {len(unrouted)}")
print(f"overflow per net order: {runs} (best kept)")
for s in m.hotspots()[:12]:
    x0, y0, x1, y1 = s["box"]
    print(f"  hotspot ({x0:.1f}..{x1:.1f}, {y0:.1f}..{y1:.1f}) overflow {s['overflow']:.2f} mm, {len(s['tiles'])} tiles, "
          f"blocked by {', '.join(s['blocked_by'])}; nets: {', '.join(s['nets'][:10])}")
for k, ns in fixed.items():
    c = m.conns[k]
    print(f"  through fixed copper: {c['net']}  {c['ends'][0]['desc'][:40]} -> {c['ends'][1]['desc'][:40]} ({len(ns)} tiles)")
for c in unrouted:
    print(f"  no path: {c['net']} {c['ends'][0]['desc'][:50]} -> {c['ends'][1]['desc'][:50]} (end not on a signal layer)")
if a.json:
    json.dump({"tile": m.T, "origin": [m.X0, m.Y0], "layers": m.LAYERS, "overflow": tot, "hotspots": m.hotspots(),
               "demand": [[tx, ty, n] for (tx, ty), n in sorted(m.demand().items())],
               "routes": [{"net": c["net"], "a": c["ends"][0]["desc"], "b": c["ends"][1]["desc"], "path": r}
                          for c, r in zip(m.conns, m.routes)]}, open(a.json, "w"))
if a.png:
    m.png(a.png)
    print(f"wrote {a.png} (panels: {', '.join(m.LAYERS)})")
m.close()
sys.exit(1 if tot > 1e-6 or fixed or unrouted else 0)
