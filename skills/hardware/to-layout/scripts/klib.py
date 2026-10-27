"""Shared helpers for the /to-layout scripts. Run everything with KiCad's own Python (it has pcbnew):

    KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3

Board config: hw/<board>.layout.json (see SKILL.md, "Board config"). Every key is optional; scripts state which keys
they read. Net names are matched on their last path element ("/Gate driver/DRV_VCP" -> "DRV_VCP").

Headless-pcbnew gotchas handled here: never call board.Remove() or ZONE_FILLER (both crash without the GUI): strip
items by text (strip_items) and fill zones with kicad-cli (drc()). Hand zone outlines over with thisown = 0. A zone
keeps one outline: zone() splits multi-outline shapes into one zone per piece."""
import fnmatch, json, math, os, re, subprocess, sys
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

KICAD_CLI = os.environ.get("KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
LAYER = {"F": pcbnew.F_Cu, "B": pcbnew.B_Cu}
LAYER.update({f"In{k}": getattr(pcbnew, f"In{k}_Cu") for k in range(1, 7)})


def short(net):
    return str(net).split("/")[-1]


def load_config(board_path):
    p = re.sub(r"\.kicad_pcb$", ".layout.json", board_path)
    return json.load(open(p)) if os.path.exists(p) else {}


class Board:
    """Thin wrapper: one loaded board, its footprints by reference, its outline box and its net groups."""

    def __init__(self, path, cfg=None):
        self.path = path
        self.b = pcbnew.LoadBoard(path)
        self.fp = {f.GetReference(): f for f in self.b.GetFootprints()}
        self.cfg = cfg if cfg is not None else load_config(path)
        bb = self.b.GetBoardEdgesBoundingBox()
        self.x0, self.y0 = ToMM(bb.GetX()), ToMM(bb.GetY())
        self.w, self.h = ToMM(bb.GetWidth()), ToMM(bb.GetHeight())
        g = self.cfg.get("net_groups", {})
        self.hv_pat = g.get("hv", ["VBUS", "PHASE_*"])
        self.sense_pat = g.get("sense", ["*SENSE*"])
        self.plane_pat = g.get("plane", ["GND"])

    # ---- nets
    def _match(self, net, pats):
        n = short(net)
        return any(fnmatch.fnmatchcase(n, p) for p in pats)

    def is_hv(self, net):
        return self._match(net, self.hv_pat)

    def is_sense(self, net):
        return self._match(net, self.sense_pat)

    def is_plane(self, net):
        return self._match(net, self.plane_pat)

    def net(self, name):
        nets = self.b.GetNetsByName()
        for n in (name, "/" + name):
            if nets.has_key(n) if hasattr(nets, "has_key") else n in nets:
                c = nets[n].GetNetCode()
                if c > 0:
                    return c
        for nm, ni in self.b.GetNetsByName().items():
            if short(nm) == short(name):
                return ni.GetNetCode()
        raise KeyError(name)

    # ---- geometry
    def pad(self, ref, num, biggest=False):
        ps = [p for p in self.fp[ref].Pads() if p.GetNumber() == num]
        return max(ps, key=lambda p: p.GetSizeX() * p.GetSizeY()) if biggest else ps[0]

    def pad_xy(self, ref, num):
        p = self.pad(ref, num).GetPosition()
        return ToMM(p.x), ToMM(p.y)

    def net_pad(self, ref, net):
        return [p for p in self.fp[ref].Pads() if short(p.GetNetname()) == short(net)][0]

    def inside(self, box, margin=0.3):
        x1, y1, x2, y2 = box
        return x1 >= self.x0 + margin and y1 >= self.y0 + margin and x2 <= self.x0 + self.w - margin and y2 <= self.y0 + self.h - margin

    # ---- placement
    def put(self, ref, x, y, rot=0, bottom=False):
        f = self.fp[ref]
        if f.IsFlipped() != bottom:
            f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        f.SetOrientationDegrees(rot)
        f.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))

    def orient(self, ref, x, y, rot, net, tx, ty, bottom=False):
        """Place at (x, y) with rot or rot + 180, whichever puts the pad of `net` nearer (tx, ty)."""
        best = None
        for r in (rot, (rot + 180) % 360):
            self.put(ref, x, y, r, bottom)
            p = self.net_pad(ref, net).GetPosition()
            d = math.hypot(ToMM(p.x) - tx, ToMM(p.y) - ty)
            if best is None or d < best[0]:
                best = (d, r)
        self.put(ref, x, y, best[1], bottom)

    def court(self, ref):
        f = self.fp[ref]
        c = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
        return c if c.OutlineCount() else None

    def rect_of(self, ref):
        """Courtyard box grown to cover the pads (some library courtyards are smaller than their pads)."""
        f = self.fp[ref]; c = self.court(ref)
        bb = c.BBox() if c else f.GetBoundingBox(False)
        r = [ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())]
        for p in f.Pads():
            pb = p.GetBoundingBox()
            r = [min(r[0], ToMM(pb.GetLeft())), min(r[1], ToMM(pb.GetTop())), max(r[2], ToMM(pb.GetRight())), max(r[3], ToMM(pb.GetBottom()))]
        return tuple(r)

    def court_gap(self, a, c):
        """Courtyard-to-courtyard distance in mm (0 when touching or overlapping)."""
        pa, pc = self.court(a), self.court(c)
        if pa is None or pc is None:
            return 99.0
        for k in range(300):
            if pa.Collide(pc.Outline(0), FromMM(k * 0.05)) or pc.Collide(pa.Outline(0), FromMM(k * 0.05)):
                return k * 0.05
        return 99.0

    # ---- copper
    def track(self, pts, net, layer, width, lock=True):
        code = self.net(net) if isinstance(net, str) else net
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1))); t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
            t.SetWidth(FromMM(width)); t.SetLayer(LAYER[layer]); t.SetNetCode(code); t.SetLocked(lock)
            self.b.Add(t)

    def via(self, x, y, net, drill=0.3, dia=0.6, lock=True):
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(VECTOR2I(FromMM(x), FromMM(y))); v.SetDrill(FromMM(drill)); v.SetWidth(FromMM(dia))
        v.SetNetCode(self.net(net) if isinstance(net, str) else net); v.SetLocked(lock)
        self.b.Add(v)
        return v

    def zone(self, poly, net, layer, prio=1, clearance=0.3, solid=True, minw=0.25, cut=None, name=""):
        sps = polyset(poly) if not isinstance(poly, pcbnew.SHAPE_POLY_SET) else poly
        for c in cut or []:
            sps.BooleanSubtract(c)
        for part in split(sps):
            z = pcbnew.ZONE(self.b)
            z.SetLayer(LAYER[layer]); z.SetNetCode(self.net(net) if isinstance(net, str) else net)
            z.SetAssignedPriority(prio); z.SetLocalClearance(FromMM(clearance)); z.SetMinThickness(FromMM(minw))
            z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if solid else pcbnew.ZONE_CONNECTION_THERMAL)
            z.SetThermalReliefGap(FromMM(0.3)); z.SetThermalReliefSpokeWidth(FromMM(0.35))
            z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
            if name:
                z.SetZoneName(name)
            part.thisown = 0                                   # ZONE::SetOutline takes ownership
            z.SetOutline(part); z.SetLocked(True)
            self.b.Add(z)

    def keepout(self, poly, layers, tracks=True, vias=False, fills=False, footprints=False, cut=None, name=""):
        sps = polyset(poly) if not isinstance(poly, pcbnew.SHAPE_POLY_SET) else poly
        for c in cut or []:
            sps.BooleanSubtract(c)
        for part in split(sps):
            z = pcbnew.ZONE(self.b)
            z.SetIsRuleArea(True)
            ls = pcbnew.LSET()
            for l in layers:
                ls.AddLayer(LAYER[l])
            z.SetLayerSet(ls)
            z.SetDoNotAllowTracks(tracks); z.SetDoNotAllowVias(vias); z.SetDoNotAllowPads(False)
            z.SetDoNotAllowFootprints(footprints); z.SetDoNotAllowZoneFills(fills)
            if name:
                z.SetZoneName(name)
            part.thisown = 0                                   # ZONE::SetOutline takes ownership
            z.SetOutline(part); z.SetLocked(True)
            self.b.Add(z)

    def via_ok(self, x, y, net, dia, vias=(), keep_circles=(), hv_clear=0.6, clear=0.25, sense_clear=1.05):
        """A through via at (x, y) is clear of every other-net pad (hv_clear between high-voltage and other nets
        outside MOSFET / IC courtyards, sense_clear between sense and high-voltage nets), of `vias`
        [(x, y, net, dia)], of keep-out circles [(cx, cy, r)] and of the board edge."""
        net = short(net)
        if not self.inside((x - dia / 2, y - dia / 2, x + dia / 2, y + dia / 2), 0.5):
            return False
        for cx, cy, r in keep_circles:
            if math.hypot(x - cx, y - cy) < r + dia / 2:
                return False
        for vx, vy, vn, vd in vias:
            need = 0.84 if vn == net else (vd + dia) / 2 + (hv_clear if self.is_hv(vn) != self.is_hv(net) else clear)
            if math.hypot(vx - x, vy - y) < need:
                return False
        pt = VECTOR2I(FromMM(x), FromMM(y))
        for f in self.b.GetFootprints():
            ref = f.GetReference()
            for p in f.Pads():
                pn = short(p.GetNetname())
                if pn == net:
                    continue
                need = hv_clear if (self.is_hv(pn) != self.is_hv(net) and ref[0] not in "QU") else clear
                if (self.is_sense(pn) and self.is_hv(net)) or (self.is_sense(net) and self.is_hv(pn)):
                    need = sense_clear
                if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    need = 0.35
                for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if p.IsOnLayer(lay) and p.GetEffectivePolygon(lay).Collide(pt, FromMM(dia / 2 + need)):
                        return False
        return True

    def save(self, path=None):
        self.b.Save(path or self.path)


# ---- geometry helpers
def polyset(poly):
    s = pcbnew.SHAPE_POLY_SET(); s.NewOutline()
    for x, y in poly:
        s.Append(FromMM(x), FromMM(y))
    return s


def rect(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def circle(cx, cy, r, n=72):
    return polyset([(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)])


def split(sps):
    """One SHAPE_POLY_SET per outline (with its holes), disowned for handing to a zone. Drops slivers under 1 mm2."""
    out = []
    for i in range(sps.OutlineCount()):
        p = pcbnew.SHAPE_POLY_SET(); p.AddOutline(sps.Outline(i))
        for j in range(sps.HoleCount(i)):
            p.AddHole(sps.Hole(i, j))
        if abs(p.Area()) < FromMM(1) * FromMM(1):
            continue
        p.thisown = 0
        out.append(p)
    return out


def rgap(a, c):
    return math.hypot(max(a[0] - c[2], c[0] - a[2], 0), max(a[1] - c[3], c[1] - a[3], 0))


def offset_polyline(pts, d):
    """Parallel polyline at distance d to the LEFT of the direction of travel (negative d: right). Miter joins."""
    def unit(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy)
        return dx / L, dy / L
    out = []
    for i, p in enumerate(pts):
        if i == 0:
            ux, uy = unit(pts[0], pts[1]); nx, ny = uy, -ux
            out.append((p[0] + nx * d, p[1] + ny * d)); continue
        if i == len(pts) - 1:
            ux, uy = unit(pts[-2], pts[-1]); nx, ny = uy, -ux
            out.append((p[0] + nx * d, p[1] + ny * d)); continue
        u1, u2 = unit(pts[i - 1], p), unit(p, pts[i + 1])
        n1, n2 = (u1[1], -u1[0]), (u2[1], -u2[0])
        mx, my = n1[0] + n2[0], n1[1] + n2[1]; ml = math.hypot(mx, my)
        mx, my = mx / ml, my / ml
        cosh = mx * n1[0] + my * n1[1]
        out.append((p[0] + mx * d / cosh, p[1] + my * d / cosh))
    return out


def segs_cross(s, t):
    o = lambda a, b, c: (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    return o(*s, t[0]) * o(*s, t[1]) < 0 and o(*t, s[0]) * o(*t, s[1]) < 0


# ---- file-level operations (no pcbnew Remove: it crashes headless)
def _blocks(text, kinds):
    i, n = 0, len(text)
    while i < n:
        hit = next((k for k in kinds if text.startswith("\n\t(" + k, i)), None)
        if not hit:
            i = text.find("\n\t(", i + 1)
            if i < 0:
                return
            continue
        j, depth = i + 1, 0
        while True:
            c = text[j]
            depth += (c == "(") - (c == ")")
            if depth == 0 and c == ")":
                break
            j += 1
        yield i, j + 1, text[i:j + 1]
        i = j + 1


def strip_items(path, out=None, keep_locked=False, kinds=("segment", "arc", "via", "zone"), nets=None, zone_names=None):
    """Remove top-level routing items from a board file by text. nets: only items on these nets (short names);
    zone_names: only zones with these names. Returns the count removed."""
    s = open(path).read()
    parts, last, n = [], 0, 0
    for i, j, blk in _blocks(s, kinds):
        if keep_locked and "(locked yes)" in blk:
            continue
        if nets is not None:
            m = re.search(r'\(net "([^"]*)"\)', blk)
            if not m or short(m.group(1)) not in nets:
                continue
        if zone_names is not None:
            if not blk.lstrip().startswith("(zone") or not any(f'(name "{z}")' in blk for z in zone_names):
                continue
        parts.append(s[last:i]); last = j; n += 1
    parts.append(s[last:])
    open(out or path, "w").write("".join(parts))
    return n


def strip_fanouts(path, globs, cfg, reach=1.6):
    """Remove the plane-net fan-outs (a via of the pad's net within reach + 1.5 mm of the pad, joined to it by exactly
    one track) of the parts matching `globs`, skipping parts with a pad on place_opt.fixed_nets. Returns the count."""
    b = pcbnew.LoadBoard(path)
    plane_nets = {short(p["net"]) for p in cfg.get("planes", [{"net": "GND"}])}
    fixed_nets = cfg.get("place_opt", {}).get("fixed_nets", [])
    pads = []
    for f in b.GetFootprints():
        if not any(fnmatch.fnmatchcase(f.GetReference(), g) for g in globs):
            continue
        if any(any(fnmatch.fnmatchcase(short(p.GetNetname()), g) for g in fixed_nets) for p in f.Pads()):
            continue
        pads += [p for p in f.Pads() if short(p.GetNetname()) in plane_nets and p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
    vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
    segs = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
    near = lambda a_, b_, d: (a_ - b_).EuclideanNorm() <= FromMM(d)
    kill = set()
    for p in pads:
        for v in vias:
            if v.GetNetCode() != p.GetNetCode() or not near(v.GetPosition(), p.GetPosition(), reach + 1.5):
                continue
            stub = [t for t in segs if t.GetNetCode() == p.GetNetCode() and
                    ((near(t.GetStart(), p.GetPosition(), 0.05) and near(t.GetEnd(), v.GetPosition(), 0.05)) or
                     (near(t.GetEnd(), p.GetPosition(), 0.05) and near(t.GetStart(), v.GetPosition(), 0.05)))]
            if len(stub) == 1:                                   # matched by geometry: UUIDs can change on a reload
                kill.add(("via", round(ToMM(v.GetPosition().x), 3), round(ToMM(v.GetPosition().y), 3)))
                t = stub[0]
                kill.add(("segment",) + tuple(sorted([(round(ToMM(t.GetStart().x), 3), round(ToMM(t.GetStart().y), 3)),
                                                      (round(ToMM(t.GetEnd().x), 3), round(ToMM(t.GetEnd().y), 3))])))
    del b
    txt = open(path).read()
    parts, last, n = [], 0, 0
    num = lambda v: round(float(v), 3)
    for i, j, blk in _blocks(txt, ("segment", "via")):
        if blk.lstrip().startswith("(via"):
            m = re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", blk)
            key = ("via", num(m.group(1)), num(m.group(2))) if m else None
        else:
            a_ = re.search(r"\(start ([-\d.]+) ([-\d.]+)\)", blk); b_ = re.search(r"\(end ([-\d.]+) ([-\d.]+)\)", blk)
            key = ("segment",) + tuple(sorted([(num(a_.group(1)), num(a_.group(2))), (num(b_.group(1)), num(b_.group(2)))])) if a_ and b_ else None
        if key in kill:
            parts.append(txt[last:i]); last = j; n += 1
    parts.append(txt[last:])
    open(path, "w").write("".join(parts))
    return n


def strip_region(path, box, keep_nets=(), keep_locked=False):
    """Remove tracks and vias lying wholly inside box (x0, y0, x1, y1, mm), except nets matching keep_nets globs
    (the power stage) and, with keep_locked, locked items. Used before a block rotates (its old local copper would
    short the new pad positions) and by repair.py (rip-up around walled-in pins)."""
    txt = open(path).read()
    x0, y0, x1, y1 = box
    inside = lambda x, y: x0 <= x <= x1 and y0 <= y <= y1
    parts, last, n = [], 0, 0
    for i, j, blk in _blocks(txt, ("segment", "via")):
        m = re.search(r'\(net (?:\d+ )?"([^"]*)"\)', blk)
        if m and any(fnmatch.fnmatchcase(short(m.group(1)), g) for g in keep_nets):
            continue
        if keep_locked and re.search(r"\(locked(?: yes)?\)", blk):
            continue
        pts = [(float(a), float(b)) for a, b in re.findall(r"\((?:at|start|end) ([-\d.]+) ([-\d.]+)", blk)]
        if pts and all(inside(x, y) for x, y in pts):
            parts.append(txt[last:i]); last = j; n += 1
    parts.append(txt[last:])
    open(path, "w").write("".join(parts))
    return n


def drc(board_path, json_out, refill=True, save=True, parity=True):
    """Refill zones (kicad-cli does it headless) and run DRC. Returns the parsed report."""
    cmd = [KICAD_CLI, "pcb", "drc", "--format", "json", "-o", json_out]
    if refill:
        cmd += ["--refill-zones"]
    if save:
        cmd += ["--save-board"]
    if parity:
        cmd += ["--schematic-parity"]
    env = dict(os.environ, FONTCONFIG_FILE="/dev/null")
    subprocess.run(cmd + [board_path], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.load(open(json_out))


def drc_summary(rep, show=("clearance", "shorting_items", "track_width", "hole_clearance", "hole_to_hole",
                           "courtyards_overlap", "copper_edge_clearance", "via_dangling", "pth_inside_courtyard")):
    from collections import Counter
    c = Counter(v["type"] for v in rep["violations"])
    lines = [f"violations {dict(c)} | unconnected {len(rep['unconnected_items'])} | parity {len(rep.get('schematic_parity', []))}"]
    for v in rep["violations"]:
        if v["type"] in show:
            it = v["items"][0]["pos"]
            lines.append(f"  {v['type']} @ ({it['x']:.2f}, {it['y']:.2f}) | " + " / ".join(i["description"][:60] for i in v["items"]))
    return "\n".join(lines)
