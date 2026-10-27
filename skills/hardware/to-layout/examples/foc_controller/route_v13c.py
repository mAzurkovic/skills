"""Stage C (v13): one 0.2 / 0.45 mm GND via beside every GND pad of the small parts (power-stage parts excluded: their
GND reaches L2 through the pours and the stage-A vias), 9 thermal vias in each exposed GND pad. Locked."""
import math, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM
from rlib import R, CX, CY, X0, Y0, W

r = R(); b = r.b; fp = r.fp
HV = ("PHASE_", "BUCK_SW", "BUCK_BST", "DRV_VCP", "DRV_CPH", "DRV_CPL", "GHA", "GHB", "GHC")
is_hv = lambda n: n == "VBUS" or any(n.startswith(h) for h in HV)
PADS = [(p, str(p.GetNetname()).split("/")[-1], f.GetReference()) for f in b.GetFootprints() for p in f.Pads()]
VIAS = [(ToMM(t.GetPosition().x), ToMM(t.GetPosition().y), str(t.GetNetname()).split("/")[-1], ToMM(t.GetWidth(pcbnew.F_Cu)))
        for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
TRK = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
ZONES = [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu) and str(z.GetNetname()) != "GND"]


def ok(x, y, own, dia=0.45):
    if not (X0 + 0.9 < x < X0 + W - 0.9 and Y0 + 0.9 < y < Y0 + W - 0.9):
        return False
    pt = VECTOR2I(FromMM(x), FromMM(y))
    for vx, vy, vn, vd in VIAS:
        if math.hypot(vx - x, vy - y) < (vd + dia) / 2 + (0.3 if vn == "GND" else 0.25):
            return False
    for p, pn, ref in PADS:
        if pn == "GND" and p is not own:
            continue
        if p is own:
            continue
        need = 0.6 if is_hv(pn) and ref[0] not in "QU" else 0.2
        if "SENSE" in pn:
            need = 0.25
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            need = 0.35
        for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
            if p.IsOnLayer(lay) and p.GetEffectivePolygon(lay).Collide(pt, FromMM(dia / 2 + need)):
                return False
    for z in ZONES:                                           # stay out of the power pours (other nets)
        lay = z.GetLayer()
        if z.GetFilledPolysList(lay).Collide(pt, FromMM(dia / 2 + 0.25)):
            return False
    return True


def link_ok(x1, y1, x2, y2, own, side):
    seg = pcbnew.SEG(VECTOR2I(FromMM(x1), FromMM(y1)), VECTOR2I(FromMM(x2), FromMM(y2)))
    for p, pn, ref in PADS:
        if p is own or pn == "GND" or not p.IsOnLayer(side):
            continue
        if p.GetEffectivePolygon(side).Collide(seg, FromMM(0.125 + 0.2)):
            return False
    return True


POWER = {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "R8", "R9", "R10", "C1", "C5", "C9", "C50", "C51", "C52",
         "NT1", "NT2", "NT3", "NT4", "NT5", "NT6", "J1", "J2", "J3", "J4", "J5", "H1", "H2", "H3", "H4"}
done, miss = 0, []
for f in b.GetFootprints():
    ref = f.GetReference()
    if ref in POWER:
        continue
    for p in f.Pads():
        if str(p.GetNetname()) != "GND" or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
            continue
        bb = p.GetBoundingBox(); w, h = ToMM(bb.GetWidth()), ToMM(bb.GetHeight())
        px, py = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)
        if w > 2.5 and h > 2.5:                               # exposed pad: 3 x 3 thermal vias inside
            k = 0
            for i in (-1, 0, 1):
                for j in (-1, 0, 1):
                    x, y = px + i * min(1.2, w / 3), py + j * min(1.2, h / 3)
                    if ok(x, y, p, 0.45):
                        r.via(x, y, "GND", drill=0.2, dia=0.45); VIAS.append((x, y, "GND", 0.45)); k += 1
            print(ref, "exposed-pad vias", k); done += 1
            continue
        side = pcbnew.B_Cu if f.IsFlipped() else pcbnew.F_Cu
        best = None
        for d in [0.5 + 0.1 * i for i in range(20)]:
            for a in range(0, 360, 15):
                x, y = px + d * math.cos(math.radians(a)), py + d * math.sin(math.radians(a))
                # the via sits outside the pad, its link stays short
                if p.GetEffectivePolygon(side).Collide(VECTOR2I(FromMM(x), FromMM(y)), FromMM(0.225)):
                    continue
                if ok(x, y, p) and link_ok(px, py, x, y, p, side):
                    best = (x, y); break
            if best:
                break
        if not best:
            miss.append(f"{ref}.{p.GetNumber()}"); continue
        x, y = best
        r.via(x, y, "GND", drill=0.2, dia=0.45); VIAS.append((x, y, "GND", 0.45))
        r.track([(px, py), (x, y)], "GND", "B" if f.IsFlipped() else "F", 0.25)
        done += 1
r.save()
print("GND pads with a via:", done, "without:", len(miss), miss)
