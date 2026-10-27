# Writing .kicad_sch with kicad-sch-api

Verified against KiCad 10.0.7 with kicad-sch-api 0.5.5. Run with `KICAD_SYMBOL_DIR=/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols hw/.venv/bin/python <script>`.

## Basics

```python
import kicad_sch_api as ksa

sch = ksa.create_schematic("power")          # new sheet
sch = ksa.load_schematic("hw/power.kicad_sch")  # existing: load, change, save
sch.set_paper_size("A4")                      # A4 A3 A2 A1 A0 Letter Legal Tabloid
sch.save("hw/power.kicad_sch")
```

## Parts

```python
sch.components.add("Regulator_Linear:AP2112K-3.3", reference="U1", value="AP2112K-3.3",
                   position=(101.6, 76.2), footprint="Package_TO_SOT_SMD:SOT-23-5",
                   LCSC="C51118", MPN="AP2112K-3.3TRG1")
c = sch.components.get("C1"); c.value = "1u 16V X7R"
sch.components.add("power:GND", reference="#PWR01", value="GND", position=(x, y))
sch.components.add("power:PWR_FLAG", reference="#FLG01", value="PWR_FLAG", position=(x, y))
```

- Positions in mm. Keep them on the 2.54 mm grid.
- Project symbols: `sch.library.add_library_path("hw/lib/<board>.kicad_sym")` (or append the dir to `KICAD_SYMBOL_DIR`, colon-separated), and add the library to the project's `sym-lib-table` so KiCad finds it too.

## Wires

```python
p = sch.get_component_pin_position("U1", "1")   # Point(x, y) of the pin end
sch.list_component_pins("U1")                    # [(pin, Point), ...]
sch.add_wire((x1, y1), (x2, y2))
sch.junctions.add((x, y))
sch.add_label("USB_DP", position=(x, y))
sch.add_hierarchical_label("PWM_AH", position=(x, y), shape="input")
```

Gotchas found in testing:
- A wire that ends in the middle of another wire does **not** connect. Split the wire at the T point (end both segments there) and add a junction.
- `add_label(..., pin=(ref, pin))` drops the label right on the pin, over the pin number. Do not use it: draw a stub wire, label its end.
- The library's own `validate()` is not ERC. Only trust `kicad-cli sch erc` (via `tools/render`).
- Missing `PWR_FLAG` shows as ERC "Input Power pin not driven by any Output Power pins".

## Hierarchy

```python
root = ksa.create_schematic("controller")
sheet = root.add_sheet("Power", "power.kicad_sch", position=(x, y), size=(w, h))  # returns uuid
root.add_sheet_pin(sheet, "+3V3", pin_type="output", edge="right", position_along_edge=5.08)
# one sheet pin per hierarchical label in the child sheet
```

Check sheet pin names match the child's hierarchical labels exactly; ERC flags mismatches.

## Helper pattern

```python
G = 2.54
def at(ref, pin):
    p = sch.get_component_pin_position(ref, pin); return (p.x, p.y)
def wire(*pts):
    for a, b in zip(pts, pts[1:]): sch.add_wire(a, b)
```
