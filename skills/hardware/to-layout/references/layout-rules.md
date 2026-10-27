# Layout rules

General PCB practice. Every rule is either enforced by DRC (`.kicad_dru`, netclasses), by `tools/pcb-lint`, or measured and recorded in `layout-check.md`. Power components add `power-stage.md` on top.

## Stackup (4 layers)

| Layer | Use |
|---|---|
| L1 top | Parts, power-stage copper, short signals |
| L2 | Solid GND. No signals, no splits. The reference for every L1 signal. |
| L3 | Power distribution (bus, logic rails) as pours, plus signals that cannot go on L1 |
| L4 bottom | GND pour + power return; bottom-side parts (e.g. encoder) |

- Confirm copper weights and thickness with the fab (kicad-happy `jlcpcb`), set them in Board Setup → Physical Stackup so impedance and current calcs use real numbers.
- One ground. Never split GND into analog/digital/power planes. Separate by placement; the return currents stay apart because the parts are apart.

## Sizing policy: as thin and as tight as the fab and the current allow

Routing room is the scarce resource on a small board. Every track width, clearance and via is the smallest value that satisfies all of:

1. **Fab minimum for that layer's copper weight, plus margin.** Not the 1 oz number on a 2 oz layer.
2. **Current:** IPC-2152 width for the net's worst-case RMS current at ≤ 10 °C rise (record it). Vias: enough in parallel for the current.
3. **Voltage:** IPC-2221B clearance for the net's voltage (rules file). Outer layers: B2 (uncoated, e.g. 0.6 mm at 51 to 100 V) only where exposed copper is involved, i.e. a pad; between tracks, zones and tented vias under solder mask B4 (coated, 0.13 mm) applies, so the netclass clearance holds. Inner: B1.
4. **Function:** impedance for diff pairs, gate-loop inductance for gate drive.

Wider or looser than that only with a reason written in `layout-check.md`. A signal net carrying milliamps gets the fab-minimum-plus-margin width, not a round 0.2 or 0.25 mm.

**Computed, not typed.** `scripts/sizing.py` derives every class from the `currents` table in `layout.json` (RMS, rise, peak and duration, volts, pour or track, `min_width` with a `why`) and the stackup: IPC-2152 width per layer and copper weight, adiabatic pulse width, IPC-2221B spacing, via barrel current, fab floor. `--write` puts the classes in `.kicad_pro` and the per-layer floors, exposed-pad spacing and via rules in a generated block of `.kicad_dru`. Its table goes into `layout-check.md`. Never hand-edit a netclass width or a sizing rule: change the currents and re-run. After routing, `current_check.py` proves the copper: max-flow over each power path's real copper and via barrels, against the same numbers.

JLCPCB 4-layer limits (check the [capabilities page](https://jlcpcb.com/capabilities/pcb-capabilities) for changes and record the date):

| Item | Fab min | Use (with margin) | Note |
|---|---|---|---|
| Track / space, outer 1 oz | 0.09 / 0.09 mm | 0.1 / 0.1 mm | |
| Track / space, outer 2 oz | 0.15 / 0.15 mm | 0.15 / 0.15 mm | 2 oz etch limits; no margin left to give |
| Track / space, inner (0.5 or 1 oz) | 0.09 / 0.09 mm | 0.1 / 0.1 mm | inner layers are the cheap routing room on a 2 oz board |
| Pad to track | 0.1 mm | 0.1 mm | |
| Via hole to track | 0.2 mm | 0.2 mm | `hole_clearance` |
| Hole to hole, pads | 0.45 mm | 0.45 mm | `hole_to_hole` |
| Hole to hole, via to via | 0.2 mm | 0.25 mm | separate rule, else via arrays need 0.45 mm |
| Signal via, no extra cost | 0.2 drill / 0.45 dia | 0.2 / 0.45 mm | below 0.45 dia (or below 0.2 drill) costs extra |
| Smallest via (extra cost) | 0.15 / 0.25 mm | ask the user first | only if the escape budget fails with 0.2 / 0.45 |
| Power via | | 0.3 / 0.6 mm | more copper per via in arrays |

Via current: barrel as a conductor (π × (drill + plating) × plating) on the IPC-2152 chart (`ipc.via_amps`). At 18 µm plating and 10 °C: 0.2 mm drill about 1.1 A, 0.3 mm about 1.4 A. Confirm the fab's plating thickness and set `sizing.plating_mm`. Per mm² of board, small vias carry more than big ones (more barrel wall per area), so via arrays use the signal via unless hole count matters.

## Netclasses

Assigned by name pattern in `.kicad_pro` (`net_settings.netclass_patterns`). The values come from `sizing.py`; the table shows what it gives for 2 oz outer, 1 oz inner and the motor-controller currents, as a sanity reference. Netclass width is the width the autorouter uses, so it must be the minimum for the class, not a comfortable value.

| Class | Nets | Track (outer / inner floor) | Clearance | Via (drill/dia) | Why |
|---|---|---|---|---|---|
| Default | logic signals (mA) | 0.15 / 0.1 mm | 0.15 mm, inner 0.1 | 0.2 / 0.45 | fab floor |
| HV | bus, phases | pours (current_check); tracks 0.15 / 0.1 | 0.15 mm; exposed pads 0.6 mm (B2) | 0.2 / 0.45 class, power arrays per sizing | current in pours, 80 V |
| HV_SIG | VCP, CPH/CPL, buck SW/BST | 0.15 / 0.1 mm | 0.15 mm; exposed pads 0.6 mm | 0.2 / 0.45 | mA at 80 V |
| GATE_HS / GATE_LS | GHx, GLx | 0.3 mm (`min_width`), necked in the driver courtyard | 0.15 mm; GHx exposed pads 0.6 mm | 0.2 / 0.45 | gate-loop inductance, not heat |
| SENSE | shunt Kelvin pairs, CSA outputs | 0.15 / 0.1 mm | 1.0 mm from HV (rules file) | 0.2 / 0.45 | mA |
| PWR | +5V, +3V3, DVDD, VGLS | 0.15 / 0.1 mm (0.5 A needs less than the floor on 2 oz) | 0.15 mm | 0.2 / 0.45 (1.1 A each) | IPC-2152 |
| USB, CAN | diff pairs | impedance (fixed-width classes) | 0.15 mm | avoid | 90 / 120 Ω |

- Gate width: about 1 A peak for tens of ns; 0.3 mm of 2 oz is plenty. Wider only lowers inductance if the return is tight, so pair the return before widening.
- Neck-down: any class wider than a fine-pitch pad necks to the pad width inside that part's courtyard (rules file exemption). Never make the class narrow everywhere to reach one pad.

- Diff-pair width/gap from the KiCad PCB Calculator (Transmission line → coupled microstrip) with the real stackup. USB FS (12 Mbps) and CAN tolerate ±20 % impedance; matching matters more than the exact number.

## Current capacity

- Size every power path with IPC-2152 (KiCad PCB Calculator, track width tab) for ≤ 10 °C rise at the worst-case RMS current. Record current, copper weight, layer, width. Quick check (IPC-2221): I = k · ΔT^0.44 · A^0.725, A in mil², k = 0.048 outer, 0.024 inner, 1 oz = 1.378 mil.
- **Reserve every high-current path before placing small parts.** List it in config `current_paths` (net, from pad, to pad, amps, rise, layers); `feasibility.py` gives the width it needs per layer against the free width across its corridor. Then `corridors.py` turns it into a rule area that keeps parts out. A pass-through path (connector in to connector out) found blocked after the small parts are placed costs a re-placement.
- Copper weight and current rating go together: lowering the current rating is the usual answer when a path does not fit; ask the user which (copper weight, rating, rise) before changing either.
- Above about 3 A: pours, not tracks. Use the same pour on 2+ layers in parallel, stitched with vias along its length.
- Via current: count one 0.3 mm via as 1 A (conservative). Every layer change of a power path needs vias ≥ the path's current in amps, spread across the copper width, not in a single row.
- Watch necks: a pour is only as wide as its narrowest point. Measure the narrowest section of each power path.

## Placement

- Placement is 80 % of layout quality. Route nothing until placement is approved.
- **Feasibility gate first.** After the draft placement of the big parts (connectors, power stage, ICs) run `feasibility.py`: global demand / capacity ≤ 0.4 and no 2.5 mm cell above 1.0, every current path fits. A failing gate is a placement or board-size question for the user now, not after routing.
- **Power cells are keep-outs on both sides.** The half-bridge cell (FETs, their ceramics, shunt, pours) needs its area on every layer: no small parts on the other side under it, except the cell's own. Put it in `keepout_boxes`.
- **Every pad of a power cell needs a legal connection** before you move on: a pour it sits in, or a via site that passes `klib.via_ok` (HV clearance, sense clearance, keep-out circles). A shunt or cap with no legal via site is a re-placement later.
- **Strips and pours that leave a cell stay outside sensor keep-outs** (encoder magnet circle, crystal): check the whole path, not only the parts.
- Connectors at the edges, oriented outward, as the design doc fixes them.
- Group by function, mirroring the schematic sheets. Power stage in one region, logic in another, interfaces at their connectors. Hot and noisy far from sensitive and cool.
- Decoupling caps: smallest value closest to the pin, on the same layer as the IC, between the pin and its via to the plane. Order: pin → cap pad → via. Never pin → via → cap.
- Crystal: within 5 mm of the MCU pins, load caps between crystal and MCU, nothing routed under it on L1, GND on L2 under it.
- Regulators: input cap, output cap, and feedback divider at the IC. Feedback divider next to the FB pin; sense the output at the load side of the output cap.
- Rotation and pin mapping are routing decisions, not cosmetic ones: see "Untangle" below.
- Parts in rows, same orientation for same-type parts (polarized parts all pointing the same way where possible) for assembly and inspection.
- Courtyards never overlap. Keep 0.5 mm between tall parts and anything needing rework access.

### Placement checks (measure and record)

| Check | Limit |
|---|---|
| Decoupling cap pad to its IC pin | ≤ 2 mm for 100 nF, ≤ 5 mm for bulk |
| Crystal to MCU pins | ≤ 5 mm |
| Buck hot loop (see power-stage) | area recorded, minimized |
| ESD part to connector pins | ≤ 5 mm, before anything else on the line |
| CAN transceiver to connectors | per design doc |
| Sensitive parts (encoder, MCU analog, crystal) to switch nodes | per design doc, ≥ 10 mm otherwise |
| Parts within 0.5 mm of board edge | none except connectors meant to overhang |
| Ratsnest crossings per IC-to-IC bus | recorded for every rotation tried; chosen one minimal |
| Escape budget per fine-pitch IC side | vias needed ≤ via sites available (`escape.py`) |
| Feasibility: demand / capacity, hotspot cells, current paths | ≤ 0.4, ≤ 1.0, fit (`feasibility.py`) |
| Corridors free of parts | none inside (`corridors.py --check-only`) |

### Untangle (before placement review)

A tangled ratsnest cannot be fixed by the router: every crossing between two links of the same bus costs a via pair or a detour, and between two fine-pitch ICs there is no room for either.

1. **Rotation search.** For every IC with more than about 8 signal links to other parts (MCU, gate driver, transceivers, regulators with many pins), try all four rotations (and the other board side, if the design doc allows it). For each, count straight-line ratsnest crossings among its signal links (`pcbnew-api.md`, "Ratsnest crossings"), ignoring GND and nets carried by planes. For each IC-to-IC bus also run `bus_check.py`: when both pin rows face the same way the bus U-turns, and the straight-line count is wrong (on this board it read 6 for a bus with 9 real crossings, and 12 for the fixed order with 3). Also count crossings against the links of its neighbours, since rotating one part can tangle another. Pick the lowest total; the placement still has to pass every other placement check.
2. **Pin swaps.** Where crossings remain, list swaps that would remove them: MCU GPIOs with free choice (enables, faults, chip selects, LEDs), alternate-function remaps (SPI, UART, I2C, timer channels on other pins), ADC channel swaps, swappable gates/resistor-network elements, connector pin order where the design doc leaves it open. Check each swap against the MCU datasheet's alternate-function table and against firmware constraints in the design doc (e.g. complementary timer outputs must stay on one timer). Order the bus so the pin sequence along one IC's edge matches the reversed sequence along the other's: then it river-routes on one layer.
3. **Check every swap in both datasheets** (MCU alternate-function table, and the other IC's pin functions): only what the datasheet states. Then `bus_check.py --map` with the swaps.
4. **Present the swap list** to the user as a table (net, old pin, new pin, reason, crossings removed). Approved swaps go to `/to-schematic`, then F8, then re-measure. Target: 0 crossings within each IC-to-IC bus, single digits for the whole board.

### Escape budget (before routing)

For each fine-pitch IC (QFN, QFP, ≤ 0.65 mm pitch), per side:
- Pins that can leave on the top layer: the outer ring of pads routes straight out at the class width and clearance. At 0.5 mm pitch, a 0.15 mm track with 0.15 mm space fits one track per pad, none between pads.
- Pins that must change layer (blocked by a neighbour's track, or going the other way): need a via within the escape ring. With 0.2 / 0.45 mm vias and 0.15 mm clearance, via pitch is 0.6 mm per row, staggered rows 0.55 mm apart.
- Available via sites = ring area free of caps, pours and keep-outs divided by via pitch². Needed ≤ available, with 20 % spare. If it fails: untangle more, move decoupling caps to the other side, widen the ring, or (with the user's OK) the 0.15 / 0.25 mm via option.

## Routing

- Corners: 45° or arcs only. No 90° or acute corners (`tools/pcb-lint`). No acid traps.
- Short and direct. Every L1 signal has unbroken GND directly below on L2. A signal crossing a gap in its reference plane is a bug.
- Changing layers: put a GND stitching via within 1 mm of the signal via so the return current can follow.
- Diff pairs: routed together from start to end, same layers, same via count, length matched (rules file), no other trace between them.
- Clocks and fast edges: shortest, on L1 over GND, away from board edges (≥ 3 mm) and connectors.
- Analog: away from switching and digital; route over GND; filter caps at the ADC pin.
- Width changes: taper or teardrop, never a step into a pad.
- No traces between the pads of fine-pitch parts unless the fab rules allow it with margin.
- No stubs. No dangling tracks. No unused vias.

## Vias

- Signal vias 0.2 mm drill / 0.45 mm pad (smallest without extra fab cost); power vias 0.3 / 0.6 mm. See the sizing policy.
- No via in pad unless the fab fills and caps it (costs extra). Exception: thermal vias in exposed pads, small (0.3 mm) and tented on the bottom or covered by paste-window design per the IC datasheet.
- Tent signal vias (solder mask over) on both sides unless they are test points.
- Stitching: GND vias along board edges every ≤ 5 mm, around the power stage, and next to every signal layer change.

## Pours and planes

- GND pour on every layer after routing, connected by stitching vias. Remove islands (zone setting: remove islands always) and slivers narrower than 0.5 mm.
- Zone clearance to other nets ≥ the netclass clearance; HV zones keep 0.6 mm outer.
- Solid (no thermal relief) for high-current pads; thermal relief for everything else so it solders.
- Pour priorities: power zones above GND where they overlap.

## Mechanical and DFM

- Copper ≥ 0.5 mm from the board edge (rules file).
- Mounting holes: plated, connected to GND only if the design doc says so; keep-out around the screw head.
- Fab limits from kicad-happy `jlcpcb`: min track/space for the copper weight, min drill, min annular ring, hole-to-hole.
- Teardrops on every pad and via (Edit → Edit Teardrops) for mechanical robustness.
- Panelization, fiducials, tooling: not needed for JLCPCB assembly unless they ask.

## Silkscreen

- Every refdes visible, upright or rotated 90° only, not over pads, vias, or other parts.
- Pin 1 marks on every IC and connector; polarity on diodes, polarized caps, LEDs.
- Board name, revision, date on the board. Connector pinouts labelled (e.g. `GND CANL CANH`).
- Text ≥ 0.8 mm high, ≥ 0.15 mm stroke.

## Test and debug

- Test pads on rails and key signals, ≥ 1.0 mm diameter, ≥ 2.54 mm apart, reachable with a probe (no tall parts adjacent).
- Debug pads in the programmer's order.
