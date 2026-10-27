"""Placement loop: move, rotate and swap the parts the config allows until the global routing overflow is 0, never
breaking a placement rule.

    place_opt.py BOARD --out OUT.kicad_pcb [--moves 300] [--seed 1] [--tile 1.0] [--log OUT.md]

Config "place_opt": {
  "movable": [glob],            parts the loop may move (default: C*, R*, D*, TH*, FB*, LED*)
  "fixed": [glob],              never moved, even if matched above (connectors, power stage, ICs, encoder)
  "fixed_nets": [glob],         parts with a pad on these nets never move (power stage: VBUS, PHASE_*, SHUNT_*)
  "max_shift": 3.0,             mm from the starting position, per part
  "step": 0.25,                 mm, move grid
  "rotate": true, "swap": true, "flip": false,
  "blocks": [anchor ref],       ICs moved and rotated as one rigid block with their members: every part tied to the
                                anchor by a decoupling or pad_distance check (cap, crystal, ESD part), unless fixed
  "block_shift": 2.0 }          mm, per block

Hard rules (a move that breaks one is rejected; a rule that already fails may not get worse): inside the outline
with 0.3 mm margin; courtyard boxes 0.2 mm apart on the same side; config checks (decoupling, pad_distance,
keepout_distance); keepout_circles and keepout_boxes; corridors that forbid footprints; pads not on another net's
fixed zone fill.

The plane-net fan-outs (via + stub) of the movable parts are left out of the model (they would stay behind when
the part moves); plane-net connections over their plane are not routed. Re-fan after the loop, with the demand map.

Objective: overflow of g4.Model (warm start, a few PathFinder passes after each move) plus 0.002 x route length.
Moves: a part near the worst hotspot (else any movable part) shifts by up to 1 mm, rotates 90 / 180 degrees, or
swaps place with a movable part of the same footprint, value and nets. Simulated annealing with a fixed seed: the run is
reproducible. The best state is written to --out (from the original board, so all copper stays as it was) and a
final cold solve is reported. Exit 0 when the final overflow is 0."""
import argparse, fnmatch, math, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I
from klib import load_config, rgap, short
from g4 import Model

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--out", required=True); ap.add_argument("--moves", type=int, default=300)
ap.add_argument("--seed", type=int, default=1); ap.add_argument("--tile", type=float, default=1.0)
ap.add_argument("--passes", type=int, default=6, help="PathFinder passes after each move")
ap.add_argument("--log")
ap.add_argument("--baseline", help="board whose courtyard overlaps are accepted (e.g. before a block rotation): only new overlaps are legalized")
a = ap.parse_args()
cfg = load_config(a.board)
P = cfg.get("place_opt", {})
mov_g = P.get("movable", ["C*", "R*", "D*", "TH*", "FB*", "LED*"])
fix_g = P.get("fixed", [])
MAX_SHIFT, STEP = P.get("max_shift", 3.0), P.get("step", 0.25)
rng = random.Random(a.seed)

probe = pcbnew.LoadBoard(a.board)
refs = sorted(f.GetReference() for f in probe.GetFootprints())
fix_nets = P.get("fixed_nets", [])
on_fixed_net = lambda r: any(any(fnmatch.fnmatchcase(short(p.GetNetname()), g) for g in fix_nets) for p in probe.FindFootprintByReference(r).Pads())
movable = [r for r in refs if any(fnmatch.fnmatchcase(r, g) for g in mov_g) and not any(fnmatch.fnmatchcase(r, g) for g in fix_g)
           and not probe.FindFootprintByReference(r).IsLocked() and not on_fixed_net(r)]
CK = cfg.get("checks", {})
blocks = {}
for anc in P.get("blocks", []):
    mem = {cap for cap, ic, *_ in CK.get("decoupling", []) if ic == anc}
    mem |= {ra for ra, _, rb, *_ in CK.get("pad_distance", []) if rb == anc} | {rb for ra, _, rb, *_ in CK.get("pad_distance", []) if ra == anc}
    mem = sorted(r for r in mem if r != anc and not any(fnmatch.fnmatchcase(r, g) for g in fix_g) and not on_fixed_net(r))
    blocks[anc] = [anc] + mem
for grp in blocks.values():
    for r in grp:
        if r not in movable:
            movable.append(r)
BLOCK_SHIFT = P.get("block_shift", 2.0)
del probe
t0 = time.time()
m = Model(a.board, cfg, tile=a.tile, movable=movable, refan=movable)
b, fp = m.b, m.fp
start = {r: (ToMM(fp[r].GetPosition().x), ToMM(fp[r].GetPosition().y), fp[r].GetOrientationDegrees(), fp[r].IsFlipped()) for r in movable}
print(f"model built in {time.time() - t0:.1f} s: {len(m.conns)} connections, {len(movable)} movable parts", file=sys.stderr)


# ---- geometry and rules
def court_box(ref):
    f = fp[ref]
    c = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
    bb = c.BBox() if c.OutlineCount() else f.GetBoundingBox(False)
    r = [ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())]
    for p in f.Pads():
        pb = p.GetBoundingBox()
        r = [min(r[0], ToMM(pb.GetLeft())), min(r[1], ToMM(pb.GetTop())), max(r[2], ToMM(pb.GetRight())), max(r[3], ToMM(pb.GetBottom()))]
    return tuple(r)


def court_poly(ref):
    f = fp[ref]
    c = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
    return c if c.OutlineCount() else None


def too_close(r1, r2, gap=0.2):
    """Courtyards closer than `gap` (real polygons; the box test only rules pairs out)."""
    if rgap(court_box(r1), court_box(r2)) >= gap:
        return False
    c1, c2 = court_poly(r1), court_poly(r2)
    if c1 is None or c2 is None:
        return True
    g = FromMM(gap)
    return c1.Collide(c2.Outline(0), g) or c2.Collide(c1.Outline(0), g)


def side_of(ref):
    f = fp[ref]
    th = any(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in f.Pads())
    return {"F", "B"} if th else ({"B"} if f.IsFlipped() else {"F"})


def pad_box(p):
    bb = p.GetBoundingBox()
    return ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())


def pad(ref, num):
    return [p for p in fp[ref].Pads() if p.GetNumber() == num][0]


C = cfg.get("checks", {})


def check_values(ref):
    """Values of every config check that involves `ref`: list of (key, value, limit, kind) with kind max/min."""
    out = []
    for cap, ic, pin, net, lim in C.get("decoupling", []):
        if ref in (cap, ic):
            try:
                v = min(rgap(pad_box(p), pad_box(pad(ic, pin))) for p in fp[cap].Pads() if short(p.GetNetname()) == short(net))
            except (ValueError, IndexError, KeyError):
                continue
            out.append((("dec", cap, ic, pin), v, lim, "max"))
    for ra, pa, rb, pb, lim, label in C.get("pad_distance", []):
        if ref in (ra, rb):
            out.append((("pad", ra, pa, rb, pb), rgap(pad_box(pad(ra, pa)), pad_box(pad(rb, pb))), lim, "max"))
    for k in C.get("keepout_distance", []):
        if not any(fnmatch.fnmatchcase(ref, g) for g in k.get("refs", ["*"])) and ref != k.get("center_ref"):
            continue
        if "center_ref" in k:
            c = fp[k["center_ref"]].GetPosition(); cx, cy = ToMM(c.x), ToMM(c.y)
        else:
            cx, cy = k["center"]
        best = 1e9
        for r2 in ([ref] if ref != k.get("center_ref") else [r for r in fp if any(fnmatch.fnmatchcase(r, g) for g in k.get("refs", ["*"]))]):
            if r2 == k.get("center_ref"):
                continue
            for p in fp[r2].Pads():
                if any(fnmatch.fnmatchcase(short(p.GetNetname()), g) for g in k["nets"]):
                    best = min(best, math.hypot(ToMM(p.GetPosition().x) - cx, ToMM(p.GetPosition().y) - cy))
        if best < 1e9:
            out.append((("keep", k["label"], ref), best, k["min"], "min"))
    return out


def ok_value(v, lim, kind, before):
    good = v <= lim + 1e-9 if kind == "max" else v >= lim - 1e-9
    if good:
        return True
    if before is None:
        return False
    return v <= before + 1e-9 if kind == "max" else v >= before - 1e-9      # already failing: no worse


def segdist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def box_seg_dist(bx, s):
    (ax, ay), (cx, cy) = s
    x0, y0, x1, y1 = bx
    if x0 <= ax <= x1 and y0 <= ay <= y1:
        return 0.0
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    d = min(segdist(px, py, ax, ay, cx, cy) for px, py in pts)
    return min(d, min(segdist(px, py, *pts[i], *pts[(i + 1) % 4]) for px, py in ((ax, ay), (cx, cy)) for i in range(4)))


corridor_segs = []
for cd in cfg.get("corridors", []):
    if "footprints" not in cd.get("forbid", []):
        continue
    if "path" in cd:
        pts = cd["path"]
    else:
        ra, pa = cd["from"].split("."); rb, pb = cd["to"].split(".")
        pts = [(ToMM(pad(ra, pa).GetPosition().x), ToMM(pad(ra, pa).GetPosition().y)), (ToMM(pad(rb, pb).GetPosition().x), ToMM(pad(rb, pb).GetPosition().y))]
    for s in zip(pts, pts[1:]):
        corridor_segs.append((s, cd["width"] / 2, set(cd.get("layers", ["F", "B"]))))


def zone_clash(ref):
    """Pad cells of `ref` on another net's fixed zone fill (count)."""
    n = 0
    for p in fp[ref].Pads():
        for ln in ("F", "B"):
            if not p.IsOnLayer(pcbnew.F_Cu if ln == "F" else pcbnew.B_Cu):
                continue
            zn = m.zone_net[ln]
            x0, y0, x1, y1 = pad_box(p)
            i0, j0 = m.fine.ij(x0, y0); i1, j1 = m.fine.ij(x1, y1)
            for j in range(max(0, j0), min(m.fine.ny, j1 + 1)):
                for i in range(max(0, i0), min(m.fine.nx, i1 + 1)):
                    v = zn[j][i]
                    if v and v != p.GetNetCode():
                        n += 1
    return n


base_rules = {r: {k: v for k, v, _, _ in check_values(r)} for r in movable}
start_gap = {}                                                  # pairs already closer than 0.2 mm may stay, not shrink
for r in movable:
    for r2 in fp:
        if r2 != r and side_of(r2) & side_of(r):
            g = rgap(court_box(r), court_box(r2))
            if g < 0.2:
                start_gap[(r, r2)] = g
base_zone = {r: zone_clash(r) for r in movable}


def legal(ref):
    bx = court_box(ref)
    if bx[0] < m.X0 + 0.3 or bx[1] < m.Y0 + 0.3 or bx[2] > m.X1 - 0.3 or bx[3] > m.Y1 - 0.3:
        return "outside board"
    sides = side_of(ref)
    for r2, f2 in fp.items():
        if r2 == ref or not (side_of(r2) & sides):
            continue
        if not too_close(ref, r2):
            continue
        g = rgap(bx, court_box(r2))
        if g < start_gap.get((ref, r2), start_gap.get((r2, ref), 0.2)) - 1e-6:
            return f"courtyard {r2}"
    for k, v, lim, kind in check_values(ref):
        if not ok_value(v, lim, kind, base_rules.get(ref, {}).get(k)):
            return f"rule {k}"
    for cx, cy, r, side, *_ in cfg.get("keepout_circles", []):
        if side in sides and rgap(bx, (cx, cy, cx, cy)) < r:
            return "keep-out circle"
    for x1, y1, x2, y2, side, label, *ex in cfg.get("keepout_boxes", []):
        if side in sides and ref not in (ex[0] if ex else []) and rgap(bx, (x1, y1, x2, y2)) <= 0:
            return f"keep-out {label}"
    for s, hw, ls in corridor_segs:
        if ls & sides and box_seg_dist(bx, s) < hw:
            return "corridor"
    if zone_clash(ref) > base_zone.get(ref, 0):
        return "on another net's zone"
    return None


# ---- legalize: parts that overlap a courtyard (after a block rotation, a hand edit) go to the nearest legal spot
def strict_overlaps(ref):
    bx, sides = court_box(ref), side_of(ref)
    return [r2 for r2 in fp if r2 != ref and (ref, r2) not in old_pairs and side_of(r2) & sides and too_close(ref, r2)]


old_pairs = set()
if a.baseline:
    bl = pcbnew.LoadBoard(a.baseline)
    def _box(f):
        c = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
        bb = c.BBox() if c.OutlineCount() else f.GetBoundingBox(False)
        r = [ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())]
        for p in f.Pads():
            pb = p.GetBoundingBox()
            r = [min(r[0], ToMM(pb.GetLeft())), min(r[1], ToMM(pb.GetTop())), max(r[2], ToMM(pb.GetRight())), max(r[3], ToMM(pb.GetBottom()))]
        return tuple(r), ({"B"} if f.IsFlipped() else {"F"}) if not any(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in f.Pads()) else {"F", "B"}
    bx_ = {f.GetReference(): _box(f) for f in bl.GetFootprints()}
    for r1, (b1, s1) in bx_.items():
        for r2, (b2, s2) in bx_.items():
            if r1 < r2 and s1 & s2 and rgap(b1, b2) < 0.2:
                old_pairs |= {(r1, r2), (r2, r1)}
    del bl
legalized, stuck = [], []
for _ in range(3):
    bad = [r for r in movable if r not in blocks and strict_overlaps(r)]            # anchors stay, neighbours move
    if not bad:
        break
    for ref in sorted(bad, key=lambda r: (r in blocks, (court_box(r)[2] - court_box(r)[0]) * (court_box(r)[3] - court_box(r)[1]))):
        if not strict_overlaps(ref):
            continue
        x, y, rot, flip = ToMM(fp[ref].GetPosition().x), ToMM(fp[ref].GetPosition().y), fp[ref].GetOrientationDegrees(), fp[ref].IsFlipped()
        saved = {k: v for k, v in start_gap.items() if ref in k and k not in old_pairs}
        for k in saved:
            del start_gap[k]
        done = False
        for d in [k * STEP for k in range(1, 17)]:
            ring = sorted({(round(x + d * math.cos(t), 3), round(y + d * math.sin(t), 3)) for t in [i * math.pi / 8 for i in range(16)]})
            for nx, ny in ring:
                for nr in (rot, (rot + 90) % 360):
                    tok = m.move(ref, nx, ny, nr)
                    if legal(ref) is None:
                        legalized.append((ref, x, y, nx, ny, nr)); done = True; break
                    m.undo(tok)
                if done:
                    break
            if done:
                break
        if not done:
            start_gap.update(saved)
            if ref not in stuck:
                stuck.append(ref)
for ref in movable:                                               # remaining overlaps are the new baseline
    for r2 in fp:
        if r2 != ref and side_of(r2) & side_of(ref):
            g = rgap(court_box(ref), court_box(r2))
            if g < 0.2:
                start_gap[(ref, r2)] = min(g, start_gap.get((ref, r2), 1))
if legalized or stuck:
    print(f"legalized {len(legalized)} parts" + (f"; could not place: {stuck}" if stuck else ""), file=sys.stderr)


# ---- objective
def score(passes):
    o = m.solve(iters=passes, warm=True)
    length = sum(len(r) for r in m.routes if r) * m.T
    return o + 0.002 * length, o


def snapshot():
    return list(m.routes)


def restore(snap):
    for k, c in enumerate(m.conns):
        if m.routes[k]:
            m._apply(m.routes[k], c, -1)
    m.routes = list(snap)
    for k, c in enumerate(m.conns):
        if m.routes[k]:
            m._apply(m.routes[k], c, +1)


m.solve(iters=30)
cur, cur_o = score(a.passes)                                     # same procedure as every candidate
best = (cur, cur_o, {r: (ToMM(fp[r].GetPosition().x), ToMM(fp[r].GetPosition().y), fp[r].GetOrientationDegrees(), fp[r].IsFlipped()) for r in movable})
print(f"start: overflow {cur_o:.2f} mm", file=sys.stderr)
log = [f"start overflow {cur_o:.2f} mm, {len(m.conns)} connections, {len(movable)} movable parts"]
def swap_key(r):
    return fp[r].GetFPIDAsString(), fp[r].GetValue(), tuple(sorted(short(p.GetNetname()) for p in fp[r].Pads()))


by_fp = {}                     # swap only identical parts: same footprint, value and nets (two crystal load caps
for r in movable:                # trade nets when swapped: the coarse model scores it, the detailed route crosses)
    by_fp.setdefault(swap_key(r), []).append(r)
temp0 = max(0.5, cur_o * 0.05)
rejected, stats = {}, {"scored": 0, "accepted": 0, "skipped": 0}
for it in range(a.moves):
    temp = temp0 * (1 - it / a.moves) + 1e-3
    spots = m.hotspots()
    near = []
    if spots:
        for s in spots[:3]:
            x0, y0, x1, y1 = s["box"]
            near += [r for r in movable if rgap(court_box(r), (x0 - 1.5, y0 - 1.5, x1 + 1.5, y1 + 1.5)) <= 0]
    pool = near or movable
    ref = rng.choice(sorted(set(pool)))
    x, y, rot, flip = ToMM(fp[ref].GetPosition().x), ToMM(fp[ref].GetPosition().y), fp[ref].GetOrientationDegrees(), fp[ref].IsFlipped()
    kind = rng.random()
    toks, moved = [], [ref]
    snap = snapshot()
    if blocks and kind < 0.3:
        anc = rng.choice(sorted(blocks)); grp = blocks[anc]
        ax, ay = ToMM(fp[anc].GetPosition().x), ToMM(fp[anc].GetPosition().y)
        if rng.random() < 0.7:
            dx, dy = 0.5 * rng.randint(-2, 2), 0.5 * rng.randint(-2, 2)
            if math.hypot(ax + dx - start[anc][0], ay + dy - start[anc][1]) > BLOCK_SHIFT or (dx, dy) == (0, 0):
                continue
            for r in grp:
                f = fp[r]
                toks.append(m.move(r, ToMM(f.GetPosition().x) + dx, ToMM(f.GetPosition().y) + dy, f.GetOrientationDegrees()))
            desc = f"block {anc} by ({dx:+.1f}, {dy:+.1f})"
        else:
            q = rng.choice((90, 180, 270)); c, s_ = round(math.cos(math.radians(q))), round(math.sin(math.radians(q)))
            for r in grp:
                f = fp[r]; x, y = ToMM(f.GetPosition().x) - ax, ToMM(f.GetPosition().y) - ay
                # KiCad y points down: a positive orientation turns counter-clockwise on screen
                toks.append(m.move(r, ax + x * c + y * s_, ay - x * s_ + y * c, (f.GetOrientationDegrees() + q) % 360))
            desc = f"block {anc} rotate {q}"
        moved = list(grp)
    elif kind < 0.65:
        nx, ny = x + STEP * rng.randint(-2, 2), y + STEP * rng.randint(-2, 2)
        sx, sy = start[ref][0], start[ref][1]
        if math.hypot(nx - sx, ny - sy) > MAX_SHIFT:
            continue
        desc = f"{ref} to ({nx:.2f}, {ny:.2f})"
        toks.append(m.move(ref, nx, ny, rot))
    elif kind < 0.88 and P.get("rotate", True):
        nr = (rot + rng.choice((90, 180, 270))) % 360
        desc = f"{ref} rotate to {nr:g}"
        toks.append(m.move(ref, x, y, nr))
    elif P.get("swap", True) and len(by_fp[swap_key(ref)]) > 1:
        other = rng.choice([r for r in by_fp[swap_key(ref)] if r != ref])
        ox, oy, orot = ToMM(fp[other].GetPosition().x), ToMM(fp[other].GetPosition().y), fp[other].GetOrientationDegrees()
        if fp[other].IsFlipped() != flip:
            continue
        desc = f"swap {ref} and {other}"
        toks.append(m.move(ref, ox, oy, orot)); toks.append(m.move(other, x, y, rot)); moved.append(other)
    else:
        continue
    why = next((w for w in (legal(r) for r in moved) if w), None)
    if why:
        for t in reversed(toks):
            m.undo(t)
        restore(snap)
        rejected[why.split(" ")[0]] = rejected.get(why.split(" ")[0], 0) + 1
        continue
    new, new_o = score(a.passes)
    stats["scored"] += 1
    if new <= cur or rng.random() < math.exp(-(new - cur) / temp):
        cur, cur_o = new, new_o
        stats["accepted"] += 1
        if new < best[0] - 1e-9:
            best = (new, new_o, {r: (ToMM(fp[r].GetPosition().x), ToMM(fp[r].GetPosition().y), fp[r].GetOrientationDegrees(), fp[r].IsFlipped()) for r in movable})
            log.append(f"move {it + 1}: {desc} -> overflow {new_o:.2f} mm (best)")
            print(f"move {it + 1}: {desc} -> overflow {new_o:.2f} mm (best)", file=sys.stderr)
        if new_o < 1e-6:
            break
    else:
        for t in reversed(toks):
            m.undo(t)
        restore(snap)

# ---- best state: write it from the original board, then a cold check
for r, (x, y, rot, flip) in best[2].items():
    m._place(r, x, y, rot, flip)
final = m.solve(iters=60)
changed = {r: v for r, v in best[2].items() if (round(v[0], 3), round(v[1], 3), v[2], v[3]) != (round(start[r][0], 3), round(start[r][1], 3), start[r][2], start[r][3])}
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
import shutil
from klib import strip_fanouts
shutil.copy(a.board, a.out)                                      # fan-outs come off at the old pad positions first
n_fan = strip_fanouts(a.out, sorted(changed), cfg) if changed else 0
out = pcbnew.LoadBoard(a.out)
for r, (x, y, rot, flip) in changed.items():
    f = out.FindFootprintByReference(r)
    if f.IsFlipped() != flip:
        f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    f.SetOrientationDegrees(rot); f.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
out.Save(a.out)
import shutil
for ext in (".kicad_pro", ".kicad_dru", ".layout.json"):
    src = a.board[:-len(".kicad_pcb")] + ext
    if os.path.exists(src):
        shutil.copy(src, a.out[:-len(".kicad_pcb")] + ext)
log.append(f"moves: {a.moves} tried, {stats['scored']} legal and scored, {stats['accepted']} accepted; "
           f"rejected by rule: {rejected}; moved parts: {len(changed)}")
for r, (x, y, rot, flip) in sorted(changed.items()):
    sx, sy, srot, _ = start[r]
    log.append(f"  {r}: ({sx:.2f}, {sy:.2f}) {srot:g} -> ({x:.2f}, {y:.2f}) {rot:g}")
log.append(f"final cold solve: overflow {final:.2f} mm (start {log[0].split()[2]} mm); time {time.time() - t0:.0f} s")
log.append(f"removed {n_fan} stale plane vias/stubs of moved parts: next run global_route.py --json G4.json on --out, then "
           f"plane_fanout.py --refan '<movable globs>' --demand G4.json")
print("\n".join(log))
if a.log:
    open(a.log, "w").write("\n".join(log) + "\n")
m.close()
sys.exit(0 if final < 1e-6 else 1)
