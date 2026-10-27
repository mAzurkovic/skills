# Power-stage layout

For every power component: half-bridges, gate driver, shunts, bulk caps, buck regulator, power connectors. Each section ends in checks to measure and record in `layout-check.md`.

The core idea: every fast-changing current flows in a loop. The loop's area is its inductance; inductance × di/dt is ringing, overshoot, and radiated noise. Find each loop, shrink it, and put its return directly under it.

## Half-bridge (commutation loop)

The loop: bus ceramic caps (+) → high-side drain → high-side source = phase node → low-side drain → low-side source → shunt → GND → ceramic caps (−).

- Place the high-side and low-side MOSFETs of one phase next to each other. The 4.7 µF ceramics sit right at the high-side drain and the shunt's GND end, within 3 mm of both.
- Return on L2 directly under the loop (vertical loop): the GND plane under the bridge carries the return current and cancels the field. Stitch GND vias densely (≤ 2 mm pitch) at the cap GND pads and the shunt GND end.
- The cell (both FETs, their ceramics, the shunt, the pours) is a keep-out on both board sides for every other part. Every pad in it connects through its pour or a via that meets HV and sense clearance; check that while placing, not while routing.
- Three phases identical: same placement, same orientation, same copper shapes. Copy one phase and repeat. Asymmetry shows up as current-measurement offset and uneven heating.
- Phase nodes: as small as the current allows. They swing 0 to bus at up to 2 V/ns; every mm² is an antenna and couples into anything above or below. Nothing sensitive on any layer above or below a phase node.
- Bus pour: wide, on L1 and L3 in parallel, stitched. Bus caps between the connector and the bridge so ripple current stays local.
- Phase outputs to the motor connector or pads: pours sized for the RMS phase current, multiple layers, via count ≥ amps per layer change.

Checks:
| Check | Limit |
|---|---|
| Ceramic bus cap to HS drain pad, each phase | ≤ 3 mm |
| Ceramic bus cap GND to shunt GND end, each phase | ≤ 3 mm |
| GND plane on L2 under the full commutation loop | unbroken |
| Phase copper area, each phase | recorded, equal within 10 % |
| Vias per power-path layer change | ≥ RMS amps |
| Narrowest point of bus and phase pours | width recorded, ≥ IPC-2152 width for the current |

## Gate drive

Loops: gate driver GHx → HS gate → HS source → SHx back to the driver. GLx → LS gate → LS source → SLx (or driver ground) back.

- Driver as close to the MOSFETs as placement allows; gate traces ≤ 20 mm, ideally ≤ 10 mm.
- Route GHx with SHx as a pair, side by side or stacked on adjacent layers. Same for GLx with SLx. The pair is the loop; keep it tight.
- SHx connects at the HS MOSFET's source pins, not somewhere on the phase pour. SLx connects at the LS MOSFET's source pins (Kelvin).
- Gate traces 0.3 mm (2 oz), necked to pad width at the driver; peak gate current is about 1 A for tens of ns. Keep the return tight before making it wider.
- Keep gate pairs away from the phase node of another phase.
- Charge pump and bootstrap caps (VCP, CPH/CPL, VGLS, DVDD on DRV83xx): at their pins, ≤ 2 mm, before any via.
- Driver exposed pad: thermal vias to GND per the driver datasheet's layout section.
- Read the gate driver datasheet's layout guidelines section and its example layout figure. Apply every item; list them in the check table.

Checks:
| Check | Limit |
|---|---|
| Gate trace length, each of 6 | ≤ 20 mm, recorded |
| Gate and return routed as a pair | yes for all 6 |
| Driver charge-pump / supply caps to pins | ≤ 2 mm |
| Datasheet layout guideline items | each pass |

## Current-sense shunts

- Kelvin connection: two sense traces leave from the inside edge of the shunt's pads (or the dedicated sense pads of a 4-terminal footprint), never from the power copper.
- Route the pair together to the amplifier (SPx/SNx), as a diff pair, on a layer over GND, away from phase nodes (≥ 1 mm by rules file, more where you can).
- Filter components (if any) at the amplifier pins, not at the shunt.
- The shunt's GND end ties to the power GND at the bridge, not to logic ground somewhere else.
- Shunts carry the full phase current: pad copper on both sides sized like the phase path, with vias.

Checks:
| Check | Limit |
|---|---|
| Sense traces start at pad inside edge / sense pads | yes, all 3 |
| Sense pairs routed as pairs, equal length | yes, all 3 |
| Sense pair distance to any phase node | ≥ 1 mm (more preferred), recorded |

## Bulk capacitors

- Electrolytic/polymer bulk caps near the bridge on the bus pour, each with short wide connections and ≥ 2 vias per terminal to the inner bus/GND layers.
- Ceramics closest to the switches, bulk further out: the ceramics handle the fast edges, the bulk handles the ripple.
- Spread bulk caps so each phase sees similar impedance.

## Buck regulator (e.g. LM5008A)

Hot loop: input cap → switch (VIN to SW inside the IC) → catch diode → input cap ground.

- Input cap at the VIN and GND pins, ≤ 2 mm. Catch diode right at SW and the input cap ground. This loop as small as possible, on one layer.
- SW node: small copper, just enough for the inductor and diode. Nothing sensitive near it.
- Inductor next to SW; output cap at the inductor's output and the diode/input-cap ground.
- Feedback divider at the FB pin; feedback trace from the output cap, routed away from the inductor and SW.
- Follow the regulator datasheet's layout section and example layout exactly.

Checks:
| Check | Limit |
|---|---|
| Hot-loop area | recorded, minimized |
| Input cap to VIN pin | ≤ 2 mm |
| FB trace distance to SW node and inductor | ≥ 2 mm |

## Thermal

- MOSFET drain/source pads: thermal vias (0.3 mm power vias, ~1.0 to 1.2 mm pitch) under and around the pads to L2/L3/L4 copper, per the MOSFET datasheet's recommended footprint.
- Bottom side kept flat and pour-filled under the power stage if a heatsink pad mounts there (design doc).
- Temperature sensor (NTC) touching the hottest copper it is meant to measure, on the same pour.
- Parts rated 85 °C (MCU, some connectors) away from the MOSFETs.

## Power connectors

- Pad copper and vias sized for the connector's full current on every layer it connects.
- Pass-through current (in → out connector) routed so its path and return stay together and avoid the sensitive area (design doc).
- Reserve the pass-through path before anything else is placed (layout-rules "Current capacity": `current_paths`, `feasibility.py`, `corridors.py`). Its width per layer comes from the rated current, the copper weight and the allowed rise; through-hole connector pins connect it on every layer.
- Ground return path from the connector to the bridge GND: wide, short, and directly under the bus path.
