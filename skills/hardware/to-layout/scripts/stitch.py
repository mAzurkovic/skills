"""Stitch the fragments of a net's pours together: every filled fragment (per layer) that has no via or plated hole
of the net gets one, at a legal point where the net's fill exists on at least one other layer too.

    stitch.py BOARD [--net GND] [--step 0.25] [--out OUT.kicad_pcb]

Dense routing cuts pours and planes into pieces; a piece that holds a pad but no via leaves that pad, or the piece,
unconnected. A via site is legal when it is clear of every other-net pad, track, via and hole (netclass clearance
+ 5 um; 0.6 mm to exposed pads of high-voltage nets outside Q* / U* parts) and 0.5 mm inside the board edge. Vias are
sizing.vias.signal, locked. Prints each fragment it could not stitch."""
import argparse, fnmatch, json, math, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I
from klib import KICAD_CLI, load_config, short
from raster import CU, stack

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--net", default="GND"); ap.add_argument("--step", type=float, default=0.25)
ap.add_argument("--out")
a = ap.parse_args()
out = a.out or a.board
if out != a.board:
    for e in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".layout.json"):
        if os.path.exists(a.board[:-len(".kicad_pcb")] + e):
            shutil.copy(a.board[:-len(".kicad_pcb")] + e, out[:-len(".kicad_pcb")] + e)
cfg = load_config(a.board)
drill, dia = cfg.get("sizing", {}).get("vias", {}).get("signal", [0.2, 0.45])
HV = set(cfg.get("freerouting", {}).get("hv_classes", ["HV", "HV_SIG", "GATE_HS"]))
EXEMPT = cfg.get("sizing", {}).get("pad_exempt_courtyards", ["Q*", "U*"])
pro = json.load(open(a.board[:-len(".kicad_pcb")] + ".kicad_pro"))["net_settings"]
classes = {c["name"]: c for c in pro["classes"]}


def netclass(n):
    for p in pro.get("netclass_patterns", []):
        if fnmatch.fnmatchcase(n, p["pattern"]) or fnmatch.fnmatchcase("/" + short(n), p["pattern"]):
            return classes.get(p["netclass"], classes["Default"])
    return classes["Default"]


env = dict(os.environ, FONTCONFIG_FILE="/dev/null")
subprocess.run([KICAD_CLI, "pcb", "drc", "--refill-zones", "--save-board", "-o", "/dev/null", out], env=env,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
b = pcbnew.LoadBoard(out)
code = b.FindNet(a.net).GetNetCode()
layers = [CU[n] for n in stack(b)]
frags = []                                          # (layer, SHAPE_POLY_SET of one outline)
for z in b.Zones():
    if z.GetIsRuleArea() or z.GetNetCode() != code:
        continue
    for l in layers:
        if not z.IsOnLayer(l):
            continue
        f = z.GetFilledPolysList(l)
        for k in range(f.OutlineCount()):
            one = pcbnew.SHAPE_POLY_SET(); one.AddOutline(f.Outline(k))
            for h in range(f.HoleCount(k)):
                one.AddHole(f.Hole(k, h))
            frags.append((l, one))
own = [(t.GetPosition()) for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T and t.GetNetCode() == code] + \
      [p.GetPosition() for p in b.GetPads() if p.GetNetCode() == code and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
others = [p for p in b.GetPads() if p.GetNetCode() != code] + [t for t in b.GetTracks() if t.GetNetCode() != code]
ties = [g for f in b.GetFootprints() for g in f.GraphicalItems() if g.GetLayer() in layers]   # net-tie copper (no net)
holes = [p for p in b.GetPads() if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)] + \
        [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
bb = b.GetBoardEdgesBoundingBox()
X0, Y0, X1, Y1 = ToMM(bb.GetLeft()) + 0.5, ToMM(bb.GetTop()) + 0.5, ToMM(bb.GetRight()) - 0.5, ToMM(bb.GetBottom()) - 0.5
D = classes["Default"]


def hv(it):
    return netclass(it.GetNetname()).get("name") in HV


def legal(x, y):
    r = dia / 2
    if not (X0 + r < x < X1 - r and Y0 + r < y < Y1 - r):
        return False
    pt = VECTOR2I(FromMM(x), FromMM(y))
    for it in holes:
        if math.hypot(ToMM(it.GetPosition().x) - x, ToMM(it.GetPosition().y) - y) < r + 0.25 + 0.2 + 0.005:
            return False
    for g in ties:                                  # a via hole keeps 0.2 mm from copper of any net, ties included
        if g.GetEffectiveShape(g.GetLayer()).Collide(pt, FromMM(r + max(D["clearance"], 0.2) + 0.005)):
            return False
    for it in others:
        q = it.GetPosition()
        if abs(ToMM(q.x) - x) > 3 or abs(ToMM(q.y) - y) > 3:
            if not (isinstance(it, pcbnew.PCB_TRACK) and it.Type() != pcbnew.PCB_VIA_T):
                continue
        c = max(D["clearance"], netclass(it.GetNetname())["clearance"]) + 0.005
        if isinstance(it, pcbnew.PAD) and hv(it) and not any(fnmatch.fnmatchcase(it.GetParentFootprint().GetReference(), g) for g in EXEMPT):
            c = max(c, 0.605)
        for l in layers:
            if it.IsOnLayer(l) and it.GetEffectiveShape(l).Collide(pt, FromMM(r + c)):
                return False
    return True


added, left = 0, []
for l, fr in frags:
    if any(fr.Contains(p) for p in own):
        continue
    bbx = fr.BBox()
    done = False
    xs = [ToMM(bbx.GetLeft()) + a.step * k for k in range(int(ToMM(bbx.GetWidth()) / a.step) + 1)]
    ys = [ToMM(bbx.GetTop()) + a.step * k for k in range(int(ToMM(bbx.GetHeight()) / a.step) + 1)]
    for y in ys:
        for x in xs:
            pt = VECTOR2I(FromMM(x), FromMM(y))
            if not fr.Contains(pt):
                continue
            if not any(l2 != l and f2.Contains(pt) for l2, f2 in frags):
                continue                                # a via must reach the net on another layer
            if not legal(x, y):
                continue
            v = pcbnew.PCB_VIA(b); v.SetPosition(pt); v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
            v.SetNetCode(code); v.SetLocked(True); b.Add(v)
            own.append(pt); holes.append(v); added += 1; done = True
            break
        if done:
            break
    if not done:
        left.append((b.GetLayerName(l), round(ToMM(bbx.Centre().x), 2), round(ToMM(bbx.Centre().y), 2),
                     round(ToMM(bbx.GetWidth()) * ToMM(bbx.GetHeight()), 2)))
b.Save(out)
print(f"{a.net}: {len(frags)} fill fragments, {added} stitching vias added, {len(left)} could not be stitched")
for ln, x, y, area in left:
    print(f"  no site: {ln} fragment at ({x}, {y}), box {area} mm2")
