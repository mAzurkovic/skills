"""Remove duplicate tracks and vias (same net, layer, end points / position): plane_fanout once stacked vias.

    dedupe.py BOARD"""
import sys
import pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
seen, kill = set(), []
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        k = ("v", t.GetNetCode(), t.GetPosition().x, t.GetPosition().y)
    else:
        a, e = (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)
        k = ("t", t.GetNetCode(), t.GetLayer(), t.GetWidth(), min(a, e), max(a, e))
    if k in seen:
        kill.append(t)
    seen.add(k)
for t in kill:
    b.Remove(t)
b.Save(sys.argv[1])
print(f"removed {len(kill)} duplicate tracks/vias")
