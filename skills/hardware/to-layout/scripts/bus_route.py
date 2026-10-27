"""Route a structured IC-to-IC bus as parallel tracks from one centerline (the densest bus is scripted, not
autorouted). Run bus_check.py first: on one layer the bus routes only when its crossing count is 0.

    bus_route.py BOARD --bus NAME [--dry-run]

Config "buses": [{
  "name": "pwm_high", "layer": "F", "width": 0.15, "pitch": 0.5,
  "nets": ["INHC", "INHB", "INHA"],      # LEFT to RIGHT, looking along the path direction
  "path": [[x, y], ...],                 # centerline from the start pins to the end pins, 45 / 90 degree bends
  "start": "U3", "end": "U4",            # the parts whose pins the tracks start and end at
  "via_start": false, "via_end": false,  # true: a via at that end of each track (stub on the pin's layer)
  "via": [0.2, 0.45], "lock": true,
  "fan": 0.6}]                           # stub leaves each pin straight out of the chip edge for this long first
Each net's track is the centerline offset by (index - middle) x pitch to the left of travel (miter corners). Each
end joins its pin by a stub that first leaves the pin straight out of the chip edge for "fan" mm (so it never cuts
a neighbouring pin) and then runs to the track end: pick the path start where the tracks' pitch has room. DRC decides whether the result is legal: run drc.py after."""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from klib import Board, offset_polyline, short

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--bus", required=True); ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()
B = Board(a.board)
bus = next(b for b in B.cfg.get("buses", []) if b["name"] == a.bus)
path = [tuple(p) for p in bus["path"]]
n = len(bus["nets"]); mid = (n - 1) / 2
w, pitch, layer = bus.get("width", 0.15), bus.get("pitch", 0.5), bus["layer"]
drill, dia = bus.get("via", [0.2, 0.45])
lock = bus.get("lock", True)


def pin_of(ref, net):
    """Pad centre, its layer, and the point `fan` mm straight out of the chip edge from it."""
    from pcbnew import ToMM, F_Cu
    ps = [p for p in B.fp[ref].Pads() if short(p.GetNetname()) == short(net)]
    if not ps:
        raise SystemExit(f"{ref} has no pad on net {net}")
    p = ps[0]; c = B.fp[ref].GetPosition()
    x, y = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y); dx, dy = x - ToMM(c.x), y - ToMM(c.y)
    ux, uy = ((1 if dx > 0 else -1), 0) if abs(dx) > abs(dy) else (0, (1 if dy > 0 else -1))
    # start the straight part at the pad's outer edge
    bb = p.GetBoundingBox(); half = (ToMM(bb.GetWidth()) if ux else ToMM(bb.GetHeight())) / 2
    fan = bus.get("fan", 0.6)
    return (x, y), ("F" if p.IsOnLayer(F_Cu) else "B"), (x + ux * (half + fan), y + uy * (half + fan))


for i, net in enumerate(bus["nets"]):
    # nets are listed left to right; offset_polyline takes + as left of travel
    line = offset_polyline(path, (mid - i) * pitch)
    (sx, sy), slay, sfan = pin_of(bus["start"], net)
    (ex, ey), elay, efan = pin_of(bus["end"], net)
    print(f"{net:10} start pin ({sx:.2f}, {sy:.2f}) -> track {len(line) - 1} segments -> end pin ({ex:.2f}, {ey:.2f})")
    if a.dry_run:
        continue
    B.track(line, net, layer, w, lock)
    for (px, py), fan_pt, (tx, ty), use_via, play in (((sx, sy), sfan, line[0], bus.get("via_start"), slay),
                                                        ((ex, ey), efan, line[-1], bus.get("via_end"), elay)):
        pts = [(px, py), fan_pt, (tx, ty)]
        if use_via:
            B.via(tx, ty, net, drill, dia, lock)
            B.track(pts, net, play, w, lock)
        else:
            B.track(pts, net, layer, w, lock)
if not a.dry_run:
    B.save()
