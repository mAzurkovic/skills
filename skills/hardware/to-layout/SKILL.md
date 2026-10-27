---
name: to-layout
description: Turn an approved KiCad schematic into a placed, routed, DRC-clean PCB laid out the way a seasoned PCB and power-electronics engineer would. Use when user says "/to-layout", "lay out the board", "route the board", or has an approved schematic and wants the PCB.
---

# /to-layout

Approved schematic in, fab-ready `.kicad_pcb` out. You are a seasoned PCB engineer with a power-electronics background: placement decides whether the board works, routing decides whether it passes EMC, and every number (width, clearance, via count, distance) is chosen, not defaulted: the thinnest track, tightest clearance and smallest via the fab, the current and the voltage allow (layout-rules "Sizing policy"). Routing room is the scarce resource.

## Voice

- No em-dashes. Fragments fine.
- Numbers with units. Name refdes, nets, layers.

## Inputs and outputs

- In: `./hw/<board>.kicad_sch` (approved by /to-schematic), `./specs/<feature>/design-electronics.md` (board size, layer count, mechanical, layout rules).
- Out: `./hw/<board>.kicad_pcb`, `./hw/<board>.kicad_dru`, netclasses in `./hw/<board>.kicad_pro`, `./hw/<board>.layout.json` (board config), `./hw/review/layout-check.md`.

## Rules

Read all three before touching the board:
- `references/layout-rules.md`: stackup, netclasses, placement, routing, vias, planes, DFM. General best practice.
- `references/power-stage.md`: half-bridge, gate drive, shunts, bulk caps, buck, thermal. Applies to every power component.
- `references/pcbnew-api.md`: scripting the board, the script library, headless gotchas, Freerouting.

Design doc wins on conflicts. Ask before deviating.

## Scripts and board config

`scripts/` holds the tested tools (table in pcbnew-api.md); run them with KiCad's Python (`$KP`). Use them instead of writing new ones; write a per-board script only for board-specific copper (start from `examples/foc_controller/`). Every script reads `hw/<board>.layout.json`: net groups (HV, sense, plane), stackup, current paths, corridors, keep-outs, blocks and small parts, buses, checks, Freerouting and fab settings. Start it from `examples/foc_controller/foc_controller.layout.json` in step 2 and keep it current: it is the record of every placement and routing decision.

## Flow

1. **Preconditions.** `tools/render hw/<board>.kicad_pro` shows ERC 0. Ask the user to open the PCB editor, run Tools → Update PCB from Schematic (F8), save. kicad-cli cannot do this step.
2. **Board setup.** Stackup and fab limits from the kicad-happy `jlcpcb` skill and the JLC capabilities page, per copper weight.
   - **Decision checklist (ask once, all together, before placing).** Copper weight per layer and the current rating it buys (pass-through, phase), allowed temperature rise, which IPC-2221B case applies (B2 at pads, B4 under mask), which pins the user allows to swap (MCU GPIOs, timer channels, SPI instances), both-side assembly or one side, board size firm or not. One AskUserQuestion, not one question per stall. Fill the `currents` table in `layout.json` from the design doc (RMS, rise, peak and duration, volts, pour or track, `min_width` with a reason) and `current_paths` (source pad to load pad for every power path). Netclass patterns in `.kicad_pro`; then `sizing.py hw/<board>.kicad_pcb --write` sets every class and the generated sizing rules. Never type a width. Copy `assets/rules.kicad_dru` to `hw/<board>.kicad_dru` and adapt refdes patterns. Outline, mounting holes, keep-outs from the design doc.
3. **Place.** Order: connectors and mechanically fixed parts → power stage (power-stage.md) → gate driver → MCU and its decoupling/crystal → interfaces → everything else. Script it (pcbnew-api.md). Then measure: every distance rule in layout-rules "Placement checks" computed from pad coordinates, not eyeballed (`checks.py`).
   - **Feasibility gate** after the big parts, before any small part: `feasibility.py` (quick demand / capacity). Fails: rethink placement or ask about board size now.
   - **Corridors**: `corridors.py` reserves the current paths and bus lanes; then `place_small.py` places blocks and small parts around them and the power-cell keep-outs.
   - **Untangle** (layout-rules): try all four rotations of every IC with many signal links, score the ratsnest crossings of the whole neighbourhood, keep the best that still passes the placement checks. Then `bus_check.py` per IC-to-IC bus (U-turn aware) and list pin swaps that remove the remaining crossings (`--map` to verify).
   - **Escape budget** (layout-rules): `escape.py`, via sites around each fine-pitch IC ≥ vias needed + 20 %.
   - **Routability gates, in order, each deterministic** (they run on the placement plus locked copper, unlocked routing is ignored):
     - G0 rules: `checks.py` exit 0. Every design-doc distance is a `checks` entry, so the loop below can never break one.
     - G1 plane access: `plane_fanout.py --dry`: every plane-net pad has a via site on its plane. A pad with no plane under it is a plane-shape problem (grow the plane, or the net is routed as a track tree), named per pad.
     - G4 routing: `global_route.py --png`: overflow and hotspots at 1.0 mm tiles. Read the PNG.
   - **Placement loop** while G4 shows overflow: `place_opt.py hw/<board>.kicad_pcb --out <work>/opt.kicad_pcb` with `place_opt` in the config (movable globs, fixed parts and nets, IC `blocks` with their members, shifts). It never breaks a G0 rule. Then rerun G1 and G4 on its output. Still overflow after about 300 moves: the hotspot list names the nets and what blocks them; act on that level (rotate or move a fixed IC with the user's OK, pin swaps, plane shape, board size) and say which.
4. **Placement review (stop).** `tools/render`, read `place-top.png`, `place-bottom.png`, `3d-top.png`. Write the placement checklist to `hw/review/layout-check.md` with measured values, the crossing count per rotation tried, and the escape budget. Show the user the images, the table and the pin-swap list. Approved swaps go to `/to-schematic`, then F8, then re-measure. Wait for approval or their edits in KiCad. Reload the board after.
5. **Route critical copper (script, no autorouter).** Then `current_check.py --png`: every power path carries its current through its real copper and vias; fix the named bottleneck before going on. Power-stage zones on every layer, gate-drive pairs, shunt Kelvin pairs, buck hot loop, crystal, USB and CAN pairs (per-board script from the example). Then the densest IC-to-IC bus (e.g. MCU to gate driver): after untangling it river-routes, so `bus_route.py` it. Keep a signal region free on the inner signal layer under the logic area. Lock them (`SetLocked(True)`). `drc.py` after each stage; `strip.py` before re-running one.
6. **Plane fan-out, then the rest.** Plane vias go where the signals are not: `global_route.py --json <work>/g4.json` (plane-net ends over their plane are skipped), then `plane_fanout.py --refan "<small-part globs>" --demand <work>/g4.json` (exit 0; decoupling caps keep their own via, `planes[].own_via`), then `global_route.py` again: 0 (else back to step 3 with the hotspot list). Never fan out nearest-first before the signals are known: on the FOC board that put six GND vias in the DRV-to-MCU channel and doubled the overflow. Then the pin-access gate `droute.py --gate-only` (exit 0; on exit 2 find the wall by deleting nearby parts one at a time on a copy, then `access_fix.py` with that part, as a `LEAD+NEIGHBOUR` group when the neighbour must move too), then `droute.py` on the remaining signal nets. `fr_run.py` (Freerouting) is the fallback (pcbnew-api.md): it checks the DSN (per-class widths, both via sizes), adds the HV and sense class-to-class clearances, runs one job at a time and imports the SES into `<work>/routed.kicad_pcb` with its DRC. If fanout leaves pins unescaped or connections stay unrouted: find the failed pins and go back to step 3 (untangle, escape budget). Do not resize the board, add layers or rerun with more passes as the fix.
   - **Order is what makes it route.** Route in locked stages, most constrained first: the IC-to-IC bus with the
     nets that share its pins (`droute.py --only ... --reserve-escapes`), then each IC's short cap links, phases and
     gates, sense pairs, MCU-local nets (interleaved pairs alone first), the rest, plane vias last. Fan out first
     (`fanout.py`, `--via` dog-bones for pins whose net leaves on another layer). Lock a stage only when KiCad DRC is
     clean (`nudge.py` fixes µm misses). When a later net is walled in, rip the newer blocking copper and re-route in
     a better order; more iterations do not fix an order problem.
   - **Repair rule, not hand-off.** Connections left after a detailed run: run `global_route.py` on the result, read its hotspots, and go back to the placement loop with those regions (more movable parts there, blocks, a rotation). The only stop is a conflict between a requirement and routability that no allowed move resolves: report it with the heat map and the rule it would break, and ask the user which gives. Do not hand the routing to the user.
   - Clean up: no autorouter detours longer than 2× Manhattan distance on any net you care about; re-route by script if so.
7. **Finish.** GND pours on all layers, stitching vias, teardrops, silkscreen pass, refill zones: `kicad-cli pcb drc --refill-zones --save-board hw/<board>.kicad_pcb`.
8. **Check loop.** Repeat until all pass:
   - `tools/render hw/<board>.kicad_pro` exits 0: ERC 0, DRC 0, custom rules loaded, pcb-lint 0 (corner angles).
   - Read every layer PNG and the placement PNGs. Look for: splits or slots in the GND plane under signals, slivers, isolated copper islands, thin necks in power zones, long return paths.
   - kicad-happy `emc` and `kicad` reviews: no high-severity findings left unexplained.
   - Every item of layout-rules and power-stage checklists: pass with a measured value, or a reason.
9. **Present.** Layer PNGs, 3D renders, `layout-check.md`, open items. Command for the diff: `tools/kiri hw/<board>.kicad_pro -g HEAD..LOCAL`. Wait for approval. Offer to commit.
10. **Fab files (when the user asks).** `fab_export.py hw/<board>.kicad_pcb --out build/fab`: Gerber zip, drill, JLC BOM and CPL (csv + xlsx). Connectors whose JLC model sits rotated get a `fab.cpl_rotation` entry after the user checks the JLC 3D preview. Parts on both sides: JLC Standard PCBA, both sides, and under 70 × 70 mm edge rails or a panel; tell the user before they upload.

## Done means

- `tools/render` exits 0 and every PNG reviewed.
- `layout-check.md` complete: every rule pass with evidence, or waived by the user.
- Every fine-pitch IC passes its escape budget; every IC-to-IC bus is at its minimum crossing count.
- `plane_fanout.py`, `current_check.py` and `global_route.py` exit 0; their tables are in layout-check.md.
- User approved placement (step 4) and the final board.

## Not your job

No schematic changes yourself. Pin swaps are proposed here and applied by /to-schematic after the user approves them, then F8. Fab files only when asked; ordering is the user's.
