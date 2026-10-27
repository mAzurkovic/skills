"""Size every netclass from the board's currents and voltages: the thinnest track, tightest clearance and smallest via
that the fab, the current (IPC-2152), the pulse (adiabatic) and the voltage (IPC-2221B) allow.

    sizing.py BOARD [--write] [--md OUT.md]

Without --write: prints the sizing table (markdown) and what would change. With --write: sets track width,
clearance and via per class in BOARD's .kicad_pro, and replaces the sizing rules in its .kicad_dru with a generated
block (per-layer width floors, exposed-pad spacing, via sizes). Rules named in sizing.replace_rules are removed
from the .kicad_dru first; every other rule stays.

Config:
  "stackup": {"F": 2, "In1": 1, "In2": 1, "B": 2}                  oz per layer
  "currents": [{"nets": [glob], "rms": A, "rise_c": C, "peak": A, "peak_s": s, "peak_rise_c": C,
                "volts": V, "pour": bool, "min_width": mm, "why": text}, ...]   first match wins
  "sizing": {"rise_c": 10, "default_rms": 0.02, "default_volts": 5, "derate": 1.0, "plating_mm": 0.018,
             "vias": {"signal": [0.2, 0.45], "power": [0.3, 0.6]}, "neck_courtyards": ["U*"],
             "pad_exempt_courtyards": ["Q*", "U*"], "fixed_width_classes": ["USB", "CAN"],
             "replace_rules": [rule names], "fab_track_space": {"0.5": 0.09, "1": 0.09, "2": 0.15}}

Per net and layer: width = max(fab floor, IPC-2152 width for rms at rise_c, adiabatic width for the peak pulse,
min_width). Pour nets (rms carried by zones on several layers): the class width is the fab floor or min_width,
the pour width is reported per layer and checked after routing by current_check.py. Class value = max over its
nets; netclass width = max over layers (the router's width), DRC floor per layer (outer / inner) = that layer's
value. Clearance: netclass = max(fab space, B4 coated) on outer, inner rule = max(fab space, B1); exposed pads of a
class above 30 V get B2 to other classes outside pad_exempt_courtyards. Via: the signal via when it carries the net's
rms, else the power via; vias per layer change = ceil(rms / via_amps)."""
import argparse, fnmatch, json, math, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ipc

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--write", action="store_true"); ap.add_argument("--md")
a = ap.parse_args()

base = re.sub(r"\.kicad_pcb$", "", a.board)
cfg = json.load(open(base + ".layout.json")) if os.path.exists(base + ".layout.json") else {}
S = cfg.get("sizing", {})
pro_path, dru_path = base + ".kicad_pro", base + ".kicad_dru"
pro = json.load(open(pro_path))
stack = {k: float(v) for k, v in cfg.get("stackup", {"F": 1, "In1": 0.5, "In2": 0.5, "B": 1}).items()}
outer = [l for l in stack if l in ("F", "B")]
inner = [l for l in stack if l not in ("F", "B")]
rise0, derate, plating = S.get("rise_c", 10), S.get("derate", 1.0), S.get("plating_mm", 0.018)
fab = {float(k): v for k, v in S.get("fab_track_space", {}).items()} or None
vias = S.get("vias", {"signal": [0.2, 0.45], "power": [0.3, 0.6]})
fixed = set(S.get("fixed_width_classes", ["USB", "CAN"]))
neck = S.get("neck_courtyards", ["U*"])
pad_exempt = S.get("pad_exempt_courtyards", ["Q*", "U*"])
DEFAULT_REPLACE = ["HV clearance, outer", "HV clearance, inner", "HV track width", "gate drive width",
                   "logic power width", "outer track and space", "inner signal track and space", "via size",
                   "power via size"]
replace = S.get("replace_rules", DEFAULT_REPLACE)


def short(n):
    return n.split("/")[-1]


# ---- nets on the board and their classes (same matching as KiCad: pattern on the full name)
txt = open(a.board).read()
nets = sorted({m for m in re.findall(r'\(net (?:\d+ )?"([^"]+)"\)', txt) if m and not m.startswith("unconnected")})
patterns = pro["net_settings"].get("netclass_patterns", [])
classes = {c["name"]: c for c in pro["net_settings"]["classes"]}


def netclass(n):
    for p in patterns:
        if fnmatch.fnmatchcase(n, p["pattern"]) or fnmatch.fnmatchcase("/" + short(n), p["pattern"]):
            return p["netclass"]
    return "Default"


def current(n):
    for c in cfg.get("currents", []):
        if any(fnmatch.fnmatchcase(short(n), g) for g in c["nets"]):
            return c
    return {}


def fab_floor(l):
    return ipc.fab_track_space(stack[l], fab)


def via_for(rms, rise):
    for kind in ("signal", "power"):
        d = vias[kind]
        if ipc.via_amps(d[0], rise, plating, derate) >= rms or kind == "power":
            return kind, d, max(1, math.ceil(rms / ipc.via_amps(d[0], rise, plating, derate)))


# ---- per net
rows, per_class = [], {}
for n in nets:
    cl = netclass(n)
    if cl not in classes:
        cl = "Default"
    c = current(n)
    rms, rise = c.get("rms", S.get("default_rms", 0.02)), c.get("rise_c", rise0)
    volts = c.get("volts", S.get("default_volts", 5))
    w = {}
    for l in stack:
        cur = ipc.width_for_current(rms, rise, stack[l], derate)
        pul = ipc.pulse_width(c["peak"], c.get("peak_s", 1), c.get("peak_rise_c", 60), stack[l]) if c.get("peak") else 0
        need = 0 if c.get("pour") else max(cur, pul)
        w[l] = round(max(fab_floor(l), need, c.get("min_width", 0)) + 0.004, 2)
    kind, vsize, nvia = via_for(rms, rise)
    pc = per_class.setdefault(cl, {"w": {l: 0 for l in stack}, "volts": 0, "via": "signal", "nets": []})
    for l in stack:
        pc["w"][l] = max(pc["w"][l], w[l])
    pc["volts"] = max(pc["volts"], volts)
    if kind == "power" and not c.get("pour"):         # pours change layer through via arrays, not the class via
        pc["via"] = "power"
    pc["nets"].append(short(n))
    pour = ""
    if c.get("pour"):
        layers = c.get("layers", outer + inner)
        k = len(layers)
        per = {l: ipc.width_for_current(rms / k, rise, stack[l], derate) for l in layers}
        if c.get("peak"):
            pa = ipc.pulse_area_mm2(c["peak"], c.get("peak_s", 1), c.get("peak_rise_c", 60))
            tot = sum(ipc.thickness_mm(stack[l]) for l in layers)
            per = {l: max(per[l], pa / tot) for l in layers}
        pour = ", ".join(f"{l} {v:.1f}" for l, v in per.items())
    if c or kind == "power":
        rows.append((short(n), cl, f"{rms:g}", f"{rise:g}", f"{c['peak']:g} A {c.get('peak_s', 1):g} s" if c.get("peak") else "",
                     f"{volts:g}", " / ".join(f"{w[l]:.2f}" for l in stack), pour,
                     f"{vsize[0]:g}/{vsize[1]:g} x{nvia}", c.get("why", "")))

# ---- per class
out_cls = {}
for cl, pc in per_class.items():
    width = max(pc["w"].values())
    v = pc["volts"]
    clear = max(max(fab_floor(l) for l in outer), ipc.spacing(v, "B4"))
    d = vias[pc["via"]]
    out_cls[cl] = {"track_width": width, "clearance": round(clear, 2), "via_drill": d[0], "via_diameter": d[1],
                   "outer": max(pc["w"][l] for l in outer), "inner": max(pc["w"][l] for l in inner) if inner else width,
                   "volts": v, "pad_b2": ipc.spacing(v, "B2") if v > 30 else 0}
    if cl in fixed:
        out_cls[cl]["track_width"] = classes[cl]["track_width"]

hdr = "| Net | Class | RMS A | Rise C | Peak | V | Width mm (" + " / ".join(stack) + ") | Pour width mm per layer | Via x per layer change | Why |"
md = [hdr, "|" + "---|" * 10]
md += ["| " + " | ".join(r) + " |" for r in rows]
md += ["", "| Class | Track mm (router) | Outer floor | Inner floor | Clearance mm | Exposed-pad spacing mm | Via drill/dia | Was |",
       "|---|---|---|---|---|---|---|---|"]
for cl, o in sorted(out_cls.items()):
    old = classes[cl]
    was = f"{old['track_width']:g} / {old['clearance']:g} / {old['via_drill']:g}/{old['via_diameter']:g}"
    md.append(f"| {cl}{' (fixed width)' if cl in fixed else ''} | {o['track_width']:g} | {o['outer']:g} | {o['inner']:g} | {o['clearance']:g} | "
              f"{o['pad_b2'] or '-'} | {o['via_drill']:g}/{o['via_diameter']:g} | {was} |")
inner_clear = max([fab_floor(l) for l in inner] + [ipc.spacing(max(o["volts"] for o in out_cls.values()), "B1")]) if inner else None
md.append(f"\nInner-layer clearance (all classes): {inner_clear} mm. Rise {rise0} C unless listed; IPC-2152 universal chart"
          f" fit, derate {derate}; via plating {plating * 1000:g} um; pulses adiabatic at 100 C resistivity.")
text = "\n".join(md)
print(text)
if a.md:
    open(a.md, "w").write(text + "\n")
if not a.write:
    sys.exit(0)

# ---- write .kicad_pro
for c in pro["net_settings"]["classes"]:
    o = out_cls.get(c["name"])
    if o:
        for k in ("track_width", "clearance", "via_drill", "via_diameter"):
            c[k] = o[k]
r = pro["board"]["design_settings"]["rules"]
r["min_track_width"] = min(fab_floor(l) for l in stack)
r["min_clearance"] = min(fab_floor(l) for l in stack)
r["min_via_diameter"] = min(v[1] for v in vias.values())
r["min_through_hole_diameter"] = min(v[0] for v in vias.values())
json.dump(pro, open(pro_path, "w"), indent=2)

# ---- write .kicad_dru: drop the hand sizing rules, replace the generated block
dru = open(dru_path).read() if os.path.exists(dru_path) else "(version 1)\n"
dru = re.sub(r"\n# ---- sizing\.py: generated.*?# ---- end sizing\.py\n", "\n", dru, flags=re.S)
for name in replace:
    i = dru.find(f'(rule "{name}"')
    if i < 0:
        continue
    j, depth = i, 0
    while True:
        depth += (dru[j] == "(") - (dru[j] == ")")
        j += 1
        if depth == 0:
            break
    dru = dru[:i].rstrip("\n") + "\n" + dru[j:].lstrip("\n")
not_in = lambda pats, who="A": " && ".join(f"!{who}.intersectsCourtyard('{p}')" for p in pats)
g = ["# ---- sizing.py: generated, do not edit by hand (re-run sizing.py --write)"]
for l in ("outer", "inner"):
    ls = outer if l == "outer" else inner
    if not ls:
        continue
    g.append(f'(rule "sizing: fab floor, {l}"\n  (layer {l})\n  (condition "A.Type == \'Track\'")\n'
             f'  (constraint track_width (min {min(fab_floor(x) for x in ls)}mm)))')
for cl, o in sorted(out_cls.items()):
    for l in ("outer", "inner"):
        w = o[l]
        if w <= min(fab_floor(x) for x in (outer if l == "outer" else inner)) or cl in fixed:
            continue
        g.append(f'(rule "sizing: {cl} width, {l}"\n  (layer {l})\n'
                 f'  (condition "A.Type == \'Track\' && A.hasNetclass(\'{cl}\') && {not_in(neck)}")\n'
                 f'  (constraint track_width (min {w}mm)))')
if inner_clear:
    g.append(f'(rule "sizing: inner clearance"\n  (layer inner)\n  (condition "A.Type == \'Track\' || A.Type == \'Via\' || A.Type == \'Zone\'")\n'
             f'  (constraint clearance (min {inner_clear}mm)))')
for cl, o in sorted(out_cls.items()):
    if o["pad_b2"] > o["clearance"]:
        g.append(f'(rule "sizing: {cl} exposed pads, outer"\n  (layer outer)\n'
                 f'  (condition "(A.Type == \'Pad\' || B.Type == \'Pad\') && A.hasNetclass(\'{cl}\') && !B.hasNetclass(\'{cl}\') && '
                 f'{not_in(pad_exempt)} && {not_in(pad_exempt, "B")}")\n  (constraint clearance (min {o["pad_b2"]}mm)))')
sig, pwr = vias["signal"], vias["power"]
g.append(f'(rule "sizing: via size"\n  (condition "A.Type == \'Via\'")\n  (constraint hole_size (min {sig[0]}mm))\n'
         f'  (constraint via_diameter (min {sig[1]}mm))\n  (constraint annular_width (min {round((sig[1] - sig[0]) / 2 - 0.001, 3)}mm)))')
pw = [cl for cl, o in out_cls.items() if o["via_drill"] >= pwr[0]]
if pw:
    cond = " || ".join(f"A.hasNetclass('{cl}')" for cl in sorted(pw))
    g.append(f'(rule "sizing: power via size"\n  (condition "A.Type == \'Via\' && ({cond})")\n'
             f'  (constraint hole_size (min {pwr[0]}mm))\n  (constraint via_diameter (min {pwr[1]}mm)))')
g.append("# ---- end sizing.py")
open(dru_path, "w").write(dru.rstrip("\n") + "\n\n" + "\n".join(g) + "\n")
print(f"\nwrote {pro_path} (classes) and {dru_path} ({len(g) - 2} generated rules)")
