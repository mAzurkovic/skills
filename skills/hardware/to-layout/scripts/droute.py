"""Detailed router driven by the global routes: every open connection is routed inside its g4 corridor on a fine grid
with the real clearances, rip-up and reroute by negotiated congestion, tracks and vias written to a copy, KiCad DRC.

    droute.py BOARD --out OUT.kicad_pcb [--cell 0.1] [--iters 30] [--g4-restarts 3] [--png OUT.png] [--keep-routed]

Config router.layer_pref {"INH?": "F", "INL?": "B", ...}: those nets pay router.off_layer_cost (3) x length on
other layers. For buses whose pin orders only match per layer (one group per layer, no crossings).

--reserve-escapes (with --only, for routing in stages): before routing, every pad of router.escape_parts (default
U*) whose net still has an open connection outside --only (pour and plane nets excepted) gets its escape reserved: a stub from
the pad straight out of the chip edge for router.escape_len (1.0 mm; odd pins router.escape_stagger, 0.7 mm, further)
and a via site at its tip. The staged nets
route around them, so the later stages are not walled in.

Config router.join_any_copper [nets]: a connection of these nets may end on any copper of the other island (the
nearest pair KiCad reports can be a pin buried in a fan-out).

--keep-routed finishes another router's result: its tracks and vias stay (as fixed copper) and only the open
connections are routed.

Pipeline: g4.Model (refilled copy, unlocked routing stripped, plane-net ends over their plane skipped) gives the
connections and a tile path for each; the best of --g4-restarts net orders is kept.

Grid: per signal layer, --cell mm. Every pad, track, via, filled zone (except freerouting.drop_zones pours, which
fill around tracks) and track keep-out is grown by its clearance + half the routing width; a cell covered only by
copper of net N is still open to N (pin access, joining its own copper). Vias: a separate map grown by via radius +
clearance over every copper layer; plane zones (config "planes") do not block vias.

Pin access (before routing): from every connection end, flood fill over the fixed copper; an end that reaches
fewer than router.access_cells (1500) cells and not its other end is walled in. They are listed and the run stops
with exit 2 (router.route_anyway: true routes the rest): fix the placement around them first.

Search: A* over (layer, cell), 8 directions (45-degree tracks), a via between any two signal layers where the via
map is open, confined to the connection's g4 tiles grown by --corridor tiles (then 3x, then the whole board if it
fails). Cost: length x (1 + history) + present penalty for cells another net's route claims, + via cost + a small
turn cost. A route claims the cells within its net's pitch of its centreline (width/2 + clearance + default
width/2), on its layer, and a via disc on every layer. PathFinder: route all, then rip up and reroute every
connection that shares a cell with another net, penalties rising, until none do or --iters runs out.

Output: unlocked tracks (netclass width, collinear cells merged, 90-degree and sharper corners chamfered) and
signal vias, saved to --out with its .kicad_pro / .kicad_dru / .layout.json; then refill + DRC and a summary.
Exit 0 when DRC reports no unconnected items and no clearance or short violations."""
import argparse, collections, fnmatch, heapq, json, math, os, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I
from klib import drc, drc_summary, load_config, short
from raster import CU, NAME, Grid, item_poly, rings_of, stack
from g4 import Model

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--out", required=True); ap.add_argument("--cell", type=float, default=0.1)
ap.add_argument("--iters", type=int, default=30); ap.add_argument("--g4-restarts", type=int, default=3)
ap.add_argument("--corridor", type=int, default=1, help="tiles added around the g4 path")
ap.add_argument("--via-cost", type=float, default=1.0, help="mm of track"); ap.add_argument("--png")
ap.add_argument("--only", help="comma-separated nets to route (debugging)"); ap.add_argument("--debug", action="store_true")
ap.add_argument("--gate-only", action="store_true", help="pin-access check only: no global or detailed routing")
ap.add_argument("--time-budget", type=float, default=0, help="seconds: stop iterating and write the result after this")
ap.add_argument("--trapped-json", help="with --gate-only: write the walled-in ends (net, x, y) here")
ap.add_argument("--reserve-escapes", action="store_true",
                help="with --only: keep a 1 mm escape stub + via site free at every IC pin of the nets routed later")
ap.add_argument("--keep-routed", action="store_true", help="keep the unlocked tracks and vias as fixed copper; route only what is open")
a = ap.parse_args()
t0 = time.time()
cfg = load_config(a.board)

# ---- global routes (best of a few net orders)
import random
m = Model(a.board, cfg, keep_routed=a.keep_routed)
order0, best = list(m.conns), None
for k in range(0 if a.gate_only else a.g4_restarts):
    m.conns = list(order0)
    if k:
        random.Random(k).shuffle(m.conns)
    m.routes = [None] * len(m.conns)
    m.reset_usage()
    ov = m.solve(iters=60)
    if best is None or ov < best[0]:
        best = (ov, list(m.conns), list(m.routes))
if best:
    m.conns, m.routes = best[1], best[2]
if best:
    print(f"global: {len(m.conns)} connections, overflow {best[0]:.2f} mm ({time.time() - t0:.0f} s)", file=sys.stderr)

b, LAYERS = m.b, m.LAYERS
NL, C = len(LAYERS), a.cell
D = m.D
WD, CLR = D["track_width"], D["clearance"]
vdrill, vdia = m.vdrill, m.vdia
G = Grid(m.X0, m.Y0, m.X1, m.Y1, C)
NX, NY = G.nx, G.ny
FREE, MULTI = 0, -1

# ---- fixed obstacles with net ownership: 0 free, net code if only that net, -1 blocked for everyone.
# Three maps per layer: normal nets, high-voltage nets (0.6 mm to other nets' exposed pads, IPC-2221B B2) and sense
# nets (1.0 mm from high-voltage copper); pins inside the exempt courtyards (ICs, MOSFETs) keep netclass clearance.
FR = cfg.get("freerouting", {})
RT = cfg.get("router", {})
HV_CLASSES = set(FR.get("hv_classes", ["HV", "HV_SIG", "GATE_HS"]))
SENSE_CLASSES = set(FR.get("sense_classes", ["SENSE"]))
MARGIN = RT.get("margin", 0.005)                    # on every clearance: diagonal tracks on the grid land a few um short
HV_PAD = RT.get("hv_pad_clear", 0.6) + 0.01           # margin: rasterised round pads come out a few um small
SENSE_HV = RT.get("sense_hv_clear", 1.0) + 0.01
EXEMPT = cfg.get("sizing", {}).get("pad_exempt_courtyards", ["Q*", "U*"])
cls_name = {}


def klass(code):
    if code <= 0:
        return ""
    if code not in cls_name:
        nm = b.FindNet(code).GetNetname()
        for pat in m.patterns:
            if fnmatch.fnmatchcase(nm, pat["pattern"]) or fnmatch.fnmatchcase("/" + short(nm), pat["pattern"]):
                cls_name[code] = pat["netclass"]; break
        else:
            cls_name[code] = "Default"
    return cls_name[code]


KEYS = ["N", "S"] + sorted(HV_CLASSES)                          # normal, sense, one per high-voltage class
OWN = {k: [G.new(FREE) for _ in LAYERS] for k in KEYS}
VOWN = {k: G.new(FREE) for k in KEYS}
own = OWN["N"]
inside = G.new(0)
eb = pcbnew.SHAPE_POLY_SET(); b.GetBoardPolygonOutlines(eb, True)
sh = pcbnew.SHAPE_POLY_SET(eb); sh.Deflate(FromMM(0.5 + WD / 2), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
for poly in rings_of(sh):
    G.fill(poly, inside, 1)
vin = G.new(0)
sh = pcbnew.SHAPE_POLY_SET(eb); sh.Deflate(FromMM(0.5 + vdia / 2), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
for poly in rings_of(sh):
    G.fill(poly, vin, 1)


# items touching these courtyards keep netclass clearance (the rules file exempts them the same way)
EXEMPT_BOXES = []
for f in b.GetFootprints():
    if any(fnmatch.fnmatchcase(f.GetReference(), g) for g in EXEMPT):
        crt = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
        if crt.OutlineCount():
            EXEMPT_BOXES.append(crt)


def touches_exempt(sps):
    if not sps.OutlineCount():
        return False
    ol = sps.Outline(0)
    return any(c.Collide(ol, 0) or c.Contains(ol.CPoint(0)) for c in EXEMPT_BOXES)


def grow_for(key, base, half, code, exempt, is_pad):
    """Grow radius of an item of net `code` in the map used for routing nets of `key`; half = route half-size."""
    k = klass(code)
    if key == "S":                 # the sense rule's exemption is where the sense copper is (SENSE_FREE), not the pad
        return max(base, SENSE_HV + half) if k in HV_CLASSES else base
    if exempt is True:                                           # pads of Q* / U* parts: netclass clearance only
        return base
    if key == "N":
        return max(base, HV_PAD + half) if (k in HV_CLASSES and is_pad) else base
    g = base                                                     # a high-voltage class:
    if k in SENSE_CLASSES and exempt != "sense" and RT.get("hv_keeps_off_sense", True):   # 1.0 mm from sense copper
        #                                                        outside sense_escape areas (DRC re-checks it either way)
        g = max(g, SENSE_HV + half)
    return max(g, HV_PAD + half) if (is_pad and k != key) else g # 0.6 mm from other classes' exposed pads


def mark3(li, sps, grow, code, item_hv, exempt, is_pad):
    """Mark one copper item of signal layer li in every routing map."""
    for key in KEYS:
        mark(OWN[key][li], sps, grow_for(key, grow, WD / 2, code, exempt, is_pad), code)


def markv(sps, grow, code, exempt, is_pad):
    for key in KEYS:
        mark(VOWN[key], sps, grow_for(key, grow, vdia / 2, code, exempt, is_pad), code)


def mark(g, sps, grow, code):
    s = pcbnew.SHAPE_POLY_SET(sps)
    if grow > 0:
        s.Inflate(FromMM(grow), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
    for poly in rings_of(s):
        for j, i0, i1 in G.spans(poly):
            row = g[j]
            for i in range(i0, i1):
                v = row[i]
                row[i] = code if v in (FREE, code) else MULTI


def clr_of(code):
    nm = m.net_full.get(short(b.FindNet(code).GetNetname()) if code > 0 else "", "")
    return (max(CLR, m.netclass(nm)["clearance"]) if code > 0 else CLR) + MARGIN


ALL = [(n, CU[n]) for n in stack(b)]
SENSE_AREAS = []                   # sense_escape areas (U* / R* courtyards + band, per side): sense copper touching one
for f in b.GetFootprints():          # is exempt from the 1.0 mm rule, so HV routes may pass it at netclass clearance
    if f.GetReference()[:1] in "UR":
        crt = pcbnew.SHAPE_POLY_SET(f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd))
        if crt.OutlineCount():
            crt.Inflate(FromMM(RT.get("sense_exempt_band", 0.6)), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
            SENSE_AREAS.append((None, crt))                      # every copper layer (sense_escape.py does the same)


def in_sense_area(t, lid=None):
    """'sense' when t is sense copper touching a sense_escape area on its side (a via: any side), else False."""
    if klass(t.GetNetCode()) not in SENSE_CLASSES:
        return False
    via = isinstance(t, pcbnew.PCB_VIA)
    lid = lid if lid is not None else (pcbnew.F_Cu if via else t.GetLayer())
    sh = item_poly(t, lid)
    hit = sh.OutlineCount() > 0 and any((via or lay is None or lay == lid) and (a_.Collide(sh.Outline(0), 0) or a_.Contains(sh.Outline(0).CPoint(0)))
                                        for lay, a_ in SENSE_AREAS)
    return "sense" if hit else False


for p in b.GetPads():
    code = p.GetNetCode() if p.GetNetCode() > 0 else MULTI
    ref = p.GetParentFootprint().GetReference()
    ex0 = any(fnmatch.fnmatchcase(ref, g) for g in EXEMPT)
    for ln, lid in ALL:
        if p.IsOnLayer(lid):
            sps = item_poly(p, lid)
            ex = True if (ex0 or touches_exempt(sps)) else in_sense_area(p, lid)
            if ln in LAYERS:
                mark3(LAYERS.index(ln), sps, clr_of(code) + WD / 2, code, klass(code) in HV_CLASSES, ex, True)
            markv(sps, clr_of(code) + vdia / 2, code, ex, True)
    if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
        hole = pcbnew.SHAPE_POLY_SET(); hole.NewOutline()
        r = ToMM(max(p.GetDrillSizeX(), p.GetDrillSizeY())) / 2
        x, y = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)
        for k in range(24):
            hole.Append(FromMM(x + r * math.cos(k * math.pi / 12)), FromMM(y + r * math.sin(k * math.pi / 12)))
        for key in KEYS:
            mark(VOWN[key], hole, 0.25 + vdia / 2, MULTI)                   # hole to hole
            for li in range(NL):                                           # hole to track
                mark(OWN[key][li], hole, 0.25 + WD / 2, MULTI if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH else code)
for t in b.GetTracks():
    code = t.GetNetCode()
    hv = klass(code) in HV_CLASSES
    sx = in_sense_area(t)
    if t.Type() == pcbnew.PCB_VIA_T:
        for ln, lid in ALL:
            if ln in LAYERS:
                mark3(LAYERS.index(ln), item_poly(t, lid), clr_of(code) + WD / 2, code, hv, sx, False)
        markv(item_poly(t, pcbnew.F_Cu), max(clr_of(code), 0.25) + vdia / 2, code, False, False)
    else:
        ln = NAME.get(t.GetLayer())
        sps = item_poly(t, t.GetLayer())
        if ln in LAYERS:
            mark3(LAYERS.index(ln), sps, clr_of(code) + WD / 2, code, hv, sx, False)
        markv(sps, clr_of(code) + vdia / 2, code, sx, False)
for f in b.GetFootprints():                                       # copper graphics: net-tie bridges
    for g in f.GraphicalItems():
        ln = NAME.get(g.GetLayer())
        if ln is None or not hasattr(g, "TransformShapeToPolygon"):
            continue
        tied = [(ToMM(p.GetPosition().x), ToMM(p.GetPosition().y), p.GetNetCode()) for p in f.Pads()
                if p.IsOnLayer(g.GetLayer()) and p.GetNetCode() > 0]
        near = lambda x, y: min(tied, key=lambda t: math.hypot(t[0] - x, t[1] - y))[2] if tied else MULTI
        sps = item_poly(g, g.GetLayer())
        maps = [(OWN[k][LAYERS.index(ln)], CLR + WD / 2) for k in KEYS] if ln in LAYERS else []
        for k in KEYS:                                             # a via hole keeps clear of it whatever its net
            mark(VOWN[k], sps, max(CLR, 0.2) + vdia / 2, MULTI)
        for gm, grow in maps:                                      # each cell belongs to the nearer tied pad's net
            s_ = pcbnew.SHAPE_POLY_SET(sps)
            s_.Inflate(FromMM(grow), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
            for poly in rings_of(s_):
                for jj, i0, i1 in G.spans(poly):
                    row = gm[jj]
                    for ii in range(i0, i1):
                        code = near(*G.xy(ii, jj))
                        v = row[ii]
                        row[ii] = code if v in (FREE, code) else MULTI
for z in b.Zones():
    for lid in z.GetLayerSet().CuStack():
        ln = NAME.get(lid)
        if z.GetIsRuleArea():
            if z.GetDoNotAllowTracks() and ln in LAYERS:             # no copper of the track inside: half-width
                for key in KEYS:
                    mark(OWN[key][LAYERS.index(ln)], z.Outline(), WD / 2 + 0.01, MULTI)
            if z.GetDoNotAllowVias():
                for key in KEYS:
                    mark(VOWN[key], z.Outline(), vdia / 2 + 0.01, MULTI)
            continue
        if z.GetZoneName() in m.drop or f"{short(z.GetNetname())}@{ln}" in m.drop:
            continue
        fill = z.GetFilledPolysList(lid)
        code = z.GetNetCode()
        if ln in LAYERS:
            mark3(LAYERS.index(ln), fill, clr_of(code) + WD / 2, code, klass(code) in HV_CLASSES, False, False)
        if (short(z.GetNetname()), ln) not in m.planes:
            markv(fill, clr_of(code) + vdia / 2, code, False, False)
SENSE_BAND = RT.get("sense_exempt_band", 0.6)  # the rules exempt sense copper in a sense_escape area: U* / R*
SENSE_FREE = {l: G.new(0) for l in ("F", "B")}  # courtyards + this band, on the part's own side (sense_escape.py)
for f in b.GetFootprints():
    if f.GetReference()[:1] in "UR":
        crt = pcbnew.SHAPE_POLY_SET(f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd))
        if crt.OutlineCount():
            crt.Inflate(FromMM(SENSE_BAND), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
        for poly in rings_of(crt):
            G.fill(poly, SENSE_FREE["B" if f.IsFlipped() else "F"], 1)
for j in range(NY):
    for i in range(NX):
        if SENSE_FREE["F"][j][i] or SENSE_FREE["B"][j][i]:        # the areas cover every copper layer
            for li in range(NL):
                OWN["S"][li][j][i] = OWN["N"][li][j][i]
            VOWN["S"][j][i] = VOWN["N"][j][i]
print(f"grid {NX} x {NY} x {NL} at {C} mm built ({time.time() - t0:.0f} s)", file=sys.stderr)

# ---- connections
net_code = {short(str(nm)): n.GetNetCode() for nm, n in b.GetNetsByName().items()}


def key_for(code):
    k = klass(code)
    return k if k in HV_CLASSES else "S" if k in SENSE_CLASSES else "N"


def map_for(code, w=None, band=False):
    """Obstacle map for a net; a track wider than the default sees every obstacle grown by the extra half-width.
    band: the neck-down zone includes NECKB (router.neck_band_classes)."""
    key = key_for(code)
    if w is None or w <= WD + 1e-9:
        return OWN[key]
    off = wide_offs(w)
    if (key, len(off), band) not in WIDE_MAPS:
        out = []
        for g in OWN[key]:
            n_ = [row[:] for row in g]                              # interior cells keep their value
            for j in range(NY):
                row, up, dn = g[j], g[j - 1] if j else g[j], g[j + 1] if j + 1 < NY else g[j]
                for i in range(NX):
                    v = row[i]
                    if v == FREE:
                        continue
                    if (i and row[i - 1] == v) and (i + 1 < NX and row[i + 1] == v) and up[i] == v and dn[i] == v:
                        continue                                    # dilation changes only boundary cells' neighbours
                    for di, dj in off:
                        x, y = i + di, j + dj
                        if 0 <= x < NX and 0 <= y < NY:
                            u = n_[y][x]
                            n_[y][x] = v if u in (FREE, v) else MULTI
            for j in range(NY):                                     # necked inside IC courtyards
                nk, nb, row, nrow = NECK[j], NECKB[j], g[j], n_[j]
                for i in range(NX):
                    if nk[i] or (band and nb[i]):
                        nrow[i] = row[i]
            out.append(n_)
        WIDE_MAPS[(key, len(off), band)] = out
    return WIDE_MAPS[(key, len(off), band)]


WIDE_MAPS = {}
NECK = G.new(0)                    # IC courtyards: wide tracks neck down to the default width there (the rules allow
NECKB = G.new(0)                   # it); NECKB: + router.neck_band mm, for router.neck_band_classes only (USB: no
for f in b.GetFootprints():        # minimum width rule, so a short neck outside the courtyard is legal too)
    if any(fnmatch.fnmatchcase(f.GetReference(), g) for g in cfg.get("sizing", {}).get("neck_courtyards", ["U*"])):
        crt = pcbnew.SHAPE_POLY_SET(f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd))
        for poly in rings_of(crt):
            G.fill(poly, NECK, 1)
        if crt.OutlineCount() and RT.get("neck_band", 0) > 0:
            crt.Inflate(FromMM(RT["neck_band"]), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
            for poly in rings_of(crt):
                G.fill(poly, NECKB, 1)
NECK_BAND_CLASSES = set(RT.get("neck_band_classes", ["USB"]))


def necked(c, i, j):
    return NECK[j][i] or (NECKB[j][i] and c.get("cls") in NECK_BAND_CLASSES)


def wide_offs(w):
    """Cell offsets within the extra half-width of a track of width w over the default (at least the 4-neighbours)."""
    r = (w - WD) / 2 + C * 0.75
    R = int(math.ceil(r / C))
    return [(di, dj) for di in range(-R, R + 1) for dj in range(-R, R + 1) if math.hypot(di, dj) * C < r]


def end_cells(e, code):
    """Cells where a route may end: inside its pad (on the pad's layers), or own copper near a track / zone end."""
    out = set()
    own = map_for(code)
    if e["pad"] is not None:
        p = e["pad"]
        for li, l in enumerate(LAYERS):
            if p.IsOnLayer(CU[l]):
                for poly in rings_of(item_poly(p, CU[l])):
                    for j, i0, i1 in G.spans(poly):
                        for i in range(i0, i1):
                            if own[li][j][i] in (FREE, code) and inside[j][i]:
                                out.add((li, i, j))
        return out
    i0, j0 = G.ij(e["x"], e["y"])
    for li in e.get("layers", range(NL)):
        for r in range(1, 12):
            for j in range(j0 - r, j0 + r + 1):
                for i in range(i0 - r, i0 + r + 1):
                    if 0 <= i < NX and 0 <= j < NY and own[li][j][i] == code:
                        out.add((li, i, j))
            if out:
                break
    return out


INNER_W = {}                       # sizing.py rules "sizing: CLASS width, inner" (min width per class on inner layers)
try:
    import re as _re
    _dru = open(a.board[:-len(".kicad_pcb")] + ".kicad_dru").read()
    for _m in _re.finditer(r'\(rule "sizing: (\S+) width, inner".*?track_width \(min ([\d.]+)mm\)', _dru, _re.S):
        INNER_W[_m.group(1)] = float(_m.group(2))
except OSError:
    pass
_COPPER = {}


def copper_cells(code):
    """(layer, i, j) cells covered by this net's actual copper (pads, tracks, vias; no clearance), signal layers."""
    if code not in _COPPER:
        cells = set()
        items = [p for p in b.GetPads() if p.GetNetCode() == code] + [t for t in b.GetTracks() if t.GetNetCode() == code]
        for z in b.Zones():                                          # pour fill counts as copper too
            if z.GetIsRuleArea() or z.GetNetCode() != code:
                continue
            for li, l in enumerate(LAYERS):
                if z.IsOnLayer(CU[l]):
                    for poly in rings_of(z.GetFilledPolysList(CU[l])):
                        for j, i0, i1 in G.spans(poly):
                            for i in range(i0, i1):
                                if inside[j][i]:
                                    cells.add((li, i, j))
        for it in items:
            for li, l in enumerate(LAYERS):
                if not it.IsOnLayer(CU[l]):
                    continue
                for poly in rings_of(item_poly(it, CU[l])):
                    for j, i0, i1 in G.spans(poly):
                        for i in range(i0, i1):
                            if inside[j][i]:
                                cells.add((li, i, j))
        _COPPER[code] = cells
    return _COPPER[code]


def island_cells(code, start):
    """Copper cells of `code` connected to `start` through copper (4-neighbour, same layer; vias join layers)."""
    cu = copper_cells(code)
    vias = {(ToMM(t.GetPosition().x), ToMM(t.GetPosition().y)) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetCode() == code}
    vcells = {G.ij(x, y) for x, y in vias}
    seen = {n for n in start if n in cu} or set(start)
    q = list(seen)
    while q:
        li, i, j = q.pop()
        nbrs = [(li, i + 1, j), (li, i - 1, j), (li, i, j + 1), (li, i, j - 1)]
        if (i, j) in vcells:
            nbrs += [(l2, i, j) for l2 in range(NL)]
        for n in nbrs:
            if n in cu and n not in seen:
                seen.add(n); q.append(n)
    return seen


only = set(a.only.split(",")) if a.only else None
if a.reserve_escapes and only:                                    # escapes of the nets routed in later stages
    poured = cfg.get("place_opt", {}).get("fixed_nets", []) + [q["net"] for q in cfg.get("planes", [])] + \
        cfg.get("net_groups", {}).get("plane", [])               # zones and planes connect these, not tracks
    later = {c["net"] for c in m.conns if c["net"] not in only and not any(fnmatch.fnmatchcase(c["net"], g) for g in poured)}
    EL = RT.get("escape_len", 1.0)
    nres = 0
    for f in b.GetFootprints():
        if not any(fnmatch.fnmatchcase(f.GetReference(), g) for g in RT.get("escape_parts", ["U*"])):
            continue
        fc = f.GetPosition(); rot0 = math.radians(f.GetOrientationDegrees())
        lay = pcbnew.B_Cu if f.IsFlipped() else pcbnew.F_Cu
        ln = NAME.get(lay)
        for p in f.Pads():
            if short(p.GetNetname()) not in later or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or ln not in LAYERS:
                continue
            x, y = ToMM(p.GetPosition().x) - ToMM(fc.x), ToMM(p.GetPosition().y) - ToMM(fc.y)
            lx, ly = x * math.cos(rot0) - y * math.sin(rot0), x * math.sin(rot0) + y * math.cos(rot0)
            if max(abs(lx), abs(ly)) < 0.5:
                continue                                          # exposed pad
            nx, ny = ((1 if lx > 0 else -1), 0) if abs(lx) > abs(ly) else (0, (1 if ly > 0 else -1))
            ux, uy = nx * math.cos(rot0) + ny * math.sin(rot0), -nx * math.sin(rot0) + ny * math.cos(rot0)
            bb = p.GetBoundingBox(); half = max(ToMM(bb.GetWidth()), ToMM(bb.GetHeight())) / 2
            px, py = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)
            stag = RT.get("escape_stagger", 0.7) if (p.GetNumber().isdigit() and int(p.GetNumber()) % 2) else 0.0
            tx, ty = px + ux * (half + EL + stag), py + uy * (half + EL + stag)    # staggered via sites: at 0.5 mm
            #                                                                    pitch one row of discs is a wall
            tr = pcbnew.PCB_TRACK(b); tr.SetStart(p.GetPosition()); tr.SetEnd(VECTOR2I(FromMM(tx), FromMM(ty)))
            tr.SetWidth(FromMM(WD)); tr.SetLayer(lay)
            vi = pcbnew.PCB_VIA(b); vi.SetPosition(VECTOR2I(FromMM(tx), FromMM(ty))); vi.SetWidth(FromMM(vdia)); vi.SetDrill(FromMM(vdrill))
            code = p.GetNetCode()
            mark3(LAYERS.index(ln), item_poly(tr, lay), clr_of(code) + WD / 2, code, False, True, False)
            for li in range(NL):
                mark3(li, item_poly(vi, pcbnew.F_Cu), clr_of(code) + WD / 2, code, False, True, False)
            markv(item_poly(vi, pcbnew.F_Cu), clr_of(code) + vdia / 2, code, True, False)
            nres += 1
    print(f"escapes reserved: {nres} pins", file=sys.stderr)
conns = []
for c, r in zip(m.conns, m.routes):
    if only and c["net"] not in only:
        continue
    code = net_code.get(c["net"], 0)
    cl = dict(m.netclass(m.net_full.get(c["net"], c["net"])))
    wi = max(cl["track_width"], INNER_W.get(cl.get("name"), 0))   # thinner inner copper: a wider inner minimum
    ea, eb_ = end_cells(c["ends"][0], code), end_cells(c["ends"][1], code)
    if RT.get("join_any_copper") and c["net"] in RT["join_any_copper"]:
        ia = island_cells(code, ea)                                  # start anywhere on one island, end anywhere
        ib = island_cells(code, eb_) - ia                            # on the other
        if ib:
            ea, eb_ = ea | ia, eb_ | ib
    tiles = {(tx, ty) for _, tx, ty in r} if r else set()
    conns.append({"net": c["net"], "code": code, "a": ea, "b": eb_, "tiles": tiles, "w": cl["track_width"], "wi": wi, "cls": cl.get("name"),
                  "clr": max(CLR, cl["clearance"]), "desc": (c["ends"][0]["desc"][:40], c["ends"][1]["desc"][:40]),
                  "xy": [(e["x"], e["y"]) for e in c["ends"]]})
K = int(round(m.T / C))

# ---- claims by routes: cell -> {net: count}
claim = [collections.defaultdict(collections.Counter) for _ in range(NL)]
hist = [collections.defaultdict(float) for _ in range(NL)]


def disc(rad):
    R = int(math.ceil(rad / C - 1e-9))
    return [(di, dj) for di in range(-R, R + 1) for dj in range(-R, R + 1) if math.hypot(di, dj) * C < rad - 1e-9]


def foot(c):
    """Offsets another default-width centreline must keep from this route's centreline, and its via disc."""
    if "foot" not in c:
        c["foot"] = disc(c["w"] / 2 + c["clr"] + WD / 2)
        c["vfoot"] = disc(vdia / 2 + c["clr"] + WD / 2)
    return c["foot"], c["vfoot"]


def apply(c, path, sign):
    """Claim the cells around the centreline; cells inside the route's own end pads are covered by the pad, which the
    fixed map already keeps clear of other nets, so they claim nothing (else neighbouring pins block each other)."""
    f, vf = foot(c)
    code, ends = c["code"], c["a"] | c["b"]
    for k, (li, i, j) in enumerate(path):
        if (li, i, j) in ends and not (k and path[k - 1][0] != li):
            continue
        offs = f
        if k and path[k - 1][0] != li:
            offs = vf
            for l2 in range(NL):                                  # through via: every layer
                for di, dj in vf:
                    cnt = claim[l2][(i + di, j + dj)]
                    cnt[code] += sign
                    if cnt[code] <= 0:
                        del cnt[code]
            continue
        for di, dj in offs:
            cnt = claim[li][(i + di, j + dj)]
            cnt[code] += sign
            if cnt[code] <= 0:
                del cnt[code]


SQ2 = math.sqrt(2)
DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]


def others(li, i, j, code):
    cnt = claim[li].get((i, j))
    if not cnt:
        return 0
    return sum(v for n, v in cnt.items() if n != code)


VCHECK = None


def via_ok(i, j, code, O):
    if not vin[j][i] or VOWN[key_for(code)][j][i] not in (FREE, code):
        return False
    return all(O[l][j][i] in (FREE, code) for l in range(NL))


def via_others(i, j, code):
    """Other nets' claims anywhere under the via pad: a via is wider than the track a claim was sized for."""
    global VCHECK
    if VCHECK is None:
        VCHECK = disc(vdia / 2 - WD / 2 + C * 0.5)
    return sum(others(l, i + di, j + dj, code) for l in range(NL) for di, dj in VCHECK)


LPREF = [(g, l) for g, l in RT.get("layer_pref", {}).items()]
MAX_POPS = RT.get("max_pops", 2000000)
OFF = RT.get("off_layer_cost", 3.0)


def layer_mult(net):
    for g, l in LPREF:
        if fnmatch.fnmatchcase(net, g) and l in LAYERS:
            return [1.0 if LAYERS[li] == l else OFF for li in range(NL)]
    return [1.0] * NL


def wl(c, li):
    return c["w"] if LAYERS[li] in ("F", "B") else c.get("wi", c["w"])


def omap(c):
    """Per-layer obstacle maps at the route's width on that layer (inner layers may need more)."""
    band = c.get("cls") in NECK_BAND_CLASSES
    wo, wi = map_for(c["code"], c["w"], band), map_for(c["code"], c.get("wi", c["w"]), band)
    return [wo[li] if LAYERS[li] in ("F", "B") else wi[li] for li in range(NL)]


def route(c, pf, grow):
    code = c["code"]
    if "lm" not in c:
        c["lm"] = layer_mult(c["net"])
    lm = c["lm"]
    O = omap(c)
    if not c["a"] or not c["b"]:
        return None
    if grow is None:
        allowed = None
    else:
        tiles = set()
        for tx, ty in c["tiles"] or {(i // K, j // K) for _, i, j in c["a"] | c["b"]}:
            for dx in range(-grow, grow + 1):
                for dy in range(-grow, grow + 1):
                    tiles.add((tx + dx, ty + dy))
        for _, i, j in c["a"] | c["b"]:
            tiles.add((i // K, j // K))
        allowed = tiles
    goal = c["b"]
    c_ends = c["a"] | c["b"]
    gx = sum(i for _, i, _ in goal) / len(goal); gy = sum(j for _, _, j in goal) / len(goal)
    h = lambda i, j: math.hypot(i - gx, j - gy) * C * 0.98
    best, prev, q = {}, {}, []
    for n in c["a"]:
        best[n] = 0.0; heapq.heappush(q, (h(n[1], n[2]), 0.0, n, -1))
    vc = a.via_cost
    pops = 0
    while q:
        f, g, n, d0 = heapq.heappop(q)
        if g > best.get(n, 1e18):
            continue
        if n in goal:
            path = [n]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            return path[::-1]
        pops += 1
        if pops > MAX_POPS:                                        # search budget: "no path" can mean this ran out
            return None
        li, i, j = n
        hl = hist[li]
        for di, (dx, dy, L) in enumerate(DIRS):
            x, y = i + dx, j + dy
            if not (0 <= x < NX and 0 <= y < NY) or not inside[y][x] or O[li][y][x] not in (FREE, code):
                continue
            if allowed is not None and (x // K, y // K) not in allowed:
                continue
            if dx and dy and O[li][j][x] not in (FREE, code) and O[li][y][i] not in (FREE, code) and \
                    not (O[li][y][x] == code and O[li][j][i] == code):
                continue        # a diagonal step needs one open side (cutting a corner), except along the net's own
                #                 copper (a 45-degree track of its own is already there)
            o = 0 if (li, x, y) in c_ends else others_c(c, li, x, y)
            cost = L * C * lm[li] * (1 + hl.get((x, y), 0.0)) * (1 + pf * o) + (0.02 if d0 >= 0 and di != d0 else 0)
            m_ = (li, x, y); ng = g + cost
            if ng < best.get(m_, 1e18):
                best[m_] = ng; prev[m_] = n; heapq.heappush(q, (ng + h(x, y), ng, m_, di))
        if via_ok(i, j, code, O):
            o = via_others(i, j, code)
            for l2 in range(NL):
                if l2 == li:
                    continue
                m_ = (l2, i, j); ng = g + vc * (1 + pf * o)
                if ng < best.get(m_, 1e18):
                    best[m_] = ng; prev[m_] = n; heapq.heappush(q, (ng + h(i, j), ng, m_, -1))
    return None


def others_c(c, li, i, j):
    """Other nets' claims a route of c's width would touch at this centreline cell (claims assume default width)."""
    if c["w"] <= WD + 1e-9 or necked(c, i, j):
        return others(li, i, j, c["code"])
    if "woff" not in c:
        c["woff"] = wide_offs(c["w"])
    return sum(others(li, i + di, j + dj, c["code"]) for di, dj in c["woff"])


def conflicts(c, path):
    code, ends = c["code"], c["a"] | c["b"]
    out = [(li, i, j) for li, i, j in path if (li, i, j) not in ends and others_c(c, li, i, j)]
    for k in range(1, len(path)):
        if path[k][0] != path[k - 1][0] and via_others(path[k][1], path[k][2], code):
            out.append(path[k])
    return out


ap_ = cfg.get("router", {}).get("access_cells", 1500)


def reach(c, ends, cap_n):
    """Cells reachable from `ends` over fixed copper only (no claims), up to cap_n, at the route's width."""
    O = omap(c)
    seen, q = set(ends), list(ends)
    while q and len(seen) < cap_n:
        li, i, j = q.pop()
        for dx, dy, _ in DIRS:
            x, y = i + dx, j + dy
            if 0 <= x < NX and 0 <= y < NY and inside[y][x] and O[li][y][x] in (FREE, c["code"]) and (li, x, y) not in seen:
                if dx and dy and O[li][j][x] not in (FREE, c["code"]) and O[li][y][i] not in (FREE, c["code"]) and \
                        not (O[li][y][x] == c["code"] and O[li][j][i] == c["code"]):
                    continue
                seen.add((li, x, y)); q.append((li, x, y))
        if via_ok(i, j, c["code"], O):
            for l2 in range(NL):
                if (l2, i, j) not in seen:
                    seen.add((l2, i, j)); q.append((l2, i, j))
    return seen


# ---- pin-access gate: an end walled in by fixed copper is a placement problem, named before any routing
trapped = []
trapped_xy = []
for c in conns:
    for k, (side, desc) in enumerate((("a", c["desc"][0]), ("b", c["desc"][1]))):
        if not c[side]:
            trapped.append((c["net"], desc, "no legal cell on the pad")); trapped_xy.append((c["net"], *c["xy"][k])); continue
        r_ = reach(c, c[side], ap_)
        other = c["b" if side == "a" else "a"]
        if len(r_) < ap_ and not (r_ & other):
            trapped.append((c["net"], desc, f"walled in: {len(r_)} cells reachable")); trapped_xy.append((c["net"], *c["xy"][k]))
if a.trapped_json:
    json.dump([{"net": n, "x": x, "y": y} for n, x, y in trapped_xy], open(a.trapped_json, "w"))
if a.gate_only:
    print(f"pin access: {len(trapped)} trapped")
    for n, d, why in trapped:
        print(f"  {n:10} {d}: {why}")
    m.close()
    sys.exit(2 if trapped else 0)
if trapped:
    print(f"pin access: {len(trapped)} connection ends cannot get out (fix the placement around them):")
    for n, d, why in trapped:
        print(f"  {n:10} {d}: {why}")
    if not cfg.get("router", {}).get("route_anyway"):
        m.close()
        sys.exit(2)


routes = [None] * len(conns)
pf, curve = 0.5, []
order = sorted(range(len(conns)), key=lambda k: len(conns[k]["tiles"]))
for it in range(a.iters):
    todo = [k for k in order if routes[k] is None or conflicts(conns[k], routes[k])]
    if not todo:
        break
    for k in todo:
        c = conns[k]
        if routes[k]:
            apply(c, routes[k], -1)
        r = None
        levels = (a.corridor, 3 * a.corridor, 6 * a.corridor, None)
        for grow in levels[min(c.get("level", 0), len(levels) - 1):]:   # a connection stuck in conflict gets room
            r = route(c, pf, grow)
            if r:
                break
        routes[k] = r
        if r:
            apply(c, r, +1)
    bad = [k for k in range(len(conns)) if routes[k] and conflicts(conns[k], routes[k])]
    for k in range(len(conns)):
        c = conns[k]
        c["stuck"] = c.get("stuck", 0) + 1 if k in bad else 0
        if c["stuck"] and c["stuck"] % 3 == 0:
            c["level"] = c.get("level", 0) + 1
    if a.debug and bad:
        where = collections.Counter(); pairs = collections.Counter()
        end_of = {}
        for k2, c2 in enumerate(conns):
            for cell in c2["a"] | c2["b"]:
                end_of.setdefault(cell[1:], set()).add(c2["code"])
        for k in bad:
            c = conns[k]
            for li, i, j in conflicts(c, routes[k]):
                near_own = any((i + di, j + dj) in {x[1:] for x in c["a"] | c["b"]} for di in (-3, 0, 3) for dj in (-3, 0, 3))
                oth = {n for n in claim[li].get((i, j), {}) if n != c["code"]}
                near_other_end = any(n in end_of.get((i + di, j + dj), ()) for n in oth for di in range(-3, 4) for dj in range(-3, 4))
                where["near own end" if near_own else "near other's end" if near_other_end else "open"] += 1
                for n in oth:
                    pairs[tuple(sorted((c["net"], short(b.FindNet(n).GetNetname()))))] += 1
        print(f"  conflict cells: {dict(where)}; top pairs {pairs.most_common(8)}", file=sys.stderr)
    if a.debug:
        for k in bad[:4]:
            c = conns[k]; cf = conflicts(c, routes[k])
            li, i, j = cf[0]
            print(f"  debug {c['net']}: {len(cf)} cells, first {LAYERS[li]} {G.xy(i, j)}, claimed by "
                  f"{dict(claim[li].get((i, j), {}))}, own code {c['code']}, path len {len(routes[k])}", file=sys.stderr)
    for k in bad:
        for li, i, j in conflicts(conns[k], routes[k]):
            hist[li][(i, j)] += 0.3
    unr = sum(r is None for r in routes)
    curve.append((len(bad), unr))
    print(f"iteration {it + 1}: {len(todo)} rerouted, {len(bad)} in conflict, {unr} without a path ({time.time() - t0:.0f} s)", file=sys.stderr, flush=True)
    if a.time_budget and time.time() - t0 > a.time_budget:
        print(f"time budget {a.time_budget} s reached: writing the best so far", file=sys.stderr, flush=True)
        break
    if not bad and it:
        break
    pf *= 1.5

# ---- write tracks and vias
def to_xy(i, j):
    return G.xy(i, j)


def chamfer(pts, clear=lambda x, y: True):
    """Cut every corner of 90 degrees or sharper with a short 45-degree segment, where `clear` says the inside of
    the corner has no other net within reach (the cut moves the track toward the inside of the bend)."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = out[-1], pts[k], pts[k + 1]
        ux, uy = x1 - x0, y1 - y0; vx, vy = x2 - x1, y2 - y1
        lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
        if lu < 1e-9 or lv < 1e-9:
            continue
        cosang = (ux * vx + uy * vy) / (lu * lv)
        if cosang <= 1e-6 and clear(x1 + (vx / lv - ux / lu) * C, y1 + (vy / lv - uy / lu) * C):
            d = min(C, lu / 2, lv / 2)
            out.append((x1 - ux / lu * d, y1 - uy / lu * d)); out.append((x1 + vx / lv * d, y1 + vy / lv * d))
        else:
            out.append((x1, y1))
    out.append(pts[-1])
    return out


ntr = nvia = 0
for c, r in zip(conns, routes):
    if not r:
        continue
    runs, cur = [], [r[0]]
    for n in r[1:]:
        if n[0] != cur[-1][0]:
            runs.append(cur); cur = [n]
        else:
            cur.append(n)
    runs.append(cur)
    pieces = []                                                    # (layer run index, cells, width): neck-downs
    for k, run in enumerate(runs):
        sub = [run[0]]
        for n in run[1:]:
            if necked(c, n[1], n[2]) != necked(c, sub[-1][1], sub[-1][2]):
                pieces.append((k, sub + [n], WD if necked(c, sub[-1][1], sub[-1][2]) else wl(c, run[0][0]))); sub = [n]
            else:
                sub.append(n)
        pieces.append((k, sub, WD if necked(c, sub[-1][1], sub[-1][2]) else wl(c, run[0][0])))
    for k, run, wpiece in pieces:
        li = run[0][0]
        pts = [to_xy(i, j) for _, i, j in run]
        simp = [pts[0]]
        for idx in range(1, len(pts)):                             # merge collinear steps
            if idx < len(pts) - 1:
                (x0, y0), (x1, y1), (x2, y2) = simp[-1], pts[idx], pts[idx + 1]
                if abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) < 1e-9:
                    continue
            simp.append(pts[idx])
        def clear(x, y, li=li, c=c):
            i, j = int((x - G.x0) / C), int((y - G.y0) / C)
            O = omap(c)                                           # nor fixed copper (the cut leaves the cells)
            return not any(others(li, i + di, j + dj, c["code"]) or O[li][j + dj][i + di] not in (FREE, c["code"])
                           for di in (-2, -1, 0, 1, 2) for dj in (-2, -1, 0, 1, 2)
                           if 0 <= i + di < NX and 0 <= j + dj < NY)
        simp = chamfer(simp, clear)
        for (x1, y1), (x2, y2) in zip(simp, simp[1:]):
            if math.hypot(x2 - x1, y2 - y1) < 1e-6:
                continue
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1))); t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
            t.SetWidth(FromMM(wpiece)); t.SetLayer(CU[LAYERS[li]]); t.SetNetCode(c["code"])
            b.Add(t); ntr += 1
        if k < len(runs) - 1 and run[-1] == runs[k][-1]:
            x, y = to_xy(run[-1][1], run[-1][2])
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(VECTOR2I(FromMM(x), FromMM(y))); v.SetDrill(FromMM(vdrill)); v.SetWidth(FromMM(vdia))
            v.SetNetCode(c["code"]); b.Add(v); nvia += 1
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
b.Save(a.out)
src = a.board[:-len(".kicad_pcb")]
for ext in (".kicad_pro", ".kicad_dru", ".layout.json"):
    if os.path.exists(src + ext):
        shutil.copy(src + ext, a.out[:-len(".kicad_pcb")] + ext)
unrouted = [c for c, r in zip(conns, routes) if not r]
in_conflict = [c for c, r in zip(conns, routes) if r and conflicts(c, r)]
print(f"detailed: {len(conns) - len(unrouted)} of {len(conns)} connections routed, {len(in_conflict)} still sharing cells; "
      f"{ntr} track segments, {nvia} vias; {time.time() - t0:.0f} s")
for c in unrouted:
    print(f"  no path: {c['net']}  {c['desc'][0]} -> {c['desc'][1]}")
    if a.debug:
        O = map_for(c["code"])
        seen, q = set(c["a"]), list(c["a"])
        while q and len(seen) < 200000:                            # flood fill from end a, ignoring claims
            li, i, j = q.pop()
            for dx, dy, _ in DIRS:
                x, y = i + dx, j + dy
                if 0 <= x < NX and 0 <= y < NY and inside[y][x] and O[li][y][x] in (FREE, c["code"]) and (li, x, y) not in seen:
                    seen.add((li, x, y)); q.append((li, x, y))
            if via_ok(i, j, c["code"], O):
                for l2 in range(NL):
                    if (l2, i, j) not in seen:
                        seen.add((l2, i, j)); q.append((l2, i, j))
        if os.environ.get("DR_CROP") and c is unrouted[0]:
            from raster import write_png
            E = c[os.environ.get("DR_CROP_END", "a")]
            li0 = next(iter(E))[0]
            ci = sum(i for _, i, _ in E) // len(E); cj = sum(j for _, _, j in E) // len(E)
            seen = reach(c, E, 20000)
            Rr, Sx = int(os.environ.get("DR_CROP_R", 40)), int(os.environ.get("DR_CROP_S", 8))
            rows = []
            for j in range(cj - Rr, cj + Rr):
                row = []
                for i in range(ci - Rr, ci + Rr):
                    v = O[li0][j][i] if 0 <= i < NX and 0 <= j < NY else MULTI
                    px = (255, 255, 255) if v == FREE else (60, 60, 60) if v == MULTI else (120, 200, 120) if v == c["code"] else (200, 170, 120)
                    if (li0, i, j) in seen:
                        px = (120, 160, 255)
                    if (li0, i, j) in E:
                        px = (255, 0, 0)
                    row += [px] * Sx
                rows += [row] * Sx
            write_png(os.environ["DR_CROP"], rows)
            cnt = collections.Counter(O[li0][j][i] for j in range(cj - Rr, cj + Rr) for i in range(ci - Rr, ci + Rr) if 0 <= i < NX and 0 <= j < NY)
            print("    owners in crop:", [(b.FindNet(k).GetNetname() if k > 0 else k, n) for k, n in cnt.most_common(8)], file=sys.stderr)
            zs = [(z.GetZoneName(), short(z.GetNetname()), [NAME.get(l) for l in z.GetLayerSet().CuStack()]) for z in b.Zones() if not z.GetIsRuleArea()]
            print("    zones:", zs, "drop:", sorted(m.drop), file=sys.stderr)
        print(f"    ends: a {len(c['a'])} cells, b {len(c['b'])} cells; flood from a reaches {len(seen)} cells, "
              f"b reachable: {bool(seen & c['b'])}; key {key_for(c['code'])}", file=sys.stderr)
for c in in_conflict:
    print(f"  conflict: {c['net']}  {c['desc'][0]} -> {c['desc'][1]}")
rep = drc(a.out, a.out[:-len(".kicad_pcb")] + "_drc.json", refill=True, save=True, parity=False)
print(drc_summary(rep))
if a.png:
    from raster import write_png
    S = 3
    col = {}
    rows = []
    for j in range(NY):
        for _ in range(S):
            row = []
            for i in range(NX):
                px = (255, 255, 255) if inside[j][i] else (40, 40, 40)
                for li in range(NL):
                    if own[li][j][i] not in (FREE,):
                        px = (215, 215, 215)
                row += [px] * S
            rows.append(row)
    shade = [(220, 60, 60), (200, 160, 40), (60, 90, 220)]
    for c, r in zip(conns, routes):
        for li, i, j in r or []:
            for dy in range(S):
                for dx in range(S):
                    rows[j * S + dy][i * S + dx] = shade[li % 3]
    write_png(a.png, rows)
m.close()
bad_drc = [v for v in rep["violations"] if v["type"] in ("clearance", "shorting_items", "hole_clearance")]
sys.exit(0 if not rep["unconnected_items"] and not bad_drc else 1)
