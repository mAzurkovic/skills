"""Connect every pad of a plane net to its plane with a via and a short stub, deterministically. Plane nets are never
handed to an autorouter.

    plane_fanout.py BOARD [--out OUT.kicad_pcb] [--reach 1.6] [--dry] [--demand G4.json] [--refan GLOBS]

Config "planes": [{"net": "GND", "layer": "In1", "own_via": ["C*"]}, {"net": "+3V3", "layer": "In2"}, ...]: the
plane is every filled zone of that net on that layer. Pads of parts matching own_via (decoupling caps: pin -> cap ->
via) need a via of their own; parts matching via_in_pad may take a filled, capped via at the pad centre within --reach of the pad edge; reaching the plane through a pour does not count. Via size: sizing.vias.signal (default 0.2 / 0.45 mm); stub width: the net's netclass
width from the .kicad_pro; clearance: the larger netclass clearance of the two nets (outer; 0.6 mm to an exposed pad when one net is a
high-voltage class and the other is not, outside Q* / U* parts, as the rules file), inner clearance from
the rules (sizing.py) on the plane layer.

A pad is served when its copper cluster (KiCad connectivity, after a refill) already reaches a plane zone. For the
others, in reference / pad order: candidate via sites on rings around the pad (0.05 mm steps out to --reach mm
beyond the pad edge, nearest first). A site is taken when the via is inside the plane fill by its radius plus the
clearance, clear of every other-net pad, track, via and hole on every layer, outside via keep-outs and the board
edge margin, and the stub from the pad centre clears every other-net item on the pad's layer. One via serves the
pad's whole cluster. Exit 1 when a pad has no site: the report names the pad and what blocked it, which is a
placement problem (move the part or its neighbour).

--demand G4.json (global_route.py --json): among the first 20 legal sites, take the one with the lowest
distance + 0.3 mm x routes through its tile, so plane vias stay out of the channels the signals need.
--refan "C*,R*": first remove the existing plane-net vias and stubs of those parts' pads (a via of the pad's net
within --reach of the pad, joined to it by one track), skipping parts with a pad on place_opt.fixed_nets (the power
stage keeps its vias), then place them again."""
import argparse, fnmatch, json, math, os, re, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I
from klib import drc, load_config, short, strip_fanouts
from raster import CU, item_poly, stack

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--out"); ap.add_argument("--reach", type=float, default=1.6)
ap.add_argument("--dry", action="store_true")
ap.add_argument("--demand"); ap.add_argument("--refan"); ap.add_argument("--weight", type=float, default=0.3)
a = ap.parse_args()
out = a.out or a.board
cfg = load_config(a.board)
base = a.board[:-len(".kicad_pcb")]
pro = json.load(open(base + ".kicad_pro"))
classes = {c["name"]: c for c in pro["net_settings"]["classes"]}
patterns = pro["net_settings"].get("netclass_patterns", [])
drill, dia = cfg.get("sizing", {}).get("vias", {}).get("signal", [0.2, 0.45])
edge_margin = 0.5


def netclass(n):
    import fnmatch
    for p in patterns:
        if fnmatch.fnmatchcase(n, p["pattern"]) or fnmatch.fnmatchcase("/" + short(n), p["pattern"]):
            return classes[p["netclass"]]
    return classes["Default"]


def inner_clear():
    d = open(base + ".kicad_dru").read() if os.path.exists(base + ".kicad_dru") else ""
    m = re.search(r'\(rule "sizing: inner clearance".*?\(min ([\d.]+)mm\)', d, re.S)
    return float(m.group(1)) if m else 0.15


# refill a working copy so fills and connectivity are current
tmp = tempfile.mkdtemp()
for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru"):
    if os.path.exists(base + ext):
        shutil.copy(base + ext, os.path.join(tmp, "b" + ext))
work = os.path.join(tmp, "b.kicad_pcb")
removed = 0
if a.refan:
    removed = strip_fanouts(work, [g.strip() for g in a.refan.split(",")], cfg, a.reach)
drc(work, os.path.join(tmp, "d.json"), refill=True, save=True, parity=False)
b = pcbnew.LoadBoard(work)
b.BuildConnectivity()
conn = b.GetConnectivity()
outline = b.GetBoardEdgesBoundingBox()
X0, Y0, X1, Y1 = ToMM(outline.GetLeft()), ToMM(outline.GetTop()), ToMM(outline.GetRight()), ToMM(outline.GetBottom())
CLR_IN = inner_clear()
cu_layers = [CU[l] for l in stack(b)]

via_keepouts = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
others = []                                  # (item, net code, layers, bbox mm) for every copper item
for p in b.GetPads():
    bb = p.GetBoundingBox()
    others.append((p, p.GetNetCode(), [l for l in cu_layers if p.IsOnLayer(l)],
                   (ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom()))))
for t in b.GetTracks():
    bb = t.GetBoundingBox()
    ls = cu_layers if t.Type() == pcbnew.PCB_VIA_T else [t.GetLayer()]
    others.append((t, t.GetNetCode(), ls, (ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom()))))


HV_CLASSES = set(cfg.get("freerouting", {}).get("hv_classes", ["HV", "HV_SIG", "GATE_HS"]))
HV_PAD = cfg.get("router", {}).get("hv_pad_clear", 0.6) + 0.005
EXEMPT = cfg.get("sizing", {}).get("pad_exempt_courtyards", ["Q*", "U*"])
_hv = {}


def is_hv(code):
    if code not in _hv:
        nm = next((str(n) for n, ni in b.GetNetsByName().items() if ni.GetNetCode() == code), "")
        _hv[code] = netclass(nm).get("name", "Default") in HV_CLASSES if nm else False
    return _hv[code]


def pad_clear(it, code, c):
    """Outer clearance to an exposed pad: 0.6 mm between high-voltage and other nets outside Q* / U* parts."""
    if isinstance(it, pcbnew.PAD) and is_hv(it.GetNetCode()) != is_hv(code) and \
            not any(fnmatch.fnmatchcase(it.GetParentFootprint().GetReference(), g) for g in EXEMPT):
        return max(c, HV_PAD)
    return c


def blocked(x, y, code, clr_out):
    """Why a via of net `code` at (x, y) is not allowed, or None."""
    r = dia / 2
    if x - r < X0 + edge_margin or x + r > X1 - edge_margin or y - r < Y0 + edge_margin or y + r > Y1 - edge_margin:
        return "board edge"
    pt = VECTOR2I(FromMM(x), FromMM(y))
    for z in via_keepouts:
        if z.GetLayerSet().CuStack() and z.Outline().Collide(pt, FromMM(r)):
            return f"via keep-out {z.GetZoneName()}"
    for it, nc, ls, bb in others:
        hole = isinstance(it, pcbnew.PAD) and it.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
        if nc == code and not hole:
            continue
        m = r + max(clr_out, HV_PAD, 0.25 if hole else 0)
        if x < bb[0] - m or x > bb[2] + m or y < bb[1] - m or y > bb[3] + m:
            continue
        for l in ls:
            c = pad_clear(it, code, clr_out) if l in (pcbnew.F_Cu, pcbnew.B_Cu) else CLR_IN
            if nc == code:
                c = 0.25                                   # hole to hole / via to plated hole
            shape = it.GetEffectivePolygon(l, pcbnew.ERROR_INSIDE) if isinstance(it, pcbnew.PAD) else item_poly(it, l)
            if shape.Collide(pt, FromMM(r + c + 0.005)):                # + rounding margin, as droute
                ref = it.GetParentFootprint().GetReference() + "." + it.GetNumber() if isinstance(it, pcbnew.PAD) else "track/via"
                return f"{short(it.GetNetname())} {ref}"
    return None                                           # other-net pours re-pour around the new via


def stub_blocked(pad, x, y, width, clr_out):
    lay = pcbnew.F_Cu if pad.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
    s = pcbnew.SEG(pad.GetPosition(), VECTOR2I(FromMM(x), FromMM(y)))
    for it, nc, ls, bb in others:
        if nc == pad.GetNetCode() or lay not in ls:
            continue
        shape = it.GetEffectivePolygon(lay, pcbnew.ERROR_INSIDE) if isinstance(it, pcbnew.PAD) else item_poly(it, lay)
        if shape.Collide(s, FromMM(width / 2 + pad_clear(it, pad.GetNetCode(), clr_out) + 0.005)):
            return True
    return False


planes = cfg.get("planes", [{"net": "GND", "layer": "In1"}])
dem = {}
if a.demand:
    G = json.load(open(a.demand))
    dem = {(tx, ty): n for tx, ty, n in G.get("demand", [])}
    gT, (gx0, gy0) = G["tile"], G["origin"]


def dem_at(x, y):
    return dem.get((int((x - gx0) / gT), int((y - gy0) / gT)), 0) if dem else 0
added, failed, served = [], [], 0
for P in planes:
    code = next((n.GetNetCode() for nm, n in b.GetNetsByName().items() if short(str(nm)) == short(P["net"])), 0)
    lid = CU[P["layer"]]
    fills = []
    for z in b.Zones():
        if not z.GetIsRuleArea() and z.GetNetCode() == code and z.IsOnLayer(lid):
            f = pcbnew.SHAPE_POLY_SET(z.GetFilledPolysList(lid))
            f.Deflate(FromMM(dia / 2 + CLR_IN), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
            fills.append((z, f))
    if not fills:
        print(f"{P['net']}: no filled zone on {P['layer']}"); failed.append((P["net"], "-", "no plane")); continue
    plane_ids = {id(z) for z, _ in fills}
    nc_ = netclass(next(str(nm) for nm, n in b.GetNetsByName().items() if n.GetNetCode() == code))
    width, clr = nc_["track_width"], nc_["clearance"]
    done = set()
    pads = sorted((p for p in b.GetPads() if p.GetNetCode() == code and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD),
                  key=lambda p: (p.GetParentFootprint().GetReference(), p.GetNumber()))
    for p in pads:
        key = (p.GetParentFootprint().GetReference(), p.GetNumber())
        if key in done:
            continue
        cluster = list(conn.GetConnectedItems(p))
        if any(fnmatch.fnmatchcase(key[0], g) for g in P.get("own_via", [])):
            pbb = p.GetBoundingBox()
            px0, py0, px1, py1 = ToMM(pbb.GetLeft()), ToMM(pbb.GetTop()), ToMM(pbb.GetRight()), ToMM(pbb.GetBottom())
            linked = {i.m_Uuid.AsString() for i in cluster}    # its own via: one joined to this pad, not merely near
            own = any(it.Type() == pcbnew.PCB_VIA_T and it.GetNetCode() == code and it.m_Uuid.AsString() in linked and
                      math.hypot(max(px0 - ToMM(it.GetPosition().x), ToMM(it.GetPosition().x) - px1, 0),
                                 max(py0 - ToMM(it.GetPosition().y), ToMM(it.GetPosition().y) - py1, 0)) <= a.reach + dia / 2
                      for it, nc, ls, bb in others if nc == code)
            if own:
                served += 1; done.add(key); continue
            cluster = [p]                                      # its own via, even if a pour connects it
        reach_plane = any(isinstance(i, pcbnew.ZONE) and id(i) in plane_ids for i in cluster) or \
            any(i.Type() == pcbnew.PCB_VIA_T and any(f.Contains(i.GetPosition()) for _, f in fills) for i in cluster)
        if reach_plane:
            served += 1; done.add(key); continue
        bb = p.GetBoundingBox()
        x0, y0, x1, y1 = ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())
        cx, cy = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)
        pad_poly = p.GetEffectivePolygon(pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu, pcbnew.ERROR_INSIDE)
        cands = []
        step = 0.05
        n = int((max(x1 - x0, y1 - y0) / 2 + a.reach + dia) / step)
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                x, y = round(cx + i * step, 3), round(cy + j * step, 3)
                d = math.hypot(max(x0 - x, x - x1, 0), max(y0 - y, y - y1, 0))
                if d <= a.reach + dia / 2:
                    cands.append((d, math.atan2(y - cy, x - cx), x, y))
        vip = any(fnmatch.fnmatchcase(key[0], g) for g in P.get("via_in_pad", []))
        if vip:                                            # filled + capped via in the pad (fab process, opt-in)
            cands.insert(0, (0.0, 0.0, cx, cy))
        cands.sort()
        why, legal = {}, []
        for d, _, x, y in cands:
            if len(legal) >= (20 if dem else 1):
                break
            pt = VECTOR2I(FromMM(x), FromMM(y))
            if pad_poly.Collide(pt, FromMM(dia / 2 + 0.05)) and not (vip and (x, y) == (cx, cy)):
                continue                                   # no via in pad (unless planes[].via_in_pad lists the part)
            centre = vip and (x, y) == (cx, cy)
            if not any(f.Contains(pt) for _, f in fills):
                why["outside plane"] = why.get("outside plane", 0) + 1
                if centre:
                    why["via in pad: no plane under the pad"] = 1
                continue
            w = blocked(x, y, code, clr)
            if w:
                why[w] = why.get(w, 0) + 1
                if centre:
                    why[f"via in pad: {w}"] = 1
                continue
            if stub_blocked(p, x, y, width, clr):
                why["stub crosses other copper"] = why.get("stub crosses other copper", 0) + 1; continue
            legal.append((d + a.weight * dem_at(x, y), d, x, y, pt))
        if legal:
            _, d, x, y, pt = min(legal)
            if not a.dry:
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(pt); v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia)); v.SetNetCode(code); v.SetLocked(True)
                b.Add(v)
                t = pcbnew.PCB_TRACK(b)
                t.SetStart(p.GetPosition()); t.SetEnd(pt); t.SetWidth(FromMM(width))
                t.SetLayer(pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu); t.SetNetCode(code); t.SetLocked(True)
                b.Add(t)
                vb = (x - dia / 2, y - dia / 2, x + dia / 2, y + dia / 2)
                others.append((v, code, cu_layers, vb))
            added.append((short(P["net"]), f"{key[0]}.{key[1]}", x, y, d))
            if not any(fnmatch.fnmatchcase(key[0], g) for g in P.get("own_via", [])):
                for i in cluster:
                    if isinstance(i, pcbnew.PAD):
                        done.add((i.GetParentFootprint().GetReference(), i.GetNumber()))
            done.add(key)
        else:
            top = sorted(why.items(), key=lambda kv: -kv[1])[:3] + [kv for kv in why.items() if kv[0].startswith("via in pad")]
            failed.append((short(P["net"]), f"{key[0]}.{key[1]}", "; ".join(f"{k} ({v})" for k, v in top)))

print((f"removed for re-fan-out: {removed} vias/stubs; " if a.refan else "") + f"served already: {served} pads; vias added: {len(added)}; no site: {len(failed)}")
for n, pad, x, y, d in added:
    print(f"  + {n:6} {pad:8} via at ({x:.2f}, {y:.2f}), {d:.2f} mm from the pad")
for n, pad, why in failed:
    print(f"  ! {n:6} {pad:8} no site: {why}")
if not a.dry and (added or removed):
    b.Save(out)
    for ext in (".kicad_pro", ".kicad_dru"):
        if os.path.exists(base + ext) and out != a.board:
            shutil.copy(base + ext, out[:-len(".kicad_pcb")] + ext)
    print(f"saved {out}")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if failed else 0)
