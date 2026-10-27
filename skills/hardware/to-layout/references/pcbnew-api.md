# Scripting the board

Verified against KiCad 10.0.7. Use KiCad's own Python (has `pcbnew`):

```
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
S=~/.claude/skills/to-layout/scripts
q(){ grep -v -e wxApp -e Fontconfig -e stdpbase -e Debug; }      # zsh: a function, not a variable
$KP $S/drc.py hw/board.kicad_pcb 2>&1 | q
```

The `.kicad_pcb` is the source of truth. Never edit the board while the user has it open in KiCad: ask them to close it or save first, and reload after they edit. Try a script on a copy (`cp hw/board.* $SCRATCH/`) before the real board.

## Script library (`scripts/`)

All read the board config `hw/<board>.layout.json` (example: `examples/foc_controller/foc_controller.layout.json`). Each script's docstring lists the keys it reads. `klib.py` holds the shared helpers (`Board`, `track`, `via`, `zone`, `keepout`, `via_ok`, `strip_items`, `drc`); `ipc.py` the sizing math (pure Python, `python3 ipc.py` self-tests); `raster.py` the copper rasteriser and PNG writer; `g4.py` the global-routing model used by `global_route.py` and `place_opt.py`. KiCad's Python has no numpy: everything is pure Python and deterministic (fixed order, fixed seed).

| Script | Does | When |
|---|---|---|
| `sizing.py` | Every netclass width, clearance and via from the `currents` table (IPC-2152, adiabatic pulse, IPC-2221B, fab floors per copper weight); `--write` sets the `.kicad_pro` classes and the generated `.kicad_dru` block | Board setup, and after any change to currents, stackup or classes |
| `current_check.py` | Max-flow over each `current_paths` entry's real copper and via barrels: amps carried vs needed, bottleneck width per layer, peak-pulse area; `--png` marks the bottleneck | After power copper, after every routing stage, in the check loop |
| `plane_fanout.py` | One via + stub per plane-net pad not yet on its plane (`planes`, `own_via` for decoupling caps); `--demand G4.json` keeps vias out of the signal channels, `--refan GLOBS` redoes existing fan-outs; names every pad with no site and why | After `global_route.py --json`, before signal routing; again after placement changes |
| `global_route.py` | Routability gate: PathFinder global routing of all open connections on 1 mm tiles, overflow + hotspots (where, nets, blocked by), `--png` heat map | After placement, after every placement change; must be 0 before detailed routing |
| `droute.py` | Detailed router: g4 corridors, 0.1 mm grid with real clearances (HV exposed-pad and sense rules per class, KiCad's courtyard exemption), rip-up and reroute, writes tracks + vias and runs DRC. `--gate-only`: pin-access check in seconds (an end walled in by fixed copper is named; exit 2) | After global_route.py is 0; `--gate-only` after every placement change near fine-pitch pins |
| `access_fix.py` | Re-seats the parts that wall in pins: each part's legal spots (place_small `--cands`), kept only when the gate frees ends and checks.py fails no more; `LEAD+F1` lifts the followers while searching LEAD, then re-seats them | When `droute.py --gate-only` exits 2 |
| `place_opt.py` | Placement loop: moves, rotations, swaps and rigid IC blocks (`place_opt`), every placement rule hard, objective = global-route overflow; writes the best placement to `--out` | When global_route.py shows overflow |
| `feasibility.py` | Quick demand / capacity estimate before any copper (straight-line, per 2.5 mm cell); superseded by global_route.py and current_check.py once copper exists | Draft placement only |
| `corridors.py` | Rule areas along `corridors` (pass-through lanes, bus lanes); lists parts inside them | Before small parts |
| `bus_check.py` | Crossing count of an IC-to-IC bus, U-turn aware, with `--map` for proposed pin swaps | Rotation search, pin-swap proposals |
| `escape.py` | Vias needed vs via sites per side of each fine-pitch IC | After placement, after every swap |
| `place_small.py` | `blocks` by hand, `small_parts` next to their anchor pin, honouring keep-outs and channels; `--cands N` lists legal spots, `--lift` treats parts as unplaced | After big parts and corridors |
| `checks.py` | Decoupling, pad distance, keep-out distance, edge copper: markdown table, exit 1 on failure | Every placement iteration; paste into layout-check.md |
| `bus_route.py` | One bus as parallel tracks from a centerline, straight fan-out at each pin | After bus_check gives 0 crossings |
| `strip.py` | Remove tracks / vias / zones by text (by net, zone name, keep locked) | Before re-running a routing script |
| `fr_run.py` | Freerouting: routing copy, DSN checks, class_class rules, one job at a time, SES import + DRC | The non-critical rest |
| `drc.py` | Refill + DRC + parity, summary by type | After every change |
| `fab_export.py` | Gerbers, drill, zip, JLC BOM + CPL with rotation fixes and side counts | After final approval, when the user asks |

Board-specific copper (power-stage pours, via arrays, GND vias per pad) stays a per-board script: start from `examples/foc_controller/route_v13a.py` (half-bridge cell, shunt Kelvin, plane vias) and `route_v13c.py` (one GND via per small-part pad, thermal vias in exposed pads).

## Headless gotchas

- `board.Remove(item)` and `pcbnew.ZONE_FILLER` crash (segfault) without the GUI. Remove items by text (`strip.py`, `klib.strip_items`); fill zones with `kicad-cli pcb drc --refill-zones --save-board` (`drc.py`).
- `b.GetNetcodeFromNetname(name)` raises IndexError for a name that does not exist. Hierarchical nets are `/Sheet/NAME`; `klib.Board.net()` tries the short name and `/NAME`.
- Zone outlines handed to `z.SetOutline(poly)` need `poly.thisown = 0`, else Python frees them and the save crashes. One outline per zone: split multi-piece shapes (`klib.Board.zone` does).
- No `f"{d["k"]}"` (same quotes nested): KiCad ships Python 3.9.
- wx, Fontconfig and `Debug:` lines on stdout/stderr: filter with the `q` function above. `FONTCONFIG_FILE=/dev/null` silences kicad-cli.
- zsh: `time` prints `total`, not `real`; `$VAR` holding flags does not word-split.
- `.kicad_dru` errors are silent: a rule with a bad condition is dropped without a message. `tools/render` checks the rules loaded; after editing the file, add a deliberate violation once and see DRC report it.

## Load, move, save

```python
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

b = pcbnew.LoadBoard("hw/board.kicad_pcb")
fp = b.FindFootprintByReference("Q1")
fp.SetPosition(VECTOR2I(FromMM(20), FromMM(15)))
fp.SetOrientationDegrees(90)
fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)   # to the bottom side
pad = fp.FindPadByNumber("1"); pad.GetNetname(); pad.GetPosition()
b.Save("hw/board.kicad_pcb")
```

Edge-to-edge pad distance: `pad.GetBoundingBox()` or `pad.GetEffectivePolygon(layer)`; centre distance overstates gaps for big pads.

## Ratsnest crossings

Links = one segment per pad of the part to the nearest same-net pad on another part; skip GND and plane-carried nets. Count pairwise crossings (`klib.segs_cross`) per rotation, for the whole neighbourhood, not one part: rotating one part can tangle the next. A straight-line count misjudges a bus that U-turns (both ICs face the same way): `bus_check.py` orders the pins around the bus midpoint instead. Recompute with swapped pad positions before proposing a swap (`bus_check.py --map A=B,...`).

## Tracks, vias, zones

`klib.Board.track(pts, net, layer, width)`, `.via(x, y, net, drill, dia)`, `.zone(poly, net, layer, prio)`, `.keepout(poly, layers, tracks, vias, fills, footprints)`. Raw API:

```python
t = pcbnew.PCB_TRACK(b)
t.SetStart(VECTOR2I(FromMM(x1), FromMM(y1))); t.SetEnd(VECTOR2I(FromMM(x2), FromMM(y2)))
t.SetWidth(FromMM(0.4)); t.SetLayer(pcbnew.F_Cu); t.SetNetCode(code); t.SetLocked(True); b.Add(t)
v = pcbnew.PCB_VIA(b); v.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
v.SetDrill(FromMM(0.3)); v.SetWidth(FromMM(0.6)); v.SetNetCode(code); b.Add(v)
```

Draw 45° bends as explicit segments; `tools/pcb-lint` rejects 90° corners. Layer constants: `F_Cu`, `In1_Cu`, `In2_Cu`, `B_Cu`.

## Freerouting

Installed at `~/.local/share/freerouting/freerouting-2.5.0.jar` (Java 21+). Lock all scripted copper first. Run it through `fr_run.py`, which handles the traps below:

- **The DSN takes its classes from the `.kicad_pro` next to the board.** A copy without it exports one 0.2 mm class with one 0.6 mm via: half the via sites. fr_run copies it and stops when the DSN has one class, a class width differs from the `.kicad_pro`, or a via size is missing.
- **Freerouting knows no `.kicad_dru` rules.** High-voltage spacing and sense-to-HV spacing go in as `class_class` clearances (config `hv_classes`, `sense_classes`). KiCad exports no-track rule areas as `wire_keepout`, which Freerouting honours.
- **Zones are obstacles at their outline**, not their fill: fr_run drops the pours named in `drop_zones` (GND pours the router may cross) and reshapes the rest to their fill. A plane layer the router must not use is `(type power)` (`power_layers`).
- **Neck-down**: by default Freerouting narrows tracks to 0.11 mm at pads. fr_run passes `--router.automatic_neckdown=false` and `--router.copper_to_edge_clearance_um=500`.
- **One job at a time.** Two jobs in one folder overwrite each other's `board.ses` and `fr.log`, and halve the speed. fr_run refuses to start when one is running.
- The result is the log line `Auto-routing stage completed ... (N unrouted and M violations)`; fr_run prints it and the DRC of the imported board, unrouted per net.
- Fanout that leaves pins unescaped, or N staying high after 2 runs, is a placement problem (tangle, escape budget), not a passes problem. Typical: 100 passes on a dense 45 × 45 mm 4-layer board take 20 min.
- Freerouting uses 90° corners and takes detours. Always run the check loop after import.

## After any change

`drc.py hw/board.kicad_pcb` (refill, DRC, parity, summary), then `tools/render hw/board.kicad_pro`.
