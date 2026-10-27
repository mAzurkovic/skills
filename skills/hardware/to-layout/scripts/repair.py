"""Finish a mostly routed board by local rip-up: free the pins that other nets' tracks wall in, then route only what
is open, keeping everything else.

    repair.py BOARD --out OUT.kicad_pcb [--rounds 6] [--radius 1.5] [--grow 1.0] [--iters 20]

A round: droute.py --gate-only --keep-routed names the walled-in ends; the unlocked tracks and vias of other nets
lying wholly within --radius mm of each are removed (never locked copper, place_opt.fixed_nets, net_groups.hv, or
plane nets: those ends are left to plane_fanout.py); the radius grows by --grow for ends still walled in from the
last round. When no end is walled in, droute.py --keep-routed routes the open connections (the walled-in nets and
the nets just ripped up) on top of the rest. Each round costs one gate (seconds) instead of a whole-board route.
Exit 0 when the final DRC has no unconnected items outside the plane nets."""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from klib import load_config, strip_region

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--out", required=True); ap.add_argument("--rounds", type=int, default=6)
ap.add_argument("--radius", type=float, default=1.5); ap.add_argument("--grow", type=float, default=1.0)
ap.add_argument("--iters", type=int, default=20)
a = ap.parse_args()
HERE, KP = os.path.dirname(os.path.abspath(__file__)), sys.executable
cfg = load_config(a.board)
plane = {p["net"] for p in cfg.get("planes", [])} | set(cfg.get("net_groups", {}).get("plane", []))
keep = cfg.get("place_opt", {}).get("fixed_nets", []) + cfg.get("net_groups", {}).get("hv", []) + sorted(plane)
tmp = tempfile.mkdtemp()
cur = os.path.join(tmp, "cur.kicad_pcb")


def copy_set(src, dst):
    for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".layout.json"):
        if os.path.exists(src[:-len(".kicad_pcb")] + ext):
            shutil.copy(src[:-len(".kicad_pcb")] + ext, dst[:-len(".kicad_pcb")] + ext)


def gate(path):
    tj = os.path.join(tmp, "trapped.json")
    subprocess.run([KP, "-I", os.path.join(HERE, "droute.py"), path, "--out", os.path.join(tmp, "g.kicad_pcb"),
                    "--gate-only", "--keep-routed", "--trapped-json", tj], capture_output=True, text=True)
    return [t for t in json.load(open(tj)) if t["net"] not in plane]


copy_set(a.board, cur)
radius = {}
for rnd in range(1, a.rounds + 1):
    ends = gate(cur)
    print(f"round {rnd}: {len(ends)} signal ends walled in")
    if not ends:
        break
    n = 0
    for t in ends:
        key = (t["net"], round(t["x"], 2), round(t["y"], 2))
        r = radius[key] = radius.get(key, a.radius - a.grow) + a.grow
        n += strip_region(cur, (t["x"] - r, t["y"] - r, t["x"] + r, t["y"] + r), keep + [t["net"]], keep_locked=True)
        print(f"  {t['net']:10} ({t['x']:.2f}, {t['y']:.2f}) rip-up radius {r:.1f} mm")
    print(f"  removed {n} tracks/vias")
    if not n:
        print("  nothing left to rip up near them: the wall is fixed copper or parts (access_fix.py)")
        break
r = subprocess.run([KP, "-I", os.path.join(HERE, "droute.py"), cur, "--out", a.out, "--keep-routed", "--iters", str(a.iters),
                    "--g4-restarts", "1"], capture_output=True, text=True)
print("\n".join(l for l in (r.stdout + r.stderr).splitlines()
                if re.match(r"(global|iteration|DRC|unconnected|  )", l) and "assert" not in l)[-3000:])
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(r.returncode)
