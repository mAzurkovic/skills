"""Board copper on a grid, for the checks that need area rather than pad-to-pad distances (current_check.py,
global_route.py, plane_fanout.py). Scanline fill of the real item outlines (zone fills, tracks, pads, vias), pure
Python, deterministic.

    g = Grid(x0, y0, x1, y1, cell)            # mm
    g.fill(rings, layer_grid, value)          # rings: [[(x, y), ...], ...] of one polygon with its holes
    rings_of(shape_poly_set)                  # pcbnew SHAPE_POLY_SET -> list of ring lists, one per outline

A cell belongs to a shape when its centre is inside (even-odd within one outline and its holes)."""
import math
import pcbnew
from pcbnew import ToMM, FromMM

CU = {"F": pcbnew.F_Cu, "B": pcbnew.B_Cu}
CU.update({f"In{k}": getattr(pcbnew, f"In{k}_Cu") for k in range(1, 7)})
NAME = {v: k for k, v in CU.items()}
ORDER = ["F", "In1", "In2", "B"]          # physical stack order of a 4-layer board; stack(board) for any other


def stack(board):
    """Copper layer names of this board in physical order: F, In1 .. In(n-2), B."""
    n = board.GetCopperLayerCount()
    return ["F"] + [f"In{k}" for k in range(1, n - 1)] + ["B"]


def rings_of(sps):
    out = []
    for i in range(sps.OutlineCount()):
        rs = [sps.Outline(i)] + [sps.Hole(i, j) for j in range(sps.HoleCount(i))]
        out.append([[(ToMM(r.CPoint(k).x), ToMM(r.CPoint(k).y)) for k in range(r.PointCount())] for r in rs])
    return out


def item_poly(item, layer, inflate=0.0):
    """Copper outline of a pad, track, arc or via on `layer` (pcbnew id), grown by `inflate` mm."""
    sps = pcbnew.SHAPE_POLY_SET()
    if isinstance(item, pcbnew.PAD):
        sps = pcbnew.SHAPE_POLY_SET(item.GetEffectivePolygon(layer, pcbnew.ERROR_INSIDE))
    else:
        item.TransformShapeToPolygon(sps, layer, 0, FromMM(0.01), pcbnew.ERROR_INSIDE)
    if inflate > 0:
        sps.Inflate(FromMM(inflate), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, FromMM(0.02))
    return sps


class Grid:
    def __init__(self, x0, y0, x1, y1, cell):
        self.cell = cell
        self.x0, self.y0 = x0, y0
        self.nx, self.ny = int(math.ceil((x1 - x0) / cell)), int(math.ceil((y1 - y0) / cell))

    def new(self, fill=0):
        return [[fill] * self.nx for _ in range(self.ny)]

    def xy(self, i, j):
        return self.x0 + (i + 0.5) * self.cell, self.y0 + (j + 0.5) * self.cell

    def ij(self, x, y):
        return int((x - self.x0) / self.cell), int((y - self.y0) / self.cell)

    def spans(self, rings):
        """Yield (row, i_from, i_to_exclusive) for the cells whose centres lie inside `rings` (outline + holes)."""
        edges = []
        for r in rings:
            n = len(r)
            for k in range(n):
                (xa, ya), (xb, yb) = r[k], r[(k + 1) % n]
                if ya != yb:
                    edges.append((min(ya, yb), max(ya, yb), xa, ya, (xb - xa) / (yb - ya)))
        if not edges:
            return
        ylo, yhi = min(e[0] for e in edges), max(e[1] for e in edges)
        j0, j1 = max(0, int((ylo - self.y0) / self.cell)), min(self.ny - 1, int((yhi - self.y0) / self.cell) + 1)
        edges.sort()
        for j in range(j0, j1 + 1):
            yc = self.y0 + (j + 0.5) * self.cell
            xs = sorted(xa + (yc - ya) * s for lo, hi, xa, ya, s in edges if lo <= yc < hi)
            for a, b in zip(xs[0::2], xs[1::2]):
                i0 = max(0, int(math.ceil((a - self.x0) / self.cell - 0.5)))
                i1 = min(self.nx, int(math.floor((b - self.x0) / self.cell - 0.5)) + 1)
                if i1 > i0:
                    yield j, i0, i1

    def fill(self, rings, g, value):
        for j, i0, i1 in self.spans(rings):
            row = g[j]
            for i in range(i0, i1):
                row[i] = value

    def mark(self, rings, g, value, conflict):
        """Like fill, but a cell already holding another non-zero value becomes `conflict`."""
        for j, i0, i1 in self.spans(rings):
            row = g[j]
            for i in range(i0, i1):
                v = row[i]
                row[i] = value if v in (0, value) else conflict


def write_png(path, rgb_rows):
    """Minimal PNG writer (no PIL in KiCad's Python): rgb_rows = [[(r, g, b), ...], ...]."""
    import struct, zlib
    h, w = len(rgb_rows), len(rgb_rows[0])
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in rgb_rows)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
