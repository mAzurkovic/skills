"""Placement checks measured from pad geometry, as a markdown table for hw/review/layout-check.md.

    checks.py BOARD [--edge 0.5] [--fail-only]

Config "checks":
  "decoupling":  [[cap, ic, ic_pin, net, limit_mm], ...]   gap from the cap's `net` pad to the IC pin (pad edges)
  "pad_distance": [[refA, padA, refB, padB, limit_mm, label], ...]   pad-edge gap must be <= limit
  "keepout_distance": [{"label", "center_ref" | "center": [x, y], "nets": [glob], "refs": [glob], "min": mm}]
                  centre to the nearest pad of those nets on those parts must be >= min
  "edge_exempt": [glob]   parts allowed to have copper within --edge mm of the outline (default J*, H*)
Exit code 1 when any check fails."""
import argparse, fnmatch, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pcbnew import ToMM
from klib import Board, short

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--edge", type=float, default=0.5); ap.add_argument("--fail-only", action="store_true")
a = ap.parse_args()
B = Board(a.board)
C = B.cfg.get("checks", {})
rows = []


def box(p):
    b = p.GetBoundingBox()
    return ToMM(b.GetLeft()), ToMM(b.GetTop()), ToMM(b.GetRight()), ToMM(b.GetBottom())


def gap(p, q):
    a_, b_ = box(p), box(q)
    return math.hypot(max(a_[0] - b_[2], b_[0] - a_[2], 0), max(a_[1] - b_[3], b_[1] - a_[3], 0))


def row(check, item, val, lim, ok):
    rows.append((check, item, val, lim, "pass" if ok else "FAIL"))


for cap, ic, pin, net, lim in C.get("decoupling", []):
    try:
        v = round(min(gap(p, B.pad(ic, pin)) for p in B.fp[cap].Pads() if short(p.GetNetname()) == short(net)), 2)
    except (KeyError, ValueError):
        row("Decoupling pad to pin", f"{cap} to {ic}.{pin}", "missing", f"<= {lim} mm", False); continue
    row("Decoupling pad to pin", f"{cap} to {ic}.{pin}", f"{v} mm", f"<= {lim} mm", v <= lim)
for ra, pa, rb, pb, lim, label in C.get("pad_distance", []):
    v = round(gap(B.pad(ra, pa), B.pad(rb, pb)), 2)
    row(label, f"{ra}.{pa} to {rb}.{pb}", f"{v} mm", f"<= {lim} mm", v <= lim)
for k in C.get("keepout_distance", []):
    if "center_ref" in k:
        c = B.fp[k["center_ref"]].GetPosition(); cx, cy = ToMM(c.x), ToMM(c.y)
    else:
        cx, cy = k["center"]
    best = (1e9, "")
    for ref, f in B.fp.items():
        if not any(fnmatch.fnmatchcase(ref, g) for g in k.get("refs", ["*"])) or ref == k.get("center_ref"):
            continue
        for p in f.Pads():
            if any(fnmatch.fnmatchcase(short(p.GetNetname()), g) for g in k["nets"]):
                d = math.hypot(ToMM(p.GetPosition().x) - cx, ToMM(p.GetPosition().y) - cy)
                if d < best[0]:
                    best = (d, f"{ref}.{p.GetNumber()}")
    if best[1]:
        row("Keep-out distance", f"{k['label']} (nearest {best[1]})", f"{best[0]:.2f} mm", f">= {k['min']} mm", best[0] >= k["min"])
exempt = C.get("edge_exempt", ["J*", "H*"])
for ref, f in B.fp.items():
    if any(fnmatch.fnmatchcase(ref, g) for g in exempt):
        continue
    for p in f.Pads():
        x1, y1, x2, y2 = box(p)
        m = min(x1 - B.x0, y1 - B.y0, B.x0 + B.w - x2, B.y0 + B.h - y2)
        if m < a.edge:
            row("Copper near the board edge", f"{ref}.{p.GetNumber()}", f"{m:.2f} mm", f">= {a.edge} mm", False)
print("| Check | Item | Measured | Limit | Result |\n|---|---|---|---|---|")
for r in rows:
    if not a.fail_only or r[4] == "FAIL":
        print("| " + " | ".join(r) + " |")
fails = sum(r[4] == "FAIL" for r in rows)
print(f"\n{len(rows)} checks, {fails} failing")
sys.exit(1 if fails else 0)
