"""Merge same-net vias whose holes are closer than the via hole-to-hole rule: each group of too-close vias keeps
one (locked first, then the one with the most track ends on it); the others' track ends move onto it and they are
deleted. Fan-out, stitching and routing passes each add vias; two of the same net a hair apart are one via too
many and a fab problem.

    merge_vias.py BOARD [--min 0.25]

--min: hole edge to hole edge, mm (the rules' "via hole to hole"). Everything is read before anything is removed
(pcbnew wrappers go stale after a Remove). Run DRC after: a moved track end can come closer to other copper."""
import argparse, math
import pcbnew
from pcbnew import ToMM, VECTOR2I

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--min", type=float, default=0.25)
a = ap.parse_args()
b = pcbnew.LoadBoard(a.board)
vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
tracks = [t for t in b.GetTracks() if t.Type() != pcbnew.PCB_VIA_T]
V = [(v.GetNetCode(), v.GetPosition().x, v.GetPosition().y, ToMM(v.GetDrillValue()), v.IsLocked(), v.GetNetname()) for v in vias]
T = [(t.GetNetCode(), (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)) for t in tracks]
nends = [sum(1 for n, s, e in T if n == V[i][0] and ((V[i][1], V[i][2]) in (s, e))) for i in range(len(V))]
parent = list(range(len(V)))


def find(i):
    while parent[i] != i:
        parent[i] = parent[parent[i]]; i = parent[i]
    return i


for i in range(len(V)):
    for j in range(i + 1, len(V)):
        if V[i][0] == V[j][0]:
            gap = math.hypot(ToMM(V[i][1] - V[j][1]), ToMM(V[i][2] - V[j][2])) - V[i][3] / 2 - V[j][3] / 2
            if gap < a.min:
                parent[find(i)] = find(j)
groups = {}
for i in range(len(V)):
    groups.setdefault(find(i), []).append(i)
moves, drop = {}, set()                        # (net, x, y) of a dropped via -> keeper position
for g in groups.values():
    if len(g) < 2:
        continue
    k = max(g, key=lambda i: (V[i][4], nends[i]))
    for i in g:
        if i != k:
            moves[(V[i][0], V[i][1], V[i][2])] = (V[k][1], V[k][2]); drop.add(i)
            print(f"merged {V[i][5]} via at ({ToMM(V[i][1]):.2f}, {ToMM(V[i][2]):.2f}) into ({ToMM(V[k][1]):.2f}, {ToMM(V[k][2]):.2f})")
gone = []
for t, (n, s, e) in zip(tracks, T):
    s2, e2 = moves.get((n,) + s, s), moves.get((n,) + e, e)
    if (s2, e2) != (s, e):
        if s2 == e2:
            gone.append(t); continue
        t.SetStart(VECTOR2I(*s2)); t.SetEnd(VECTOR2I(*e2))
for i in sorted(drop):
    gone.append(vias[i])
for t in gone:
    b.Remove(t)
b.Save(a.board)
print(f"{len(drop)} vias merged")
