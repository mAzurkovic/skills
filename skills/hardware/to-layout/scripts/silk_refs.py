"""Place each footprint's reference designator on silkscreen where it is legible and clear: off every pad and
via, off other designators and silk outlines, inside the board edge. Candidates sit around the part's courtyard
(above, below, left, right, corners; then a 0.25 mm grid out to 3 mm, the part's own body included; 0 / 90 degrees) at the current text size, then at the fab minimum; the nearest clear
one wins. A part with no clear spot keeps its designator on the fab layer only (hidden on silk) and is listed.

    silk_refs.py BOARD [--min-height 0.8] [--stroke 0.15] [--clear 0.1] [--edge 0.3]

--min-height / --stroke: JLCPCB's legible silkscreen minimum (character height 0.8 mm, line 0.15 mm)."""
import argparse
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--min-height", type=float, default=0.8)
ap.add_argument("--stroke", type=float, default=0.15); ap.add_argument("--clear", type=float, default=0.1)
ap.add_argument("--edge", type=float, default=0.3)
a = ap.parse_args()
b = pcbnew.LoadBoard(a.board)
eb = b.GetBoardEdgesBoundingBox()
E = (ToMM(eb.GetLeft()) + a.edge, ToMM(eb.GetTop()) + a.edge, ToMM(eb.GetRight()) - a.edge, ToMM(eb.GetBottom()) - a.edge)


def box(bb, g=0.0):
    return (ToMM(bb.GetLeft()) - g, ToMM(bb.GetTop()) - g, ToMM(bb.GetRight()) + g, ToMM(bb.GetBottom()) + g)


def hit(r, s):
    return r[0] < s[2] and s[0] < r[2] and r[1] < s[3] and s[1] < r[3]


side_of = lambda f: "B" if f.IsFlipped() else "F"
obst = {"F": [], "B": []}                     # copper you would print on (pads, vias) and silk outlines, per side
for f in b.GetFootprints():
    for p in f.Pads():
        for s in ("F", "B"):
            if p.IsOnLayer(pcbnew.F_Cu if s == "F" else pcbnew.B_Cu):
                obst[s].append(box(p.GetBoundingBox(), a.clear))
    for g in f.GraphicalItems():
        if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and g.Type() != pcbnew.PCB_TEXT_T:
            obst["F" if g.GetLayer() == pcbnew.F_SilkS else "B"].append(box(g.GetBoundingBox(), a.clear))
for g in b.GetDrawings():                    # board-level silk (markers, logos, labels)
    if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
        obst["F" if g.GetLayer() == pcbnew.F_SilkS else "B"].append(box(g.GetBoundingBox(), a.clear))
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        for s in ("F", "B"):
            obst[s].append(box(t.GetBoundingBox(), a.clear))
placed = {"F": [], "B": []}
hidden, moved = [], 0
for f in sorted(b.GetFootprints(), key=lambda f: -ToMM(f.GetBoundingBox(False).GetWidth()) * ToMM(f.GetBoundingBox(False).GetHeight())):
    ref = f.Reference()
    if not ref.IsVisible():
        continue
    s = side_of(f)
    crt = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
    cb = box(crt.BBox()) if crt.OutlineCount() else box(f.GetBoundingBox(False))
    cx, cy = (cb[0] + cb[2]) / 2, (cb[1] + cb[3]) / 2
    sizes = [ToMM(ref.GetTextHeight())] + ([a.min_height] if ToMM(ref.GetTextHeight()) > a.min_height else [])
    best = None
    for h in sizes:
        ref.SetTextSize(VECTOR2I(FromMM(h), FromMM(h))); ref.SetTextThickness(FromMM(max(a.stroke, h * 0.15)))
        for ang in (0, 90):
            ref.SetTextAngleDegrees(ang + (0 if not f.IsFlipped() else 0))
            ref.SetPosition(VECTOR2I(FromMM(cx), FromMM(cy)))
            tb = box(ref.GetBoundingBox()); w, hh = tb[2] - tb[0], tb[3] - tb[1]
            ring = [(cx + dx * ((cb[2] - cb[0]) / 2 + w / 2 + a.clear) if dx else cx,
                     cy + dy * ((cb[3] - cb[1]) / 2 + hh / 2 + a.clear) if dy else cy)
                    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1))]
            reach = (cb[2] - cb[0]) / 2 + 3.0, (cb[3] - cb[1]) / 2 + 3.0      # then a grid out to 3 mm, inside too
            grid = [(cx + i * 0.25, cy + j * 0.25) for i in range(-int(reach[0] / 0.25), int(reach[0] / 0.25) + 1)
                    for j in range(-int(reach[1] / 0.25), int(reach[1] / 0.25) + 1)]
            for x, y in ring + sorted(grid, key=lambda q: abs(q[0] - cx) + abs(q[1] - cy)):
                r = (x - w / 2, y - hh / 2, x + w / 2, y + hh / 2)
                if not (E[0] <= r[0] and E[1] <= r[1] and r[2] <= E[2] and r[3] <= E[3]):
                    continue
                if any(hit(r, o) for o in obst[s]) or any(hit(r, o) for o in placed[s]):
                    continue
                d = abs(x - cx) + abs(y - cy) + (0 if h == sizes[0] else 5)
                if best is None or d < best[0]:
                    best = (d, x, y, ang, h, r)
                break                                     # candidates are in distance order
        if best:
            break
    if best:
        _, x, y, ang, h, r = best
        ref.SetTextSize(VECTOR2I(FromMM(h), FromMM(h))); ref.SetTextThickness(FromMM(max(a.stroke, h * 0.15)))
        ref.SetTextAngleDegrees(ang); ref.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
        placed[s].append(r); moved += 1
    else:
        ref.SetVisible(False); hidden.append(f.GetReference())
b.Save(a.board)
print(f"{moved} designators placed clear, {len(hidden)} hidden on silk (still on the fab layer): {' '.join(sorted(hidden))}")
