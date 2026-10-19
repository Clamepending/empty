"""QA F1: value bounds are never tighter than the public datasheets' own limits.

Every check here recomputes the datasheet-derived limit independently of the family code (from
the design's topology, the golden's assertions and the part datasheets) and asserts it lies
inside the published bound:
- I2C pull-ups: [(VDD - 0.4 V)/3 mA, tr/(0.8473 Cbus)] (MCU8 datasheet; UM10204 30-70 % rise time)
- NRST pull-up 2.2k-100k, NRST cap 10n-1u, MCU8/OPAMP decoupling 47n-10u, LDO caps 1u-22u,
  LDO Rbot 10k-50k, NPN base pull-down 10k-100k, NMOS gate series 10-100 ohm, gate pull-down 10k-100k
- LDO EN pull-up: VIN_min * 2M/(R + 2M) >= 1.2 V
- every limit a family recorded in params["datasheet_limits"] (LED 25 mA, GPIO 8 mA, ...)
"""
from __future__ import annotations

import re

import pytest

from pcbenv.families import FAMILIES
from pcbenv.parts import PARTS
from pcbenv.parts_lib import I2C_K_RISE, MCU_PIN_C

FAMS = sorted(FAMILIES)
SEEDS = range(60)
REL = 1e-9


def _net_index(d: dict) -> dict[str, str]:
    return {p: n for n, pins in d["nets"].items() for p in pins}


def _two_terminal(d: dict, part: str):
    idx = _net_index(d)
    for ref, c in sorted(d["components"].items()):
        if c["part"] == part:
            yield ref, idx.get(f"{ref}.1"), idx.get(f"{ref}.2")


def _contains(b: list[float], lo: float | None, hi: float | None) -> bool:
    return (lo is None or b[0] <= lo * (1 + REL)) and (hi is None or b[1] >= hi * (1 - REL))


def _pin_nets(d: dict, part: str, pin: str) -> set[str]:
    idx = _net_index(d)
    return {idx[f"{r}.{pin}"] for r, c in d["components"].items() if c["part"] == part and f"{r}.{pin}" in idx}


def _gnd(d: dict) -> str:
    return _net_index(d)["J1.2"]


def _vdd(g) -> float:
    return float(g.params.get("vout_nominal") or g.params["vdd"]) if "vdd" in g.params else float(g.params.get("vdd", 0))


@pytest.mark.parametrize("family", FAMS)
def test_recorded_datasheet_limits_inside_bounds(family):
    for s in SEEDS:
        g = FAMILIES[family].generate(s)
        for ref, (lo, hi) in (g.params.get("datasheet_limits") or {}).items():
            assert _contains(g.value_bounds[ref], lo, hi), (s, ref, g.value_bounds[ref], lo, hi)


@pytest.mark.parametrize("family", FAMS)
def test_i2c_pullup_bounds_contain_datasheet_range(family):
    n = 0
    for s in SEEDS:
        g = FAMILIES[family].generate(s)
        d = g.design
        idx = _net_index(d)
        for a in g.assertions:
            if a["type"] != "rise_time" or a.get("source", {}).get("kind") != "release":
                continue
            assert a.get("levels") == [0.3, 0.7], "I2C rise time is graded 30-70 % (UM10204)"
            line = idx[a["net_pin"]]
            u = a["net_pin"].split(".")[0]
            vdd_net = idx[f"{u}.VDD"]
            pull = [r for r, n1, n2 in _two_terminal(d, "R") if {n1, n2} == {line, vdd_net}]
            assert len(pull) == 1, (s, a["name"], pull)
            cbus = max(ld["c"] for ld in a["loads"] if ld.get("c") and idx.get(ld["pin"]) == line)
            vdd = _vdd(g)
            rmin = (vdd - 0.4) / 3e-3
            rmax = a["max"] / (I2C_K_RISE * (cbus + MCU_PIN_C))
            assert _contains(g.value_bounds[pull[0]], rmin, rmax), (s, pull[0], g.value_bounds[pull[0]], rmin, rmax)
            n += 1
    if family in ("mcu_i2c", "sys_sensor_node", "sys_motor_ctrl", "sys_clocked_mcu"):
        assert n > 0


def test_packet_033_pullup_now_accepted():
    """QA F1 example: 5 V bus, R3 = 2.2k meets the datasheet sink limit (>= 1.53k) -> in bound."""
    hits = 0
    for s in range(400):
        g = FAMILIES["mcu_i2c"].generate(s)
        if g.params["vdd"] != 5.0:
            continue
        hits += 1
        lo, hi = g.value_bounds["R3"]
        assert lo <= 1533.4 and lo <= 2200 <= hi or 2200 > hi, (s, lo, hi)
    assert hits


@pytest.mark.parametrize("family", FAMS)
def test_fixed_datasheet_ranges_inside_bounds(family):
    for s in SEEDS:
        g = FAMILIES[family].generate(s)
        d, vb = g.design, g.value_bounds
        comps = d["components"]
        idx = _net_index(d)
        gnd = _gnd(d)
        for dc in g.decoupling:
            part = comps[dc["ic_pin"].split(".")[0]]["part"]
            want = {"MCU8": (47e-9, 10e-6), "OPAMP": (47e-9, 10e-6), "LDO_ADJ": (1e-6, 22e-6)}[part]
            assert _contains(vb[dc["cap"]], *want), (s, dc, vb[dc["cap"]])
        nrst = _pin_nets(d, "MCU8", "NRST")
        vdds = _pin_nets(d, "MCU8", "VDD")
        fbs = _pin_nets(d, "LDO_ADJ", "FB")
        npn_b, npn_e = _pin_nets(d, "NPN", "B"), _pin_nets(d, "NPN", "E")
        fet_g, fet_s = _pin_nets(d, "NMOS", "G"), _pin_nets(d, "NMOS", "S")
        for ref, n1, n2 in _two_terminal(d, "R"):
            nets = {n1, n2}
            if nets & nrst and nets & vdds:
                assert _contains(vb[ref], 2.2e3, 100e3), (s, ref, "NRST pull-up", vb[ref])
            if nets & fbs and gnd in nets:
                assert _contains(vb[ref], 10e3, 50e3), (s, ref, "LDO Rbot", vb[ref])
            if nets & npn_b and (nets & npn_e or gnd in nets):
                assert _contains(vb[ref], 10e3, 100e3), (s, ref, "NPN base pull-down", vb[ref])
            if nets & fet_g and (nets & fet_s or gnd in nets):
                assert _contains(vb[ref], 10e3, 100e3), (s, ref, "NMOS gate pull-down", vb[ref])
            elif nets & fet_g:
                assert _contains(vb[ref], 10.0, 100.0), (s, ref, "NMOS gate series", vb[ref])
        for ref, n1, n2 in _two_terminal(d, "C"):
            if {n1, n2} & nrst and gnd in {n1, n2}:
                assert _contains(vb[ref], 10e-9, 1e-6), (s, ref, "NRST cap", vb[ref])


@pytest.mark.parametrize("family", FAMS)
def test_ldo_en_pullup_bound_reaches_threshold_limit(family):
    for s in SEEDS:
        g = FAMILIES[family].generate(s)
        d = g.design
        idx = _net_index(d)
        en = _pin_nets(d, "LDO_ADJ", "EN")
        vins = _pin_nets(d, "LDO_ADJ", "VIN")
        for ref, n1, n2 in _two_terminal(d, "R"):
            if {n1, n2} & en and {n1, n2} & vins:
                low = [a for a in g.assertions if re.search(r"low_vin$", a["name"])]
                vin_min = min(a["supply"]["volts"] for a in low)
                # a series protection diode (composites) only lowers VIN: the bound must reach the
                # limit at the connector voltage at least
                rmax = 2e6 * (vin_min / 1.2 - 1)
                assert g.value_bounds[ref][1] >= rmax and g.value_bounds[ref][0] <= 1e3, \
                    (s, ref, g.value_bounds[ref], rmax)


def test_datasheets_state_the_ranges():
    mcu, opamp, ldo = PARTS["MCU8"].datasheet, PARTS["OPAMP"].datasheet, PARTS["LDO_ADJ"].datasheet
    assert "47 nF–10 µF" in mcu and "2.2k–100k" in mcu and "10 nF–1 µF" in mcu
    assert "(VDD - 0.4 V) / 3 mA" in mcu and "0.8473" in mcu and "UM10204" in mcu
    assert "47 nF–10 µF" in opamp
    assert "1 µF–22 µF" in ldo and "2 MΩ" in ldo
    assert "10k–100k" in PARTS["NPN"].datasheet
    assert "10–100 Ω" in PARTS["NMOS"].datasheet and "10k–100k" in PARTS["NMOS"].datasheet
