"""Value faults: a component value that does not meet the spec.

Design and board carry the same wrong value (the schematic of record is wrong), except
`bom_mismatch`, where only the board's footprint value differs from design.json.
Every value fault (except bom_mismatch) is checked to make at least one spec assertion fail or
to leave the golden's published `value_bounds` (when the golden has them); all of them are
invisible to DRC and ERC.
"""
from __future__ import annotations

import json
import random

from pcbenv.faults.common import (FaultRecord, NotApplicable, free, set_board_values, valued_refs, value_detectable)
from pcbenv.families._common import E12, E24, E96, nearest
from pcbenv.golden import Golden
from pcbenv.parts import format_value, parse_value

# Component roles per family (refs that may be absent in some seeds are filtered at use).
ROLES: dict[str, dict[str, list[str]]] = {
    "ldo_reg": {"feedback": ["R1", "R2"], "led_res": ["R4"], "pull": ["R3"], "filter_cap": []},
    "led_driver": {"feedback": [], "led_res": ["R1", "R2", "R3", "R4"], "pull": [], "filter_cap": []},
    "npn_switch": {"feedback": [], "led_res": ["R3"], "pull": ["R4"], "filter_cap": []},
    "nmos_switch": {"feedback": [], "led_res": [], "pull": ["R2"], "filter_cap": []},
    "opamp_noninv": {"feedback": ["R1", "R2"], "led_res": [], "pull": [], "filter_cap": ["C2"]},
    "opamp_inv": {"feedback": ["R1", "R2"], "led_res": [], "pull": ["R3", "R4"], "filter_cap": ["C2"]},
    "rc_lowpass": {"feedback": [], "led_res": [], "pull": [], "filter_cap": ["C1", "C2"]},
    "divider_adc": {"feedback": ["R1", "R2"], "led_res": [], "pull": [], "filter_cap": ["C1"]},
    "mcu_i2c": {"feedback": [], "led_res": [], "pull": ["R2", "R3"], "filter_cap": []},
    "xtal_osc": {"feedback": [], "led_res": ["R2"], "pull": [], "filter_cap": ["C1", "C2"]},
}

ROLE_TEXT = {"feedback": "gain/divider-setting resistor", "led_res": "LED current-limiting resistor",
             "pull": "pull-up/pull-down resistor", "filter_cap": "filter/timing capacitor"}


def _role_refs(golden: Golden, design: dict, role: str, exclude: set[str]) -> list[str]:
    # composite (hard-tier) families record their per-seed roles in params["roles"]
    refs = ROLES.get(golden.family, {}).get(role) or golden.params.get("roles", {}).get(role, [])
    return [r for r in refs if r in design["components"] and free(exclude, r)]


def _snap(x: float, series: list[float]) -> str:
    return format_value(nearest(series, x))


def _apply(golden: Golden, design: dict, board_path: str, salt: str, changes: dict[str, str]) -> None:
    for ref, v in changes.items():
        design["components"][ref]["value"] = v
    set_board_values(board_path, changes, salt)


def _detectable_alone(golden: Golden, changes: dict[str, str]) -> bool:
    """Judge a value change on the golden design with only this change applied, so the choice does
    not depend on other faults of the same task (which may already break the spec)."""
    d = json.loads(json.dumps(golden.design))
    for ref, v in changes.items():
        d["components"][ref]["value"] = v
    return value_detectable(d, golden)


def _first_failing(golden: Golden, design: dict, ref: str, cands: list[str]) -> str | None:
    old = design["components"][ref]["value"]
    for v in cands:
        if v == old or parse_value(v) == parse_value(old):
            continue
        if _detectable_alone(golden, {ref: v}):
            return v
    return None


def _value_fault(ftype: str, role: str, factors: list[float], series: list[float], golden: Golden,
                 design: dict, board_path: str, rng: random.Random, exclude: set[str], salt: str
                 ) -> FaultRecord | None:
    refs = _role_refs(golden, design, role, exclude)
    if not refs:
        return None
    rng.shuffle(refs)
    for ref in refs:
        old = design["components"][ref]["value"]
        fs = list(factors)
        rng.shuffle(fs)
        cands = [_snap(parse_value(old) * f, series) for f in fs]
        new = _first_failing(golden, design, ref, cands)
        if new is None:
            continue
        _apply(golden, design, board_path, salt, {ref: new})
        return FaultRecord(ftype, "value", f"{ref} ({ROLE_TEXT[role]}) is {new}, should be {old}", True,
                           [ref], {"ref": ref, "golden_value": old, "value": new, "role": role})
    return None


def wrong_feedback_resistor(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    """Gain / divider resistor with the wrong value; sometimes the two divider values swapped."""
    refs = _role_refs(golden, design, "feedback", set(exclude))
    if len(refs) == 2 and rng.random() < 0.35:
        a, b = refs
        va, vb = design["components"][a]["value"], design["components"][b]["value"]
        if abs(parse_value(va) / parse_value(vb) - 1) > 0.1:
            if _detectable_alone(golden, {a: vb, b: va}):
                _apply(golden, design, board_path, salt, {a: vb, b: va})
                return FaultRecord("wrong_feedback_resistor", "value",
                                   f"{a} and {b} values swapped ({a}={vb}, {b}={va})", True, [a, b],
                                   {"refs": [a, b], "golden_values": {a: va, b: vb}, "values": {a: vb, b: va},
                                    "role": "feedback", "ref": a, "golden_value": va, "value": vb})
    return _value_fault("wrong_feedback_resistor", "feedback", [0.5, 0.68, 0.75, 1.33, 1.5, 2.0, 3.0],
                        E96, golden, design, board_path, rng, set(exclude), salt)


def wrong_led_resistor(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    return _value_fault("wrong_led_resistor", "led_res", [0.22, 0.33, 0.47, 2.2, 3.3, 4.7, 10.0],
                        E24, golden, design, board_path, rng, set(exclude), salt)


def wrong_filter_cap(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    return _value_fault("wrong_filter_cap", "filter_cap", [0.1, 0.22, 0.47, 0.68, 1.5, 2.2, 4.7, 10.0],
                        E12, golden, design, board_path, rng, set(exclude), salt)


def wrong_pull_resistor(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    return _value_fault("wrong_pull_resistor", "pull", [0.1, 0.22, 4.7, 10.0, 22.0, 47.0, 100.0],
                        E12, golden, design, board_path, rng, set(exclude), salt)


def magnitude_slip(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    """Unit / multiplier typo: the value is 1000x too large or too small (4.7k -> 4.7, 100n -> 100u)."""
    refs = [r for r in valued_refs(design) if free(set(exclude), r) and not r.startswith("Y")]
    rng.shuffle(refs)
    for ref in refs:
        old = design["components"][ref]["value"]
        fs = [1e3, 1e-3]
        rng.shuffle(fs)
        cands = [format_value(parse_value(old) * f) for f in fs]
        cands = [c for c in cands if 1e-13 < parse_value(c) < 1e10]
        new = _first_failing(golden, design, ref, cands)
        if new is None:
            continue
        _apply(golden, design, board_path, salt, {ref: new})
        return FaultRecord("magnitude_slip", "value", f"{ref} is {new} (unit slip), should be {old}", True, [ref],
                           {"ref": ref, "golden_value": old, "value": new})
    return None


def bom_mismatch(golden, design, board_path, rng, exclude=frozenset(), salt="") -> FaultRecord | None:
    """The board's footprint value differs from design.json (layout BOM out of sync)."""
    refs = [r for r in valued_refs(design) if free(set(exclude), r)]
    if not refs:
        return None
    ref = refs[rng.randrange(len(refs))]
    old = design["components"][ref]["value"]
    others = sorted({design["components"][r]["value"] for r in refs
                     if design["components"][r]["part"] == design["components"][ref]["part"]} - {old})
    if others and rng.random() < 0.5:
        new = others[rng.randrange(len(others))]
    else:
        f = [0.1, 0.47, 2.2, 10.0][rng.randrange(4)]
        new = _snap(parse_value(old) * f, E12 if ref[0] in "CL" else E24)
    if new == old:
        raise NotApplicable("same value")
    set_board_values(board_path, {ref: new}, salt)
    return FaultRecord("bom_mismatch", "value", f"board value of {ref} is {new}, design.json says {old}", True, [ref],
                       {"ref": ref, "golden_value": old, "board_value": new, "board_only": True})
