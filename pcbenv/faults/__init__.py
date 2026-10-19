"""Fault injector registry (G4).

Every fault type is a function `inject(golden, design, board_path, rng, exclude=..., salt=...)
-> FaultRecord | None` that mutates `design` (dict, in place) and/or the board file at
`board_path`, or returns None (leaving both untouched) when it does not apply to this golden.
`exclude` holds refs / "net:NAME" already used by other faults of the same task, so that
faults stay disjoint and cannot cancel each other.

`apply_fault` is the safe entry point: it works on copies, commits only on success, checks
that the result still loads/validates (`InvalidInjection` otherwise) and fills in
`invisible_to_drc_erc` empirically (ERC of the design + DRC of the board before/after).
"""
from __future__ import annotations

import os
import random
import shutil
import tempfile
from dataclasses import dataclass
from typing import Callable

from pcbenv import design as D
from pcbenv.faults import boardfaults, connectivity, values
from pcbenv.faults.common import FaultRecord, NotApplicable, copy_design, drc_result, erc_codes, load_board
from pcbenv.golden import Golden


class InvalidInjection(RuntimeError):
    """The injector produced files that do not load/validate (counts against validity)."""


@dataclass(frozen=True)
class FaultType:
    name: str
    category: str              # value | connectivity | board
    fn: Callable
    area: str                  # what an "explicit" hint points at, see prompts.py


FAULT_TYPES: dict[str, FaultType] = {f.name: f for f in (
    FaultType("wrong_feedback_resistor", "value", values.wrong_feedback_resistor, "value"),
    FaultType("wrong_led_resistor", "value", values.wrong_led_resistor, "value"),
    FaultType("wrong_filter_cap", "value", values.wrong_filter_cap, "value"),
    FaultType("wrong_pull_resistor", "value", values.wrong_pull_resistor, "value"),
    FaultType("magnitude_slip", "value", values.magnitude_slip, "value"),
    FaultType("bom_mismatch", "value", values.bom_mismatch, "board_value"),
    FaultType("swapped_ic_pins", "connectivity", connectivity.swapped_ic_pins, "pins"),
    FaultType("reversed_polarity", "connectivity", connectivity.reversed_polarity, "pins"),
    FaultType("transistor_pinout", "connectivity", connectivity.transistor_pinout, "pins"),
    FaultType("pin_to_wrong_net", "connectivity", connectivity.pin_to_wrong_net, "pin"),
    FaultType("floating_pin", "connectivity", connectivity.floating_pin, "pin"),
    FaultType("decap_misconnected", "connectivity", connectivity.decap_misconnected, "cap_conn"),
    FaultType("board_pad_swap", "board", boardfaults.board_pad_swap, "pads"),
    FaultType("clearance_violation", "board", boardfaults.clearance_violation, "net_routing"),
    FaultType("broken_trace", "board", boardfaults.broken_trace, "net_routing"),
    FaultType("short_between_nets", "board", boardfaults.short_between_nets, "net_routing"),
    FaultType("narrow_power_trace", "board", boardfaults.narrow_power_trace, "net_routing"),
    FaultType("decap_moved_far", "board", boardfaults.decap_moved_far, "placement"),
    FaultType("footprint_swap", "board", boardfaults.footprint_swap, "footprint"),
)}

CATEGORY_ORDER = {"connectivity": 0, "value": 1, "board": 2}


def _check_valid(design: dict, board_path: str) -> None:
    try:
        D.validate(design)
    except D.DesignError as e:
        raise InvalidInjection(f"design invalid: {e}") from None
    try:
        load_board(board_path)
    except Exception as e:  # noqa: BLE001
        raise InvalidInjection(f"board does not load: {e}") from None


def _visible_state(design: dict, board_path: str) -> tuple[list[str], list[str], int]:
    r = drc_result(board_path)
    return erc_codes(design), sorted(e["type"] for e in r.errors), r.unconnected


def apply_fault(name: str, golden: Golden, design: dict, board_path: str, rng: random.Random,
                exclude: set[str] | frozenset = frozenset(), salt: str = "") -> FaultRecord | None:
    """Apply fault `name` to (design, board_path) in place. None if not applicable.

    Raises InvalidInjection if the injector produced unloadable files (nothing is committed)."""
    ft = FAULT_TYPES[name]
    d2 = copy_design(design)
    with tempfile.TemporaryDirectory(prefix="pcbinj_") as td:
        b2 = os.path.join(td, "board.kicad_pcb")
        shutil.copyfile(board_path, b2)
        before = _visible_state(design, board_path)
        try:
            rec = ft.fn(golden, d2, b2, rng, exclude=set(exclude), salt=f"{salt}:{name}")
        except NotApplicable:
            return None
        if rec is None:
            return None
        _check_valid(d2, b2)
        after = _visible_state(d2, b2)
        # invisible = this fault adds no ERC error, no DRC error and no unconnected item
        new_erc = bool(set(after[0]) - set(before[0])) or len(after[0]) > len(before[0])
        new_drc = len(after[1]) > len(before[1]) or after[2] > before[2]
        rec.invisible_to_drc_erc = not new_erc and not new_drc
        rec.data["erc_after"] = after[0]
        rec.data["drc_after"] = {"errors": after[1], "unconnected": after[2]}
        design.clear()
        design.update(d2)
        shutil.copyfile(b2, board_path)
    return rec


__all__ = ["FAULT_TYPES", "FaultType", "FaultRecord", "apply_fault", "InvalidInjection", "CATEGORY_ORDER",
           "NotApplicable"]
