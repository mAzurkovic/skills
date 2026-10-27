"""Placement v13: 45 x 45 mm, two-sided. XT30 pair on the top edge with the USB-C between them (motor side),
DRV8353S on top directly over the encoder, MCU beside it, FET row on the bottom edge, 1206 shunts.
Usage (KiCad python, repo root): place_v13.py [U3rot U4rot U4side]  -- no args: rotation search, then place."""
import itertools, math, sys
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

PCB = "hw/foc_controller.kicad_pcb"
b = pcbnew.LoadBoard(PCB)
fp = {f.GetReference(): f for f in b.GetFootprints()}
X0, Y0, W = 102.5, 102.5, 45.0
CX, CY = X0 + W / 2, Y0 + W / 2
HVNETS = ("VBUS", "PHASE_", "BUCK_SW", "BUCK_BST", "DRV_VCP", "DRV_CPH", "DRV_CPL", "GHA", "GHB", "GHC")
PITCH = 5.93                                  # FET pitch along the row
ROW_START = CX - 3 * PITCH
X_FET0 = ROW_START + 2.865


def put(ref, x, y, rot=0, bottom=False):
    f = fp[ref]
    if f.IsFlipped() != bottom:
        f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    f.SetOrientationDegrees(rot)
    f.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))


def court(f):
    c = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
    return c if c.OutlineCount() else None


def box(f):
    c = court(f)
    bb = c.BBox() if c else f.GetBoundingBox(False)
    x1, y1, x2, y2 = ToMM(bb.GetLeft()) - 0.1, ToMM(bb.GetTop()) - 0.1, ToMM(bb.GetRight()) + 0.1, ToMM(bb.GetBottom()) + 0.1
    for p in f.Pads():
        pb = p.GetBoundingBox()
        m = 0.65 if any(h in str(p.GetNetname()) for h in HVNETS) else 0.25
        x1 = min(x1, ToMM(pb.GetLeft()) - m); y1 = min(y1, ToMM(pb.GetTop()) - m)
        x2 = max(x2, ToMM(pb.GetRight()) + m); y2 = max(y2, ToMM(pb.GetBottom()) + m)
    return x1, y1, x2, y2


def pad_xy(ref, num):
    p = fp[ref].FindPadByNumber(num).GetPosition()
    return ToMM(p.x), ToMM(p.y)


def pin_of(ref, net):
    for p in fp[ref].Pads():
        if str(p.GetNetname()).split("/")[-1] == net:
            return p.GetNumber()
    raise KeyError((ref, net))


def court_gap(a, c):
    """Courtyard-to-courtyard distance (mm), 0 when they overlap. Through-hole parts count on both sides."""
    pa, pc = court(fp[a]), court(fp[c])
    if pa is None or pc is None:
        return 99.0
    for k in range(0, 300):
        if pa.Collide(pc.Outline(0), FromMM(k * 0.05)) or pc.Collide(pa.Outline(0), FromMM(k * 0.05)):
            return k * 0.05
    return 99.0


# ---------------------------------------------------------------- connector edge (top edge = Y0)
put("J9", CX, Y0 + 3.65, 0, bottom=True)                     # USB-C on the motor side, between the CAN connectors
XT_C = 11.72                                                 # XT30 centres 23.44 mm apart: inner ear pegs clear the USB-C shield pins
XT_Y = Y0 + 8.05                                             # flush: footprint origin 8.05 mm behind the mating face
put("J1", CX - XT_C, XT_Y, 180)
put("J2", CX + XT_C, XT_Y, 180)
for j, x in (("J7", CX - XT_C), ("J8", CX + XT_C)):          # CAN connectors centred under each XT30, between its ear pegs
    put(j, x, Y0 + 2.45, 0, bottom=True)
    top = min(ToMM(p.GetBoundingBox().GetTop()) for p in fp[j].Pads())
    if top < Y0 + 0.5:
        put(j, x, Y0 + 2.45 + (Y0 + 0.5 - top), 0, bottom=True)

# M2.5 holes, 2.8 mm in from the side edges. Bottom pair 2.8 mm up from the bottom edge. Top pair slides down the side
# edge until its courtyard clears the XT30 (ear tabs take the top corners) by 0.2 mm.
HI = 2.8
put("H3", X0 + HI, Y0 + W - HI); put("H4", X0 + W - HI, Y0 + W - HI)
hy = Y0 + HI
while True:
    put("H1", X0 + HI, hy); put("H2", X0 + W - HI, hy)
    if court_gap("H1", "J1") >= 0.25 and court_gap("H2", "J2") >= 0.25:
        break
    hy += 0.1
TOP_HOLE_Y = hy

# ---------------------------------------------------------------- FET row (top), bottom edge
# HS rot 90: drain up, source + gate down. LS rot 270: drain down, source + gate up. HS drain pads 10 mm from the
# encoder centre (design doc: bridge copper >= 10 mm); the row sits as low as the bottom holes allow.
fets = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
FET_TOP = CY + 10.0 - 0.85
while True:
    FY = FET_TOP + 3.725
    for i, q in enumerate(fets):
        put(q, X_FET0 + i * PITCH, FY, 90 if i % 2 == 0 else 270)
    if court_gap("Q1", "H3") >= 0.2 and court_gap("Q6", "H4") >= 0.2:
        break
    FET_TOP -= 0.05
ROWB = FY + 3.725
phases = [("Q1", "Q2", "R8", "C1", "C50", "J3", "NT1", "NT2"), ("Q3", "Q4", "R9", "C5", "C51", "J4", "NT3", "NT4"),
          ("Q5", "Q6", "R10", "C9", "C52", "J5", "NT5", "NT6")]
for hs, ls, rs, cap, hf, jm, ntp, ntn in phases:
    pc = (ToMM(fp[hs].GetPosition().x) + ToMM(fp[ls].GetPosition().x)) / 2
    # Motor side, directly under the pair: 1206 shunt under the source rows (pad 1 SHUNT under the LS on the right,
    # pad 2 GND under the HS), 4.7 uF + 100 nF under the HS drain row.
    sy = FET_TOP + 1.975
    put(rs, pc, sy, 0, bottom=True)
    if pad_xy(rs, "1")[0] < pc:
        put(rs, pc, sy, 180, bottom=True)
    # Kelvin taps: net tie pad 1 on the inner top corner of each shunt pad, pad 2 (sense) 1 mm above it, so the
    # SPx / SNx pair leaves from the inner pad edges toward the DRV.
    for nt, num in ((ntp, "1"), (ntn, "2")):
        px, py = pad_xy(rs, num)
        x = px - 0.6 if px > pc else px + 0.6
        put(nt, x, py - 0.9 - 0.5 + 0.15, 90, bottom=True)
        if pad_xy(nt, "1")[1] < pad_xy(nt, "2")[1]:       # pad 1 (shunt net) must be the lower one
            put(nt, x, py - 0.9 - 0.5 + 0.15, 270, bottom=True)
    put(cap, pc - 3.4, FET_TOP + 4.15 + 1.645, 0, bottom=True)
    put(hf, pc + 1.6, FET_TOP + 4.15 + 1.645, 0, bottom=True)
    put(jm, pc, ROWB + 2.8)                                   # motor wire pad below the pair, between the bottom holes
cells = {q for p in phases for q in p}

# Bulk caps on the motor side beside the FET row, outside the magnet area; edge columns lie along the edge.
for k, c in enumerate(("C2", "C3", "C4")):
    put(c, X0 + 2.9, FET_TOP - 0.3 - 2.45 - (2 - k) * 4.95, 90, bottom=True)
for k, c in enumerate(("C6", "C7", "C44")):
    put(c, X0 + 8.0, FET_TOP - 10.45 + k * 3.5, 0, bottom=True)
for k, c in enumerate(("C8", "C10")):
    put(c, X0 + W - 2.9, FET_TOP - 0.3 - 2.45 - (1 - k) * 4.95, 90, bottom=True)
for k, c in enumerate(("C45", "C46", "C49")):
    put(c, X0 + W - 8.0, FET_TOP - 10.45 + k * 3.5, 0, bottom=True)
cells |= {"C2", "C3", "C4", "C6", "C7", "C8", "C10", "C44", "C45", "C46", "C49"}
fixed = {"J9", "J1", "J2", "J7", "J8", "H1", "H2", "H3", "H4"} | cells | set(fets)

# ---------------------------------------------------------------- DRV over the encoder, MCU beside it
put("U5", CX, CY, 0, bottom=True)                            # encoder, motor side, board centre (magnet axis)
put("U3", CX, CY, 0)                                         # DRV8353S directly above it


# Ratsnest crossings among the signal links of the big parts (passives not placed yet: links between placed parts only).
BIG = {"U3", "U4", "U5"} | set(fets) | {"NT1", "NT2", "NT3", "NT4", "NT5", "NT6", "J7", "J8", "J9", "J6"}
PLANE = ("GND", "", "+3V3", "VBUS")


def links(refs, placed):
    out = []
    for ref in refs:
        for p in fp[ref].Pads():
            n = str(p.GetNetname()).split("/")[-1]
            if n in PLANE or n.startswith("unconnected"):
                continue
            others = [q for r2 in placed if r2 != ref for q in fp[r2].Pads() if q.GetNetCode() == p.GetNetCode()]
            if not others:
                continue
            a = p.GetPosition()
            c = min((q.GetPosition() for q in others), key=lambda c: (c - a).EuclideanNorm())
            s = ((ToMM(a.x), ToMM(a.y)), (ToMM(c.x), ToMM(c.y)))
            if (s[1], s[0]) not in out:
                out.append(s)
    return out


def crosses(s, t):
    o = lambda a, b, c: (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    return o(*s, t[0]) * o(*s, t[1]) < 0 and o(*t, s[0]) * o(*t, s[1]) < 0


def crossings(segs):
    return sum(crosses(s, t) for s, t in itertools.combinations(segs, 2))


U4X = {"R": CX + 10.6, "L": CX - 10.6}
U4Y = CY - 1.5
def place_u4(rot, side):
    put("U4", U4X[side], U4Y, rot)


if len(sys.argv) > 1:
    choice = (int(sys.argv[1]), int(sys.argv[2]), sys.argv[3])
else:
    results = []
    placed = BIG - {"J6"}
    for r3 in (0, 90, 180, 270):
        put("U3", CX, CY, r3)
        for side in ("R",):                                   # left side holds the buck (VBUS in at J1)
            for r4 in (0, 90, 180, 270):
                place_u4(r4, side)
                segs = links(["U3", "U4"], placed)
                bus = [s for s in links(["U3"], {"U3", "U4"})]
                results.append((crossings(segs), crossings(bus), r3, r4, side))
    results.sort()
    print("rotation search (all crossings among U3/U4 links to placed parts, U3-U4 bus crossings, U3 rot, U4 rot, U4 side):")
    for r in results:
        print("  ", r)
    choice = (results[0][2], results[0][3], results[0][4])
put("U3", CX, CY, choice[0])
place_u4(choice[1], choice[2])
print("chosen U3 rot", choice[0], "U4 rot", choice[1], "U4 side", choice[2])

# Buck on the left, in the strip between J1's power pins and the gate-A path: L1 at the edge (SW pad up),
# U1 beside it (SW / BST / RCL / GND pins facing L1), catch diode D1 under the L1-U1 junction, BST cap C14 and
# VIN cap C12 above U1 under J1. Everything else of the buck goes below by the pad-gap search.
BY = Y0 + 18.4
BL = court_of_box = None
orient_later = []
put("TH1", X_FET0 + 2 * PITCH - 1.2, FET_TOP - 2.8, 0)       # NTC just above Q3, above the via strip


def orient(ref, x, y, rot, net, tx, ty):
    """Place at (x, y) with rotation rot or rot + 180, whichever puts the `net` pad nearer (tx, ty)."""
    best = None
    for r in (rot, (rot + 180) % 360):
        put(ref, x, y, r)
        p = [q for q in fp[ref].Pads() if str(q.GetNetname()).split("/")[-1] == net][0].GetPosition()
        d = math.hypot(ToMM(p.x) - tx, ToMM(p.y) - ty)
        if best is None or d < best[0]:
            best = (d, r)
    put(ref, x, y, best[1])


# DRV supply caps by hand (DRV rot 0: pins 1-5 CPL/CPH/VBUS/VBUS/VCP on the west side, upper half; 38-40
# DVDD/GND/VGLS at the west end of the north side). West of pins 1-5: CP flying cap C20 above, VCP cap C19 below,
# both lying along the pins, a 0.85 mm lane between them for the CPH trace; VM cap C18 beyond C19. North of pins
# 38-40: DVDD cap C22 over pin 38, VGLS cap C21 to its west. Gate A / sense A leave the west side below C19.
assert choice[0] == 0, "DRV cap cluster is laid out for DRV rot 0"
orient("C20", CX - 5.15, CY - 3.4, 0, "DRV_CPL", CX - 3.0, CY - 2.25)
orient("C19", CX - 5.15, CY - 1.15, 0, "DRV_VCP", CX - 3.0, CY - 0.25)
orient("C18", CX - 7.9, CY - 1.6, 90, "VBUS", CX - 3.0, CY - 0.75)
orient("C22", CX - 1.75, CY - 5.0, 90, "DRV_DVDD", CX - 1.25, CY - 3.0)
orient("C21", CX - 3.99, CY - 6.4, 90, "DRV_VGLS", CX - 2.25, CY - 3.0)
put("L1", X0 + 3.4, BY, 270)
if pad_xy("L1", pin_of("L1", "BUCK_SW"))[1] > BY:
    put("L1", X0 + 3.4, BY, 90)
l1r = ToMM(court(fp["L1"]).BBox().GetRight())
put("U1", 0, 0, 0)
u1w = ToMM(court(fp["U1"]).BBox().GetWidth()) / 2
put("U1", l1r + 0.25 + u1w, BY, 0)
d1 = court(fp["D1"]); put("D1", 0, 0, 0)
put("D1", X0 + 7.0, BY + ToMM(court(fp["L1"]).BBox().GetHeight()) / 2 + 0.25 + 1.4, 0)
ux = ToMM(fp["U1"].GetPosition().x)
orient("D1", ToMM(fp["D1"].GetPosition().x), ToMM(fp["D1"].GetPosition().y), 0, "BUCK_SW", ux - 2.11, BY - 0.97)
orient("C14", ux - 1.5, BY - 2.85, 0, "BUCK_BST", ux - 2.11, BY - 0.33)
orient("C12", ux + 1.9, BY - 2.85, 0, "VBUS", ux + 2.11, BY - 0.97)
for ref in ("L1", "U1", "D1", "C14", "C12"):
    fixed.add(ref)
print("buck: L1", round(ToMM(fp["L1"].GetPosition().x), 2), "U1", round(ux, 2))
                          # CAN termination switch on top between the XT30s, beside J2
fixed |= {"U3", "U4", "U5", "TH1", "C18", "C19", "C20", "C21", "C22"}

occ = {False: [], True: []}
PLACED = set()
def add_occ(r):
    PLACED.add(r)
    f = fp[r]; occ[f.IsFlipped()].append((r, box(f)))
    for p in f.Pads():
        if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
            pb = p.GetBoundingBox(); m = 0.65 if any(h in str(p.GetNetname()) for h in HVNETS) else 0.3
            occ[not f.IsFlipped()].append((r, (ToMM(pb.GetLeft()) - m, ToMM(pb.GetTop()) - m, ToMM(pb.GetRight()) + m, ToMM(pb.GetBottom()) + m)))
for r in fixed:
    add_occ(r)
for h in ("H1", "H2", "H3", "H4"):                           # NPTH: block both sides with the screw head
    x, y = ToMM(fp[h].GetPosition().x), ToMM(fp[h].GetPosition().y)
    occ[True].append((h, (x - 2.95, y - 2.95, x + 2.95, y + 2.95)))


def inside(x1, y1, x2, y2):
    return x1 >= X0 + 0.3 and y1 >= Y0 + 0.3 and x2 <= X0 + W - 0.3 and y2 <= Y0 + W - 0.3


RINGS = []
CUR = [None]
ESC_OK = {}


def free(bx, bottom):
    if not inside(*bx):
        return False
    x1, y1, x2, y2 = bx
    if bottom:
        for cx, cy, r in RINGS:
            if math.hypot(max(x1 - cx, 0, cx - x2), max(y1 - cy, 0, cy - y2)) < r:
                return False
    for name, (a1, b1, a2, b2) in occ[bottom]:
        if name in ESC_OK and CUR[0] in ESC_OK[name]:
            continue
        if x1 < a2 and x2 > a1 and y1 < b2 and y2 > b1:
            return False
    return True


def near(ref, aref, apad, net=None, bottom=False, maxd=10.0, zone=None):
    CUR[0] = ref
    f = fp[ref]
    ax, ay = pad_xy(aref, apad) if apad else (ToMM(fp[aref].GetPosition().x), ToMM(fp[aref].GetPosition().y))
    best = None
    tht = any(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in f.Pads())
    for rot in (0, 90, 180, 270):
        put(ref, ax, ay, rot, bottom)
        for d in [i * 0.25 for i in range(2, int(maxd / 0.25))]:
            if best and d > best[0] + 2.5:
                break
            for ang in range(0, 360, 10):
                x = ax + d * math.cos(math.radians(ang)); y = ay + d * math.sin(math.radians(ang))
                f.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
                bx = box(f)
                if not free(bx, bottom) or (tht and not free(bx, not bottom)):
                    continue
                if zone and not (bx[0] >= zone[0] and bx[1] >= zone[1] and bx[2] <= zone[2] and bx[3] <= zone[3]):
                    continue
                pads = [p for p in f.Pads() if net is None or str(p.GetNetname()).endswith(net)] or list(f.Pads())
                p = pads[0].GetPosition()
                s = math.hypot(ToMM(p.x) - ax, ToMM(p.y) - ay)
                if best is None or s < best[0] - 1e-6:
                    best = (s, x, y, rot)
    if best is None:
        return False
    put(ref, best[1], best[2], best[3], bottom)
    add_occ(ref)
    print(f"{ref:5} -> {aref}.{apad} {best[0]:.2f} mm{' (motor side)' if bottom else ''}")
    return True


def grid(ref, aref, apad, net=None, bottom=False, step=0.5):
    CUR[0] = ref
    f = fp[ref]; ax, ay = pad_xy(aref, apad); best = None
    for rot in (0, 90, 180, 270):
        put(ref, X0, Y0, rot, bottom)
        for i in range(int(W / step)):
            for j in range(int(W / step)):
                x, y = X0 + j * step, Y0 + i * step
                f.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
                bx = box(f)
                tht = any(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in f.Pads())
                if not free(bx, bottom) or (tht and not free(bx, not bottom)):
                    continue
                pads = [p for p in f.Pads() if net is None or str(p.GetNetname()).endswith(net)] or list(f.Pads())
                p = pads[0].GetPosition(); d = math.hypot(ToMM(p.x) - ax, ToMM(p.y) - ay)
                if best is None or d < best[0]:
                    best = (d, x, y, rot)
    if best is None:
        print("NO SPOT (grid)", ref, "bottom" if bottom else "top"); return False
    put(ref, best[1], best[2], best[3], bottom); add_occ(ref)
    print(f"{ref:5} -> {aref}.{apad} {best[0]:.2f} mm (grid{', motor side' if bottom else ''})")
    return True


def pad_gap(p, q):
    a, c = p.GetBoundingBox(), q.GetBoundingBox()
    dx = max(ToMM(a.GetLeft()) - ToMM(c.GetRight()), ToMM(c.GetLeft()) - ToMM(a.GetRight()), 0)
    dy = max(ToMM(a.GetTop()) - ToMM(c.GetBottom()), ToMM(c.GetTop()) - ToMM(a.GetBottom()), 0)
    return math.hypot(dx, dy)


CHANNELS = {False: [], True: []}                             # routing channels kept free of small parts: (box, allowed refs)


HVSET = ("VBUS", "PHASE_", "BUCK_SW", "BUCK_BST", "DRV_VCP", "DRV_CPH", "DRV_CPL", "GHA", "GHB", "GHC")


def is_hv(n):
    return any(n.startswith(h) for h in HVSET)


def rect_of(f):
    """Courtyard bbox, grown to cover the pads (some library courtyards are smaller than their pads)."""
    c = court(f); bb = c.BBox() if c else f.GetBoundingBox(False)
    x1, y1, x2, y2 = ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())
    for p in f.Pads():
        pb = p.GetBoundingBox()
        x1 = min(x1, ToMM(pb.GetLeft())); y1 = min(y1, ToMM(pb.GetTop())); x2 = max(x2, ToMM(pb.GetRight())); y2 = max(y2, ToMM(pb.GetBottom()))
    return x1, y1, x2, y2


def rgap(a, c):
    return math.hypot(max(a[0] - c[2], c[0] - a[2], 0), max(a[1] - c[3], c[1] - a[3], 0))


NEAR = [None]


def fits(ref, bottom):
    """Real rules for a small part: courtyard 0.2 mm from every placed part on the same side (through-hole parts on
    both), pad clearance 0.2 mm (0.6 mm between high-voltage and other nets outside chip courtyards), board edge,
    magnet ring, routing channels."""
    f = fp[ref]; me = rect_of(f)
    if not inside(*me):
        return False
    if ref in ("C47", "C48") and math.hypot(max(me[0] - CX, 0, CX - me[2]), max(me[1] - CY, 0, CY - me[3])) < 10.0:
        return False                                          # bus copper >= 10 mm from the encoder
    if bottom:
        for cx, cy, r in RINGS:
            if math.hypot(max(me[0] - cx, 0, cx - me[2]), max(me[1] - cy, 0, cy - me[3])) < r:
                return False
    for c, ok in CHANNELS[bottom]:
        if ref not in ok and me[0] < c[2] and me[2] > c[0] and me[1] < c[3] and me[3] > c[1]:
            return False
    mine = [(str(p.GetNetname()).split("/")[-1], p.GetBoundingBox()) for p in f.Pads()]
    for o in (NEAR[0] if NEAR[0] is not None else PLACED):
        g = fp[o]
        th = any(p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) for p in g.Pads())
        if g.IsFlipped() != bottom and not th:
            continue
        orc = rect_of(g)
        if rgap(me, orc) > 1.0:
            continue
        if (g.IsFlipped() == bottom or o[0] == "H") and o[0] != "U" and rgap(me, orc) < 0.2:
            return False
        for p in g.Pads():
            n2 = str(p.GetNetname()).split("/")[-1]
            pb = p.GetBoundingBox(); r2 = (ToMM(pb.GetLeft()), ToMM(pb.GetTop()), ToMM(pb.GetRight()), ToMM(pb.GetBottom()))
            for n1, mb in mine:
                if n1 == n2 and n1:
                    continue
                need = 0.6 if (is_hv(n1) != is_hv(n2) and o[0] not in "UQ") else 0.2
                r1 = (ToMM(mb.GetLeft()), ToMM(mb.GetTop()), ToMM(mb.GetRight()), ToMM(mb.GetBottom()))
                if rgap(r1, r2) < need:
                    return False
        if o[0] == "U" and g.IsFlipped() == bottom:              # chips: courtyard rule against the true courtyard
            c = court(g); cb = c.BBox() if c else None
            if cb is not None:
                cr = (ToMM(cb.GetLeft()), ToMM(cb.GetTop()), ToMM(cb.GetRight()), ToMM(cb.GetBottom()))
                mc = court(f); mb2 = mc.BBox()
                mr = (ToMM(mb2.GetLeft()), ToMM(mb2.GetTop()), ToMM(mb2.GetRight()), ToMM(mb2.GetBottom()))
                if rgap(mr, cr) < 0.2:
                    return False
    for name, (a1, b1, a2, b2) in occ[bottom]:                    # keep-out boxes (via strips, vbus rings), not parts
        if name in PLACED or name.startswith("escape") or name in ("H1", "H2", "H3", "H4"):
            continue
        if me[0] < a2 and me[2] > a1 and me[1] < b2 and me[3] > b1:
            return False
    return True


def tight(ref, aref, apin, net, bottom=False, reach=5.0, step=0.15, other=None, commit=True):
    """Decoupling placement: the free spot (0.1 mm grid, 4 rotations) with the smallest pad-edge gap between the cap's
    `net` pad and the IC pin; `other` = (pin, net) adds the gap of the cap's second pad to a second pin."""
    CUR[0] = ref
    f = fp[ref]; ax, ay = pad_xy(aref, apin); pin = fp[aref].FindPadByNumber(apin)
    pin2 = fp[aref].FindPadByNumber(other[0]) if other else None
    best = None
    n = int(reach / step)
    NEAR[0] = [o for o in PLACED if rgap(rect_of(fp[o]), (ax - reach - 3, ay - reach - 3, ax + reach + 3, ay + reach + 3)) == 0]
    for rot in (0, 90, 180, 270):
        put(ref, ax, ay, rot, bottom)
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                x, y = ax + j * step, ay + i * step
                f.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
                if not fits(ref, bottom):
                    continue
                pads = {str(p.GetNetname()).split("/")[-1]: p for p in f.Pads()}
                g = pad_gap(pads[net], pin)
                if pin2 is not None:
                    g += pad_gap(pads[other[1]], pin2)
                if best is None or g < best[0] - 1e-6:
                    best = (g, x, y, rot)
    NEAR[0] = None
    if not commit:
        return best
    if best is None:
        print("NO SPOT (tight)", ref); return False
    put(ref, best[1], best[2], best[3], bottom); add_occ(ref)
    print(f"{ref:5} -> {aref}.{apin} pad gap {best[0]:.2f} mm (tight{', motor side' if bottom else ''})")
    return True


near("C40", "U5", "11", "+3V3", bottom=True, maxd=4)
RINGS.append((CX, CY, 7.5))                                  # magnet area: no other motor-side parts within 7.5 mm
# Escape rings, 1.3 mm around the MCU and the DRV on both sides: only each chip's own supply caps (and the crystal) inside.
for chip, ok in (("U4", {"C24", "C25", "C26", "C28", "C30", "Y1", "C32", "C33"}), ("U3", {"C18", "C19", "C20", "C21", "C22", "C23"})):
    x1, y1, x2, y2 = box(fp[chip])
    occ[False].append((f"escape {chip}", (x1 - 1.3, y1 - 1.3, x2 + 1.3, y2 + 1.3)))
    occ[True].append((f"escape {chip} bottom", (x1 - 1.3, y1 - 1.3, x2 + 1.3, y2 + 1.3)))
    ESC_OK[f"escape {chip}"] = ok
    ESC_OK[f"escape {chip} bottom"] = ok - {"Y1", "C32", "C33"}
# Routing channels next to the DRV and between DRV and MCU, kept free of other parts' caps.
CHANNELS[False] += [
    ((CX - 6.3, CY - 0.1, CX - 3.3, CY + 3.4), set()),                    # GHA / SHA / GLA / SPA / SNA fan-out, west then south
    ((CX - 1.0, CY - 8.0, CX + 2.6, CY - 3.3), set()),                    # INHx / INLx / EN, north then east to the MCU
    ((CX - 2.6, CY + 3.3, CX + 2.6, FET_TOP - 0.2), set()),               # gates B / C and sense B / C, south to the FETs
    ((CX + 3.3, CY - 2.6, ToMM(fp["U4"].GetPosition().x) - 4.4, CY + 2.6), {"C23", "C26"}),   # SOx, SPI, nFAULT to the MCU
]
# Via strips above each FET pair (both sides): HS drain to the inner VBUS layer, LS source down to the shunt.
for i in range(3):
    pcx = X_FET0 + 2 * i * PITCH + PITCH / 2
    for side in (False, True):
        occ[side].append(("via strip", (pcx - 5.5, FET_TOP - 2.25, pcx + 6.1, FET_TOP)))
# XT30 power pins are hand-soldered from the motor side after reflow: motor-side parts 3 mm clear of them.
for xt in ("J1", "J2"):
    for n in ("1", "2"):
        px, py = pad_xy(xt, n)
        RINGS.append((px, py, 1.4 + 3.0))


def vbus_keepout(bottom):
    out = []
    for f in b.GetFootprints():
        for p in f.Pads():
            if str(p.GetNetname()).endswith("VBUS") and (f.IsFlipped() == bottom or p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH):
                pb = p.GetBoundingBox()
                out.append(("vbus 5 mm", (ToMM(pb.GetLeft()) - 5.0, ToMM(pb.GetTop()) - 5.0, ToMM(pb.GetRight()) + 5.0, ToMM(pb.GetBottom()) + 5.0)))
    return out


TOPY = Y0 + 8.0
u4x = ToMM(fp["U4"].GetPosition().x)
MCUSIDE = (CX + 3.0, TOPY, X0 + W - 0.3, FET_TOP - 0.2) if u4x > CX else (X0 + 0.3, TOPY, CX - 3.0, FET_TOP - 0.2)
BUCKZ = (X0 + 0.3, Y0 + 7.0, CX - 4.0, FET_TOP - 0.2)
DRVZ = (CX - 9.0, TOPY, CX + 9.0, FET_TOP - 0.2)
MID = (CX - 6.5, Y0 + 8.7, CX + 6.5, Y0 + 17.5)
BOT = (X0 + 0.5, Y0 + 6.6, X0 + W - 0.5, FET_TOP - 0.3)
U4P = lambda net: ("U4", pin_of("U4", net))
U3P = lambda net: ("U3", pin_of("U3", net))
plan = [
    ("C47", "J1", "2", "VBUS", None), ("C48", "J2", "2", "VBUS", None),
    ("C23", "U3", "24", "+3V3", DRVZ),
    ("C24", "U4", "23", "+3V3", MCUSIDE), ("C25", "U4", "35", "+3V3", MCUSIDE), ("C26", "U4", "48", "+3V3", MCUSIDE),
    ("C30", "U4", "20", "+3V3", MCUSIDE), ("C28", "U4", "21", "+3V3", MCUSIDE),
    ("Y1", "U4", "5", "XTAL_IN", MCUSIDE), ("C32", "Y1", "1", "XTAL_IN", MCUSIDE), ("C33", "Y1", "3", "XTAL_OUT", MCUSIDE),
    ("C34", "U4", "7", "NRST", MCUSIDE), ("C27", "U4", "1", "+3V3", MCUSIDE), ("C29", "U4", "21", "+3V3", MCUSIDE), ("C31", "U4", "20", "+3V3", MCUSIDE),
    ("C11", "U1", "8", "VBUS", BUCKZ), ("C15", "L1", "2", "BUCK_ESR", BUCKZ),
    ("C13", "U1", "7", "BUCK_VCC", BUCKZ), ("R1", "U1", "6", "BUCK_RT", BUCKZ), ("R2", "U1", "3", "BUCK_RCL", BUCKZ),
    ("R4", "U1", "5", "BUCK_FB", BUCKZ), ("R3", "U1", "5", "BUCK_FB", BUCKZ),
    ("R5", "L1", "2", "+5V_BUCK", BUCKZ),
    ("D4", "U4", "18", None, MCUSIDE), ("R12", "D4", "1", "LED_G_A", None), ("R13", "D4", "2", "LED_R_A", None),
    # 5 V power path on top between the XT30s: diode-OR of buck and USB 5 V right at the LDO input.
    ("U2", "J9", "A9", None, MID), ("C16", "U2", "1", "+5V", MID), ("C17", "U2", "5", "+3V3", MID),
    ("D2", "U2", "1", "+5V", None), ("D3", "U2", "1", "+5V", None), ("C43", "J9", "A9", "+5V_USB", BOT, True),
    ("U6", "J8", "1", None, BOT, True),
    ("C42", "U6", "5", "+3V3", BOT, True), ("C41", "U6", "3", "+3V3", BOT, True), ("R20", "U6", "2", None, BOT, True),
    ("U7", "J9", "A6", "USB_DP", BOT, True),
    ("R22", "J9", "A5", "USB_CC1", BOT, True), ("R23", "J9", "B5", "USB_CC2", BOT, True),
    ("J6", *U4P("SWCLK"), "SWCLK", BOT, True),
    ("C35", "U4", "8", "SOA_ADC", BOT, True), ("C36", "U4", "9", "SOB_ADC", BOT, True), ("C37", "U4", "17", "SOC_ADC", BOT, True),
    ("C38", "U4", "10", "VBUS_ADC", BOT, True), ("C39", "U4", "11", "NTC_SENSE", BOT, True),
    ("R14", "C35", "1", "SOA_ADC", BOT, True), ("R15", "C36", "1", "SOB_ADC", BOT, True), ("R16", "C37", "1", "SOC_ADC", BOT, True),
    ("R18", "C38", "1", "VBUS_ADC", BOT, True), ("R17", "R18", "2", "VBUS_ADC", BOT, True), ("R19", "C39", "1", "NTC_SENSE", BOT, True),
    ("R6", "U3", "26", "DRV_nFAULT", BOT, True), ("R7", "U3", "27", "DRV_SDO", BOT, True), ("R24", "U4", "25", "ENC_CS", BOT, True),
    ("R11", "U4", "46", "BOOT0", None), ("JP1", "R11", "1", "BOOT0", BOT, True),
]
FIRST = ["U7", "R22", "R23", "U2", "C16", "C17", "D2", "D3", "C20", "C19", "C22", "C21", "C18", "C23", "C24", "C25", "C26", "C30", "C28", "C29", "C31", "C27",
         "C13", "C11", "C47", "C48",
         "U7", "R22", "R23", "U6", "C41", "C42", "R20", "R21", "C43", "J6"]
plan.sort(key=lambda it: FIRST.index(it[0]) if it[0] in FIRST else len(FIRST))
OTHER = {"C20": ("2", "DRV_CPH"), "C19": ("4", "VBUS"), "C14": ("1", "BUCK_SW")}
TOP_ONLY = {"D2", "D3", "C47", "C48", "C18", "C19", "C20", "C21", "C22", "C23", "C11", "C12", "C13", "C14"}
DECAPS = {"C47", "C48", "D2", "D3", "C27", "C29", "C31", "C11", "C12", "C13", "C14", "C16", "C17", "C18", "C19", "C20", "C21", "C22", "C23", "C24", "C25", "C26", "C28", "C30", "C41", "C42"}
for item in plan:
    bot = len(item) > 5 and item[5]
    if item[0] in ("R11", "JP1"):
        occ[bot].extend(vbus_keepout(bot))
    ok = False
    if item[0] in DECAPS:
        oth = OTHER.get(item[0])
        t1 = tight(item[0], item[1], item[2], item[3], bottom=bot, other=oth, commit=False)
        t2 = tight(item[0], item[1], item[2], item[3], bottom=not bot, other=oth, commit=False) if item[0] not in TOP_ONLY else None
        if t1 or t2:
            side = bot if (t2 is None or (t1 and t1[0] <= t2[0] + 0.3)) else not bot
            ok = tight(item[0], item[1], item[2], item[3], bottom=side, other=oth)
    if not ok:
        ok = near(item[0], item[1], item[2], item[3], bottom=bot, maxd=(22 if item[0] == "JP1" else 14), zone=item[4])
    if not ok:
        if not grid(item[0], item[1], item[2], item[3], bottom=bot):
            if item[0] in ("R11", "JP1"):
                occ[not bot].extend(vbus_keepout(not bot))
            grid(item[0], item[1], item[2], item[3], bottom=not bot)
            if item[0] in ("R11", "JP1"):
                occ[not bot] = [o for o in occ[not bot] if o[0] != "vbus 5 mm"]
    if item[0] in ("R11", "JP1"):
        occ[bot] = [o for o in occ[bot] if o[0] != "vbus 5 mm"]
near("TP4", "Q1", "1", None, maxd=20)

for r in ("C50", "C51", "C52"):
    fp[r].Value().SetVisible(False); fp[r].Reference().SetVisible(False)
all_ics = ["U1", "U2", "U3", "U4", "U5", "U6", "U7"]
everything = {f.GetReference() for f in b.GetFootprints()}
print("board crossings, all signal links of the ICs:", crossings(links(all_ics, everything)))
print("U3-U4 bus crossings:", crossings(links(["U3"], {"U3", "U4"})))
print("top holes y", round(TOP_HOLE_Y - Y0, 2), "mm from the top edge; FET row top", round(FET_TOP - Y0, 2), "mm; HS drain to encoder centre", round(FET_TOP + 0.85 - CY, 2))
b.Save(PCB)
