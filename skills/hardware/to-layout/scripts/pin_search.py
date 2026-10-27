"""Search pin swaps (and rotations of the IC that owns the pins) for the fewest crossings on an IC-to-IC bus.

    pin_search.py BOARD IC_A IC_B [--top 8] [--apply K --out OUT.kicad_pcb]

Config "pin_swaps" (IC_B is the chip whose pins may change; every option must come from its datasheet):
  {"rotations": [0, 90, 180, 270],                  IC_B orientations to try, rotated as a rigid block with
                                                      place_opt.blocks members when it is a block anchor
   "permute": [["INHA", "INLA"], ["INHB", "INLB"], ...],   tuples that trade pin sets as a whole (TIM1 channel
                                                      pairs: a phase may take any channel, H and L stay paired)
   "choose": [{"nets": ["DRV_nSCS"], "pins": ["PA15", "PB6", ...]},   nets placed on any of these pins
              {"nets": ["DRV_EN", "DRV_nFAULT"], "pins": [...]}]}      (pin function names, e.g. PB7); a pin
                                                      may be taken only if it is unconnected or its net is in
                                                      the same group
Score: crossings by pin side and order (as bus_check.py) among the IC_A to IC_B links, then the straight-line
count. --apply K writes the K-th best (1 = best) to --out: nets swapped on IC_B's pads and the rotation applied to
the block. The swap list printed with it is what /to-schematic applies after the user's OK."""
import argparse, itertools, math, os, re, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I
from klib import load_config, segs_cross, short

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("a"); ap.add_argument("b"); ap.add_argument("--top", type=int, default=8)
ap.add_argument("--apply", type=int); ap.add_argument("--out")
a = ap.parse_args()
cfg = load_config(a.board)
PS = cfg.get("pin_swaps", {})
b = pcbnew.LoadBoard(a.board)
fa, fb = b.FindFootprintByReference(a.a), b.FindFootprintByReference(a.b)
plane = {short(p["net"]) for p in cfg.get("planes", [])} | {"GND"}
func = lambda p: p.GetPinFunction().split("_")[0]
pads_b = {func(p): p for p in fb.Pads() if p.GetPinFunction()}
net_of = {f: short(p.GetNetname()) for f, p in pads_b.items()}
pin_of = {n: f for f, n in net_of.items()}
bus = {short(p.GetNetname()) for p in fa.Pads()} & set(net_of.values())
bus = {n for n in bus if n and n not in plane and not n.startswith("unconnected")}


def outward(f, p, rot=None):
    """Pin position, exit point 0.8 mm outward, side, in the board frame for footprint orientation `rot`."""
    c = f.GetPosition(); cx, cy = ToMM(c.x), ToMM(c.y)
    x, y = ToMM(p.GetPosition().x) - cx, ToMM(p.GetPosition().y) - cy
    t0 = math.radians(f.GetOrientationDegrees())
    lx, ly = x * math.cos(t0) - y * math.sin(t0), x * math.sin(t0) + y * math.cos(t0)   # local frame
    t = math.radians(f.GetOrientationDegrees() if rot is None else rot)
    ct, st = math.cos(t), math.sin(t)
    X, Y = lx * ct + ly * st, -lx * st + ly * ct
    nx, ny = ((1 if lx > 0 else -1), 0) if abs(lx) > abs(ly) else (0, (1 if ly > 0 else -1))
    bx, by = nx * ct + ny * st, -nx * st + ny * ct
    return (cx + X, cy + Y), (cx + X + bx * 0.8, cy + Y + by * 0.8)


A = {short(p.GetNetname()): outward(fa, p) for p in fa.Pads() if short(p.GetNetname()) in bus}
ca, cb = fa.GetPosition(), fb.GetPosition()
mx, my = (ToMM(ca.x) + ToMM(cb.x)) / 2, (ToMM(ca.y) + ToMM(cb.y)) / 2
ang = lambda pt: math.atan2(-(pt[1] - my), pt[0] - mx) % (2 * math.pi)
between = lambda t, lo, hi: lo < t < hi if lo < hi else (t > lo or t < hi)


def score(assign, rot):
    """assign: net -> pin function on IC_B."""
    links = []
    for n in sorted(bus):
        q = outward(fb, pads_b[assign.get(n, pin_of[n])], rot)
        links.append((n, A[n], q))
    cyc = straight = 0
    for (n1, p1, q1), (n2, p2, q2) in itertools.combinations(links, 2):
        a1, b1 = sorted((ang(p1[1]), ang(q1[1])))
        if between(ang(p2[1]), a1, b1) != between(ang(q2[1]), a1, b1):
            cyc += 1
        straight += segs_cross((p1[0], q1[0]), (p2[0], q2[0]))
    return cyc, straight


# ---- the assignment space
perm = PS.get("permute", [])
slots = [tuple(pin_of[n] for n in grp) for grp in perm]
choose = PS.get("choose", [])
for g in choose:
    for pin in g["pins"]:
        if pin not in pads_b:
            sys.exit(f"{a.b} has no pin {pin}")
        n = net_of[pin]
        if n and not n.startswith("unconnected") and n not in g["nets"]:
            g["pins"] = [x for x in g["pins"] if x != pin]           # taken by another function
choices = [list(itertools.permutations(g["pins"], len(g["nets"]))) for g in choose]
rots = PS.get("rotations", [fb.GetOrientationDegrees()])
results = []
for order in itertools.permutations(range(len(slots))):
    base = {}
    for grp, k in zip(perm, order):
        for n, pin in zip(grp, slots[k]):
            base[n] = pin
    for pick in itertools.product(*choices):
        used, asg, ok = set(base.values()), dict(base), True
        for g, pins in zip(choose, pick):
            for n, pin in zip(g["nets"], pins):
                if pin in used:
                    ok = False; break
                used.add(pin); asg[n] = pin
            if not ok:
                break
        if not ok:
            continue
        for r in rots:
            cyc, st = score(asg, r)
            results.append((cyc, st, r, tuple(sorted(asg.items()))))
results.sort()
now = score({}, None)
print(f"{a.a} - {a.b}: {len(bus)} bus links; now {now[0]} crossings (straight {now[1]}) at {fb.GetOrientationDegrees():g} deg; "
      f"{len(results)} candidates")
seen = []
for cyc, st, r, asg in results:
    key = (cyc, st, r, asg)
    if key in seen:
        continue
    seen.append(key)
    if len(seen) > a.top:
        break
    moves = [f"{n} {pin_of[n]}->{p}" for n, p in asg if p != pin_of[n]]
    print(f"  {len(seen)}. {cyc} crossings (straight {st}), {a.b} at {r:g} deg; swaps: {', '.join(moves) or 'none'}")

if a.apply:
    cyc, st, r, asg = seen[a.apply - 1]
    shutil.copy(a.board, a.out)
    for ext in (".kicad_pro", ".kicad_dru", ".layout.json"):
        src = a.board[:-len(".kicad_pcb")] + ext
        if os.path.exists(src):
            shutil.copy(src, a.out[:-len(".kicad_pcb")] + ext)
    o = pcbnew.LoadBoard(a.out)
    f = o.FindFootprintByReference(a.b)
    pads = {func(p): p for p in f.Pads() if p.GetPinFunction()}
    old = {fn: p.GetNet() for fn, p in pads.items()}
    new_net = {}
    for n, pin in asg:
        new_net[pin] = old[pin_of[n]]
    freed = [pin_of[n] for n, pin in asg if pin != pin_of[n] and pin_of[n] not in new_net]
    spare = [old[pin] for n, pin in asg if pin != pin_of[n] and short(old[pin].GetNetname()).startswith("unconnected")]
    for pin, net in new_net.items():
        pads[pin].SetNet(net)
    for pin, net in zip(freed, spare):                             # freed pins take the no-connect nets left over
        pads[pin].SetNet(net)
    if r != f.GetOrientationDegrees():
        members = [f] + [o.FindFootprintByReference(m) for m in sorted(
            {cap for cap, ic, *_ in cfg.get("checks", {}).get("decoupling", []) if ic == a.b} |
            {ra for ra, _, rb, *_ in cfg.get("checks", {}).get("pad_distance", []) if rb == a.b} |
            {rb for ra, _, rb, *_ in cfg.get("checks", {}).get("pad_distance", []) if ra == a.b})]
        q = r - f.GetOrientationDegrees()
        ax, ay = ToMM(f.GetPosition().x), ToMM(f.GetPosition().y)
        c, s_ = math.cos(math.radians(q)), math.sin(math.radians(q))
        for m in members:
            x, y = ToMM(m.GetPosition().x) - ax, ToMM(m.GetPosition().y) - ay
            m.SetPosition(VECTOR2I(FromMM(ax + x * c + y * s_), FromMM(ay - x * s_ + y * c)))
            m.SetOrientationDegrees((m.GetOrientationDegrees() + q) % 360)
    o.Save(a.out)
    if r != fb.GetOrientationDegrees():
        from klib import strip_region
        xs, ys = [], []
        for m in members:
            bb = m.GetBoundingBox(False)
            xs += [ToMM(bb.GetLeft()), ToMM(bb.GetRight())]; ys += [ToMM(bb.GetTop()), ToMM(bb.GetBottom())]
        box = (min(xs) - 1.5, min(ys) - 1.5, max(xs) + 1.5, max(ys) + 1.5)
        keep = cfg.get("place_opt", {}).get("fixed_nets", []) + cfg.get("net_groups", {}).get("hv", []) + ["GH?", "GL?", "SH?", "SL?"]
        n = strip_region(a.out, box, keep)
        print(f"stripped {n} tracks/vias inside the rotated block's area {tuple(round(v, 1) for v in box)}; "
              f"run place_opt.py (it legalizes overlaps first), then plane_fanout.py")
    print(f"applied #{a.apply} to {a.out}: {a.b} at {r:g} deg, " + ", ".join(f"{n} {pin_of[n]}->{p}" for n, p in asg if p != pin_of[n]))
