"""Small helpers for scripted routing of hw/foc_controller.kicad_pcb (KiCad 10 pcbnew)."""
import math
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

PCB = "hw/foc_controller.kicad_pcb"
X0, Y0, W = 102.5, 102.5, 45.0
CX, CY = 125.0, 125.0
LAYER = {"F": pcbnew.F_Cu, "In1": pcbnew.In1_Cu, "In2": pcbnew.In2_Cu, "B": pcbnew.B_Cu}


class R:
    def __init__(self, path=PCB):
        self.b = pcbnew.LoadBoard(path)
        self.fp = {f.GetReference(): f for f in self.b.GetFootprints()}

    def net(self, name):
        for n in (name, "/" + name):
            code = self.b.GetNetcodeFromNetname(n)
            if code > 0:
                return code
        for nm, ni in self.b.GetNetsByName().items():
            if str(nm).split("/")[-1] == name:
                return ni.GetNetCode()
        raise KeyError(name)

    def pad_xy(self, ref, num):
        p = self.fp[ref].FindPadByNumber(num).GetPosition()
        return ToMM(p.x), ToMM(p.y)

    def clear(self, keep_locked=False):
        for t in list(self.b.GetTracks()):
            if keep_locked and t.IsLocked():
                continue
            self.b.Remove(t)
        for z in list(self.b.Zones()):
            if keep_locked and z.IsLocked():
                continue
            self.b.Remove(z)

    def track(self, pts, net, layer, width, lock=True):
        code = self.net(net) if isinstance(net, str) else net
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(self.b)
            t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1)))
            t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
            t.SetWidth(FromMM(width))
            t.SetLayer(LAYER[layer])
            t.SetNetCode(code)
            t.SetLocked(lock)
            self.b.Add(t)

    def via(self, x, y, net, lock=True, drill=0.3, dia=0.6):
        code = self.net(net) if isinstance(net, str) else net
        v = pcbnew.PCB_VIA(self.b)
        v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
        v.SetDrill(FromMM(drill))
        v.SetWidth(FromMM(dia))
        v.SetNetCode(code)
        v.SetLocked(lock)
        self.b.Add(v)
        return v

    def zone(self, poly, net, layer, prio=1, clearance=0.3, solid=True, minw=0.25, cut=None, name=""):
        z = pcbnew.ZONE(self.b)
        z.SetLayer(LAYER[layer])
        z.SetNetCode(self.net(net) if isinstance(net, str) else net)
        z.SetAssignedPriority(prio)
        z.SetLocalClearance(FromMM(clearance))
        z.SetMinThickness(FromMM(minw))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if solid else pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(FromMM(0.3))
        z.SetThermalReliefSpokeWidth(FromMM(0.35))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        if name:
            z.SetZoneName(name)
        sps = polyset(poly) if not isinstance(poly, pcbnew.SHAPE_POLY_SET) else poly
        for c in cut or []:
            sps.BooleanSubtract(c)
        parts = split(sps)
        z.SetOutline(parts[0])              # the zone takes ownership of the outline
        z.SetLocked(True)
        self.b.Add(z)
        for extra in parts[1:]:             # a zone file keeps one outline: one zone per piece
            self.zone(extra, net, layer, prio, clearance, solid, minw, None, name)
        return z

    def keepout(self, poly, layers, tracks=True, vias=False, fills=False, cut=None, name=""):
        z = pcbnew.ZONE(self.b)
        z.SetIsRuleArea(True)
        ls = pcbnew.LSET()
        for l in layers:
            ls.AddLayer(LAYER[l])
        z.SetLayerSet(ls)
        z.SetDoNotAllowTracks(tracks)
        z.SetDoNotAllowVias(vias)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetDoNotAllowZoneFills(fills)
        if name:
            z.SetZoneName(name)
        sps = polyset(poly) if not isinstance(poly, pcbnew.SHAPE_POLY_SET) else poly
        for c in cut or []:
            sps.BooleanSubtract(c)
        parts = split(sps)
        z.SetOutline(parts[0])
        z.SetLocked(True)
        self.b.Add(z)
        for extra in parts[1:]:
            self.keepout(extra, layers, tracks, vias, fills, None, name)
        return z

    def fill(self):
        pcbnew.ZONE_FILLER(self.b).Fill(self.b.Zones())

    def save(self, path=PCB):
        self.b.Save(path)


def polyset(poly):
    s = pcbnew.SHAPE_POLY_SET()
    s.NewOutline()
    for x, y in poly:
        s.Append(FromMM(x), FromMM(y))
    return s


def rect(x1, y1, x2, y2):
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def circle(cx, cy, r, n=72):
    return polyset([(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)])


BOARD = [(X0 + 2, Y0), (X0 + W - 2, Y0), (X0 + W, Y0 + 2), (X0 + W, Y0 + W - 2), (X0 + W - 2, Y0 + W), (X0 + 2, Y0 + W), (X0, Y0 + W - 2), (X0, Y0 + 2)]


def split(sps):
    """One SHAPE_POLY_SET per outline (with its holes), disowned for handing to a zone."""
    out = []
    for i in range(sps.OutlineCount()):
        p = pcbnew.SHAPE_POLY_SET()
        p.AddOutline(sps.Outline(i))
        for j in range(sps.HoleCount(i)):
            p.AddHole(sps.Hole(i, j))
        if abs(p.Area()) < FromMM(1) * FromMM(1):     # drop slivers under 1 mm2
            continue
        p.thisown = 0
        out.append(p)
    return out or [sps]
