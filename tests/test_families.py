"""G1 acceptance: every family x 40 seeds is valid, deterministic, diverse and passes its own spec."""
from __future__ import annotations

import copy
import os
import functools
import time

import pytest

from pcbenv.design import validate
from pcbenv.families import FAMILIES, HARD_FAMILIES, tier
from pcbenv.parts import PARTS, format_value, parse_value
from pcbenv.sim import run_assertions

SEEDS = range(40)
FAMS = sorted(FAMILIES)
PIN_FIELDS = ("net_pin", "in_pin", "out_pin", "ground_pin")


@functools.lru_cache(maxsize=None)
def gen(family: str, seed: int):
    return FAMILIES[family].generate(seed)


def test_at_least_8_families():
    assert len(FAMILIES) >= 8


@pytest.mark.parametrize("family", FAMS)
def test_valid_and_assertions_pass(family):
    failures = []
    slowest = 0.0
    for s in SEEDS:
        g = gen(family, s)
        assert g.family == family and g.seed == s
        validate(g.design)
        t = time.time()
        res = run_assertions(g.design, g.assertions)
        slowest = max(slowest, time.time() - t)
        assert len(res) == len(g.assertions)
        failures += [(s, r) for r in res if not r.passed]
    assert not failures, failures[:5]
    assert slowest < 3.0, f"slowest assertion set took {slowest:.2f}s"


@pytest.mark.parametrize("family", FAMS)
def test_deterministic(family):
    for s in SEEDS:
        assert FAMILIES[family].generate(s).to_json() == gen(family, s).to_json()


@pytest.mark.parametrize("family", FAMS)
def test_diverse(family):
    import json
    distinct = {json.dumps(gen(family, s).design, sort_keys=True) for s in SEEDS}
    assert len(distinct) >= 10, len(distinct)


@pytest.mark.parametrize("family", FAMS)
def test_golden_structure(family):
    for s in SEEDS:
        g = gen(family, s)
        d = g.design
        # every valued component has an acceptable range containing the golden value
        assert set(g.value_bounds) == {r for r, c in d["components"].items() if c["value"]}, s
        assert all(lo <= parse_value(d["components"][r]["value"]) <= hi for r, (lo, hi) in g.value_bounds.items())
        connected = {p for pins in d["nets"].values() for p in pins}
        all_pins = set()
        for ref, c in d["components"].items():
            part = PARTS[c["part"]]
            assert c["footprint"] in part.footprints, (ref, c["footprint"])
            for pin, info in part.pins.items():
                all_pins.add(f"{ref}.{pin}")
                if info.required:
                    assert f"{ref}.{pin}" in connected, f"seed {s}: required pin {ref}.{pin} unconnected"
        for name, pins in d["nets"].items():
            assert len(pins) >= 2, f"seed {s}: single-pin net {name}"
        # assertions reference pins, never net names; every assertion has a ground pin
        for a in g.assertions:
            assert a.get("ground_pin") in all_pins
            for k in PIN_FIELDS:
                if k in a:
                    assert a[k] in all_pins, (k, a[k])
            if "element" in a:
                assert a["element"] in d["components"] or a["element"] in all_pins
        # power nets exist and include GND
        assert "GND" in g.power_nets
        for n, w in g.power_nets.items():
            assert n in d["nets"] and w >= 0.2
        # every IC supply pin is decoupled
        dec = {x["ic_pin"]: x for x in g.decoupling}
        for ref, c in d["components"].items():
            for pin, info in PARTS[c["part"]].pins.items():
                if ref.startswith("U") and info.etype == "power_in" and pin not in ("GND", "V-"):
                    assert f"{ref}.{pin}" in dec, f"seed {s}: {ref}.{pin} has no decoupling cap"
        for x in g.decoupling:
            cap, icp = x["cap"], x["ic_pin"]
            assert d["components"][cap]["part"] == "C"
            net = [n for n, pins in d["nets"].items() if icp in pins]
            assert net and any(p.startswith(cap + ".") for p in d["nets"][net[0]])
        if tier(family) == "hard":
            assert 40 <= g.board_w_mm <= 90 and 40 <= g.board_h_mm <= 70
        else:
            assert 20 <= g.board_w_mm <= 50 and 20 <= g.board_h_mm <= 50
        assert g.intent.strip() and g.params


# ----------------------------------------------------------------------------- sensitivity

def _scale(d: dict, ref: str, k: float = 2.0) -> None:
    c = d["components"][ref]
    c["value"] = format_value(parse_value(c["value"]) * k)


def _swap(d: dict, a: str, b: str) -> None:
    for pins in d["nets"].values():
        for i, p in enumerate(pins):
            if p == a:
                pins[i] = b
            elif p == b:
                pins[i] = a


def _mutate(family: str, g) -> dict:
    d = copy.deepcopy(g.design)
    if family == "ldo_reg":
        _scale(d, "R1")
    elif family == "led_driver":
        _scale(d, "R1")
    elif family == "npn_switch":
        if g.params["load"] == "led":
            _scale(d, "R3")
        else:
            _swap(d, "D1.A", "D1.K")
    elif family == "nmos_switch":
        _swap(d, "Q1.D", "Q1.S")
    elif family == "opamp_noninv":
        _scale(d, "R1")
    elif family == "opamp_inv":
        _scale(d, "R2")
    elif family == "rc_lowpass":
        _scale(d, "C1")
    elif family == "divider_adc":
        _scale(d, "R2")
    elif family == "mcu_i2c":
        _scale(d, "R2")
    elif family == "xtal_osc":
        _scale(d, "C1")
    elif tier(family) == "hard":
        _scale(d, g.params["roles"]["feedback"][0])  # LDO feedback divider top: wrong rail voltage
    else:
        raise AssertionError(f"no mutation for {family}")
    return d


@pytest.mark.parametrize("family", FAMS)
def test_sensitivity(family):
    for s in range(6):
        g = gen(family, s)
        d = _mutate(family, g)
        validate(d)
        res = run_assertions(d, g.assertions)
        assert not all(r.passed for r in res), f"seed {s}: mutated design still passes"


@pytest.mark.parametrize("family", FAMS)
def test_disconnected_ground_fails(family):
    """Removing the ground connector pin from its net must break the spec."""
    g = gen(family, 0)
    d = copy.deepcopy(g.design)
    for pins in d["nets"].values():
        if "J1.2" in pins:
            pins.remove("J1.2")
    res = run_assertions(d, g.assertions)
    assert not all(r.passed for r in res)


# ------------------------------------------------------------------ broad sweep
# `python3 -m pcbenv.families.sweep --seeds 0:2000` checks every seed; here a spread sample of 200
# seeds per family plus the ldo_reg seeds whose v1 first draw did not converge in ngspice.
SWEEP_SEEDS = sorted(set(range(3, 2000, 10)) | {62, 450, 631, 1361, 1993})


def test_sweep_sample():
    from pcbenv.families.sweep import sweep
    fails = sweep(FAMS, SWEEP_SEEDS, workers=min(4, os.cpu_count() or 1))
    assert not fails, fails[:5]


def test_ldo_never_redraws():
    """v1 redrew ldo_reg parameters when ngspice failed to converge; v2's LDO model converges for
    every first draw (see tests/test_sim_convergence.py), so there is no redraw at all."""
    for s in (62, 450, 631, 1361, 1993):
        g = gen("ldo_reg", s)
        assert "redraw" not in g.params and g.seed == s
        assert all(r.passed for r in run_assertions(g.design, g.assertions))


# ------------------------------------------------------------------ hard tier (composites)
@pytest.mark.parametrize("family", HARD_FAMILIES)
def test_hard_tier_composite_structure(family):
    """Composite boards: 20-40 parts, >= 2 ICs, 2 supply rails (input + regulated) besides GND,
    decoupling for every IC supply pin, and an intent with connector and MCU pin tables."""
    assert len(HARD_FAMILIES) >= 3
    for s in SEEDS:
        g = gen(family, s)
        comps = g.design["components"]
        assert 20 <= len(comps) <= 40, (s, len(comps))
        ics = [r for r in comps if r.startswith("U")]
        assert len(ics) >= 2, (s, ics)
        assert len([n for n in g.power_nets if n != "GND"]) >= 2, (s, g.power_nets)
        assert "## Connectors" in g.intent and "Rails:" in g.intent
        if any(c["part"] == "MCU8" for c in comps.values()):
            assert "## MCU pin assignment" in g.intent
        names = [a["name"] for a in g.assertions]
        assert len(names) == len(set(names)), names


@pytest.mark.parametrize("family", FAMS)
def test_reduced_intent_mentions_every_part(family):
    """QA F10: the reduced intent (symptom / vague tasks) still names every sub-circuit, with every
    component ref, by purpose."""
    import re
    from pcbenv.prompts import reduce_intent
    for s in range(15):
        g = gen(family, s)
        red = reduce_intent(g.intent)
        missing = [r for r in g.design["components"] if not re.search(rf"\b{r}\b", red)]
        assert not missing, (s, missing)
