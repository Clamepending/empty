"""Unit tests for the SPICE assertion engine and analytic checks on tiny hand-built designs."""
from __future__ import annotations

import math

import pytest

from pcbenv.design import validate
from pcbenv.sim import run_assertions

G = "J1.2"


def mk(comps: dict, nets: dict) -> dict:
    from pcbenv.parts import PARTS
    d = {"schema": "pcbenv/design@1", "title": "t",
         "components": {r: {"part": p, "value": v, "footprint": PARTS[p].footprints[0]} for r, (p, v) in comps.items()},
         "nets": nets}
    validate(d)
    return d


def one(d, a):
    res = run_assertions(d, [a])
    assert len(res) == 1
    return res[0]


@pytest.fixture
def divider():
    return mk({"J1": ("CONN2", ""), "R1": ("R", "10k"), "R2": ("R", "30k")},
              {"VIN": ["J1.1", "R1.1"], "MID": ["R1.2", "R2.1"], "GND": ["J1.2", "R2.2"]})


SUP5 = {"supply": {"pin": "J1.1", "volts": 5.0}, "ground_pin": G}


def test_dc_voltage(divider):
    r = one(divider, {"type": "dc_voltage", "net_pin": "R2.1", "min": 3.74, "max": 3.76, **SUP5})
    assert r.passed and math.isclose(r.measured, 3.75, rel_tol=1e-4)
    r = one(divider, {"type": "dc_voltage", "net_pin": "R2.1", "min": 0, "max": 3.0, **SUP5})
    assert not r.passed


def test_dc_voltage_ref_pin(divider):
    r = one(divider, {"type": "dc_voltage", "net_pin": "J1.1", "ref_pin": "R1.2", "min": 1.24, "max": 1.26, **SUP5})
    assert r.passed, r


def test_dc_current_element_and_pin(divider):
    r = one(divider, {"type": "dc_current", "element": "R1", "min": 1.24e-4, "max": 1.26e-4, **SUP5})
    assert r.passed, r
    # current into a connector pin (supply current)
    r = one(divider, {"type": "dc_current", "element": "J1.1", "min": 1.24e-4, "max": 1.26e-4, **SUP5})
    assert r.passed, r


def test_loads_attach(divider):
    # 30k || 30k load at MID -> 15k bottom -> 5*15/25 = 3.0 V
    a = {"type": "dc_voltage", "net_pin": "R2.1", "min": 2.99, "max": 3.01, **SUP5,
         "loads": [{"pin": "R2.1", "r": 30e3}]}
    assert one(divider, a).passed


@pytest.fixture
def rc():
    # R 1k, C 159.155n -> fc = 1 kHz, tau = 159 us
    return mk({"J1": ("CONN2", ""), "J2": ("CONN2", ""), "R1": ("R", "1k"), "C1": ("C", "159.155n")},
              {"IN": ["J1.1", "R1.1"], "OUT": ["R1.2", "C1.1", "J2.1"], "GND": ["J1.2", "C1.2", "J2.2"]})


AC = {"source": {"pin": "J1.1", "ac": 1.0}, "ground_pin": G}


def test_ac_gain(rc):
    r = one(rc, {"type": "ac_gain", "in_pin": "J1.1", "out_pin": "J2.1", "freq": 1000, "min": 0.70, "max": 0.71, **AC})
    assert r.passed and math.isclose(r.measured, 1 / math.sqrt(2), rel_tol=1e-3)


def test_cutoff_lowpass(rc):
    r = one(rc, {"type": "cutoff", "in_pin": "J1.1", "out_pin": "J2.1", "min": 990, "max": 1010, **AC})
    assert r.passed, r


def test_cutoff_highpass():
    d = mk({"J1": ("CONN2", ""), "J2": ("CONN2", ""), "R1": ("R", "1k"), "C1": ("C", "159.155n")},
           {"IN": ["J1.1", "C1.1"], "OUT": ["C1.2", "R1.1", "J2.1"], "GND": ["J1.2", "R1.2", "J2.2"]})
    r = one(d, {"type": "cutoff", "in_pin": "J1.1", "out_pin": "J2.1", "edge": "low", "min": 990, "max": 1010, **AC})
    assert r.passed, r
    # a high-pass has no upper corner in the sweep
    r = one(d, {"type": "cutoff", "in_pin": "J1.1", "out_pin": "J2.1", "edge": "high", "min": 0, "max": 1e9, **AC})
    assert not r.passed and r.measured is None


def test_rise_time_step(rc):
    tau = 1e3 * 159.155e-9
    a = {"type": "rise_time", "net_pin": "J2.1", "min": 0.98 * 2.197 * tau, "max": 1.02 * 2.197 * tau,
         "tstop": 10 * tau, "source": {"pin": "J1.1", "kind": "step", "v0": 0, "v1": 3.3}, "ground_pin": G}
    r = one(rc, a)
    assert r.passed, r


def test_rise_time_open_drain_release():
    d = mk({"J1": ("CONN2", ""), "U1": ("MCU8", ""), "R1": ("R", "4.7k"), "R2": ("R", "10k")},
           {"VDD": ["J1.1", "U1.VDD", "R1.1", "R2.1"], "GND": ["J1.2", "U1.GND"], "SDA": ["U1.SDA", "R1.2"],
            "NRST": ["U1.NRST", "R2.2"]})
    tr = 2.197 * 4.7e3 * 105e-12
    a = {"type": "rise_time", "net_pin": "U1.SDA", "min": 0.97 * tr, "max": 1.03 * tr, "tstop": 5e-6,
         "supply": {"pin": "J1.1", "volts": 3.3}, "source": {"pin": "U1.SDA", "kind": "release"},
         "loads": [{"pin": "U1.SDA", "c": 100e-12}], "ground_pin": G}
    assert one(d, a).passed
    # without the pull-up the line never rises
    d["nets"]["SDA"].remove("R1.2")
    r = one(d, a)
    assert not r.passed


def _xtal(c1="27p", c2="27p", swap=False):
    nets = {"VDD": ["J1.1", "U1.VDD"], "GND": ["J1.2", "U1.GND", "C1.2", "C2.2"],
            "XIN": ["U1.PA1", "Y1.1", "C1.1"], "XOUT": ["U1.PA2", "Y1.2", "C2.1"]}
    if swap:
        nets["XIN"], nets["XOUT"] = ["U1.PA1", "Y1.2", "C1.1"], ["U1.PA2", "Y1.1", "C2.1"]
    return mk({"J1": ("CONN2", ""), "U1": ("MCU8", ""), "Y1": ("XTAL_CL18", "16M"), "C1": ("C", c1),
               "C2": ("C", c2)}, nets)


XA = {"type": "analytic", "check": "xtal_load", "xtal": "Y1", "cstray": 4.5e-12, "tol": 0.1,
      "osc_pins": ["U1.PA1", "U1.PA2"], "ground_pin": G}


def test_analytic_xtal_load():
    r = one(_xtal(), XA)
    assert r.passed and math.isclose(r.measured, 18e-12, rel_tol=1e-6)
    assert one(_xtal(swap=True), XA).passed          # crystal is non-polarised
    assert not one(_xtal(c1="54p"), XA).passed
    d = _xtal()
    d["nets"]["XOUT"].remove("U1.PA2")
    d["nets"]["X2"] = ["U1.PA2"]
    assert not one(d, XA).passed


def test_part_models():
    d = mk({"J1": ("CONN2", ""), "R1": ("R", "300"), "R2": ("R", "280"), "D1": ("LED_RED", ""), "D2": ("LED_GREEN", "")},
           {"V": ["J1.1", "R1.1", "R2.1"], "A1": ["R1.2", "D1.A"], "A2": ["R2.2", "D2.A"], "GND": ["J1.2", "D1.K", "D2.K"]})
    res = run_assertions(d, [
        {"type": "dc_voltage", "net_pin": "D1.A", "min": 1.97, "max": 2.03, **SUP5},
        {"type": "dc_voltage", "net_pin": "D2.A", "min": 2.17, "max": 2.23, **SUP5},
        {"type": "dc_current", "element": "D1", "min": 0.0095, "max": 0.0105, **SUP5},
    ])
    assert all(r.passed for r in res), res


def _ldo(en_net: str | None):
    nets = {"VIN": ["J1.1", "U1.VIN", "C1.1"], "GND": ["J1.2", "U1.GND", "C1.2", "C2.2", "R2.2"],
            "VOUT": ["U1.VOUT", "C2.1", "R1.1"], "FB": ["R1.2", "R2.1", "U1.FB"]}
    if en_net:
        nets[en_net].append("U1.EN")
    return mk({"J1": ("CONN2", ""), "U1": ("LDO_ADJ", ""), "R1": ("R", "31.6k"), "R2": ("R", "10k"),
               "C1": ("C", "1u"), "C2": ("C", "1u")}, nets)


def test_ldo_model():
    a = {"type": "dc_voltage", "net_pin": "U1.VOUT", "min": 3.30, "max": 3.36, **SUP5,
         "loads": [{"pin": "U1.VOUT", "r": 33.0}]}
    assert one(_ldo("VIN"), a).passed
    off = dict(a, min=-0.01, max=0.01)
    assert one(_ldo(None), off).passed        # EN floating -> off
    assert one(_ldo("GND"), off).passed       # EN low -> off


def test_opamp_model():
    d = mk({"J1": ("CONN2", ""), "J2": ("CONN2", ""), "U1": ("OPAMP", ""), "R1": ("R", "90k"), "R2": ("R", "10k"),
            "C1": ("C", "100n")},
           {"VCC": ["J1.1", "U1.V+", "C1.1"], "GND": ["J1.2", "U1.V-", "C1.2", "R2.2", "J2.2"],
            "IN": ["J2.1", "U1.IN+"], "OUT": ["U1.OUT", "R1.1"], "FB": ["R1.2", "R2.1", "U1.IN-"]})
    st = {**SUP5, "source": {"pin": "J2.1", "dc": 0.2, "ac": 1.0}}
    res = run_assertions(d, [
        {"type": "dc_voltage", "net_pin": "U1.OUT", "min": 1.99, "max": 2.01, **st},
        {"type": "ac_gain", "in_pin": "J2.1", "out_pin": "U1.OUT", "freq": 100, "min": 9.95, "max": 10.0, **st},
        {"type": "cutoff", "in_pin": "J2.1", "out_pin": "U1.OUT", "min": 9e4, "max": 1.1e5, **st},
        # saturates at the rail
        {"type": "dc_voltage", "net_pin": "U1.OUT", "min": 4.95, "max": 5.0, **SUP5,
         "source": {"pin": "J2.1", "dc": 1.0}},
    ])
    assert all(r.passed for r in res), res


def test_unsafe_net_names_and_order(divider):
    d = divider
    d["nets"] = {"V+ (main)": d["nets"]["VIN"], "gnd": d["nets"]["GND"], "0": d["nets"]["MID"]}
    res = run_assertions(d, [
        {"type": "dc_current", "element": "R1", "min": 1.24e-4, "max": 1.26e-4, **SUP5},
        {"type": "dc_voltage", "net_pin": "R2.1", "min": 3.74, "max": 3.76, **SUP5, "name": "mid"},
    ])
    assert [r.passed for r in res] == [True, True] and res[1].name == "mid"


@pytest.mark.parametrize("bad", [
    {"type": "dc_voltage", "net_pin": "R9.1", "min": 0, "max": 1, **SUP5},             # unknown pin
    {"type": "dc_current", "element": "Q7", "min": 0, "max": 1, **SUP5},               # unknown element
    {"type": "nonsense", "min": 0, "max": 1},                                           # unknown type
    {"type": "analytic", "check": "nope"},                                              # unknown check
    {"type": "ac_gain", "in_pin": "J1.2", "out_pin": "R2.1", "freq": 10, "min": 0, "max": 9, **AC},  # in on ground
    {"type": "dc_voltage", "net_pin": "R2.1", "min": 0, "max": 9, "supply": {"pin": "J1.1"}, "ground_pin": G},
])
def test_bad_assertions_fail_not_raise(divider, bad):
    res = run_assertions(divider, [bad])
    assert len(res) == 1 and not res[0].passed


def test_broken_designs_fail_not_raise(divider):
    a = {"type": "dc_voltage", "net_pin": "R2.1", "min": 3.74, "max": 3.76, **SUP5}
    d = {**divider, "components": {**divider["components"], "R1": {**divider["components"]["R1"], "value": "abc"}}}
    assert not run_assertions(d, [a])[0].passed            # unparsable value
    shorted = {**divider, "nets": {"VIN": ["J1.1", "R1.1", "J1.2", "R2.2"], "MID": ["R1.2", "R2.1"]}}
    assert not run_assertions(shorted, [a])[0].passed      # supply shorted to ground
    floating = {**divider, "nets": {"VIN": ["J1.1", "R1.1"], "MID": ["R1.2", "R2.1"], "GND": ["R2.2"]}}
    assert not run_assertions(floating, [a])[0].passed     # ground pin unconnected


def test_grouping_mixed_analyses(rc):
    st = {"supply": {"pin": "J1.1", "volts": 2.0}, "ground_pin": G}
    res = run_assertions(rc, [
        {"type": "dc_voltage", "net_pin": "J2.1", "min": 1.99, "max": 2.01, **st},
        {"type": "ac_gain", "in_pin": "J1.1", "out_pin": "J2.1", "freq": 10, "min": 0.99, "max": 1.0, **AC},
        {"type": "dc_current", "element": "C1", "min": 0, "max": 1e-9, **st},
        {"type": "cutoff", "in_pin": "J1.1", "out_pin": "J2.1", "min": 990, "max": 1010, **AC},
    ])
    assert [r.passed for r in res] == [True] * 4, res


def test_part_pad_maps_match_kicad_footprints():
    pcbnew = pytest.importorskip("pcbnew")
    from pcbenv.parts import FOOTPRINT_ROOT, PARTS
    for name, part in PARTS.items():
        assert part.datasheet.strip(), name
        for fp in part.footprints:
            lib, fpname = fp.split(":")
            mod = pcbnew.FootprintLoad(f"{FOOTPRINT_ROOT}/{lib}.pretty", fpname)
            assert mod is not None, fp
            pads = {p.GetNumber() for p in mod.Pads()}
            need = [i.pad for i in part.pins.values()]
            assert len(set(need)) == len(need) and set(need) <= pads, (name, fp, need, pads)
