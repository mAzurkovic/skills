"""Place blocks by hand and small parts next to their pins, from the board config. Run after the big parts
(connectors, power stage, ICs) are in place and corridors.py has reserved the lanes.

    place_small.py BOARD [--only REF,REF] [--reach 5] [--step 0.15] [--dry-run] [--lift REF,REF]

Config keys:
  "blocks": [{"ref": "C20", "x": 119.85, "y": 121.6, "rot": 0, "side": "F",
              "toward": {"net": "DRV_CPL", "x": 122.0, "y": 122.75}}]       # rot or rot+180, net pad nearer (x, y)
  "small_parts": [{"ref": "C23", "anchor": "U3.24", "net": "+3V3", "side": "F" | "B" | "either",
                   "other": ["25", "GND"],      # optional: also minimise the second pad's gap to this IC pin
                   "reach": 5,                   # search radius around the anchor pin, mm
                   "rots": [0, 90, 180, 270]}]   # rotations to try (45-degree steps beside a chip set at 45)
  "keepout_circles": [[cx, cy, r, "B", ["C40"]]]  # no parts on that side within r (e.g. magnet area); optional
                                                 # 5th item: parts allowed inside (the encoder's own cap)
  "keepout_boxes": [[x1, y1, x2, y2, "FB", "name", ["allowed"]]]
  "channels": [[x1, y1, x2, y2, "F", "name", ["C23"]]]   # routing lanes: only the listed parts may enter
  net_groups (high-voltage and sense spacing)

A candidate spot is legal when: inside the outline (0.3 mm), courtyard 0.2 mm from every placed part on that side
(through-hole and mounting holes on both sides), pad-to-pad 0.2 mm, 0.6 mm between high-voltage and other nets
outside IC / MOSFET courtyards, the same pad spacing to other nets' tracks and vias already on the board, outside
keep-outs and other parts' channels. Among legal spots (4 rotations, grid
--step) the one with the smallest pad-edge gap from the cap's `net` pad to the anchor pin wins. Parts in
small_parts that are not placed yet are not obstacles. Prints the gap per part; a gap far above the limit means the
part needs a hand position in "blocks"."""
import argparse, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import ToMM, FromMM, VECTOR2I
from klib import Board, short, rgap

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--only"); ap.add_argument("--reach", type=float, default=5.0)
ap.add_argument("--step", type=float, default=0.15); ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--cands", type=int, help="with one --only part: write its N best legal spots (JSON) instead of placing")
ap.add_argument("--cands-out")
ap.add_argument("--lift", help="parts treated as not placed yet (they are re-seated after this one)")
a = ap.parse_args()
B = Board(a.board)
cfg = B.cfg
only = set(a.only.split(",")) if a.only else None

for blk in cfg.get("blocks", []):
    if only and blk["ref"] not in only:
        continue
    bottom = blk.get("side", "F") == "B"
    if "toward" in blk:
        t = blk["toward"]; B.orient(blk["ref"], blk["x"], blk["y"], blk.get("rot", 0), t["net"], t["x"], t["y"], bottom)
    else:
        B.put(blk["ref"], blk["x"], blk["y"], blk.get("rot", 0), bottom)
    print(f"block {blk['ref']:5} at ({blk['x']}, {blk['y']}) rot {B.fp[blk['ref']].GetOrientationDegrees():g} {'B' if bottom else 'F'}")

todo = [s for s in cfg.get("small_parts", []) if not only or s["ref"] in only]
pending = {s["ref"] for s in todo} | (set(a.lift.split(",")) if a.lift else set())
PLACED = [r for r in B.fp if r not in pending]
RECT = {r: B.rect_of(r) for r in PLACED}
KC = cfg.get("keepout_circles", []); KB = cfg.get("keepout_boxes", []); CH = cfg.get("channels", [])


def box(p):
    b = p.GetBoundingBox()
    return ToMM(b.GetLeft()), ToMM(b.GetTop()), ToMM(b.GetRight()), ToMM(b.GetBottom())


def fits(ref, bottom, near):
    f = B.fp[ref]; me = B.rect_of(ref); side = "B" if bottom else "F"
    if not B.inside(me):
        return False
    for cx, cy, r, s, *ok in KC:
        if side in s and ref not in (ok[0] if ok else []) and math.hypot(max(me[0] - cx, 0, cx - me[2]), max(me[1] - cy, 0, cy - me[3])) < r:
            return False
    for x1, y1, x2, y2, s, *rest in KB:
        allowed = rest[1] if len(rest) > 1 else []
        if side in s and ref not in allowed and me[0] < x2 and me[2] > x1 and me[1] < y2 and me[3] > y1:
            return False
    for x1, y1, x2, y2, s, name, ok in CH:
        if side in s and ref not in ok and me[0] < x2 and me[2] > x1 and me[1] < y2 and me[3] > y1:
            return False
    mine = [(short(p.GetNetname()), box(p)) for p in f.Pads()]
    mc = B.court(ref); mcb = mc.BBox() if mc else None
    mcr = (ToMM(mcb.GetLeft()), ToMM(mcb.GetTop()), ToMM(mcb.GetRight()), ToMM(mcb.GetBottom())) if mcb else me
    for o in near:
        g = B.fp[o]
        th = any(p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) for p in g.Pads())
        if g.IsFlipped() != bottom and not th:
            continue
        orc = RECT[o]
        if g.IsFlipped() == bottom or o.startswith("H"):
            if o[0] in "U":                               # chips: their true courtyard (libraries often draw it tight)
                c = B.court(o)
                if c is not None:
                    cb = c.BBox()
                    if rgap(mcr, (ToMM(cb.GetLeft()), ToMM(cb.GetTop()), ToMM(cb.GetRight()), ToMM(cb.GetBottom()))) < 0.2:
                        # boxes touch: test the real outlines (a chip at 45 degrees fills only half its box)
                        if mc is None or c.Collide(mc.Outline(0), FromMM(0.2)) or mc.Collide(c.Outline(0), FromMM(0.2)):
                            return False
            elif rgap(me, orc) < 0.2:
                # boxes touch: test the real courtyards (a part at 45 degrees fills only half its box)
                c = B.court(o)
                if c is None or mc is None or c.Collide(mc.Outline(0), FromMM(0.2)) or mc.Collide(c.Outline(0), FromMM(0.2)):
                    return False
        for p in g.Pads():
            n2 = short(p.GetNetname()); r2 = box(p)
            for n1, r1 in mine:
                if n1 and n1 == n2:
                    continue
                need = 0.6 if (B.is_hv(n1) != B.is_hv(n2) and o[0] not in "UQ") else 0.2
                if rgap(r1, r2) < need and exact_close(ref, n1, p, need):
                    return False
    lay = pcbnew.B_Cu if bottom else pcbnew.F_Cu                  # fixed tracks and vias of other nets
    for t, n2, r2 in COPPER:
        if t.Type() != pcbnew.PCB_VIA_T and t.GetLayer() != lay:
            continue
        for p in f.Pads():
            n1 = short(p.GetNetname())
            if n1 and n1 == n2 or not p.IsOnLayer(lay):
                continue
            need = 0.6 if B.is_hv(n1) != B.is_hv(n2) else 0.2
            if rgap(box(p), r2) < need and p.GetEffectivePolygon(lay).Collide(t.GetEffectiveShape(lay), FromMM(need)):
                return False
    return True


COPPER = []
for t in B.b.GetTracks():
    bb = t.GetBoundingBox()
    COPPER.append((t, short(t.GetNetname()), (ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom()))))


def exact_close(ref, net, q, need):
    """Exact pad shapes closer than `need` (pad boxes overstate rotated pads)."""
    lay = pcbnew.B_Cu if B.fp[ref].IsFlipped() else pcbnew.F_Cu
    if not q.IsOnLayer(lay):
        return False
    pq = q.GetEffectivePolygon(lay)
    for p in B.fp[ref].Pads():
        if short(p.GetNetname()) == net and pq.Collide(p.GetEffectivePolygon(lay).Outline(0), FromMM(need)):
            return True
    return False


def pgap(p, q):
    return rgap(box(p), box(q))


for s in todo:
    ref = s["ref"]; aref, apin = s["anchor"].split(".")
    pin = B.pad(aref, apin); ax, ay = B.pad_xy(aref, apin)
    reach = s.get("reach", a.reach)
    near = [o for o in PLACED if rgap(RECT[o], (ax - reach - 3, ay - reach - 3, ax + reach + 3, ay + reach + 3)) == 0]
    sides = {"F": [False], "B": [True], "either": [False, True]}[s.get("side", "F")]
    other = (B.pad(aref, s["other"][0]), s["other"][1]) if s.get("other") else None
    home_bottom = B.fp[aref].IsFlipped()
    f0 = B.fp[ref]; keep = (f0.GetPosition(), f0.GetOrientationDegrees(), f0.IsFlipped())
    best, cands = None, []
    n = int(reach / a.step)
    for bottom in sides:
        for rot in s.get("rots", (0, 90, 180, 270)):
            B.put(ref, ax, ay, rot, bottom)
            f = B.fp[ref]
            for i in range(-n, n + 1):
                for j in range(-n, n + 1):
                    x, y = ax + j * a.step, ay + i * a.step
                    f.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
                    pads = {short(p.GetNetname()): p for p in f.Pads()}
                    if short(s["net"]) not in pads:
                        continue
                    g = pgap(pads[short(s["net"])], pin) + (pgap(pads[short(other[1])], other[0]) if other else 0.0)
                    g += 0.0 if bottom == home_bottom else 1.0       # other side of the board: via in the loop
                    if not a.cands and best is not None and g >= best[0] - 1e-6:
                        continue
                    if fits(ref, bottom, near):
                        if a.cands:
                            cands.append((round(g, 3), round(x, 3), round(y, 3), rot, bottom))
                        if best is None or g < best[0]:
                            best = (g, x, y, rot, bottom)
    if a.cands:
        import json
        picked = []
        for c in sorted(cands):                                   # spread out: 0.3 mm apart or another rotation
            if all(math.hypot(c[1] - q[1], c[2] - q[2]) >= 0.3 or c[3] != q[3] for q in picked):
                picked.append(c)
            if len(picked) >= a.cands:
                break
        json.dump([{"gap": g, "x": x, "y": y, "rot": r, "bottom": bt} for g, x, y, r, bt in picked], open(a.cands_out, "w"))
        print(f"{ref}: {len(cands)} legal spots, {len(picked)} written to {a.cands_out}")
        sys.exit(0)
    if best is None:
        f0.SetPosition(keep[0]); B.put(ref, ToMM(keep[0].x), ToMM(keep[0].y), keep[1], keep[2])
        print(f"{ref:5} NO SPOT within {reach} mm of {s['anchor']}: widen reach or place it in 'blocks'")
        continue
    g, x, y, rot, bottom = best
    g -= 0.0 if bottom == home_bottom else 1.0
    B.put(ref, x, y, rot, bottom)
    PLACED.append(ref); RECT[ref] = B.rect_of(ref)
    print(f"{ref:5} -> {s['anchor']} pad gap {g:.2f} mm ({'B' if bottom else 'F'}, rot {rot})")
if not a.dry_run:
    B.save()
