"""Global routing model shared by global_route.py (the routability gate) and place_opt.py (the placement loop).

    m = Model(board_path, cfg, tile=1.0, movable=["C12", ...])
    m.solve(iters=40)            -> overflow (mm of track width over capacity, summed over tiles)
    tok = m.move("C12", x, y, rot, bottom=None); m.solve(iters=8, warm=True); m.undo(tok)

Connections are KiCad's unconnected items on a refilled copy with unlocked routing stripped (keep_routed keeps it).
Ends on pads follow their footprint when it moves. Obstacles are rasterised at 0.1 mm with per-cell counts so a
footprint's pads can be taken out and put back; tile capacities (free track width per layer, via sites) follow.

Class keys, as droute.py: "N" (normal nets: high-voltage exposed pads grown to router.hv_pad_clear), "S" (sense
classes: high-voltage copper grown to router.sense_hv_clear, not inside U*/R* courtyards) and "H" (high-voltage
classes: other nets' exposed pads grown to hv_pad_clear); pads in sizing.pad_exempt_courtyards are exempt. Each key
has its own tile capacity (the general one less the cells only its extra clearance blocks, rasterised once: the
high-voltage parts are the power stage, which does not move) and its own usage; a tile overflows by the larger of
the general and the per-key excess. Without this a channel one sense track wide counts as three tracks.
See global_route.py for the capacity and cost model."""
import collections, fnmatch, heapq, json, math, os, re, shutil, tempfile
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I
from klib import drc, short, strip_fanouts, strip_items
from raster import CU, NAME, Grid, item_poly, rings_of, stack

FINE = 0.1
ALL_CU = [("F", pcbnew.F_Cu), ("In1", pcbnew.In1_Cu), ("In2", pcbnew.In2_Cu), ("B", pcbnew.B_Cu)]   # set per board
FIXED = 30.0
RN = {0: "free", 1: "pads", 2: "tracks/vias", 3: "zones", 4: "keep-outs"}


class Model:
    def __init__(self, board_path, cfg, tile=1.0, keep_routed=False, movable=(), via_cost=1.5, fine=FINE, refan=()):
        self.cfg, self.T, self.via_cost, self.FINE = cfg, tile, via_cost, fine
        self.K = int(round(tile / fine))
        base = board_path[:-len(".kicad_pcb")]
        pro = json.load(open(base + ".kicad_pro"))
        self.classes = {c["name"]: c for c in pro["net_settings"]["classes"]}
        self.patterns = pro["net_settings"].get("netclass_patterns", [])
        self.LAYERS = cfg.get("signal_layers", ["F", "B"])
        self.drop = set(cfg.get("freerouting", {}).get("drop_zones", []))
        self.planes = {(short(p["net"]), p["layer"]) for p in cfg.get("planes", [])}
        self.vdrill, self.vdia = cfg.get("sizing", {}).get("vias", {}).get("signal", [0.2, 0.45])
        D = self.D = self.classes["Default"]
        self.GROW = D["clearance"] + D["track_width"] / 2
        self.VGROW = D["clearance"] + self.vdia / 2
        self.vp = self.vdia + D["clearance"]
        FR, RT = cfg.get("freerouting", {}), cfg.get("router", {})
        self.HV_CLASSES = set(FR.get("hv_classes", ["HV", "HV_SIG", "GATE_HS"]))
        self.SENSE_CLASSES = set(FR.get("sense_classes", ["SENSE"]))
        self.HV_PAD, self.SENSE_HV = RT.get("hv_pad_clear", 0.6), RT.get("sense_hv_clear", 1.0)
        self.EXEMPT = cfg.get("sizing", {}).get("pad_exempt_courtyards", ["Q*", "U*"])

        self.tmp = tempfile.mkdtemp()
        for ext in (".kicad_pcb", ".kicad_pro", ".kicad_dru"):
            if os.path.exists(base + ext):
                shutil.copy(base + ext, os.path.join(self.tmp, "b" + ext))
        self.work = os.path.join(self.tmp, "b.kicad_pcb")
        self.stripped = 0 if keep_routed else strip_items(self.work, keep_locked=True, kinds=("segment", "arc", "via"))
        self.refanned = strip_fanouts(self.work, list(refan), cfg) if refan else 0     # plane vias of parts that move
        rep = drc(self.work, os.path.join(self.tmp, "d.json"), refill=True, save=True, parity=False)
        b = self.b = pcbnew.LoadBoard(self.work)
        global ALL_CU
        ALL_CU = [(n, CU[n]) for n in stack(b)]
        bb = b.GetBoardEdgesBoundingBox()
        self.X0, self.Y0, self.X1, self.Y1 = ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())
        self.fine = Grid(self.X0, self.Y0, self.X1, self.Y1, self.FINE)
        self.NX, self.NY = int(math.ceil((self.X1 - self.X0) / tile)), int(math.ceil((self.Y1 - self.Y0) / tile))
        self.NL = len(self.LAYERS)
        self.fp = {f.GetReference(): f for f in b.GetFootprints()}
        self.movable = set(movable)
        self.net_full = {short(str(nm)): str(nm) for nm in b.GetNetsByName().keys()}
        self._build_obstacles()
        self._build_class_caps()
        self._build_conns(rep)
        self.reset_usage()
        self.hist = [[[0.0] * self.NX for _ in range(self.NY)] for _ in range(self.NL)]
        self.routes = [None] * len(self.conns)

    def reset_usage(self):
        self.use = [[[0.0] * self.NX for _ in range(self.NY)] for _ in range(self.NL)]
        self.vuse = [[0.0] * self.NX for _ in range(self.NY)]
        self.kuse = {k: [[[0.0] * self.NX for _ in range(self.NY)] for _ in range(self.NL)] for k in self.KEYS}
        for c in self.conns:
            c.pop("applied", None)

    # ---- nets
    def key_of(self, n):
        k = self.netclass(self.net_full.get(short(n), n)).get("name", "Default")
        return "H" if k in self.HV_CLASSES else "S" if k in self.SENSE_CLASSES else "N"

    def netclass(self, n):
        for p in self.patterns:
            if fnmatch.fnmatchcase(n, p["pattern"]) or fnmatch.fnmatchcase("/" + short(n), p["pattern"]):
                return self.classes.get(p["netclass"], self.D)
        return self.D

    # ---- obstacle raster with counts
    def _spans(self, sps, grow):
        g = pcbnew.SHAPE_POLY_SET(sps)
        if grow > 0:
            g.Inflate(FromMM(grow), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
        out = []
        for poly in rings_of(g):
            out += list(self.fine.spans(poly))
        return out

    def _add(self, layer, spans, sign, kind):
        """layer: signal layer name (track map) or None (via map)."""
        K, fine = self.K, self.fine
        if layer is None:
            cnt, free = self.vcnt, self.vfree
            for j, i0, i1 in spans:
                row, ok = cnt[j], self.inside[j]
                for i in range(i0, i1):
                    before = row[i]; row[i] = before + sign
                    if ok[i] and (before == 0) != (row[i] == 0):
                        free[j // K][i // K] += -1 if before == 0 else 1
            return
        li = self.LAYERS.index(layer)
        cnt, free, rs = self.tcnt[li], self.tfree[li], self.reason[li]
        for j, i0, i1 in spans:
            row, ok, rr = cnt[j], self.inside[j], rs[j]
            for i in range(i0, i1):
                before = row[i]; row[i] = before + sign
                if sign > 0 and not rr[i]:
                    rr[i] = kind
                if ok[i] and (before == 0) != (row[i] == 0):
                    free[j // K][i // K] += -1 if before == 0 else 1

    def _pad_spans(self, f):
        """(track spans per signal layer, via spans, own-net cells) for a footprint's pads."""
        ts, vs = collections.defaultdict(list), []
        for p in f.Pads():
            first = True
            for ln, lid in ALL_CU:
                if not p.IsOnLayer(lid):
                    continue
                sps = item_poly(p, lid)
                if ln in self.LAYERS:
                    ts[ln] += self._spans(sps, self.GROW)
                if first:
                    vs += self._spans(sps, self.VGROW); first = False
        return ts, vs

    def _build_obstacles(self):
        b, fine, K = self.b, self.fine, self.K
        self.inside = fine.new(0)
        eb = pcbnew.SHAPE_POLY_SET(); b.GetBoardPolygonOutlines(eb, True)
        edge = 0.5 + self.D["track_width"] / 2
        shrunk = pcbnew.SHAPE_POLY_SET(eb); shrunk.Deflate(FromMM(edge), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
        for poly in rings_of(shrunk):
            fine.fill(poly, self.inside, 1)
        self.tcnt = [fine.new(0) for _ in self.LAYERS]
        self.vcnt = fine.new(0)
        self.reason = [fine.new(0) for _ in self.LAYERS]
        self.zone_net = {l: fine.new(0) for l in ("F", "B")}
        KK = K * K
        self.tfree = [[[0] * self.NX for _ in range(self.NY)] for _ in self.LAYERS]
        self.vfree = [[0] * self.NX for _ in range(self.NY)]
        for j in range(fine.ny):
            for i in range(fine.nx):
                if self.inside[j][i]:
                    self.vfree[j // K][i // K] += 1
                    for li in range(len(self.LAYERS)):
                        self.tfree[li][j // K][i // K] += 1
        self.tile_cells = [[0] * self.NX for _ in range(self.NY)]
        for j in range(fine.ny):
            for i in range(fine.nx):
                self.tile_cells[j // K][i // K] += 1
        # pads (movable footprints kept apart so they can move)
        self.fp_spans = {}
        for ref, f in self.fp.items():
            ts, vs = self._pad_spans(f)
            if ref in self.movable:
                self.fp_spans[ref] = (ts, vs)
            for l, sp in ts.items():
                self._add(l, sp, +1, 1)
            self._add(None, vs, +1, 1)
        for t in b.GetTracks():
            if t.Type() == pcbnew.PCB_VIA_T:
                for ln, lid in ALL_CU:
                    if ln in self.LAYERS:
                        self._add(ln, self._spans(item_poly(t, lid), self.GROW), +1, 2)
                self._add(None, self._spans(item_poly(t, pcbnew.F_Cu), self.VGROW), +1, 2)
            else:
                ln = NAME.get(t.GetLayer())
                sps = item_poly(t, t.GetLayer())
                if ln in self.LAYERS:
                    self._add(ln, self._spans(sps, self.GROW), +1, 2)
                self._add(None, self._spans(sps, self.VGROW), +1, 2)
        for z in b.Zones():
            for lid in z.GetLayerSet().CuStack():
                ln = NAME.get(lid)
                if z.GetIsRuleArea():
                    if z.GetDoNotAllowTracks() and ln in self.LAYERS:
                        self._add(ln, self._spans(z.Outline(), 0), +1, 4)
                    if z.GetDoNotAllowVias():
                        self._add(None, self._spans(z.Outline(), 0), +1, 4)
                    continue
                if z.GetZoneName() in self.drop or f"{short(z.GetNetname())}@{ln}" in self.drop:
                    continue                                      # a pour that fills around tracks
                fill = z.GetFilledPolysList(lid)
                if ln in self.LAYERS:
                    self._add(ln, self._spans(fill, self.GROW), +1, 3)
                if (short(z.GetNetname()), ln) not in self.planes:
                    self._add(None, self._spans(fill, self.VGROW), +1, 3)
                if ln in self.zone_net:
                    zn = self.zone_net[ln]
                    for j, i0, i1 in self._spans(fill, 0):
                        for i in range(i0, i1):
                            zn[j][i] = z.GetNetCode() if zn[j][i] in (0, z.GetNetCode()) else -1

    def cap(self, li, tx, ty):
        n = self.tile_cells[ty][tx]
        return self.tfree[li][ty][tx] / n * self.T if n else 0.0

    def kcap(self, key, li, tx, ty):
        n = self.tile_cells[ty][tx]
        return max(0.0, self.cap(li, tx, ty) - (self.kblock[key][li][ty][tx] / n * self.T if n else 0.0))

    def _build_class_caps(self):
        """Per key and layer: cells free of fixed copper that only the key's extra clearance blocks, per tile."""
        b, fine, K = self.b, self.fine, self.K
        self.KEYS = ("N", "S", "H")
        hv = lambda code: code > 0 and self.key_of(b.FindNet(code).GetNetname()) == "H"
        courts = lambda globs: [f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
                                for r, f in self.fp.items() if any(fnmatch.fnmatchcase(r, g) for g in globs)]
        ex_c = [c for c in courts(self.EXEMPT) if c.OutlineCount()]
        exempt = lambda sps: sps.OutlineCount() and any(c.Collide(sps.Outline(0), 0) for c in ex_c)
        mark = {k: [fine.new(0) for _ in self.LAYERS] for k in self.KEYS}
        hw = self.D["track_width"] / 2
        for f in self.fp.values():
            ex0 = any(fnmatch.fnmatchcase(f.GetReference(), g) for g in self.EXEMPT)
            for p in f.Pads():
                h = hv(p.GetNetCode())
                for ln, lid in ALL_CU:
                    if ln not in self.LAYERS or not p.IsOnLayer(lid):
                        continue
                    sps = item_poly(p, lid)
                    li = self.LAYERS.index(ln)
                    if h:
                        for j, i0, i1 in self._spans(sps, self.SENSE_HV + hw):
                            mark["S"][li][j][i0:i1] = [1] * (i1 - i0)
                    if ex0 or exempt(sps):
                        continue
                    for j, i0, i1 in self._spans(sps, self.HV_PAD + hw):
                        mark["N" if h else "H"][li][j][i0:i1] = [1] * (i1 - i0)
        for t in b.GetTracks():
            if hv(t.GetNetCode()) and t.Type() != pcbnew.PCB_VIA_T and NAME.get(t.GetLayer()) in self.LAYERS:
                li = self.LAYERS.index(NAME[t.GetLayer()])
                for j, i0, i1 in self._spans(item_poly(t, t.GetLayer()), self.SENSE_HV + hw):
                    mark["S"][li][j][i0:i1] = [1] * (i1 - i0)
        for z in b.Zones():
            if z.GetIsRuleArea() or not hv(z.GetNetCode()):
                continue
            for lid in z.GetLayerSet().CuStack():
                ln = NAME.get(lid)
                if ln in self.LAYERS and z.GetZoneName() not in self.drop:
                    li = self.LAYERS.index(ln)
                    for j, i0, i1 in self._spans(z.GetFilledPolysList(lid), self.SENSE_HV + hw):
                        mark["S"][li][j][i0:i1] = [1] * (i1 - i0)
        free_s = fine.new(0)                                       # sense next to HV is allowed in U*/R* courtyards
        for c in courts(["U*", "R*"]):
            for poly in rings_of(c):
                fine.fill(poly, free_s, 1)
        self.kblock = {}
        for k in self.KEYS:
            self.kblock[k] = [[[0] * self.NX for _ in range(self.NY)] for _ in self.LAYERS]
            for li in range(self.NL):
                m, cnt, blk = mark[k][li], self.tcnt[li], self.kblock[k][li]
                for j in range(fine.ny):
                    mj, cj, ok, fs = m[j], cnt[j], self.inside[j], free_s[j]
                    for i in range(fine.nx):
                        if mj[i] and not cj[i] and ok[i] and not (k == "S" and fs[i]):
                            blk[j // K][i // K] += 1

    def vcap(self, tx, ty):
        """Via sites: free cells are legal via centres (obstacles grown by via radius + clearance), so one free cell
        holds one via; more centres need vp spacing."""
        f = self.vfree[ty][tx]
        return (1.0 if f else 0.0) + f * self.FINE * self.FINE / (self.vp * self.vp)

    # ---- connections
    def _plane_covers(self, net, x, y):
        pt = VECTOR2I(FromMM(x), FromMM(y))
        for z in self.b.Zones():
            if z.GetIsRuleArea() or short(z.GetNetname()) != net:
                continue
            for lid in z.GetLayerSet().CuStack():
                if (net, NAME.get(lid)) in self.planes and z.GetFilledPolysList(lid).Contains(pt):
                    return True
        return False

    def _build_conns(self, rep):
        """Open connections to route. A plane-net connection whose both ends lie over that net's plane is left to
        plane_fanout.py (a via each), not routed."""
        self.conns, self.plane_skipped = [], 0
        plane_nets = {n for n, _ in self.planes}
        for u in rep["unconnected_items"]:
            ends = [self._term(it) for it in u["items"][:2]]
            net = ends[0]["net"] or ends[1]["net"]
            if short(net) in plane_nets and short(net) not in self.cfg.get("router", {}).get("route_plane_nets", []) and \
                    all(self._plane_covers(short(net), e["x"], e["y"]) for e in ends):   # route_plane_nets: when the
                #                                                   plane is cut into pieces, route the link anyway
                self.plane_skipped += 1
                continue
            cl = self.netclass(self.net_full.get(short(net), net))
            self.conns.append({"net": short(net), "ends": ends, "pitch": cl["track_width"] + cl["clearance"],
                               "key": self.key_of(net)})
        self.conns.sort(key=lambda c: (self._span_len(c), c["net"]))

    def _term(self, item):
        d = item["description"]
        m = re.search(r"\[([^\]]*)\]", d)
        t = {"net": m.group(1) if m else "", "desc": d, "x": item["pos"]["x"], "y": item["pos"]["y"], "pad": None}
        pm = re.search(r"[Pp]ad (\S+) \[[^\]]*\] of (\S+)", d)
        if pm and pm.group(2) in self.fp:
            f = self.fp[pm.group(2)]
            pads = [p for p in f.Pads() if p.GetNumber() == pm.group(1)]
            if pads:
                p = min(pads, key=lambda p: math.hypot(ToMM(p.GetPosition().x) - t["x"], ToMM(p.GetPosition().y) - t["y"]))
                t["pad"] = p; t["ref"] = pm.group(2)
                return t
        lm = re.search(r" on ([A-Za-z0-9]+)\.Cu", d)
        if d.startswith(("PTH", "Via")) or " - " in d or not lm:
            t["layers"] = list(range(self.NL))
        else:
            t["layers"] = [self.LAYERS.index(lm.group(1))] if lm.group(1) in self.LAYERS else []
        return t

    def _end(self, t):
        """(layers, tiles) of a connection end, current positions."""
        if t["pad"] is None:
            tx, ty = self.tile_of(t["x"], t["y"])
            return t["layers"], {(tx, ty)}
        p = t["pad"]
        ls = [li for li, l in enumerate(self.LAYERS) if p.IsOnLayer(CU[l])]
        bb = p.GetBoundingBox()
        x0, y0 = self.tile_of(ToMM(bb.GetLeft()), ToMM(bb.GetTop()))
        x1, y1 = self.tile_of(ToMM(bb.GetRight()), ToMM(bb.GetBottom()))
        return ls, {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}

    def _span_len(self, c):
        (a, b) = c["ends"]
        pa = (ToMM(a["pad"].GetPosition().x), ToMM(a["pad"].GetPosition().y)) if a["pad"] else (a["x"], a["y"])
        pb = (ToMM(b["pad"].GetPosition().x), ToMM(b["pad"].GetPosition().y)) if b["pad"] else (b["x"], b["y"])
        return abs(pa[0] - pb[0]) + abs(pa[1] - pb[1])

    def tile_of(self, x, y):
        return min(self.NX - 1, max(0, int((x - self.X0) / self.T))), min(self.NY - 1, max(0, int((y - self.Y0) / self.T)))

    # ---- moves
    def move(self, ref, x, y, rot, bottom=None):
        f = self.fp[ref]
        tok = (ref, ToMM(f.GetPosition().x), ToMM(f.GetPosition().y), f.GetOrientationDegrees(), f.IsFlipped())
        self._place(ref, x, y, rot, f.IsFlipped() if bottom is None else bottom)
        return tok

    def undo(self, tok):
        ref, x, y, rot, flipped = tok
        self._place(ref, x, y, rot, flipped)

    def _place(self, ref, x, y, rot, bottom):
        f = self.fp[ref]
        ts, vs = self.fp_spans[ref]
        for l, sp in ts.items():
            self._add(l, sp, -1, 1)
        self._add(None, vs, -1, 1)
        if f.IsFlipped() != bottom:
            f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        f.SetOrientationDegrees(rot)
        f.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
        ts, vs = self._pad_spans(f)
        self.fp_spans[ref] = (ts, vs)
        for l, sp in ts.items():
            self._add(l, sp, +1, 1)
        self._add(None, vs, +1, 1)
        for k, c in enumerate(self.conns):
            if any(e.get("ref") == ref for e in c["ends"]) and self.routes[k]:
                self._apply(self.routes[k], c, -1); self.routes[k] = None

    # ---- PathFinder
    def _own(self, c):
        s = set()
        for e in c["ends"]:
            ls, tiles = self._end(e)
            s |= {(l, x, y) for l in ls for x, y in tiles}
        return s

    def _node_cost(self, li, tx, ty, pitch, own, pf, key):
        if (li, tx, ty) in own:
            return self.T
        c0, u = self.cap(li, tx, ty), self.use[li][ty][tx]
        ck = self.kcap(key, li, tx, ty)
        over = max(0.0, u + pitch - c0, self.kuse[key][li][ty][tx] + pitch - ck)
        fixed = FIXED if ck < pitch * 0.5 else 1.0
        return self.T * fixed * (1 + self.hist[li][ty][tx]) * (1 + pf * over / pitch)

    def _route(self, c, pf):
        (la, ta), (lb, tb) = self._end(c["ends"][0]), self._end(c["ends"][1])
        if not la or not lb:
            return None
        own, pitch = self._own(c), c["pitch"]
        goal = {(l, x, y) for l in lb for x, y in tb}
        gx, gy = sum(x for x, _ in tb) / len(tb), sum(y for _, y in tb) / len(tb)
        h = lambda tx, ty: max(0.0, abs(tx - gx) + abs(ty - gy) - 1) * self.T
        openq, best, prev = [], {}, {}
        for l in la:
            for x, y in ta:
                n = (l, x, y); best[n] = 0.0; heapq.heappush(openq, (h(x, y), 0.0, n))
        NX, NY, NL = self.NX, self.NY, self.NL
        while openq:
            f, g, n = heapq.heappop(openq)
            if g > best.get(n, 1e18):
                continue
            if n in goal:
                path = [n]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                return path[::-1]
            li, tx, ty = n
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                x, y = tx + dx, ty + dy
                if 0 <= x < NX and 0 <= y < NY:
                    m = (li, x, y)
                    ng = g + self._node_cost(li, x, y, pitch, own, pf, c["key"])
                    if ng < best.get(m, 1e18):
                        best[m] = ng; prev[m] = n; heapq.heappush(openq, (ng + h(x, y), ng, m))
            vc = self.vcap(tx, ty)
            vover = max(0.0, self.vuse[ty][tx] + 1 - vc)
            vcost = self.via_cost * (FIXED if vc < 0.5 and n not in own else 1.0) * (1 + pf * vover)
            for l2 in range(NL):
                if l2 != li:
                    m = (l2, tx, ty); ng = g + vcost
                    if ng < best.get(m, 1e18):
                        best[m] = ng; prev[m] = n; heapq.heappush(openq, (ng + h(tx, ty), ng, m))
        return None

    def _apply(self, path, c, sign):
        """Add (+1) a route's usage, or remove (-1) exactly what was added, whatever moved since."""
        if sign < 0:
            for li, tx, ty, amt in c.pop("applied", []):
                if li < 0:
                    self.vuse[ty][tx] -= amt
                else:
                    self.use[li][ty][tx] -= amt
                    self.kuse[c["key"]][li][ty][tx] -= amt
            return
        own = self._own(c)
        c["own_cache"] = own
        added = []
        for k, (li, tx, ty) in enumerate(path):
            if (li, tx, ty) not in own:
                added.append((li, tx, ty, c["pitch"]))
            if k and path[k - 1][0] != li and path[k - 1][1:] == (tx, ty):
                added.append((-1, tx, ty, 1.0))
                for l2 in range(self.NL):
                    if self.cap(l2, tx, ty) >= self.vp:
                        added.append((l2, tx, ty, self.vp * 0.5))
        for li, tx, ty, amt in added:
            if li < 0:
                self.vuse[ty][tx] += amt
            else:
                self.use[li][ty][tx] += amt
                self.kuse[c["key"]][li][ty][tx] += amt
        c["applied"] = added

    def demand(self):
        """Route count per tile over all layers, {(tx, ty): n}: where the signals want to go."""
        d = collections.Counter()
        for r in self.routes:
            for li, tx, ty in r or []:
                d[(tx, ty)] += 1
        return d

    def overflow_split(self):
        """(track overflow mm, via overflow mm)."""
        tot, tiles = self.overflow()
        v = sum(o * self.vp for li, _, _, o in tiles if li < 0)
        return tot - v, v

    def overflow(self):
        tot, tiles = 0.0, []
        for li in range(self.NL):
            for ty in range(self.NY):
                for tx in range(self.NX):
                    o = max([self.use[li][ty][tx] - self.cap(li, tx, ty)]
                            + [self.kuse[k][li][ty][tx] - self.kcap(k, li, tx, ty) for k in self.KEYS])
                    if o > 1e-6:
                        tot += o; tiles.append((li, tx, ty, o))
        for ty in range(self.NY):
            for tx in range(self.NX):
                o = self.vuse[ty][tx] - self.vcap(tx, ty)
                if o > 1e-6:
                    tot += o * self.vp; tiles.append((-1, tx, ty, o))
        return tot, tiles

    def _touches(self, path, c):
        own = c.get("own_cache", set())
        for k, (li, tx, ty) in enumerate(path):
            if (li, tx, ty) not in own and (self.use[li][ty][tx] > self.cap(li, tx, ty) + 1e-6
                                            or self.kuse[c["key"]][li][ty][tx] > self.kcap(c["key"], li, tx, ty) + 1e-6):
                return True
            if k and path[k - 1][0] != li and self.vuse[ty][tx] > self.vcap(tx, ty) + 1e-6:
                return True
        return False

    def solve(self, iters=40, warm=False, quiet=True, reset_hist=True):
        """Negotiated congestion. warm: keep the current routes and reroute only missing or illegal ones."""
        if reset_hist:
            for li in range(self.NL):
                for row in self.hist[li]:
                    row[:] = [0.0] * self.NX
        if not warm:
            for k, c in enumerate(self.conns):
                if self.routes[k]:
                    self._apply(self.routes[k], c, -1); self.routes[k] = None
        pf, self.curve, best = 0.5, [], (1e18, None)
        step = self.D["track_width"] + self.D["clearance"]
        for it in range(iters):
            for k, c in enumerate(self.conns):
                if self.routes[k] and not self._touches(self.routes[k], c):
                    continue
                if self.routes[k]:
                    self._apply(self.routes[k], c, -1)
                self.routes[k] = self._route(c, pf)
                if self.routes[k]:
                    self._apply(self.routes[k], c, +1)
            tot, tiles = self.overflow()
            self.curve.append(round(tot, 2))
            if tot < best[0] - 1e-9:
                best = (tot, list(self.routes))
            if not quiet:
                import sys
                print(f"iteration {it + 1}: overflow {tot:.2f} mm in {len(tiles)} tiles", file=sys.stderr)
            if tot < 1e-6:
                break
            for li, tx, ty, o in tiles:
                if li >= 0:
                    self.hist[li][ty][tx] += 0.5 * min(3.0, o / step)
            pf = min(pf * 1.3, 50.0)
        if best[1] is not None:
            for k, c in enumerate(self.conns):
                if self.routes[k]:
                    self._apply(self.routes[k], c, -1)
            self.routes = best[1]
            for k, c in enumerate(self.conns):
                if self.routes[k]:
                    self._apply(self.routes[k], c, +1)
        return best[0] if best[1] is not None else self.overflow()[0]

    # ---- diagnostics
    def fixed_crossings(self):
        out = collections.defaultdict(list)
        for k, (c, r) in enumerate(zip(self.conns, self.routes)):
            own = c.get("own_cache", set())
            for li, tx, ty in r or []:
                if (li, tx, ty) not in own and self.kcap(c["key"], li, tx, ty) < c["pitch"] * 0.5:
                    out[k].append((li, tx, ty))
        return out

    def hotspots(self):
        tot, tiles = self.overflow()
        over_set = {(li, tx, ty) for li, tx, ty, _ in tiles if li >= 0}
        nets_at = collections.defaultdict(set)
        for c, r in zip(self.conns, self.routes):
            for n in r or []:
                if n in over_set:
                    nets_at[n].add(c["net"])
        cells, spots, seen = {(tx, ty) for _, tx, ty, _ in tiles}, [], set()
        for cxy in sorted(cells):
            if cxy in seen:
                continue
            grp, q = [], [cxy]; seen.add(cxy)
            while q:
                u = q.pop(); grp.append(u)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        v = (u[0] + dx, u[1] + dy)
                        if v in cells and v not in seen:
                            seen.add(v); q.append(v)
            o = sum(ov * (self.vp if li < 0 else 1) for li, tx, ty, ov in tiles if (tx, ty) in grp)
            nets = sorted({n for li in range(self.NL) for t in grp for n in nets_at.get((li, t[0], t[1]), ())})
            why = collections.Counter()
            K = self.K
            for li in range(self.NL):
                for tx, ty in grp:
                    for j in range(ty * K, min((ty + 1) * K, self.fine.ny)):
                        for i in range(tx * K, min((tx + 1) * K, self.fine.nx)):
                            if self.reason[li][j][i]:
                                why[self.reason[li][j][i]] += 1
            xs = [self.X0 + (t[0] + 0.5) * self.T for t in grp]; ys = [self.Y0 + (t[1] + 0.5) * self.T for t in grp]
            spots.append({"overflow": o, "tiles": grp, "box": (min(xs), min(ys), max(xs), max(ys)), "nets": nets,
                          "blocked_by": [RN[k] for k, _ in why.most_common(2) if k]})
        spots.sort(key=lambda s: -s["overflow"])
        return spots

    def png(self, path):
        from raster import write_png
        S, rows_all = 8, []
        fixed = {n for ns in self.fixed_crossings().values() for n in ns}
        K, fine = self.K, self.fine
        panels = []
        for li, l in enumerate(self.LAYERS):
            rows = []
            for py in range(self.NY * S):
                ty, row = py // S, []
                fy = min(fine.ny - 1, int((py + 0.5) * self.T / S / self.FINE))
                for px in range(self.NX * S):
                    tx = px // S
                    fx = min(fine.nx - 1, int((px + 0.5) * self.T / S / self.FINE))
                    if not self.inside[fy][fx]:
                        row.append((40, 40, 40)); continue
                    base_c = (205, 205, 205) if self.tcnt[li][fy][fx] else (255, 255, 255)
                    c0, u = self.cap(li, tx, ty), self.use[li][ty][tx]
                    if (li, tx, ty) in fixed:
                        row.append((220, 0, 220))
                    elif u > c0 + 1e-6:
                        row.append((255, max(0, 140 - int(120 * (u - c0) / 0.3)), 0))
                    elif u > 0:
                        f = min(1.0, u / max(c0, 0.01))
                        row.append((int(base_c[0] * (1 - 0.7 * f)), int(base_c[1] * (1 - 0.4 * f)), 255))
                    else:
                        row.append(base_c)
                rows.append(row)
            panels.append(rows)
        gap = [(40, 40, 40)] * 6
        write_png(path, [sum((p[r] + gap for p in panels), []) for r in range(self.NY * S)])

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
