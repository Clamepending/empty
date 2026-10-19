"""Connectivity faults: the schematic of record is wired wrong, and the board follows it.

The board's pad nets are made to match the faulty design.json and the affected nets are
ripped up and re-routed with the project router, so the faulted board is DRC clean and
consistent with the (wrong) design -- only the intent / datasheets / spec reveal the error.
"""
from __future__ import annotations

import random
from typing import Callable

from pcbenv import design as D
from pcbenv.faults.common import (FaultRecord, NotApplicable, copy_design, free, mirror_design, move_pin, net_of,
                                  nets_target, part_of, rails, remove_pin, swap_pins)
from pcbenv.golden import Golden
from pcbenv.layout import same_topology
from pcbenv.parts import PARTS

IC_PIN_PAIRS = {
    "OPAMP": [("IN+", "IN-"), ("V+", "V-")],
    "LDO_ADJ": [("FB", "EN"), ("VIN", "VOUT")],
    "MCU8": [("SDA", "SCL"), ("VDD", "GND"), ("NRST", "PA0"), ("PA0", "PA1"), ("PA0", "PA2"), ("PA1", "PA2")],
}
TRANSISTOR_PAIRS = {"NPN": [("B", "E"), ("C", "E"), ("B", "C")], "NMOS": [("G", "S"), ("D", "S"), ("G", "D")]}
POLARISED = ("LED_RED", "LED_GREEN", "D_SCHOTTKY")
FLOAT_PINS = {"LDO_ADJ": ["EN", "FB"], "OPAMP": ["IN+", "IN-"], "MCU8": ["NRST"], "NPN": ["B"], "NMOS": ["G"]}
GROUND_PINS = {"LDO_ADJ": ["EN", "FB"], "OPAMP": ["IN+"], "MCU8": ["NRST"], "NPN": ["B"], "NMOS": ["G"]}


def _refs(design: dict, parts) -> list[str]:
    return sorted(r for r, c in design["components"].items() if c["part"] in parts)


def _realise(ftype: str, golden: Golden, design: dict, board_path: str, rng: random.Random, exclude: set[str],
             salt: str, cands: list, mutate: Callable[[dict, object], None],
             describe: Callable[[dict, object], tuple[str, dict]]) -> FaultRecord | None:
    """Try candidates in a seeded random order; the first one that changes the topology and can be
    mirrored onto a DRC-clean board wins."""
    cands = list(cands)
    rng.shuffle(cands)
    rp = {r: c["part"] for r, c in design["components"].items()}
    before = D.partition(design)
    for c in cands:
        d2 = copy_design(design)
        mutate(d2, c)
        if same_topology(D.partition(d2), before, rp):
            continue
        # every pin whose net changed -> its ref and old/new nets must be free
        changed = [p for p in _all_pins(design, d2) if net_of(design, p) != net_of(d2, p)]
        refs = sorted({p.split(".", 1)[0] for p in changed})
        nets = sorted({n for p in changed for n in (net_of(design, p), net_of(d2, p)) if n})
        if not free(exclude, *refs, *nets_target(*nets)):
            continue
        try:
            rerouted = mirror_design(golden, d2, board_path, salt)
        except NotApplicable:
            continue
        detail, data = describe(design, c)
        data["moves"] = {p: [net_of(design, p), net_of(d2, p)] for p in sorted(changed)}
        design.clear()
        design.update(d2)
        return FaultRecord(ftype, "connectivity", detail, True,
                           refs + nets_target(*sorted(set(nets) | set(rerouted))), data)
    return None


def _all_pins(a: dict, b: dict) -> list[str]:
    return sorted({p for d in (a, b) for pins in d["nets"].values() for p in pins})


def swapped_ic_pins(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    """Two IC pins exchanged (op-amp IN+/IN-, LDO FB/EN or VIN/VOUT, MCU SDA/SCL, VDD/GND, GPIOs)."""
    cands = []
    for ref in _refs(design, IC_PIN_PAIRS):
        part = part_of(design, ref)
        for a, b in IC_PIN_PAIRS[part]:
            pa, pb = f"{ref}.{a}", f"{ref}.{b}"
            na, nb = net_of(design, pa), net_of(design, pb)
            if na == nb or (na is None and nb is None):
                continue
            if part == "MCU8" and {a, b} == {"PA1", "PA2"}:
                xa = na and any(p.startswith("Y") for p in design["nets"][na])
                xb = nb and any(p.startswith("Y") for p in design["nets"][nb])
                if xa or xb:
                    continue  # XIN/XOUT exchange is electrically equivalent for a 2-pin crystal
            cands.append((pa, pb))
    return _realise("swapped_ic_pins", golden, design, board_path, rng, set(exclude), salt, cands,
                    lambda d, c: swap_pins(d, c[0], c[1]),
                    lambda d, c: (f"{c[0]} and {c[1]} connections exchanged", {"pins": list(c)}))


def reversed_polarity(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    """LED / diode placed backwards (anode and cathode nets exchanged)."""
    cands = [(f"{r}.A", f"{r}.K") for r in _refs(design, POLARISED)]
    return _realise("reversed_polarity", golden, design, board_path, rng, set(exclude), salt, cands,
                    lambda d, c: swap_pins(d, c[0], c[1]),
                    lambda d, c: (f"{c[0].split('.')[0]} anode/cathode reversed", {"pins": list(c)}))


def transistor_pinout(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    """Transistor wired with the wrong pinout (B/E, C/E, G/S, D/S ... exchanged)."""
    cands = []
    for ref in _refs(design, TRANSISTOR_PAIRS):
        for a, b in TRANSISTOR_PAIRS[part_of(design, ref)]:
            cands.append((f"{ref}.{a}", f"{ref}.{b}"))
    return _realise("transistor_pinout", golden, design, board_path, rng, set(exclude), salt, cands,
                    lambda d, c: swap_pins(d, c[0], c[1]),
                    lambda d, c: (f"{c[0]} and {c[1]} connections exchanged (pinout error)", {"pins": list(c)}))


def _rail_caps(design: dict) -> list[tuple[str, str, str]]:
    """Caps between a supply-ish net and ground: [(ref, rail pin, gnd pin)]."""
    sup, gnd = rails(design)
    out = []
    if gnd is None:
        return out
    for ref in _refs(design, ("C",)):
        n1, n2 = net_of(design, f"{ref}.1"), net_of(design, f"{ref}.2")
        for rp, gp, rn in ((f"{ref}.1", f"{ref}.2", n1), (f"{ref}.2", f"{ref}.1", n2)):
            if net_of(design, gp) != gnd or rn is None or rn == gnd:
                continue
            if rn in _supply_nets(design):
                out.append((ref, rp, gp))
    return out


def _supply_nets(design: dict) -> set[str]:
    sup, gnd = rails(design)
    out = set()
    for name, pins in design["nets"].items():
        if name == gnd:
            continue
        for p in pins:
            ref, pin = p.split(".", 1)
            info = PARTS[part_of(design, ref)].pins[pin]
            if info.etype == "power_out" or (info.etype == "power_in" and pin.upper() not in ("GND", "V-")):
                out.add(name)
    if sup is not None and out:
        out.add(sup)
    return out


def pin_to_wrong_net(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    """A pin tied to the wrong existing net (pull-up returned to GND, EN/NRST/gate grounded, ...)."""
    sup, gnd = rails(design)
    cands = []
    if gnd is None:
        return None
    railcaps = {r for r, _, _ in _rail_caps(design)}
    for ref in _refs(design, ("R", "C")):
        if ref in railcaps:
            continue
        for pin in ("1", "2"):
            p = f"{ref}.{pin}"
            n = net_of(design, p)
            if n == gnd and sup:
                cands.append((p, sup))
            elif n == sup and sup:
                cands.append((p, gnd))
    for ref in _refs(design, GROUND_PINS):
        for pin in GROUND_PINS[part_of(design, ref)]:
            p = f"{ref}.{pin}"
            if net_of(design, p) not in (None, gnd):
                cands.append((p, gnd))
    return _realise("pin_to_wrong_net", golden, design, board_path, rng, set(exclude), salt, cands,
                    lambda d, c: move_pin(d, c[0], c[1]),
                    lambda d, c: (f"{c[0]} tied to net {c[1]} instead of {net_of(d, c[0])}",
                                  {"pin": c[0], "net": c[1], "golden_net": net_of(d, c[0])}))


def floating_pin(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    """A required IC/transistor input left unconnected (open trace / missing wire)."""
    cands = []
    for ref in _refs(design, FLOAT_PINS):
        for pin in FLOAT_PINS[part_of(design, ref)]:
            p = f"{ref}.{pin}"
            if net_of(design, p) is not None:
                cands.append(p)
    return _realise("floating_pin", golden, design, board_path, rng, set(exclude), salt, cands,
                    lambda d, c: remove_pin(d, c),
                    lambda d, c: (f"{c} left unconnected (should be on {net_of(d, c)})",
                                  {"pin": c, "golden_net": net_of(d, c)}))


def decap_misconnected(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    """Supply decoupling / bulk cap disconnected, shorted to GND on both ends, or on the wrong rail."""
    sup, gnd = rails(design)
    supplies = _supply_nets(design)
    cands = []
    for ref, rp, gp in _rail_caps(design):
        cur = net_of(design, rp)
        cands.append((rp, None, "disconnected"))
        cands.append((rp, gnd, "both_gnd"))
        for other in sorted(supplies - {cur}):
            cands.append((rp, other, "wrong_rail"))
    # weight: prefer the DRC/ERC-invisible variants
    weighted = [c for c in cands if c[2] != "disconnected"] * 2 + [c for c in cands if c[2] == "disconnected"]
    seen, uniq = set(), []
    tmp = list(weighted)
    rng.shuffle(tmp)
    for c in tmp:
        if c not in seen:
            seen.add(c)
            uniq.append(c)

    def describe(d, c):
        ref = c[0].split(".")[0]
        txt = {"disconnected": f"{ref} supply-side pin {c[0]} not connected (should be on {net_of(d, c[0])})",
               "both_gnd": f"{ref} supply-side pin {c[0]} tied to {c[1]} (cap shorted out, should be on {net_of(d, c[0])})",
               "wrong_rail": f"{ref} decouples {c[1]} instead of {net_of(d, c[0])}"}[c[2]]
        return txt, {"pin": c[0], "net": c[1], "golden_net": net_of(d, c[0]), "variant": c[2], "cap": ref}

    rng2 = random.Random(rng.random())
    return _realise("decap_misconnected", golden, design, board_path, _NoShuffle(rng2), set(exclude), salt, uniq,
                    lambda d, c: move_pin(d, c[0], c[1]), describe)


class _NoShuffle:
    """rng wrapper whose shuffle is a no-op (candidate order already randomised)."""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def shuffle(self, xs) -> None:
        return None
