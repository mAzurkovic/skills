"""Crossings of an IC-to-IC bus, aware of which chip side each pin leaves from.

    bus_check.py BOARD IC_A IC_B [--nets REGEX] [--map NET1=NET2,NET3=NET4] [--list]

Each link leaves its pin outward from the chip side (N / S / E / W). Order every exit point by angle around the
point midway between the two chips; two links must cross on one layer when their endpoints interleave in that
cyclic order. This sees what a straight-line ratsnest count misses: two north-facing pin rows joined by a U-turn
need REVERSED pin order to route without crossings. The straight-line count is printed for comparison.

--map simulates pin swaps on IC_B before you touch the schematic: "INHA=INHC,INHC=INHA" swaps the two nets' pads.
Plane nets (config net_groups.plane) are ignored."""
import argparse, itertools, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcbnew import ToMM
from klib import Board, short, segs_cross

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("a"); ap.add_argument("b")
ap.add_argument("--nets", default=".*"); ap.add_argument("--map", default=""); ap.add_argument("--list", action="store_true")
a = ap.parse_args()
B = Board(a.board)
swap = dict(kv.split("=") for kv in a.map.split(",") if kv)


def pins(ref, remap=None):
    f = B.fp[ref]; c = f.GetPosition(); cx, cy = ToMM(c.x), ToMM(c.y)
    out = {}
    for p in f.Pads():
        n = short(p.GetNetname())
        if not n or n.startswith("unconnected") or B.is_plane(n) or not re.search(a.nets, n):
            continue
        if remap:
            n = remap.get(n, n)
        x, y = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)
        dx, dy = x - cx, y - cy
        if abs(dx) < 0.05 and abs(dy) < 0.05:            # exposed pad
            continue
        # side in the chip's own frame (a chip placed at 45 degrees has its pin rows diagonal on the board)
        t = math.radians(f.GetOrientationDegrees()); ct, st = math.cos(t), math.sin(t)
        lx, ly = dx * ct - dy * st, dx * st + dy * ct
        nx, ny = ((1 if lx > 0 else -1), 0) if abs(lx) > abs(ly) else (0, (1 if ly > 0 else -1))
        side = {(1, 0): "E", (-1, 0): "W", (0, 1): "S", (0, -1): "N"}[(nx, ny)]
        bx, by = nx * ct + ny * st, -nx * st + ny * ct          # outward normal back on the board
        out[n] = ((x, y), (x + bx * 0.8, y + by * 0.8), side, p.GetNumber())
    return out


pa, pb = pins(a.a), pins(a.b, swap)
links = [(n, pa[n], pb[n]) for n in sorted(set(pa) & set(pb))]
ca, cb = B.fp[a.a].GetPosition(), B.fp[a.b].GetPosition()
mx, my = (ToMM(ca.x) + ToMM(cb.x)) / 2, (ToMM(ca.y) + ToMM(cb.y)) / 2
ang = lambda pt: math.atan2(-(pt[1] - my), pt[0] - mx) % (2 * math.pi)


def between(t, lo, hi):
    return lo < t < hi if lo < hi else (t > lo or t < hi)


cyc, straight = [], []
for (n1, p1, q1), (n2, p2, q2) in itertools.combinations(links, 2):
    a1, b1 = sorted((ang(p1[1]), ang(q1[1])))
    inside = [between(ang(p2[1]), a1, b1), between(ang(q2[1]), a1, b1)]
    if inside[0] != inside[1]:
        cyc.append((n1, n2))
    if segs_cross((p1[0], q1[0]), (p2[0], q2[0])):
        straight.append((n1, n2))
print(f"{a.a} - {a.b}: {len(links)} links; crossings by pin side and order: {len(cyc)} (straight-line count: {len(straight)})")
if a.map:
    print("  with swaps on " + a.b + ": " + a.map)
for n1, n2 in cyc:
    print(f"  {n1} x {n2}")
if a.list:
    for n, p, q in links:
        print(f"  {n:14} {a.a}.{p[3]} ({p[2]})  ->  {a.b}.{q[3]} ({q[2]})")
