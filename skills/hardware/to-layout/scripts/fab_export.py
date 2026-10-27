"""JLCPCB fab files from the finished board: Gerbers + drill (zipped), BOM and CPL in JLC's columns.

    fab_export.py hw/BOARD.kicad_pcb [--out build/fab] [--no-xlsx]

Runs with any python3 (kicad-cli does the work; no pcbnew). The schematic is the .kicad_sch next to the board.
  Gerbers: every copper layer of the board, masks, paste, silk, Edge.Cuts; zone fill checked; drill Excellon mm,
           PTH and NPTH separate, with maps. Zipped to <out>/<board>_gerbers.zip.
  BOM:     Comment, Designator, Footprint, LCSC Part #, Quantity; grouped by Value + Footprint + LCSC; DNP excluded.
  CPL:     Designator, Mid X, Mid Y, Layer (Top / Bottom), Rotation; only parts in the BOM. Rotation corrections from
           config fab.cpl_rotation {footprint glob: degrees} (JLC's library origin differs from KiCad's for some
           connectors: check the JLC 3D preview, then add the part here).
  .xlsx copies of BOM and CPL when openpyxl is importable.
Checks printed at the end: every BOM part placed, every BOM line has an LCSC number, parts per side. Double-sided
assembly at JLC needs Standard PCBA, and a board under 70 x 70 mm needs edge rails or a panel for it."""
import argparse, csv, fnmatch, io, json, os, re, shutil, subprocess, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

KICAD_CLI = os.environ.get("KICAD_CLI", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
ENV = dict(os.environ, FONTCONFIG_FILE="/dev/null")

ap = argparse.ArgumentParser()
ap.add_argument("board"); ap.add_argument("--out", default="build/fab"); ap.add_argument("--no-xlsx", action="store_true")
a = ap.parse_args()
base = os.path.splitext(a.board)[0]; name = os.path.basename(base)
sch = base + ".kicad_sch"
cfgp = base + ".layout.json"
fab = (json.load(open(cfgp)) if os.path.exists(cfgp) else {}).get("fab", {})
out = a.out; gdir = os.path.join(out, "gerbers")
shutil.rmtree(gdir, ignore_errors=True); os.makedirs(gdir)


def cli(*args):
    r = subprocess.run([KICAD_CLI, *args], env=ENV, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"kicad-cli {' '.join(args[:3])} failed:\n{r.stdout}{r.stderr}")
    return r.stdout


# ---- Gerbers and drill
text = open(a.board).read()
layers_blk = text[text.find("\n\t(layers"):text.find("\n\t)", text.find("\n\t(layers"))]
copper = re.findall(r'"((?:F|B|In\d+)\.Cu)"', layers_blk)
layers = copper + ["F.Mask", "B.Mask", "F.Paste", "B.Paste", "F.Silkscreen", "B.Silkscreen", "Edge.Cuts"]
cli("pcb", "export", "gerbers", "--layers", ",".join(layers), "--subtract-soldermask", "--check-zones", "-o", gdir + "/", a.board)
cli("pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm", "--excellon-separate-th",
    "--generate-map", "--map-format", "gerberx2", "-o", gdir + "/", a.board)
zp = os.path.join(out, f"{name}_gerbers.zip")
with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(os.listdir(gdir)):
        z.write(os.path.join(gdir, f), f)
print(f"gerbers: {len(copper)} copper layers, {len(os.listdir(gdir))} files -> {zp}")

# ---- BOM
tmp = os.path.join(out, ".bom_kicad.csv")
cli("sch", "export", "bom", "--fields", "Value,Reference,Footprint,LCSC,MPN,${QUANTITY}", "--labels", "Value,Reference,Footprint,LCSC,MPN,Qty",
    "--group-by", "Value,Footprint,LCSC", "--ref-range-delimiter", "", "--exclude-dnp", "-o", tmp, sch)
lines = {}                                   # one line per LCSC part: JLC flags two lines matched to the same part
for r in csv.DictReader(open(tmp)):
    refs = [x.strip() for x in r["Reference"].split(",") if x.strip()]
    if not refs or all(x.startswith("#") for x in refs):
        continue
    key = r["LCSC"] or (r["Value"], r["Footprint"])
    if key in lines:                         # same part under different values (J1 "bus IN", J2 "bus OUT"): name it by MPN
        row = lines[key]; row[0] = r["MPN"] or row[0]; row[1] += "," + ",".join(refs)
    else:
        lines[key] = [r["Value"], ",".join(refs), r["Footprint"], r["LCSC"]]
os.remove(tmp)
bom = [row + [str(len(row[1].split(",")))] for row in lines.values()]
bom_refs = {x for row in bom for x in row[1].split(",")}
exclude = set(fab.get("exclude_from_assembly", []))
bom = [row for row in bom if not set(row[1].split(",")) <= exclude]
BOM_HEAD = ["Comment", "Designator", "Footprint", "LCSC Part #", "Quantity"]

# ---- CPL
tmp = os.path.join(out, ".pos_kicad.csv")
cli("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "--exclude-dnp", "-o", tmp, a.board)
cpl, placed = [], set()
for r in csv.DictReader(open(tmp)):
    ref = r["Ref"]
    if ref not in bom_refs or ref in exclude:
        continue
    rot = float(r["Rot"])
    for g, d in fab.get("cpl_rotation", {}).items():
        if fnmatch.fnmatchcase(r["Package"], g) or fnmatch.fnmatchcase(ref, g):
            rot += d
    rot %= 360
    placed.add(ref)
    cpl.append([ref, f"{float(r['PosX']):.4f}mm", f"{float(r['PosY']):.4f}mm", "Top" if r["Side"] == "top" else "Bottom", f"{rot:g}"])
os.remove(tmp)
CPL_HEAD = ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]


def write(path, head, rows):
    with open(path + ".csv", "w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL if "bom" in path else csv.QUOTE_MINIMAL); w.writerow(head); w.writerows(rows)
    if a.no_xlsx:
        return
    try:
        import openpyxl
    except ImportError:
        return
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(head)
    for r in rows:
        ws.append([int(c) if c.isdigit() and head[i] == "Quantity" else c for i, c in enumerate(r)])
    wb.save(path + ".xlsx")


write(os.path.join(out, f"{name}_bom_jlc"), BOM_HEAD, bom)
write(os.path.join(out, f"{name}_cpl_jlc"), CPL_HEAD, cpl)

# ---- checks
assembled = {x for row in bom for x in row[1].split(",")}
missing = sorted(assembled - placed)
no_lcsc = [row[1] for row in bom if not row[3].strip()]
top = sum(r[3] == "Top" for r in cpl); bot = len(cpl) - top
print(f"BOM: {len(bom)} lines, {len(assembled)} parts | CPL: {len(cpl)} parts, {top} top / {bot} bottom")
if missing:
    print("FAIL: in the BOM but not on the board:", ", ".join(missing))
if no_lcsc:
    print("FAIL: BOM lines without an LCSC number:", "; ".join(no_lcsc))
if bot and top:
    print("note: parts on both sides -> JLC Standard PCBA, both sides; under 70 x 70 mm add edge rails or a panel")
rot = fab.get("cpl_rotation", {})
print("CPL rotation corrections:", ", ".join(f"{k} {v:+g}" for k, v in rot.items()) or "none")
sys.exit(1 if missing or no_lcsc else 0)
