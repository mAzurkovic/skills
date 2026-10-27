"""Reserve corridors before small parts are placed: high-current paths and bus lanes become rule areas that forbid
footprints (and optionally other tracks or vias) on the listed layers. Placement scripts and DRC both respect them.

    corridors.py BOARD [--check-only] [--remove]

Config "corridors": [
  {"name": "pass-through VBUS top", "layers": ["F"], "width": 2.5,
   "path": [[x, y], ...]            # or "from": "J1.2", "to": "J2.2" for a straight pad-to-pad lane
   "forbid": ["footprints"]}        # any of footprints, tracks, vias (tracks/vias block every net, so use them
                                    # only for lanes that will be poured or hand-routed later)
]
--check-only: report the parts that sit in each corridor, add nothing. --remove: delete corridors added earlier
(rule areas named "corridor: ..."). Without either, existing corridor areas are replaced."""
import argparse, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from pcbnew import FromMM, ToMM, VECTOR2I
from klib import Board, LAYER, polyset, circle, strip_items

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--check-only", action="store_true"); ap.add_argument("--remove", action="store_true")
a = ap.parse_args()

# drop corridor areas from an earlier run (by name prefix, through the file: Remove() crashes headless)
names = [str(z.GetZoneName()) for z in pcbnew.LoadBoard(a.board).Zones() if str(z.GetZoneName()).startswith("corridor: ")]
if names and not a.check_only:
    print("removed old corridor areas:", strip_items(a.board, kinds=("zone",), zone_names=names))
if a.remove:
    sys.exit(0)
B = Board(a.board)


def lane(points, width):
    out = None
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        L = math.hypot(x2 - x1, y2 - y1); nx, ny = -(y2 - y1) / L * width / 2, (x2 - x1) / L * width / 2
        seg = polyset([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])
        out = seg if out is None else (out.BooleanAdd(seg) or out)
    for x, y in points[1:-1]:
        out.BooleanAdd(circle(x, y, width / 2, 24))
    return out


for c in B.cfg.get("corridors", []):
    ends = set()
    if "path" in c:
        pts = [tuple(p) for p in c["path"]]
    else:
        ends = {c["from"].split(".")[0], c["to"].split(".")[0]}
        (ra, pa), (rb, pb) = c["from"].split("."), c["to"].split(".")
        pts = [B.pad_xy(ra, pa), B.pad_xy(rb, pb)]
    shape = lane(pts, c["width"])
    hits = []
    for ref, f in B.fp.items():
        side = "B" if f.IsFlipped() else "F"
        th = any(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in f.Pads())
        if side not in c["layers"] and not (th and any(l in ("F", "B") for l in c["layers"])):
            continue
        crt = B.court(ref)
        if crt is not None and shape.Collide(crt.Outline(0), 0):
            # parts of the corridor's own net (e.g. the connector it starts at) are allowed
            if c.get("net") and all(str(p.GetNetname()).split("/")[-1] in (c["net"], "") for p in f.Pads()):
                continue
            if ref in ends:                   # the connectors the lane starts and ends at
                continue
            hits.append(ref)
    print(f"{c['name']}: {len(pts) - 1} segment(s), {c['width']} mm on {','.join(c['layers'])}; parts inside: {', '.join(sorted(hits)) or 'none'}")
    if not a.check_only:
        forbid = c.get("forbid", ["footprints"])
        B.keepout(shape, c["layers"], tracks="tracks" in forbid, vias="vias" in forbid, footprints="footprints" in forbid,
                  name="corridor: " + c["name"])
if not a.check_only:
    B.save()
