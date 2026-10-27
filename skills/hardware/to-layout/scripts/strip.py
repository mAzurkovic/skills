"""Remove routing from a board file by text (pcbnew's Remove() crashes headless).

    strip.py BOARD [--out OUT] [--keep-locked] [--nets N1,N2] [--zones NAME1,NAME2] [--kinds segment,arc,via,zone]

Default: every track, arc, via and zone. --nets: only items on those nets (short names). --zones: only zones with
those names (use this to drop the outer GND pours from a routing copy)."""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from klib import strip_items

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--out"); ap.add_argument("--keep-locked", action="store_true")
ap.add_argument("--nets"); ap.add_argument("--zones"); ap.add_argument("--kinds", default="segment,arc,via,zone")
a = ap.parse_args()
kinds = tuple(a.kinds.split(","))
if a.zones:
    kinds = ("zone",)
n = strip_items(a.board, a.out, a.keep_locked, kinds, a.nets.split(",") if a.nets else None, a.zones.split(",") if a.zones else None)
print("removed", n)
