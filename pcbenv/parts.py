"""Generic parts library: pinouts, allowed footprints, SPICE models, datasheets.

Parts are deliberately generic (not real manufacturer part numbers). Each part's
datasheet is self-contained so an agent can solve tasks from the task folder alone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

FOOTPRINT_ROOT = "/usr/share/kicad/footprints"

_SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
_VALUE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*([pnuµmkKMG]?)\s*[a-zA-ZΩ]*\s*$")


def parse_value(s: str) -> float:
    """Parse an SI value string ("4.7k", "100n", "10m", "1M", "2.2") to a float.

    Trailing unit letters (F, H, Ohm, V) are ignored. Raises ValueError on garbage.
    """
    m = _VALUE_RE.match(s)
    if not m:
        raise ValueError(f"bad value: {s!r}")
    return float(m.group(1)) * _SI[m.group(2)]


def format_value(x: float) -> str:
    """Format a float as a compact SI string (inverse of parse_value, 3 significant digits)."""
    if x == 0:
        return "0"
    for suffix, mult in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0), ("m", 1e-3), ("u", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if abs(x) >= mult * 0.9995:
            return f"{x / mult:.3g}{suffix}"
    return f"{x:.3g}"


@dataclass(frozen=True)
class PinInfo:
    pad: str
    etype: str  # power_in | power_out | input | output | bidir | passive | nc
    required: bool = True


@dataclass(frozen=True)
class Part:
    name: str
    description: str
    pins: dict[str, PinInfo]
    footprints: list[str]
    value_required: bool
    # spice(ref, nodes{pin->node}, value_str) -> netlist text (may define/instantiate subckts)
    spice: Callable[[str, dict[str, str], str], str]
    datasheet: str
    # extra subckt/model definitions this part needs, emitted once per deck
    models: str = ""
    extra: dict = field(default_factory=dict)


PARTS: dict[str, Part] = {}


def register(part: Part) -> Part:
    if part.name in PARTS:
        raise ValueError(f"duplicate part {part.name}")
    PARTS[part.name] = part
    return part


# --- Core passives (more parts are registered in pcbenv/parts_lib.py) ---------

_P2 = {"1": PinInfo("1", "passive"), "2": PinInfo("2", "passive")}

register(Part(
    name="R", description="Resistor", pins=_P2,
    footprints=["Resistor_SMD:R_0603_1608Metric", "Resistor_SMD:R_0805_2012Metric", "Resistor_SMD:R_1206_3216Metric"],
    value_required=True,
    spice=lambda ref, n, v: f"R{ref} {n['1']} {n['2']} {parse_value(v):.6g}",
    datasheet="# R — resistor\n\nTwo-terminal resistor. Pins `1`, `2` (non-polarised). Value in ohms.\n",
))

register(Part(
    name="C", description="Capacitor (ceramic, non-polarised)", pins=_P2,
    footprints=["Capacitor_SMD:C_0603_1608Metric", "Capacitor_SMD:C_0805_2012Metric", "Capacitor_SMD:C_1206_3216Metric"],
    value_required=True,
    spice=lambda ref, n, v: f"C{ref} {n['1']} {n['2']} {parse_value(v):.6g}",
    datasheet="# C — ceramic capacitor\n\nTwo-terminal non-polarised capacitor. Pins `1`, `2`. Value in farads.\n",
))

register(Part(
    name="CONN2", description="2-pin header (power/signal input or output)",
    pins={"1": PinInfo("1", "passive"), "2": PinInfo("2", "passive")},
    footprints=["Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"],
    value_required=False,
    spice=lambda ref, n, v: "",
    datasheet="# CONN2 — 2-pin header\n\nPin `1` = signal/supply, pin `2` = ground by board convention.\n",
))
