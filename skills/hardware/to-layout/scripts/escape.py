"""Escape budget per side of each fine-pitch IC (run on the placement, before routing).

    escape.py BOARD U3 U4 [--via 0.45] [--clear 0.15] [--ring 2.6] [--margin 1.2]

Vias needed on a side: one per pin whose link (nearest same-net pad elsewhere) is on the other board side or crosses
another link of the same IC, plus one per group of adjacent pins on a via-to-plane net (config key
"escape_via_nets", default: net_groups.plane). Via sites: free points of a ring from 0.35 mm to --ring mm outside the
pad row, where a via of --via diameter clears the IC's own pads, other parts' pads and courtyards (both sides: a via
goes through) and existing other-net vias; free area / staggered via pitch. Pass when needed x --margin <= sites."""
import argparse, itertools, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import ToMM, FromMM, VECTOR2I
from klib import Board, short, segs_cross

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("ics", nargs="+")
ap.add_argument("--via", type=float, default=0.45); ap.add_argument("--clear", type=float, default=0.15)
ap.add_argument("--ring", type=float, default=2.6); ap.add_argument("--margin", type=float, default=1.2)
a = ap.parse_args()
B = Board(a.board)
VIA_NETS = B.cfg.get("escape_via_nets", B.plane_pat)
import fnmatch
via_net = lambda n: any(fnmatch.fnmatchcase(n, p) for p in VIA_NETS)
pitch_area = (a.via + a.clear) * (a.via + a.clear) * 0.92          # staggered rows
r_need = a.via / 2 + a.clear

# blockers as boxes for a fast first pass, exact polygons second
items = []
for f in B.b.GetFootprints():
    c = B.court(f.GetReference())
    cb = None
    if c is not None:
        bb = c.BBox(); cb = (ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom()))
    pads = []
    for p in f.Pads():
        pb = p.GetBoundingBox()
        pads.append((p, (ToMM(pb.GetLeft()), ToMM(pb.GetTop()), ToMM(pb.GetRight()), ToMM(pb.GetBottom()))))
    items.append((f.GetReference(), c, cb, pads))
other_vias = [(ToMM(t.GetPosition().x), ToMM(t.GetPosition().y), ToMM(t.GetWidth(pcbnew.F_Cu)) / 2, short(t.GetNetname()))
              for t in B.b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]


def site_free(x, y, ic):
    pt = VECTOR2I(FromMM(x), FromMM(y))
    for vx, vy, vr, vn in other_vias:
        if math.hypot(vx - x, vy - y) < vr + r_need:
            return False
    near = lambda b, m: b[0] - m <= x <= b[2] + m and b[1] - m <= y <= b[3] + m
    for ref, c, cb, pads in items:
        if ref != ic and c is not None and near(cb, a.via / 2) and c.Collide(pt, FromMM(a.via / 2)):
            return False
        for p, pb in pads:
            if not near(pb, r_need):
                continue
            lay = pcbnew.B_Cu if p.GetParentFootprint().IsFlipped() and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD else pcbnew.F_Cu
            if p.GetEffectivePolygon(lay).Collide(pt, FromMM(r_need)):
                return False
    return True


for ic in a.ics:
    f = B.fp[ic]; c = f.GetPosition(); cx, cy = ToMM(c.x), ToMM(c.y)
    pads = [p for p in f.Pads() if short(p.GetNetname()) and not (abs(ToMM(p.GetPosition().x) - cx) < 0.05 and abs(ToMM(p.GetPosition().y) - cy) < 0.05)]
    half = max(max(abs(ToMM(p.GetPosition().x) - cx), abs(ToMM(p.GetPosition().y) - cy)) for p in pads) + 0.4
    sides = {"N": [], "S": [], "E": [], "W": []}
    for p in pads:
        dx, dy = ToMM(p.GetPosition().x) - cx, ToMM(p.GetPosition().y) - cy
        sides[("E" if dx > 0 else "W") if abs(dx) > abs(dy) else ("S" if dy > 0 else "N")].append(p)
    segs = {}
    for p in pads:
        n = short(p.GetNetname())
        if via_net(n) or n.startswith("unconnected"):
            continue
        others = [q for q in B.b.GetPads() if q.GetNetCode() == p.GetNetCode() and q.GetParentFootprint().GetReference() != ic]
        if not others:
            continue
        q = min(others, key=lambda q: (q.GetPosition() - p.GetPosition()).EuclideanNorm())
        segs[p.GetNumber()] = (((ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)), (ToMM(q.GetPosition().x), ToMM(q.GetPosition().y))),
                               q.GetParentFootprint().IsFlipped() != f.IsFlipped())
    for s, ps in sides.items():
        if not ps:
            continue
        need, why, last = 0, [], None
        for p in sorted(ps, key=lambda p: (ToMM(p.GetPosition().x), ToMM(p.GetPosition().y))):
            n = short(p.GetNetname())
            if via_net(n):
                if n != last:
                    need += 1; why.append(f"{p.GetNumber()} {n}")
                last = n
                continue
            last = None
            if p.GetNumber() not in segs:
                continue
            seg, other_side = segs[p.GetNumber()]
            x = sum(segs_cross(seg, t[0]) for k, t in segs.items() if k != p.GetNumber())
            if other_side or x:
                need += 1; why.append(f"{p.GetNumber()} {n} " + ("other side" if other_side else f"{x} crossings"))
        free, step = 0, 0.1
        for i in range(int((a.ring - 0.35) / step)):
            d = half + 0.35 + i * step
            for j in range(int(2 * (half + a.ring) / step)):
                t = -half - a.ring + j * step
                x, y = {"N": (cx + t, cy - d), "S": (cx + t, cy + d), "E": (cx + d, cy + t), "W": (cx - d, cy + t)}[s]
                if B.inside((x, y, x, y), 0.5) and site_free(x, y, ic):
                    free += 1
        sites = free * step * step / pitch_area
        ok = need * a.margin <= sites
        print(f"{ic} {s}: vias needed {need}, via sites {sites:.0f} -> {'pass' if ok else 'FAIL'}" + (f"  ({'; '.join(why)})" if why else ""))
