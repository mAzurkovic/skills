"""Freerouting adapter: routing copy, DSN with the board's real rules, one job at a time, log summary, SES import.

    fr_run.py BOARD [--work DIR] [--dsn-only] [--passes N] [--timeout S] [--no-import] [--jar PATH]

Steps:
  1. Copy BOARD with its .kicad_pro and .kicad_dru into --work (default build/freerouting/<board>). Without the
     .kicad_pro next to the copy the DSN carries one 0.2 mm class and nothing else.
  2. Drop the zones named in freerouting.drop_zones (pours the router must not see), refill the rest with kicad-cli,
     reshape every remaining zone outline to its fill (the router treats the outline as copper).
  3. Export the DSN, then check it: more than one class, every .kicad_pro class width present, both via padstacks.
     Any check failing stops the run.
  4. DSN edits: freerouting.power_layers -> (type power); freerouting.drop_nets removed from the router; class to
     class clearances: every hv_classes x every other class at hv_other_um, every hv_classes x sense_classes at
     sense_hv_um (Freerouting knows no custom DRC rules: these stand in for the .kicad_dru ones).
  5. Run Freerouting (no neck-down, copper 0.5 mm from the edge, --passes, --timeout). Refuses to start when another
     Freerouting job is running: two jobs clobber each other's files and halve the speed.
  6. Import the SES into a copy of BOARD (<work>/routed.kicad_pcb), refill it, print its DRC summary and the
     unrouted connections per net. Copy it over the real board yourself when it is better.

Config "freerouting": {"drop_zones": [...], "power_layers": ["In1"], "drop_nets": ["GND"],
                       "hv_classes": [...], "sense_classes": [...], "hv_other_um": 200, "sense_hv_um": 600,
                       "max_passes": 100, "timeout_s": 2400, "jar": "~/.local/share/freerouting/freerouting-2.5.0.jar"}"""
import argparse, glob, json, os, re, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pcbnew
from klib import KICAD_CLI, drc, drc_summary, load_config, short, strip_items

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--work"); ap.add_argument("--dsn-only", action="store_true")
ap.add_argument("--passes", type=int); ap.add_argument("--timeout", type=int); ap.add_argument("--no-import", action="store_true")
ap.add_argument("--jar")
a = ap.parse_args()
cfg = load_config(a.board).get("freerouting", {})
base = os.path.splitext(a.board)[0]; name = os.path.basename(base)
work = os.path.abspath(a.work or os.path.join("build", "freerouting", name)); os.makedirs(work, exist_ok=True)
lock = os.path.join(work, "fr.lock")


def running():
    r = subprocess.run(["pgrep", "-f", "freerouting.*\\.jar"], capture_output=True, text=True)
    return [p for p in r.stdout.split() if int(p) != os.getpid()]


if not a.dsn_only and (running() or os.path.exists(lock)):
    raise SystemExit(f"Freerouting already running (pids {running()}, lock {lock}): wait, or kill it and delete the lock")

# 1-2. routing copy
rb = os.path.join(work, "route.kicad_pcb")
shutil.copy(a.board, rb)
for ext in (".kicad_pro", ".kicad_dru"):
    if os.path.exists(base + ext):
        shutil.copy(base + ext, os.path.join(work, "route" + ext))
if not os.path.exists(base + ".kicad_pro"):
    raise SystemExit(f"{base}.kicad_pro missing: the DSN would carry one default class")
if cfg.get("drop_zones"):
    print("zones dropped", strip_items(rb, kinds=("zone",), zone_names=cfg["drop_zones"]))
subprocess.run([KICAD_CLI, "pcb", "drc", "--refill-zones", "--save-board", "-o", os.path.join(work, "fill.rpt"), rb],
               env=dict(os.environ, FONTCONFIG_FILE="/dev/null"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
b = pcbnew.LoadBoard(rb)
n = 0
for z in list(b.Zones()):
    if z.GetIsRuleArea():
        continue
    fill = z.GetFilledPolysList(z.GetLayer())
    if fill.OutlineCount() == 0:
        continue
    cp = pcbnew.SHAPE_POLY_SET(fill); cp.thisown = 0
    z.SetOutline(cp); n += 1
print("zones reshaped to their fill", n)
b.Save(rb)

# 3. DSN and its checks
dsn = os.path.join(work, "board.dsn")
pcbnew.ExportSpecctraDSN(b, dsn)
d = open(dsn).read()
classes = dict(re.findall(r"\(class (\S+) .*?\(width (\d+(?:\.\d+)?)\)", d, re.S))
pro = json.load(open(base + ".kicad_pro"))["net_settings"]["classes"]
bad = []
if len(classes) < 2:
    bad.append(f"DSN has {len(classes)} class: the .kicad_pro classes did not export")
for c in pro:
    k = "kicad_default" if c["name"] == "Default" else c["name"]
    if k in classes and abs(float(classes[k]) - c["track_width"] * 1000) > 1:
        bad.append(f"class {k} width {classes[k]} um, .kicad_pro {c['track_width']} mm")
vias = set(re.findall(r'\(padstack "?(Via\[[^\s")]+)', d))
want = {(c["via_diameter"], c["via_drill"]) for c in pro}
if len(vias) < len(want):
    bad.append(f"DSN via padstacks {sorted(vias)}, .kicad_pro has {len(want)} via sizes")
print("DSN classes", ", ".join(f"{k} {float(v) / 1000:g}" for k, v in classes.items()), "| vias", ", ".join(sorted(vias)))
if bad:
    raise SystemExit("DSN check failed:\n  " + "\n  ".join(bad))

# 4. DSN edits
for lay in cfg.get("power_layers", []):
    # the DSN names a layer by its board name: "In1.Cu", or the user name when the layer has one
    d = re.sub(r"\(layer (%s\.Cu|%s)\s+\(type signal\)" % (re.escape(lay), re.escape(lay)), r"(layer \1 (type power)", d)


def drop_block(text, head):
    i = text.find(head)
    if i < 0:
        return text
    j, depth = i, 0
    while True:
        depth += (text[j] == "(") - (text[j] == ")")
        if depth == 0:
            return text[:i] + text[j + 1:]
        j += 1


for net in cfg.get("drop_nets", []):
    d = drop_block(d, f"(net {net}\n") if f"(net {net}\n" in d else drop_block(d, f"(net {net} ")
    d = re.sub(r"(\(class \S+ [^()]*?)(?<=\s)%s(?=\s)" % re.escape(net), r"\1", d)
hv, sense = cfg.get("hv_classes", []), cfg.get("sense_classes", [])
others = [k for k in classes if k not in hv and k not in sense]
cc = [f"    (class_class (classes {h} {o}) (rule (clearance {cfg.get('hv_other_um', 200)})))" for h in hv for o in others]
cc += [f"    (class_class (classes {h} {s}) (rule (clearance {cfg.get('sense_hv_um', 600)})))" for h in hv for s in sense]
if cc:
    k = d.rfind("  )", 0, d.find("  (wiring"))                  # end of (network ...)
    d = d[:k] + "\n".join(cc) + "\n" + d[k:]
open(dsn, "w").write(d)
print("class_class rules", len(cc), "| DSN", dsn)
if a.dsn_only:
    sys.exit(0)

# 5. run
jar = os.path.expanduser(a.jar or cfg.get("jar") or (sorted(glob.glob(os.path.expanduser("~/.local/share/freerouting/freerouting-*.jar"))) or [""])[-1])
if not os.path.exists(jar):
    raise SystemExit("Freerouting jar not found: set freerouting.jar or --jar")
ses, log = os.path.join(work, "board.ses"), os.path.join(work, "fr.log")
if os.path.exists(ses):
    os.remove(ses)
cmd = ["java", "-jar", jar, "-de", dsn, "-do", ses, f"--router.autorouter.max_passes={a.passes or cfg.get('max_passes', 100)}",
       "--router.automatic_neckdown=false", "--router.copper_to_edge_clearance_um=500", "--gui.enabled=false"]
open(lock, "w").write(str(os.getpid()))
t0 = time.time()
try:
    with open(log, "w") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=a.timeout or cfg.get("timeout_s", 2400))
except subprocess.TimeoutExpired:
    print("timed out: the SES (if any) holds the last saved pass")
finally:
    os.remove(lock)
txt = open(log).read()
m = re.findall(r"\((\d+) unrouted and (\d+) violations\)", txt)
print(f"Freerouting {time.time() - t0:.0f} s: " + (f"{m[-1][0]} unrouted connections, {m[-1][1]} router violations" if m else "no summary in the log"))

# 6. import into a copy of the real board (with the zones the router never saw)
if os.path.exists(ses) and not a.no_import:
    out = os.path.join(work, "routed.kicad_pcb")
    shutil.copy(a.board, out)
    for ext in (".kicad_pro", ".kicad_dru"):
        if os.path.exists(base + ext):
            shutil.copy(base + ext, os.path.join(work, "routed" + ext))
    r = pcbnew.LoadBoard(out)
    print("SES import", pcbnew.ImportSpecctraSES(r, ses))
    r.Save(out)
    rep = drc(out, os.path.join(work, "routed_drc.json"), save=False, parity=False)
    from collections import Counter
    per = Counter(short(it["items"][0]["description"].split("[")[-1].split("]")[0]) for it in rep["unconnected_items"])
    print(drc_summary(rep, show=()))
    print("unrouted per net:", ", ".join(f"{k} {v}" for k, v in per.most_common()))
    print("routed board", out)
