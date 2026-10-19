"""DC operating-point robustness (v2, P0).

v1 accepted ngspice's "transient op" fallback point when Newton + gmin/source stepping failed on
the stiff v1 LDO model (e.g. ldo_reg seed 450 first draw: VOUT 36.9 V from a 12 V input), and
ldo_reg papered over it by redrawing. v2: a smooth finite-gain LDO model, and `sim._run_deck`
rejects the fallback / out-of-span points, re-derives the operating point (stepping retries,
pseudo-transient power-up -> .nodeset -> Newton) and otherwise fails the assertion with
"simulation did not converge" -- never a fabricated measurement.
"""
from __future__ import annotations

import dataclasses
import random
import re
import subprocess

import pytest

from pcbenv import sim
from pcbenv.families import FAMILIES, ldo_reg
from pcbenv.parts import PARTS, Part, PinInfo

# ldo_reg seeds whose v1 first draw did not converge with the v1 LDO model (v1 redrew them)
V1_REDRAWN = [62, 276, 376, 450, 631, 1361, 1993]


def _two_pin_design(part: str) -> dict:
    return {"schema": "pcbenv/design@1", "title": "t",
            "components": {"J1": {"part": "CONN2", "value": "", "footprint": ""},
                           "X1": {"part": part, "value": "", "footprint": ""},
                           "R1": {"part": "R", "value": "1k", "footprint": ""}},
            "nets": {"IN": ["J1.1", "R1.1"], "A": ["R1.2", "X1.1"], "GND": ["J1.2", "X1.2"]}}


@pytest.fixture
def patho_part(monkeypatch):
    """A 2-terminal part with no DC solution: it pushes its node away from 0.5 V both ways."""
    p = Part(name="PATHO", description="test only", pins={"1": PinInfo("1", "passive"), "2": PinInfo("2", "passive")},
             footprints=[], value_required=False,
             spice=lambda ref, n, v: f"B{ref} {n['2']} {n['1']} I=-1e3*(u(v({n['1']},{n['2']})-0.5)-0.5)",
             datasheet="")
    monkeypatch.setitem(PARTS, "PATHO", p)
    return "PATHO"


def test_ldo_generate_has_no_redraw():
    for s in V1_REDRAWN + list(range(20)):
        g = ldo_reg.generate(s)
        assert "redraw" not in g.params
        assert g.to_json() == ldo_reg._generate(s, random.Random(s)).to_json()


def test_ldo_first_draws_converge_without_rescue():
    """Every v1-problem seed (and a spread sample) passes on the plain Newton solve."""
    before = dict(sim.STATS)
    for s in V1_REDRAWN + list(range(0, 2000, 37)):
        g = ldo_reg.generate(s)
        res = sim.run_assertions(g.design, g.assertions)
        assert all(r.passed for r in res), (s, [(r.name, r.measured, r.detail) for r in res])
    assert sim.STATS == before, "a golden needed the robust fallback path"


def test_goldens_never_need_rescue():
    before = dict(sim.STATS)
    for f in sorted(FAMILIES):
        for s in range(5):
            g = FAMILIES[f].generate(s)
            assert all(r.passed for r in sim.run_assertions(g.design, g.assertions)), (f, s)
    assert sim.STATS == before


def test_ldo_matches_analytic_on_random_dividers():
    """Random E24/E96 dividers meeting the spec analytically: sim within 1 % of 0.8*(1+R1/R2)
    (`reports/v2/ldo_analytic_agreement.py` runs 500)."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "reports" / "v2" / "ldo_analytic_agreement.py"
    spec = importlib.util.spec_from_file_location("ldo_agree", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(60, 7) == 0


def test_ldo_regulation_error_within_half_percent():
    """Finite error-amp gain: worst static error over the family's output range <= 0.5 %."""
    for s in range(0, 400, 7):
        g = ldo_reg.generate(s)
        a = dict(g.assertions[0])
        a.pop("min"), a.pop("max")
        m = sim.run_assertions(g.design, [a])[0].measured
        assert abs(m / g.params["vout_nominal"] - 1) <= 0.005, (s, m, g.params["vout_nominal"])


def test_ldo_dropout_and_enable():
    g = ldo_reg.generate(0)
    base = dict(g.assertions[0])
    base.pop("min"), base.pop("max")
    vout = g.params["vout_nominal"]
    # input below the set point: output follows VIN minus the pass-element drop, never above VIN
    low = dict(base, supply={"pin": "J1.1", "volts": round(vout - 0.5, 3)})
    m = sim.run_assertions(g.design, [low])[0].measured
    assert m is not None and 0 < m < vout - 0.5
    # EN floating -> off
    d = dataclasses.replace(g).design
    d = {**d, "nets": {k: [p for p in v if p != "U1.EN"] for k, v in d["nets"].items()}}
    m = sim.run_assertions(d, [base])[0].measured
    assert m is not None and abs(m) < 0.05


def test_old_stiff_ldo_model_is_rescued(monkeypatch):
    """With the v1 model (tanh(4000*...) loop), the plain solve falls back to transient op for
    the V1_REDRAWN draws; the robust path must still return the true operating point."""
    old = (".subckt PCB_LDO vin vss en fb vout\nRq vin vss 100k\nRen en vss 2Meg\nRdo vin vi 0.6\n"
           "Bena ena vss V=0.5*(1+tanh((v(en,vss)-1.2)/0.03))\nRena ena vss 1Meg\n"
           "Bpass vi vout I=0.5*v(ena,vss)*0.5*(1+tanh(4000*(0.8-v(fb,vss))))*tanh(max(v(vi,vout),0)/0.05)\n"
           "Rdis vout vss 1Meg\n.ends PCB_LDO")
    monkeypatch.setitem(PARTS, "LDO_ADJ", dataclasses.replace(PARTS["LDO_ADJ"], models=old))
    before = sim.STATS["rescued"]
    for s in (450, 1993):
        g = ldo_reg.generate(s)
        res = sim.run_assertions(g.design, g.assertions)
        for r in res:
            assert r.passed or r.detail == sim.NOT_CONVERGED, (s, r)
            if r.measured is not None and r.name.startswith("vout"):
                assert abs(r.measured / g.params["vout_nominal"] - 1) < 0.01
    assert sim.STATS["rescued"] > before


def test_no_dc_solution_reports_not_converged(patho_part):
    d = _two_pin_design(patho_part)
    a = {"name": "va", "type": "dc_voltage", "net_pin": "X1.1", "min": -100, "max": 100,
         "supply": {"pin": "J1.1", "volts": 1.0}, "ground_pin": "J1.2"}
    i = {"name": "ix", "type": "dc_current", "element": "R1", "min": 0, "max": 1,
         "supply": {"pin": "J1.1", "volts": 1.0}, "ground_pin": "J1.2"}
    ac = {"name": "g", "type": "ac_gain", "in_pin": "J1.1", "out_pin": "X1.1", "freq": 1e3, "min": 0, "max": 10,
          "source": {"pin": "J1.1", "dc": 1.0, "ac": 1.0}, "ground_pin": "J1.2"}
    res = sim.run_assertions(d, [a, i, ac])
    for r in res:
        assert not r.passed and r.measured is None and r.detail == sim.NOT_CONVERGED, r


def test_raw_ngspice_falls_back_on_patho(patho_part):
    """Guard for the test above: plain ngspice really does take the transient-op fallback here."""
    d = _two_pin_design(patho_part)
    nl = sim.Netlist(d, "J1.2")
    body = nl.lines() + sim._stimulus_lines(nl, {"supply": {"pin": "J1.1", "volts": 1.0}})
    _, log = sim._exec(sim._deck(body, ["op"]), [])
    assert sim._fell_back(log) or "singular" in log.lower() or "failed" in log.lower()


def test_sanity_span():
    body = ["Vzsup0 zsup0 0 DC 12", "Vzsrc0 zsrc0 0 DC 0.5 AC 1", "Vzsrc1 zsrc1 0 PWL(0 0 1e-6 0 2e-6 3.3)"]
    lo, hi = sim._stimulus_span(body)
    assert lo == 0.0 and hi == 12.0
    assert sim._sane([0.0, 11.9, 12.2], (lo, hi))
    assert not sim._sane([36.86], (lo, hi))
    assert not sim._sane([-1.0], (lo, hi))
    assert not sim._sane([float("nan")], (lo, hi))


def test_ngspice_fallback_marker_text():
    """The marker we look for is what ngspice 42 prints when it falls back."""
    out = subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout
    assert re.search(r"ngspice-4\d", out), out
    assert "Transient op started" in sim._FALLBACK_MARKERS


def test_old_hard_clamp_opamp_with_ldo_rail_is_rescued(monkeypatch):
    """v1 op-amp model (hard min/max output clamp) powered from the LDO rail: Newton and both
    stepping methods fail for sys_analog_frontend seed 14 and ngspice falls back to a transient op
    with the rail at 1.24 V instead of 3.3 V. The robust path (pseudo-transient power-up -> full
    .nodeset incl. subcircuit-internal nodes -> Newton) must recover the true operating point."""
    old = (".subckt PCB_OPAMP out vn inp inm vp\nRin inp inm 10Meg\nRcp inp vn 1e10\nRcm inm vn 1e10\nRq vp vn 50k\n"
           "Bmid mid vn V=0.5*v(vp,vn)\nG1 mid x inp inm 1\nR1 x mid 100000\nC1 x mid 1.59155e-06\n"
           "Bo o vn V=min(max(v(x,vn),0.005),max(v(vp,vn)-0.005,0.005))\nRo o out 30\n.ends PCB_OPAMP")
    monkeypatch.setitem(PARTS, "OPAMP", dataclasses.replace(PARTS["OPAMP"], models=old))
    g = FAMILIES["sys_analog_frontend"].generate(14)
    before = sim.STATS["rescued"]
    res = sim.run_assertions(g.design, g.assertions)
    assert all(r.passed for r in res), [(r.name, r.measured, r.detail) for r in res if not r.passed]
    assert sim.STATS["rescued"] > before


def test_raw_voltage_parser():
    text = ("Title: t\nNo. Variables: 3\nNo. Points: 2\nVariables:\n\t0\ttime\ttime\n\t1\tv(n1)\tvoltage\n"
            "\t2\tvzsup0#branch\tcurrent\nValues:\n0\t0.0\n\t1.0\n\t-1e-3\n1\t1e-3\n\t2.5\n\t-2e-3\n")
    assert sim._raw_voltages(text) == {"n1": 2.5}
    assert sim._raw_voltages(None) is None
