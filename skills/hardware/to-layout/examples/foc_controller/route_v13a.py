"""Routing stage A (placement v13): power-stage pours, via arrays, inner planes. All locked.
Run on a board with no routing (strip.py first). Coordinates come from the pads."""
import math, sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM
from rlib import R, rect, circle, polyset, BOARD, CX, CY, X0, Y0, W

r = R()
b = r.b
fp = r.fp
ENC_R = 10.0


def bb(p):
    x = p.GetBoundingBox()
    return ToMM(x.GetLeft()), ToMM(x.GetTop()), ToMM(x.GetRight()), ToMM(x.GetBottom())


def pad(ref, num, big=False):
    ps = [p for p in fp[ref].Pads() if p.GetNumber() == num]
    return max(ps, key=lambda p: p.GetSizeX() * p.GetSizeY()) if big else ps[0]


def union(boxes):
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def netpad(ref, net):
    return [p for p in fp[ref].Pads() if str(p.GetNetname()).split("/")[-1] == net][0]


VIAS = []
HV = ("PHASE_", "BUCK_SW", "BUCK_BST", "DRV_VCP", "DRV_CPH", "DRV_CPL", "GHA", "GHB", "GHC")
PADS = [(p, str(p.GetNetname()).split("/")[-1], f.GetReference()) for f in b.GetFootprints() for p in f.Pads()]
SKIPPED = []


def is_hv(n):
    return n == "VBUS" or any(n.startswith(h) for h in HV)


def via_ok(x, y, net, dia):
    """Through via: clear of every other-net pad on its layers (0.6 mm between high-voltage and other nets outside
    MOSFET courtyards, else 0.25 mm), other vias, the encoder circle and the board edge."""
    net = net.split("/")[-1]
    if math.hypot(x - CX, y - CY) < ENC_R + dia / 2 or not (X0 + 0.9 < x < X0 + W - 0.9 and Y0 + 0.9 < y < Y0 + W - 0.9):
        return False
    pt = VECTOR2I(FromMM(x), FromMM(y))
    for vx, vy, vn, vd in VIAS:
        need = (0.84 if vn == net else (vd + dia) / 2 + (0.6 if is_hv(vn) != is_hv(net) else 0.25))
        if math.hypot(vx - x, vy - y) < need:
            return False
    for p, pn, ref in PADS:
        if pn == net:
            continue
        need = 0.6 if (is_hv(pn) != is_hv(net) and ref[0] != "Q") else 0.25
        if "SENSE" in pn and is_hv(net):
            need = 1.05                                       # sense pairs >= 1 mm from high-voltage copper
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            need = 0.35
        for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
            if p.IsOnLayer(lay) and p.GetEffectivePolygon(lay).Collide(pt, FromMM(dia / 2 + need)):
                return False
    return True


def via(x, y, net, drill=0.3, dia=0.6):
    if not via_ok(x, y, net, dia):
        SKIPPED.append((round(x, 2), round(y, 2), net.split("/")[-1]))
        return False
    r.via(x, y, net, drill=drill, dia=dia)
    VIAS.append((x, y, net.split("/")[-1], dia))
    return True


PH = [("A", "Q1", "Q2", "R8", "C1", "C50", "J3"), ("B", "Q3", "Q4", "R9", "C5", "C51", "J4"), ("C", "Q5", "Q6", "R10", "C9", "C52", "J5")]
cells = []
for ph, hs, ls, rs, cap, hf, jm in PH:
    D = bb(pad(hs, "5", big=True))                                   # HS drain (VBUS)
    tabs_top = min(bb(p)[1] for p in fp[hs].Pads() if p.GetNumber() == "5")
    S = union([bb(pad(ls, n)) for n in ("1", "2", "3")])             # LS sources (shunt node)
    GL = bb(pad(ls, "4")); GH = bb(pad(hs, "4"))
    LD = bb(pad(ls, "5", big=True))                                  # LS drain (phase)
    J = bb(pad(jm, "1"))
    Rs, Rg = bb(netpad(rs, "SHUNT_" + ph)), bb(netpad(rs, "GND"))
    Cv, Cg = bb(netpad(cap, "VBUS")), bb(netpad(cap, "GND"))
    Hv = bb(netpad(hf, "VBUS"))
    row_top = min(tabs_top, S[1])
    strip_top = row_top - 2.25
    PHN, SHN = f"/PHASE_{ph}", f"/Bridge/SHUNT_{ph}"
    enc = [circle(CX, CY, ENC_R)]
    # ---- top
    r.zone(rect(D[0] - 0.25, strip_top, D[2], D[3]), "VBUS", "F", prio=3, clearance=0.6, cut=enc, name=f"VBUS_top_{ph}")
    r.zone(rect(GL[2] + 0.35, strip_top, S[2] + 0.25, S[3]), SHN, "F", prio=3, clearance=0.3, cut=enc, name=f"SHUNT_top_{ph}")
    phase = polyset(rect(D[0] - 0.25, D[3] + 0.3, LD[2], J[3] + 0.4))
    phase.BooleanAdd(polyset(rect(LD[0], LD[1], LD[2], D[3] + 0.3)))
    r.zone(phase, PHN, "F", prio=3, clearance=0.6, name=f"PHASE_top_{ph}")
    # ---- bottom: VBUS under the strip and the HS drain down to the bus cap and the 100 nF; shunt from the strip to
    # the shunt pad (clear of the Kelvin net tie on its inner corner)
    vb = polyset(rect(D[0] - 0.25, strip_top, Rg[0] - 0.65, Cv[3]))
    vb.BooleanAdd(polyset(rect(Cv[0], Cv[3] - 0.5, Hv[2] + 0.2, Hv[3] + 0.2)))
    r.zone(vb, "VBUS", "B", prio=3, clearance=0.6, cut=enc, name=f"VBUS_bot_{ph}")
    nt_right = max(bb(p)[2] for f in (fp[n] for n in fp if n.startswith("NT")) for p in f.Pads()
                   if Rs[0] - 0.6 <= bb(p)[0] <= Rs[2] and Rs[1] - 1.5 <= bb(p)[1] <= Rs[3])
    r.zone(rect(nt_right + 0.35, strip_top, S[2] + 0.25, Rs[3]), SHN, "B", prio=3, clearance=0.3, cut=enc, name=f"SHUNT_bot_{ph}")
    # ---- vias: VBUS strip above the HS, VBUS in the HS drain pad (vertical loop to the bus cap under it),
    # shunt strip above the LS sources
    n = {"vbus": 0, "shunt": 0}
    x = D[0] + 0.4
    while x <= D[2] - 0.75:
        for y in (strip_top + 0.6, strip_top + 1.45):
            n["vbus"] += via(x, y, "VBUS")
        x += 0.9
    for xx in (D[0] + 0.6, D[0] + 1.5):
        y = D[1] + 0.45
        while y <= min(D[3], Cv[1] + 0.3) - 0.4:
            n["vbus"] += via(xx, y, "VBUS")
            y += 0.9
    x = GL[2] + 1.2
    while x <= S[2] + 0.05:
        for y in (strip_top + 0.6, strip_top + 1.45):
            n["shunt"] += via(x, y, SHN)
        x += 0.9
    # shunt node straight down: one via in each LS source pin onto the shunt pad under it
    for num in ("1", "2", "3"):
        q = bb(pad(ls, num))
        n["shunt"] += via((q[0] + q[2]) / 2, (q[1] + q[3]) / 2, SHN) or via((q[0] + q[2]) / 2, (q[1] + q[3]) / 2 + 0.15, SHN)
    cells.append(dict(ph=ph, D=D, LD=LD, S=S, GL=GL, GH=GH, J=J, strip_top=strip_top, n=n))

# GND vias in the gaps between the cells (top: between a LS drain and the next HS drain) and beside the row ends
gaps = [(cells[i]["LD"][2], cells[i + 1]["D"][0]) for i in range(2)]
ng = 0
for gi, (x1, x2) in enumerate(gaps):
    xm = (x1 + x2) / 2
    y = cells[0]["D"][1] + 0.6
    while y <= cells[0]["D"][3] + 0.8:
        if gi == 1 and y < cells[0]["D"][1] + 2.0:
            # phase B's strip is inside the encoder keep-out: its shunt node also goes down here, beside Q4's sources
            cells[1]["n"]["shunt"] += via(xm, y, "/Bridge/SHUNT_B")
        else:
            ng += via(xm, y, "GND")
        y += 0.9
cB = cells[1]
r.zone(rect(cB["S"][2], cB["S"][1], (gaps[1][0] + gaps[1][1]) / 2 + 0.45, cells[0]["D"][1] + 2.0), "/Bridge/SHUNT_B", "F", prio=4, clearance=0.25, name="SHUNT_B_side_top")
rsb = bb(netpad("R9", "SHUNT_B"))
r.zone(rect(rsb[0], rsb[1], (gaps[1][0] + gaps[1][1]) / 2 + 0.45, rsb[3]), "/Bridge/SHUNT_B", "B", prio=4, clearance=0.3, name="SHUNT_B_side_bot")

# ---- bulk caps: two power vias at each VBUS pad, on the side away from the cap's GND pad, linked by a 0.6 mm track
BULK = ["C2", "C3", "C4", "C6", "C7", "C44", "C8", "C10", "C45", "C46", "C49", "C47", "C48", "C12"]
bulk_n = {}
for c in BULK:
    f = fp[c]; side = "B" if f.IsFlipped() else "F"
    v = netpad(c, "VBUS"); g = netpad(c, "GND")
    vx, vy = ToMM(v.GetPosition().x), ToMM(v.GetPosition().y)
    gx, gy = ToMM(g.GetPosition().x), ToMM(g.GetPosition().y)
    ux, uy = vx - gx, vy - gy; L = math.hypot(ux, uy); ux, uy = ux / L, uy / L
    k = 0
    cands = []
    for d in [0.9 + 0.1 * i for i in range(18)]:
        for a in range(0, 360, 15):
            x, y = vx + d * math.cos(math.radians(a)), vy + d * math.sin(math.radians(a))
            if math.hypot(x - gx, y - gy) < math.hypot(x - vx, y - vy):   # never on the GND pad's side
                continue
            cands.append((d, x, y))
    lay = pcbnew.B_Cu if side == "B" else pcbnew.F_Cu
    for d, x, y in cands:
        if k >= 2:
            break
        seg = pcbnew.SEG(VECTOR2I(FromMM(vx), FromMM(vy)), VECTOR2I(FromMM(x), FromMM(y)))
        clash = False
        for p, pn, ref in PADS:
            if pn == "VBUS" or not p.IsOnLayer(lay):
                continue
            need = 0.6 if ref[0] not in "QU" else 0.25
            if p.GetEffectivePolygon(lay).Collide(seg, FromMM(0.3 + need)):
                clash = True; break
        if clash:
            continue
        if via(x, y, "VBUS"):
            r.track([(vx, vy), (x, y)], "VBUS", side, 0.6); k += 1
    bulk_n[c] = k

# VBUS bars on the motor side joining the VBUS pads of each inner bulk-cap column
for col, name in ((["C6", "C7", "C44"], "VBUS_bar_left"), (["C45", "C46", "C49"], "VBUS_bar_right")):
    pads = [bb(netpad(c, "VBUS")) for c in col]
    x1, y1, x2, y2 = union(pads)
    r.zone(rect(x1 - 0.1, y1 - 0.1, x2 + 0.1, y2 + 0.1), "VBUS", "B", prio=3, clearance=0.6, name=name)

# ---- inner planes: L2 solid GND; L3 VBUS ring (connector band, side strips, strip band over the FET row)
r.zone(BOARD, "GND", "In1", prio=0, clearance=0.25, solid=False, name="GND_plane")
r.keepout(BOARD, ["In1"], tracks=True, name="In1_no_tracks")
st = min(c["strip_top"] for c in cells)
rb = max(c["S"][3] for c in cells)
ring = polyset(rect(X0, Y0, X0 + W, Y0 + 16.5))
for rc in (rect(X0, Y0, X0 + 7.6, rb), rect(X0 + W - 10.5, Y0, X0 + W, rb), rect(X0, st, X0 + W, rb),
           rect(X0, Y0, X0 + 16.0, Y0 + 22.5)):                 # under the buck and the DRV's west caps
    ring.BooleanAdd(polyset(rc))
r.zone(ring, "VBUS", "In2", prio=2, clearance=0.25, cut=[circle(CX, CY, ENC_R)], name="VBUS_In2")
# The 10 A pass-through runs in this band (J1+ to J2+): no signal tracks on L3 here, vias allowed.
r.keepout(rect(X0, Y0, X0 + W, Y0 + 16.5), ["In2"], tracks=True, vias=False, name="In2_passthrough_no_tracks")
r.zone(BOARD, "GND", "F", prio=0, clearance=0.3, solid=False, name="GND_top")
r.zone(BOARD, "GND", "B", prio=0, clearance=0.3, solid=False, name="GND_bot")
r.save()
for c in cells:
    print(c["ph"], c["n"], "strip_top", round(c["strip_top"], 2))
print("GND gap vias", ng)
print("bulk-cap VBUS vias", bulk_n)
