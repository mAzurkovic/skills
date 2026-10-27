# Worked example: 45 x 45 mm 4-layer FOC motor controller

- `foc_controller.layout.json`: the board config every script in `../../scripts/` reads. Copy it to
  `hw/<board>.layout.json` and replace the values; drop the keys you do not need.
- `place_v13.py`: placement of the big parts with a rotation search (connectors, FET row, driver over the encoder).
  Superseded for small parts by `place_small.py`; kept for the power-stage geometry.
- `route_v13a.py`: power-stage copper: half-bridge cells as pours on every layer, shunt Kelvin pads, via arrays,
  inner planes, pass-through lane. All locked. Run on a board stripped of routing (`strip.py`).
- `route_v13c.py`: one GND via beside every GND pad of the small parts, thermal vias in exposed pads.
- `rlib.py`: the helpers these three use (older form of `klib.py`).

Board-specific: coordinates, refdes and nets are this board's. Read them for the method, not the numbers.
