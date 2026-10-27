"""Refill zones, save, run DRC with schematic parity, print a summary.

    drc.py BOARD [--json OUT.json] [--no-refill] [--no-save] [--all]

Without --all only the violation types that matter for copper are listed one by one (silkscreen is counted only)."""
import argparse, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from klib import drc, drc_summary

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--json"); ap.add_argument("--no-refill", action="store_true")
ap.add_argument("--no-save", action="store_true"); ap.add_argument("--all", action="store_true")
a = ap.parse_args()
out = a.json or os.path.join(tempfile.gettempdir(), "drc_%d.json" % os.getpid())
rep = drc(a.board, out, refill=not a.no_refill, save=not a.no_save)
if a.all:
    print(drc_summary(rep, show=tuple({v["type"] for v in rep["violations"]})))
else:
    print(drc_summary(rep))
