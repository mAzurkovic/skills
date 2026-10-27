"""Copper sizing shared by sizing.py, current_check.py, feasibility.py and the routers. Pure functions, no pcbnew.

Track width: IPC-2152 universal chart (Figure 5-1), least-squares fit published by smps.us, within about 3 % of the
chart from 2 to 100 C (10 A, 20 C: chart 500 mil2, fit 513). IPC-2152 uses one chart for internal and external
copper. The chart board is 1.78 mm polyimide with no planes; FR4 with a plane next to the track runs cooler, so the
fit is conservative for a 4-layer board. `derate` (config "sizing.derate", default 1.0) scales the area if the
user wants the IPC-2152 board/plane modifiers applied by hand.

Via: the plated barrel is a conductor of width pi x (drill + t) and thickness t (plating), sized with the same chart.

Pulse: adiabatic copper heating (no heat leaves the copper), resistivity at 100 C. Conservative for seconds-long
pulses on a board, exact for milliseconds.

Spacing: IPC-2221B Table 6-1. B1 internal, B2 external uncoated (exposed pads), B4 external under solder mask."""
import math

MIL = 0.0254                      # mm
OZ_MM = 0.0347                    # 1 oz/ft2 copper, mm
RHO_100C = 1.72e-8 * (1 + 0.00393 * 80)   # ohm m
CU_HEAT = 3.45e6                  # J / (m3 K), copper volumetric heat capacity

# IPC-2221B Table 6-1, mm, by upper voltage bound (DC or AC peak)
_V = [15, 30, 50, 100, 150, 170, 250, 300, 500]
_SPACING = {
    "B1": [0.05, 0.05, 0.1, 0.1, 0.2, 0.2, 0.2, 0.2, 0.25],
    "B2": [0.1, 0.1, 0.6, 0.6, 0.6, 1.25, 1.25, 1.25, 2.5],
    "B4": [0.13, 0.13, 0.13, 0.13, 0.4, 0.4, 0.4, 0.4, 0.8],
}

# JLCPCB multilayer limits (capabilities page, checked 2026-10-21): minimum track and space by copper weight
JLC_TRACK_SPACE = {0.5: 0.09, 1: 0.09, 2: 0.15}


def area_mil2(amps, rise_c, derate=1.0):
    """IPC-2152 cross-section (mil2) for `amps` RMS at `rise_c` temperature rise."""
    if amps <= 0:
        return 0.0
    return derate * (117.555 * rise_c ** -0.913 + 1.15) * amps ** (0.84 * rise_c ** -0.108 + 1.159)


def amps_for_area(a_mil2, rise_c, derate=1.0):
    """Inverse of area_mil2: RMS current a cross-section carries at `rise_c`."""
    if a_mil2 <= 0:
        return 0.0
    k = derate * (117.555 * rise_c ** -0.913 + 1.15)
    return (a_mil2 / k) ** (1 / (0.84 * rise_c ** -0.108 + 1.159))


def thickness_mm(oz):
    return oz * OZ_MM


def width_for_current(amps, rise_c, oz, derate=1.0):
    """Track width (mm) for `amps` on copper of `oz`, current only (no fab floor)."""
    t_mil = thickness_mm(oz) / MIL
    return area_mil2(amps, rise_c, derate) / t_mil * MIL


def amps_for_width(width_mm, rise_c, oz, derate=1.0):
    return amps_for_area(width_mm / MIL * thickness_mm(oz) / MIL, rise_c, derate)


def via_amps(drill_mm, rise_c, plating_mm=0.018, derate=1.0):
    """RMS current one plated through via carries at `rise_c` (barrel only, conservative)."""
    a = math.pi * (drill_mm + plating_mm) * plating_mm / (MIL * MIL)
    return amps_for_area(a, rise_c, derate)


def pulse_area_mm2(amps, seconds, rise_c):
    """Copper cross-section (mm2) so an adiabatic `amps` pulse of `seconds` heats it by at most `rise_c`."""
    if amps <= 0 or seconds <= 0:
        return 0.0
    return amps * math.sqrt(RHO_100C * seconds / (CU_HEAT * rise_c)) * 1e6


def pulse_width(amps, seconds, rise_c, oz):
    return pulse_area_mm2(amps, seconds, rise_c) / thickness_mm(oz)


def spacing(volts, case):
    """IPC-2221B minimum conductor spacing (mm) for `volts` (peak) and case B1, B2 or B4."""
    for vmax, s in zip(_V, _SPACING[case]):
        if volts <= vmax:
            return s
    return _SPACING[case][-1] + (volts - 500) * {"B1": 0.0025, "B2": 0.005, "B4": 0.00305}[case]


def fab_track_space(oz, limits=None, margin=0.01):
    """Smallest track = space the fab etches on `oz` copper, plus `margin` (mm), rounded to 0.01 mm."""
    lim = limits or JLC_TRACK_SPACE
    k = min((o for o in lim if o >= oz), default=max(lim))
    return round(lim[k] + (margin if lim[k] < 0.15 else 0), 2)


if __name__ == "__main__":
    # self-test against the published fit check point and sanity values
    a = area_mil2(10, 20)
    assert abs(a - 513) < 3, a
    assert abs(amps_for_area(a, 20) - 10) < 1e-6
    w = width_for_current(10, 20, 2)
    print(f"10 A, 20 C: {a:.0f} mil2 -> {w:.2f} mm on 2 oz, {width_for_current(10, 20, 1):.2f} mm on 1 oz")
    print(f"1 A, 10 C, 1 oz: {width_for_current(1, 10, 1):.3f} mm")
    print(f"via 0.2 mm: {via_amps(0.2, 10):.2f} A, 0.3 mm: {via_amps(0.3, 10):.2f} A (10 C, 18 um plating)")
    print(f"40 A, 2 s, 60 C rise: {pulse_area_mm2(40, 2, 60):.3f} mm2 = {pulse_width(40, 2, 60, 2):.1f} mm of 2 oz")
    print(f"48 V spacing: B1 {spacing(48, 'B1')}, B2 {spacing(48, 'B2')}, B4 {spacing(48, 'B4')} mm")
    print(f"fab track/space: 2 oz {fab_track_space(2)}, 1 oz {fab_track_space(1)} mm")
