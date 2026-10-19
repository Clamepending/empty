"""Electrical rule check on a design.json (name-insensitive: net names are never used).

Pin classes come from the parts library (`PinInfo.etype`, pin names of the part):
- *ground pin*: a `power_in` pin whose part-level name is GND / V- / VSS / VEE.
- *supply pin*: any other `power_in` pin (VIN, VDD, V+, ...).
- *source pin*: a `power_out` pin, or any pin of a connector part (`CONN*`) -- connectors are
  where external supplies attach.
- *driver pin*: `output` or `power_out`.

Errors (fail grading):
- `unconnected_required`  a required pin is on no net (or alone on a net, see below)
- `single_pin_net`        a net with exactly one pin (connects nothing)
- `driver_conflict`       two or more driver pins on one net
- `no_supply`             a power_in pin whose net has no source pin
- `supply_short`          a supply pin or power_out pin on the same net as a ground pin
- `output_to_ground`      an `output` pin on the same net as a ground pin
- `undriven_input`        a net whose pins are all `input` pins (nothing can set its level)
Warnings (diagnostic only):
- `nc_connected`          an `nc` pin is on a net
- `unconnected_optional`  a non-required pin is unconnected (normal for spare GPIOs; not reported)
"""
from __future__ import annotations

from dataclasses import dataclass

from pcbenv.parts import PARTS

GROUND_PIN_NAMES = frozenset({"GND", "V-", "VSS", "VEE"})


@dataclass(frozen=True)
class ErcIssue:
    severity: str  # "error" | "warning"
    code: str
    detail: str


def _pin_info(design: dict, pin: str):
    ref, name = pin.split(".", 1)
    part = PARTS[design["components"][ref]["part"]]
    return part, name, part.pins[name]


def is_ground_pin(design: dict, pin: str) -> bool:
    _, name, info = _pin_info(design, pin)
    return info.etype == "power_in" and name.upper() in GROUND_PIN_NAMES


def run_erc(design: dict) -> list[ErcIssue]:
    """ERC a validated design (see module docstring). Deterministic order."""
    issues: list[ErcIssue] = []
    comps = design["components"]
    connected: dict[str, str] = {}
    for net, pins in sorted(design["nets"].items()):
        for p in pins:
            connected[p] = net

    for ref in sorted(comps):
        part = PARTS[comps[ref]["part"]]
        for name, info in sorted(part.pins.items()):
            pin = f"{ref}.{name}"
            if pin in connected:
                if info.etype == "nc":
                    issues.append(ErcIssue("warning", "nc_connected", f"{pin} is a no-connect pin but is on a net"))
                continue
            if info.required and info.etype != "nc":
                issues.append(ErcIssue("error", "unconnected_required", f"{pin} must be connected"))

    for net, pins in sorted(design["nets"].items()):
        pins = sorted(set(pins))
        if not pins:
            continue
        where = f"net {net!r} ({', '.join(pins)})"
        if len(pins) == 1:
            issues.append(ErcIssue("error", "single_pin_net", f"{where} has a single pin"))
        infos = {p: _pin_info(design, p) for p in pins}
        etypes = {p: i[2].etype for p, i in infos.items()}
        grounds = [p for p in pins if is_ground_pin(design, p)]
        supplies = [p for p in pins if etypes[p] == "power_in" and p not in grounds]
        drivers = [p for p in pins if etypes[p] in ("output", "power_out")]
        sources = [p for p in pins if etypes[p] == "power_out" or infos[p][0].name.startswith("CONN")]
        if len(drivers) >= 2:
            issues.append(ErcIssue("error", "driver_conflict", f"{where}: several outputs drive it: {drivers}"))
        for p in pins:
            if etypes[p] == "power_in" and not sources:
                issues.append(ErcIssue("error", "no_supply",
                                       f"{p} is a power input but its net has no power output or connector"))
        if grounds:
            for p in supplies + [p for p in drivers if etypes[p] == "power_out"]:
                issues.append(ErcIssue("error", "supply_short", f"{p} is shorted to ground pin {grounds[0]}"))
            for p in drivers:
                if etypes[p] == "output":
                    issues.append(ErcIssue("error", "output_to_ground", f"output {p} is shorted to ground pin {grounds[0]}"))
        if len(pins) >= 2 and all(etypes[p] == "input" for p in pins):
            issues.append(ErcIssue("error", "undriven_input", f"{where}: only input pins, nothing drives it"))
    return issues


def errors(issues: list[ErcIssue]) -> list[ErcIssue]:
    return [i for i in issues if i.severity == "error"]
