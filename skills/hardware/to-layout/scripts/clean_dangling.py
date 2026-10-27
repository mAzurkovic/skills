"""Remove the tracks and vias KiCad DRC reports as dangling (track_dangling, via_dangling), repeating until none
are left (removing one stub can leave the next one dangling). Locked items are removed too: a dangling locked
stub is leftover fan-out, not power copper; the report names every item removed.

    clean_dangling.py BOARD

Each round runs in its own process: a second pcbnew.LoadBoard in one process can return a bare SWIG pointer."""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if len(sys.argv) > 2 and sys.argv[1] == "--once":
    import pcbnew
    from klib import drc
    path = sys.argv[2]
    rep = drc(path, os.path.join(tempfile.mkdtemp(), "d.json"), refill=True, save=True, parity=False)
    ids = {it["uuid"] for v in rep["violations"] if v["type"] in ("track_dangling", "via_dangling") for it in v["items"]}
    b = pcbnew.LoadBoard(path)
    kill = [t for t in b.GetTracks() if t.m_Uuid.AsString() in ids]
    notes = [f"removed dangling {'via' if t.Type() == pcbnew.PCB_VIA_T else 'track'} {t.GetNetname()}" for t in kill]
    for t, note in zip(kill, notes):
        b.Remove(t)
        print(note, flush=True)
    if kill:
        b.Save(path)
    print(f"ROUND {len(kill)}", flush=True)
    sys.exit(0)

total = 0
for rnd in range(10):
    out = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--once", sys.argv[1]],
                         capture_output=True, text=True).stdout
    n = 0
    for line in out.splitlines():
        if line.startswith("ROUND "):
            n = int(line.split()[1])
        elif line.startswith("removed"):
            print(line)
    total += n
    if not n:
        break
print(f"{total} dangling items removed")
