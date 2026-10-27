"""Re-seat parts that wall in pins: try each part's best legal spots and keep the one that leaves the fewest
connection ends walled in (droute.py --gate-only), then the smallest pad gap.

    access_fix.py BOARD --out OUT.kicad_pcb --parts C23,C19+C18 [--n 20]

Each part needs a "small_parts" entry in the config (anchor pin, net, side, reach, other, rots): its candidates
come from place_small.py --cands, i.e. they already pass every placement rule place_small checks. Parts are done in
the order given; each sees the previous ones in their new spots. A group LEAD+F1+F2 searches LEAD with the
followers lifted (not obstacles), then re-seats each follower at its best legal spot: for a wall that only moves
when its neighbour moves too. Spots are ranked by (walled-in ends, failing checks.py checks, pad gap); one is kept
only when it beats the current spot on that order (fewer walled-in ends, or as many and fewer failing checks).
Exit 0 when no end is walled in."""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--out", required=True); ap.add_argument("--parts", required=True)
ap.add_argument("--n", type=int, default=20)
ap.add_argument("--gate-args", default="", help='extra droute.py gate arguments, e.g. "--only N1,N2 --reserve-escapes" '
                                                 "for a staged route (the walls a stage sees)")
a = ap.parse_args()
HERE = os.path.dirname(os.path.abspath(__file__))
KP = sys.executable
tmp = tempfile.mkdtemp()
src = a.board[:-len(".kicad_pcb")]
cur = os.path.join(tmp, "cur.kicad_pcb")
for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".layout.json"):
    if os.path.exists(src + ext):
        shutil.copy(src + ext, cur[:-len(".kicad_pcb")] + ext)


def gate(path):
    r = subprocess.run([KP, "-I", os.path.join(HERE, "droute.py"), path, "--out", os.path.join(tmp, "g.kicad_pcb"), "--gate-only"]
                       + a.gate_args.split(), capture_output=True, text=True)
    m = re.search(r"pin access: (\d+) trapped", r.stdout)
    lines = [l.strip() for l in r.stdout.splitlines() if "walled in" in l or "no legal cell" in l]
    return (int(m.group(1)) if m else 999), lines


def fails(path):
    r = subprocess.run([KP, "-I", os.path.join(HERE, "checks.py"), path, "--fail-only"], capture_output=True, text=True)
    m = re.search(r"(\d+) failing", r.stdout)
    return int(m.group(1)) if m else 999


def reseat(path, refs):
    """Follower parts to their best legal spot on `path` (in place); False when one has none."""
    for ref in refs:
        r = subprocess.run([KP, "-I", os.path.join(HERE, "place_small.py"), path, "--only", ref], capture_output=True, text=True)
        if "NO SPOT" in r.stdout:
            return False
    return True


def place(path, ref, c, out):
    code = f"""
import pcbnew
from pcbnew import FromMM, VECTOR2I
b = pcbnew.LoadBoard({path!r}); f = b.FindFootprintByReference({ref!r})
if f.IsFlipped() != {c['bottom']}:
    f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
f.SetOrientationDegrees({c['rot']}); f.SetPosition(VECTOR2I(FromMM({c['x']}), FromMM({c['y']}))); b.Save({out!r})
"""
    subprocess.run([KP, "-I", "-c", code], capture_output=True)
    for ext in (".kicad_pro", ".kicad_dru", ".layout.json"):
        shutil.copy(path[:-len(".kicad_pcb")] + ext, out[:-len(".kicad_pcb")] + ext)


base_n, base_lines = gate(cur)
base_f = fails(cur)
print(f"start: {base_n} ends walled in, {base_f} placement checks failing")
for l in base_lines:
    print("  " + l)
for grp in a.parts.split(","):
    ref, *follow = grp.split("+")
    cj = os.path.join(tmp, f"{ref}.json")
    subprocess.run([KP, "-I", os.path.join(HERE, "place_small.py"), cur, "--only", ref, "--cands", str(a.n), "--cands-out", cj]
                   + (["--lift", ",".join(follow)] if follow else []), capture_output=True, text=True)
    if not os.path.exists(cj):
        print(f"{ref}: no candidates (no small_parts entry, or no legal spot)"); continue
    cands = json.load(open(cj))
    best = (base_n, base_f, 1e9, None)
    for k, c in enumerate(cands):
        trial = os.path.join(tmp, f"t_{ref}_{k}.kicad_pcb")
        place(cur, ref, c, trial)
        if follow and not reseat(trial, follow):
            continue
        n, _ = gate(trial)
        if n > base_n:
            continue
        fl = fails(trial)
        if (n, fl) < (base_n, base_f) and (n, fl, c["gap"]) < best[:3]:
            best = (n, fl, c["gap"], trial, c)
        if n == 0 and fl == 0:
            break
    if len(best) < 5:
        print(f"{ref}: no spot beats {base_n} walled-in ends / {base_f} failing checks; kept where it is ({len(cands)} tried)")
        continue
    n, fl, g, trial, c = best
    for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".layout.json"):
        shutil.copy(trial[:-len(".kicad_pcb")] + ext, cur[:-len(".kicad_pcb")] + ext)
    print(f"{ref}: -> ({c['x']}, {c['y']}) rot {c['rot']} {'B' if c['bottom'] else 'F'}, pad gap {g} mm; walled-in ends {base_n} -> {n}, "
          f"failing checks {base_f} -> {fl}"
          + (f"; re-seated {', '.join(follow)}" if follow else ""))
    base_n, base_f = n, fl
final_n, lines = gate(cur)
for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru", ".layout.json"):
    if os.path.exists(cur[:-len(".kicad_pcb")] + ext):
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        shutil.copy(cur[:-len(".kicad_pcb")] + ext, a.out[:-len(".kicad_pcb")] + ext)
print(f"final: {final_n} ends walled in; saved {a.out}")
for l in lines:
    print("  " + l)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if final_n == 0 else 1)
