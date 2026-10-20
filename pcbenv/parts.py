"""Generic parts library: pinouts, allowed footprints, SPICE models, datasheets.

Parts are deliberately generic (not real manufacturer part numbers). Each part's
datasheet is self-contained so an agent can solve tasks from the task folder alone.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable

FOOTPRINT_ROOT = "/usr/share/kicad/footprints"

_SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3, "K": 1e3,
       "M": 1e6, "meg": 1e6, "MEG": 1e6, "Meg": 1e6, "G": 1e9}
# number, optional SI prefix (mega also as SPICE "meg"), optional unit letters (checked per part below)
_VALUE_RE = re.compile(r"(?P<num>(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)"
                       r"(?P<pre>meg|MEG|Meg|[pnuµμmkKMG])?(?P<unit>[A-Za-zΩΩ]*)")
_OHM = ("", "Ω", "Ω", "ohm", "Ohm", "R")
# unit letters a value may carry, by part (anything else is rejected, e.g. "100nH" on a capacitor)
VALUE_UNITS: dict[str, tuple[str, ...]] = {"R": _OHM, "C": ("", "F"), "L": ("", "H"),
                                           "XTAL": ("", "Hz"), "XTAL_CL18": ("", "Hz")}
VALUE_GRAMMAR_MD = """\
## Value notation (all parts)

A value is `<number><SI prefix?><unit?>`, e.g. `4.7k`, `100n`, `2.2u`, `10R`, `1meg`, `1.5e3`:
- number: digits with an optional decimal point and an optional exponent (`1e3`); no sign, no
  digit grouping, no RKM notation (`4k7`);
- SI prefix (case-sensitive): `p` `n` `u`/`µ`/`μ` (micro) `m` (milli) `k`/`K` `M`/`meg`/`MEG` (mega) `G`;
  an exponent and a prefix together (`1e3k`) are rejected;
- unit letters, optional, must match the part: R `Ω`/`ohm`/`Ohm`/`R`; C `F`; L `H`; crystals `Hz`;
  other parts none (`100nH` on a capacitor is rejected);
- no whitespace or control characters inside the value (leading/trailing spaces are ignored).

design.json and the board must carry the same value; they are compared as numbers (`1k` == `1000`).
"""


def parse_value(s: str, part: str | None = None) -> float:
    """Parse an SI value string ("4.7k", "100n", "10m", "1M", "1meg", "2.2", "10kΩ") to a float.

    Grammar: see VALUE_GRAMMAR_MD. With `part`, unit letters must be one the part allows
    (`VALUE_UNITS`); without it, any unit of any part is accepted. Raises ValueError otherwise.
    """
    if not isinstance(s, str):
        raise ValueError(f"bad value: {s!r}")
    m = _VALUE_RE.fullmatch(s.strip(" "))
    if not m:
        raise ValueError(f"bad value: {s!r}")
    num, pre, unit = m.group("num"), m.group("pre") or "", m.group("unit")
    if pre and ("e" in num or "E" in num):
        raise ValueError(f"bad value: {s!r} (exponent and SI prefix together)")
    allowed = VALUE_UNITS.get(part, ("",)) if part is not None else {u for us in VALUE_UNITS.values() for u in us}
    if unit not in allowed:
        raise ValueError(f"bad value: {s!r} (unit {unit!r} not allowed"
                         + (f" for part {part})" if part is not None else ")"))
    x = float(num) * _SI[pre]
    if not math.isfinite(x):
        raise ValueError(f"bad value: {s!r} (not finite)")
    return x


def values_equal(a: str, b: str, part: str | None = None) -> bool:
    """Same value on board and design: equal strings, or both parse (for `part`) to the same number."""
    if a == b:
        return True
    try:
        x, y = parse_value(a, part), parse_value(b, part)
    except ValueError:
        return False
    return abs(x - y) <= 1e-9 * max(abs(x), abs(y))


def datasheet_text(name: str) -> str:
    """Datasheet as written into a task's `parts/<PART>.md`: the part's datasheet, plus the value
    notation section for parts that carry a value."""
    part = PARTS[name]
    text = part.datasheet.rstrip() + "\n"
    return text + ("\n" + VALUE_GRAMMAR_MD if part.value_required else "")


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

from pcbenv import parts_lib  # noqa: E402,F401
