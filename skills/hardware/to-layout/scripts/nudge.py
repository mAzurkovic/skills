"""Fix near-miss clearances the router's 0.1 mm grid leaves: move an unlocked via (and the track ends on it) straight
away from the item it is too close to, by the shortfall + 5 um, when the shortfall is under --max mm.

    nudge.py BOARD [--max 0.02]

Reads KiCad DRC (refilled), moves, saves, and runs DRC again; prints what moved and what is left. A shortfall
larger than --max is a routing problem, not rounding, and is left alone."""
import argparse, json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I
from klib import drc

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--max", type=float, default=0.02)
a = ap.parse_args()
js = a.board[:-len(".kicad_pcb")] + "_nudge.json"
rep = drc(a.board, js, refill=True, save=True, parity=False)
b = pcbnew.LoadBoard(a.board)
vias = {(round(ToMM(t.GetPosition().x), 3), round(ToMM(t.GetPosition().y), 3)): t for t in b.GetTracks()
        if t.Type() == pcbnew.PCB_VIA_T and not t.IsLocked()}
moved = 0
for v in rep["violations"]:
    if v["type"] not in ("clearance", "hole_clearance"):
        continue
    m = re.search(r"clearance ([\d.]+) mm; actual ([\d.]+) mm", v["description"])
    if not m:
        continue
    short_by = float(m.group(1)) - float(m.group(2))
    if short_by <= 0 or short_by > a.max:
        continue
    its = v["items"]
    for k, it in enumerate(its):
        key = (round(it["pos"]["x"], 3), round(it["pos"]["y"], 3))
        if not it["description"].startswith("Via") or key not in vias:
            continue
        o = its[1 - k]["pos"]
        dx, dy = key[0] - o["x"], key[1] - o["y"]
        L = math.hypot(dx, dy) or 1.0
        d = short_by + 0.005
        t = vias.pop(key)
        old = t.GetPosition(); new = VECTOR2I(old.x + FromMM(dx / L * d), old.y + FromMM(dy / L * d))
        for tr in b.GetTracks():
            if tr.Type() != pcbnew.PCB_VIA_T and tr.GetNetCode() == t.GetNetCode():
                if tr.GetStart() == old:
                    tr.SetStart(new)
                if tr.GetEnd() == old:
                    tr.SetEnd(new)
        t.SetPosition(new); moved += 1
        print(f"moved via {it['description'][:30]} at {key} by {d:.3f} mm away from {its[1 - k]['description'][:40]}")
        break
b.Save(a.board)
rep = drc(a.board, js, refill=True, save=True, parity=False)
left = [v for v in rep["violations"] if v["type"] in ("clearance", "hole_clearance")]
print(f"nudged {moved} vias; clearance violations left: {len(left)}")
