"""Does the routed copper carry each power path's current? Max-flow over the real copper, after a zone refill.

    current_check.py BOARD [--cell 0.25] [--png DIR] [--only NAME]

Config "current_paths": [{"name", "net", "from": "J1.2" | "Q1", "to": ..., "amps", "rise_c", "peak", "peak_s",
"peak_rise_c"}]. Missing current values come from the "currents" entry matching the net. "from"/"to": a pad
(REF.PAD) or a whole part (REF: every copper cell of the net inside its courtyard, all layers: the package and its
leads are the source or load, IPC-2152 widths apply to the copper between parts). Copper within
sizing.terminal_margin_mm (default 2.0) of that courtyard counts as terminal too: a neck that short is set by the
package and sheds its heat into the copper on both sides (10 A through 2 mm of 3.4 mm x 70 um copper: about 14 mW).
A bottleneck lying wholly inside those margins is reported as a short link and passes, with its width printed.

Model: every copper cell of the net on every layer is a node; neighbours on one layer are joined with capacity
cell x A/mm, where A/mm = amps / IPC-2152 width for that layer's copper weight (exact at the required width,
conservative below it). Each via and plated hole is a barrel chained through the layers with capacity via_amps per
segment (ipc.via_amps, sizing.plating_mm). Max flow from the source pads to the load pads is the current the copper
carries at the allowed rise. The minimum cut is the bottleneck: its width per layer and its via count are printed,
and its cross-section is checked against the adiabatic area for the peak pulse.

Exit 1 when any path fails. --png writes <name>.png: copper grey per layer, the bottleneck in red."""
import argparse, collections, fnmatch, math, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import ToMM
import ipc
from klib import drc, load_config, short
from raster import CU, NAME, Grid, item_poly, rings_of, stack as stack_of, write_png

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--cell", type=float, default=0.25); ap.add_argument("--png")
ap.add_argument("--only")
a = ap.parse_args()
cfg = load_config(a.board)
S = cfg.get("sizing", {})
stack = {k: float(v) for k, v in cfg.get("stackup", {"F": 1, "In1": 0.5, "In2": 0.5, "B": 1}).items()}
plating, derate = S.get("plating_mm", 0.018), S.get("derate", 1.0)
MARGIN = S.get("terminal_margin_mm", 2.0)

# refill on a copy so the fills match the outlines
tmp = tempfile.mkdtemp()
base = a.board[:-len(".kicad_pcb")]
for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru"):
    if os.path.exists(base + ext):
        shutil.copy(base + ext, os.path.join(tmp, "b" + ext))
drc(os.path.join(tmp, "b.kicad_pcb"), os.path.join(tmp, "d.json"), refill=True, save=True, parity=False)
b = pcbnew.LoadBoard(os.path.join(tmp, "b.kicad_pcb"))
board_stack = stack_of(b)


def current_of(net):
    for c in cfg.get("currents", []):
        if any(fnmatch.fnmatchcase(short(net), g) for g in c["nets"]):
            return c
    return {}


def end_pads(spec, code):
    ref, _, num = spec.partition(".")
    f = b.FindFootprintByReference(ref)
    if f is None:
        sys.exit(f"no part {ref}")
    ps = [p for p in f.Pads() if p.GetNetCode() == code and (not num or p.GetNumber() == num)]
    if not ps:
        sys.exit(f"{spec}: no pad on the net")
    return ps


class Flow:
    """Dinic max-flow with float capacities, adjacency in flat lists."""

    def __init__(self, n):
        self.n, self.head = n, [-1] * n
        self.to, self.cap, self.nxt = [], [], []

    def add(self, u, v, c, c_back=0.0):
        for x, y, k in ((u, v, c), (v, u, c_back)):
            self.to.append(y); self.cap.append(k); self.nxt.append(self.head[x]); self.head[x] = len(self.to) - 1

    def run(self, s, t):
        total, eps = 0.0, 1e-9
        to, cap, nxt, head = self.to, self.cap, self.nxt, self.head
        while True:
            lvl = [-1] * self.n; lvl[s] = 0; q = collections.deque([s])
            while q:
                u = q.popleft(); e = head[u]
                while e >= 0:
                    if cap[e] > eps and lvl[to[e]] < 0:
                        lvl[to[e]] = lvl[u] + 1; q.append(to[e])
                    e = nxt[e]
            if lvl[t] < 0:
                self.lvl = lvl
                return total
            it = head[:]
            while True:                                   # blocking flow: augmenting paths with current-arc pointers
                path, u = [], s
                while u != t:
                    e = it[u]
                    while e >= 0 and not (cap[e] > eps and lvl[to[e]] == lvl[u] + 1):
                        e = nxt[e]
                    it[u] = e
                    if e >= 0:
                        path.append(e); u = to[e]
                        continue
                    lvl[u] = -1                           # dead end: prune and step back
                    if not path:
                        break
                    u = to[path.pop() ^ 1]
                    it[u] = nxt[it[u]]
                if u != t:
                    break
                f = min(cap[e] for e in path)
                for e in path:
                    cap[e] -= f; cap[e ^ 1] += f
                total += f

    def source_side(self, s):
        seen = [False] * self.n; seen[s] = True; q = [s]
        while q:
            u = q.pop(); e = self.head[u]
            while e >= 0:
                if self.cap[e] > 1e-9 and not seen[self.to[e]]:
                    seen[self.to[e]] = True; q.append(self.to[e])
                e = self.nxt[e]
        return seen


paths = cfg.get("current_paths", [])
if a.only:
    paths = [p for p in paths if p["name"] == a.only]
fails = 0
print("| Path | Net | Required | Copper carries | Bottleneck width per layer | Vias in cut | Peak area | Result |")
print("|---|---|---|---|---|---|---|---|")
for P in paths:
    code = next(n.GetNetCode() for nm, n in b.GetNetsByName().items() if short(str(nm)) == short(P["net"]))
    c = {**current_of(P["net"]), **P}
    amps, rise = c.get("amps", c.get("rms")), c.get("rise_c", S.get("rise_c", 10))
    layers = [l for l in board_stack if l in stack]
    items = {l: [] for l in layers}
    for z in b.Zones():
        if z.GetIsRuleArea() or z.GetNetCode() != code:
            continue
        for lid in z.GetLayerSet().CuStack():
            if NAME.get(lid) in items:
                items[NAME[lid]] += rings_of(z.GetFilledPolysList(lid))
    barrels = []
    for t in b.GetTracks():
        if t.GetNetCode() != code:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            for l in layers:
                items[l] += rings_of(item_poly(t, CU[l]))
            barrels.append((ToMM(t.GetPosition().x), ToMM(t.GetPosition().y), ToMM(t.GetDrillValue())))
        elif NAME.get(t.GetLayer()) in items:
            items[NAME[t.GetLayer()]] += rings_of(item_poly(t, t.GetLayer()))
    for p in b.GetPads():
        if p.GetNetCode() != code:
            continue
        for l in layers:
            if p.IsOnLayer(CU[l]):
                items[l] += rings_of(item_poly(p, CU[l]))
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            barrels.append((ToMM(p.GetPosition().x), ToMM(p.GetPosition().y), ToMM(min(p.GetDrillSizeX(), p.GetDrillSizeY()))))
    pts = [pt for l in layers for poly in items[l] for ring in poly for pt in ring]
    if not pts:
        print(f"| {P['name']} | {P['net']} | {amps} A | no copper | | | | FAIL |"); fails += 1; continue
    G = Grid(min(x for x, _ in pts) - 0.5, min(y for _, y in pts) - 0.5, max(x for x, _ in pts) + 0.5, max(y for _, y in pts) + 0.5, a.cell)
    cu = {}
    for l in layers:
        g = G.new(0)
        for poly in items[l]:
            G.fill(poly, g, 1)
        cu[l] = g
    # nodes: cells, then barrel segments, then source / sink
    idx = {}
    for li, l in enumerate(layers):
        for j in range(G.ny):
            row = cu[l][j]
            for i in range(G.nx):
                if row[i]:
                    idx[(li, i, j)] = len(idx)
    nb = len(idx)
    F = Flow(nb + len(barrels) * len(layers) + 2)
    s, t = F.n - 2, F.n - 1
    apm = {l: amps / ipc.width_for_current(amps, rise, stack[l], derate) for l in layers}
    edge_info = {}
    for (li, i, j), u in idx.items():
        cap = a.cell * apm[layers[li]]
        for di, dj in ((1, 0), (0, 1)):
            v = idx.get((li, i + di, j + dj))
            if v is not None:
                edge_info[len(F.to)] = (layers[li], i, j)
                F.add(u, v, cap, cap)
    vcap = {}
    for k, (x, y, d) in enumerate(barrels):
        i, j = G.ij(x, y); va = ipc.via_amps(d, rise, plating, derate)
        for li in range(len(layers)):
            bn = nb + k * len(layers) + li
            u = idx.get((li, i, j))
            if u is not None:
                F.add(u, bn, 1e9, 1e9)
            if li:
                edge_info[len(F.to)] = ("via", x, y)
                F.add(bn - 1, bn, va, va)
    ends, term = {}, {}
    for side, spec, node in (("from", c["from"], s), ("to", c["to"], t)):
        seen_c = set()
        pads_ = end_pads(spec, code)
        whole = "." not in spec                                  # a whole part: its courtyard is the source / load
        for p in pads_:
            for li, l in enumerate(layers):
                if not p.IsOnLayer(CU[l]):
                    continue
                for j, i0, i1 in G.spans(rings_of(item_poly(p, CU[l]))[0]):
                    for i in range(i0, i1):
                        seen_c.add((li, i, j))
        if whole:
            f = pads_[0].GetParentFootprint()
            crt = pcbnew.SHAPE_POLY_SET(f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd))
            if crt.OutlineCount() and MARGIN > 0:
                crt.Inflate(pcbnew.FromMM(MARGIN), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, pcbnew.FromMM(0.02))
            for poly in rings_of(crt) if crt.OutlineCount() else []:
                for j, i0, i1 in G.spans(poly):
                    for i in range(i0, i1):
                        for li in range(len(layers)):
                            seen_c.add((li, i, j))
        term[side] = seen_c
    both = term["from"] & term["to"]                               # overlapping margins belong to neither end
    for side, node in (("from", s), ("to", t)):
        n_end = 0
        for key in term[side] - both:
            u = idx.get(key)
            if u is not None:
                (F.add(node, u, 1e9) if node == s else F.add(u, node, 1e9)); n_end += 1
        ends[side] = n_end
    if os.environ.get("CC_DEBUG"):
        print("  debug", {l: sum(map(sum, cu[l])) for l in layers}, "barrels", len(barrels), "ends", ends, file=sys.stderr)
    flow = F.run(s, t)
    seen = F.source_side(s)
    cut_w = collections.Counter(); cut_v = 0; cut_cells = []
    for e, info in edge_info.items():
        u, v = F.to[e ^ 1], F.to[e]
        if seen[u] != seen[v]:
            if info[0] == "via":
                cut_v += 1
            else:
                cut_w[info[0]] += a.cell; cut_cells.append(info)
    adjacent = flow > 1e8
    ok = flow >= amps * 0.999
    peak_txt = ""
    if c.get("peak"):
        need = ipc.pulse_area_mm2(c["peak"], c.get("peak_s", 1), c.get("peak_rise_c", 60))
        have = sum(w * ipc.thickness_mm(stack[l]) for l, w in cut_w.items())
        peak_txt = f"{have:.2f} / {need:.2f} mm2"
        ok = ok and (have >= need or not cut_w)
    margin_cells = term["from"] | term["to"]
    short_link = not adjacent and not ok and cut_cells and all((layers.index(l), i, j) in margin_cells for l, i, j in cut_cells)
    if adjacent or short_link:
        ok, peak_txt = True, peak_txt + (" (short link: bottleneck within the end parts' margin)" if short_link else "")
    if adjacent:
        cut_w, cut_v = {}, 0
    fails += not ok
    print(f"| {P['name']} | {short(P['net'])} | {amps:g} A at {rise:g} C | " + ("parts adjacent (no conductor)" if adjacent else f"{flow:.1f} A") + " | "
          + ", ".join(f"{l} {w:.1f} mm" for l, w in sorted(cut_w.items())) + f" | {cut_v} | {peak_txt} | {'pass' if ok else 'FAIL'} |")
    if a.png:
        os.makedirs(a.png, exist_ok=True)
        shade = {"F": (200, 60, 60), "In1": (90, 160, 90), "In2": (200, 170, 60), "In3": (160, 90, 200), "In4": (60, 170, 170),
                 "In5": (150, 150, 150), "In6": (120, 120, 120), "B": (70, 110, 200)}
        rows = []
        cutset = {(i, j) for _, i, j in cut_cells}
        for j in range(G.ny):
            row = []
            for i in range(G.nx):
                if (i, j) in cutset:
                    row.append((255, 0, 0)); continue
                on = [l for l in layers if cu[l][j][i]]
                if not on:
                    row.append((255, 255, 255)); continue
                r, g_, bl = (sum(shade[l][k] for l in on) / len(on) for k in range(3))
                f = 0.35 + 0.65 * (1 - len(on) / len(layers))
                row.append((int(255 - (255 - r) * (1 - f) * 1.4) if r < 255 else 255, int(g_ + (255 - g_) * f * 0.5), int(bl + (255 - bl) * f * 0.5)))
            rows.append(row)
        k = max(1, int(600 / max(G.nx, G.ny)))
        write_png(os.path.join(a.png, P["name"].replace(" ", "_") + ".png"), [[px for px in r for _ in range(k)] for r in rows for _ in range(k)])
shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{len(paths)} paths, {fails} failing (cell {a.cell} mm; capacities linearised at the IPC-2152 width)")
sys.exit(1 if fails else 0)
