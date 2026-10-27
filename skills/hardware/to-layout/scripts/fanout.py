"""Fan out a fine-pitch IC: a short straight stub out of each pin, along the pad, before routing. Neighbouring
stubs are parallel at the pin pitch, so the router starts past the pin field instead of fighting inside it.

    fanout.py BOARD --part U3 --nets GHA,GLA,... [--len 0.6] [--via] [--stagger 0.7] [--out OUT.kicad_pcb]

--via makes each stub a dog-bone: a signal via (sizing.vias.signal) at its tip, odd-numbered pins --stagger mm
further out, so the vias of a 0.5 mm pitch row fit side by side. For pins whose nets leave on another layer.

For every SMD pad of --part on one of --nets (exposed pads skipped): a locked track of the net's netclass width
(the default width inside neck_courtyards, as the rules allow) from the pad centre straight out of the chip edge
to --len mm beyond the pad end. A stub is skipped, and named, when it would come closer than the clearance (+5 um)
to another net's pad or fixed copper; KiCad DRC decides the rest."""
import argparse, json, math, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I
from klib import load_config, short
from raster import CU, stack

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--part", required=True); ap.add_argument("--nets", required=True)
ap.add_argument("--len", type=float, default=0.6); ap.add_argument("--out")
ap.add_argument("--via", action="store_true"); ap.add_argument("--stagger", type=float, default=0.7)
a = ap.parse_args()
out = a.out or a.board
if out != a.board:
    for e in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".layout.json"):
        if os.path.exists(a.board[:-len(".kicad_pcb")] + e):
            shutil.copy(a.board[:-len(".kicad_pcb")] + e, out[:-len(".kicad_pcb")] + e)
pro = json.load(open(a.board[:-len(".kicad_pcb")] + ".kicad_pro"))["net_settings"]
classes = {c["name"]: c for c in pro["classes"]}
import fnmatch


def netclass(n):
    for p in pro.get("netclass_patterns", []):
        if fnmatch.fnmatchcase(n, p["pattern"]) or fnmatch.fnmatchcase("/" + short(n), p["pattern"]):
            return classes.get(p["netclass"], classes["Default"])
    return classes["Default"]


b = pcbnew.LoadBoard(out)
f = b.FindFootprintByReference(a.part)
nets = set(a.nets.split(","))
lay = pcbnew.B_Cu if f.IsFlipped() else pcbnew.F_Cu
fc = f.GetPosition(); t0 = math.radians(f.GetOrientationDegrees())
D = classes["Default"]
made, skipped = 0, []
others = [p for g in b.GetFootprints() for p in g.Pads() if p.IsOnLayer(lay)]
fixed = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T or t.GetLayer() == lay]
all_pads = [p for g in b.GetFootprints() for p in g.Pads()]
all_tracks = list(b.GetTracks())
cfg = load_config(a.board)
CUS = [CU[n] for n in stack(b)]
for p in f.Pads():
    n = short(p.GetNetname())
    if n not in nets or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
        continue
    x, y = ToMM(p.GetPosition().x) - ToMM(fc.x), ToMM(p.GetPosition().y) - ToMM(fc.y)
    lx, ly = x * math.cos(t0) - y * math.sin(t0), x * math.sin(t0) + y * math.cos(t0)
    if max(abs(lx), abs(ly)) < 0.5:
        continue
    nx, ny = ((1 if lx > 0 else -1), 0) if abs(lx) > abs(ly) else (0, (1 if ly > 0 else -1))
    ux, uy = nx * math.cos(t0) + ny * math.sin(t0), -nx * math.sin(t0) + ny * math.cos(t0)
    sz = p.GetSize(); half = max(ToMM(sz.x), ToMM(sz.y)) / 2
    px, py = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)
    L = a.len + (a.stagger if a.via and p.GetNumber().isdigit() and int(p.GetNumber()) % 2 else 0.0)
    tx, ty = px + ux * (half + L), py + uy * (half + L)
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(p.GetPosition()); t.SetEnd(VECTOR2I(FromMM(tx), FromMM(ty)))
    t.SetWidth(FromMM(D["track_width"])); t.SetLayer(lay); t.SetNet(p.GetNet()); t.SetLocked(True)
    clr = max(D["clearance"], netclass(p.GetNetname())["clearance"]) + 0.005
    sh = t.GetEffectiveShape(lay)
    v = None
    if a.via:
        vd, vdia = cfg.get("sizing", {}).get("vias", {}).get("signal", [0.2, 0.45])
        v = pcbnew.PCB_VIA(b); v.SetPosition(VECTOR2I(FromMM(tx), FromMM(ty))); v.SetDrill(FromMM(vd)); v.SetWidth(FromMM(vdia))
        v.SetNet(p.GetNet()); v.SetLocked(True)
    shapes = [(sh, lay)] + ([(v.GetEffectiveShape(l), l) for l in CUS] if v else [])
    hit = lambda it, l: it.GetNetCode() != p.GetNetCode() and it.IsOnLayer(l) and \
        any(it.GetEffectiveShape(l).Collide(s_, FromMM(clr)) for s_, l2 in shapes if l2 == l)
    bad = [q for q in all_pads if any(hit(q, l) for l in CUS)] + [u for u in all_tracks if any(hit(u, l) for l in CUS)]
    if bad:
        skipped.append((n, p.GetNumber(), bad[0].GetParentFootprint().GetReference() + "." + bad[0].GetNumber()
                        if isinstance(bad[0], pcbnew.PAD) else bad[0].GetNetname()))
        continue
    b.Add(t); made += 1
    if v:
        b.Add(v); fixed.append(v); all_tracks.append(v)
    fixed.append(t); all_tracks.append(t)
b.Save(out)
print(f"{a.part}: {made} fan-out stubs ({a.len} mm past the pad end)")
for n, pin, why in skipped:
    print(f"  skipped {n} pin {pin}: too close to {why}")
