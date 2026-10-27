"""Feasibility gate (run on the draft placement, before the placement review).

    feasibility.py BOARD [--util 0.4] [--cell 2.5] [--top 10]

1. Routing demand vs capacity. Demand = for every net that is not a plane net or a high-voltage (poured) net, the
   Manhattan minimum spanning tree over its pads, times its netclass pitch (track + clearance). Capacity = board area
   x signal layers x utilisation, minus no-track keep-outs. Ratio above about 0.8: expect the autorouter to leave
   connections; above 1: re-place or grow the board before routing.
2. Hotspots: the same demand rasterised on a grid (L-shaped paths), cells over capacity listed.
3. Current paths (config "current_paths"): IPC-2221 width needed on each listed layer for the current and rise, vs
   the free copper width along the straight pad-to-pad line on that layer (other-net pads and holes block). Pass when
   the sum over layers of free / needed >= 1.

Config keys: net_groups, signal_layers, stackup (oz per layer), current_paths."""
import argparse, fnmatch, json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import ToMM, FromMM
from klib import Board, LAYER, short

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--util", type=float, default=0.4); ap.add_argument("--cell", type=float, default=2.5)
ap.add_argument("--top", type=int, default=10)
ap.add_argument("--half", type=float, default=12.0, help="current-path corridor half-width to search (mm)")
a = ap.parse_args()
B = Board(a.board)
cfg = B.cfg
pro = json.load(open(re.sub(r"\.kicad_pcb$", ".kicad_pro", a.board)))
classes = {c["name"]: c for c in pro["net_settings"]["classes"]}
patterns = pro["net_settings"].get("netclass_patterns", [])


def netclass(name):
    for p in patterns:
        if fnmatch.fnmatchcase(name, p["pattern"]) or fnmatch.fnmatchcase("/" + short(name), p["pattern"]):
            return p["netclass"]
    return "Default"


def pitch(name):
    c = classes.get(netclass(name), classes["Default"])
    return c["track_width"] + c["clearance"]


# ---- 1. demand
pads_by_net = {}
for f in B.b.GetFootprints():
    for p in f.Pads():
        n = str(p.GetNetname())
        if n and not n.startswith("unconnected"):
            pads_by_net.setdefault(n, []).append((ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)))
edges = []                      # (net, (x1, y1), (x2, y2), pitch)
for n, pts in pads_by_net.items():
    if len(pts) < 2 or B.is_plane(n) or B.is_hv(n):
        continue
    inside, rest = [pts[0]], pts[1:]
    while rest:                 # Prim, Manhattan
        d, i, j = min((abs(p[0] - q[0]) + abs(p[1] - q[1]), i, j) for i, p in enumerate(inside) for j, q in enumerate(rest))
        edges.append((n, inside[i], rest[j], pitch(n)))
        inside.append(rest.pop(j))
demand = sum((abs(e[1][0] - e[2][0]) + abs(e[1][1] - e[2][1])) * e[3] for e in edges)
layers = cfg.get("signal_layers", ["F", "B"])
area = B.w * B.h
ko = 0.0
for z in B.b.Zones():
    if z.GetIsRuleArea() and z.GetDoNotAllowTracks():
        nl = sum(1 for l in layers if z.IsOnLayer(LAYER[l]))
        ko += ToMM(ToMM(z.Outline().Area())) * nl if nl else 0
capacity = area * len(layers) * a.util - ko * a.util
ratio = demand / capacity
verdict = "OK (global; the hotspots below decide)" if ratio < 0.8 else ("TIGHT: expect leftovers after autorouting" if ratio < 1.0 else "OVER: re-place or grow the board")
print(f"Routing demand {demand:.0f} mm2 over {len(edges)} connections; capacity {capacity:.0f} mm2 "
      f"({len(layers)} signal layers x {area:.0f} mm2 x {a.util} - keep-outs) -> ratio {ratio:.2f}: {verdict}")

# ---- 2. hotspots
nx, ny = int(B.w / a.cell) + 1, int(B.h / a.cell) + 1
grid = [[0.0] * nx for _ in range(ny)]


def add_line(x1, y1, x2, y2, p):
    L = abs(x2 - x1) + abs(y2 - y1)
    steps = max(1, int(L / 0.25))
    for k in range(steps):
        t = (k + 0.5) / steps
        x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
        i, j = int((y - B.y0) / a.cell), int((x - B.x0) / a.cell)
        if 0 <= i < ny and 0 <= j < nx:
            grid[i][j] += L / steps * p


for n, (x1, y1), (x2, y2), p in edges:
    add_line(x1, y1, x2, y1, p); add_line(x2, y1, x2, y2, p)
cap_cell = a.cell * a.cell * len(layers) * a.util
hot = sorted(((grid[i][j] / cap_cell, B.x0 + (j + 0.5) * a.cell, B.y0 + (i + 0.5) * a.cell) for i in range(ny) for j in range(nx)), reverse=True)
over = [h for h in hot if h[0] > 1.0]
print(f"Hotspots ({a.cell} mm cells, demand / capacity): {len(over)} cells over 1.0")
for r, x, y in hot[:a.top]:
    print(f"  ({x:6.1f}, {y:6.1f})  {r:4.2f}")

# ---- 3. current paths
OZ_MIL = 1.378


def ipc2221_width_mm(amps, rise, oz, internal):
    k = 0.024 if internal else 0.048
    area_mil2 = (amps / (k * rise ** 0.44)) ** (1 / 0.725)
    return area_mil2 / (oz * OZ_MIL) * 0.0254


paths = cfg.get("current_paths", [])
if paths:
    print("Current paths (IPC-2221, straight pad-to-pad corridor):")
blk = {}
for t in B.b.GetTracks():                     # other-net vias block every layer
    if t.Type() == pcbnew.PCB_VIA_T:
        r = ToMM(t.GetWidth(pcbnew.F_Cu)) / 2; x, y = ToMM(t.GetPosition().x), ToMM(t.GetPosition().y)
        for l in LAYER:
            blk.setdefault(l, []).append((short(t.GetNetname()), (x - r, y - r, x + r, y + r)))
for f in B.b.GetFootprints():
    for p in f.Pads():
        pb = p.GetBoundingBox()
        box = (ToMM(pb.GetLeft()), ToMM(pb.GetTop()), ToMM(pb.GetRight()), ToMM(pb.GetBottom()))
        th = p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
        for l, lid in LAYER.items():
            if th or p.IsOnLayer(lid):
                blk.setdefault(l, []).append((short(p.GetNetname()), box))
for cp in paths:
    ra, pa = cp["from"].split("."); rb, pb_ = cp["to"].split(".")
    (x1, y1), (x2, y2) = B.pad_xy(ra, pa), B.pad_xy(rb, pb_)
    L = math.hypot(x2 - x1, y2 - y1); ux, uy = (x2 - x1) / L, (y2 - y1) / L; nxv, nyv = -uy, ux
    total = 0.0
    parts = []
    for l in cp["layers"]:
        oz = cfg.get("stackup", {}).get(l, 1)
        need = ipc2221_width_mm(cp["amps"], cp.get("rise_c", 10), oz, l.startswith("In"))
        free_min = 1e9
        s = 1.0
        while s < L - 1.0:                    # skip the pads themselves
            cx, cy = x1 + ux * s, y1 + uy * s
            # longest free run across the corridor (current can step around a pin): scan the perpendicular line
            best = run = 0.0
            d = -a.half
            while d <= a.half:
                px, py = cx + nxv * d, cy + nyv * d
                blocked = (not B.inside((px, py, px, py), 0.5)) or any(
                    nn != short(cp["net"]) and b[0] - 0.3 <= px <= b[2] + 0.3 and b[1] - 0.3 <= py <= b[3] + 0.3 for nn, b in blk.get(l, []))
                run = 0.0 if blocked else run + 0.1
                best = max(best, run)
                d += 0.1
            free_min = min(free_min, best)
            s += 0.25
        frac = free_min / need
        total += frac
        parts.append(f"{l} ({oz} oz): needs {need:.1f} mm, narrowest free {free_min:.1f} mm")
    print(f"  {cp['name']}: {cp['amps']} A, {cp.get('rise_c', 10)} C rise, {L:.1f} mm -> {'PASS' if total >= 1 else 'FAIL'} "
          f"(sum over layers of narrowest free / needed = {total:.2f}; approximate: widest free run across the corridor)")
    for t in parts:
        print("     " + t)
