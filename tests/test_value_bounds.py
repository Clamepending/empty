"""Component value bounds (red team RT01): every valued component has an acceptable [min, max]
range, published in spec.json / TASK.md and graded by the verifier's `values` check.

- every family x seeds 0..39: each valued component has a bound and the golden value is inside it
- bounds reach hidden/meta.json and public/spec.json; TASK.md lists them; pcbtool sim reports them
- per family: one value pushed outside its bound -> reward 0 with `values` failing (for the
  values no assertion constrains, `spec` still passes: only the bound catches it)
- alternative valid repairs (other E-series values that meet the spec, within bounds) -> 1.0
- backwards compatibility: old meta / Golden dicts without `value_bounds` -> no check
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pcbenv.checks import value_violations
from pcbenv.families import FAMILIES
from pcbenv.families._common import E96, nearest
from pcbenv.golden import Golden
from pcbenv.parts import PARTS, format_value, parse_value
from pcbenv.parts_lib import led_vf
from pcbenv.sim import run_assertions
from pcbenv.verify import verify
from tests.fixtures.verify_tasks import build_task, edit_board, edit_design, workdir

ROOT = Path(__file__).resolve().parent.parent
FAMS = sorted(FAMILIES)

# family -> (ref, out-of-bound value, value is unconstrained by the spec assertions)
OUT_OF_BOUND = {
    "divider_adc": ("R3", "10k", True),       # series resistor into an unloaded ADC pin
    "ldo_reg": ("C2", "100u", True),          # output cap x20
    "led_driver": ("R1", "10k", False),
    "mcu_i2c": ("C1", "1n", True),            # decoupling /100
    "nmos_switch": ("R1", "470", True),       # gate series resistor
    "npn_switch": ("C1", "22u", True),        # decoupling x220
    "opamp_inv": ("C3", "100n", True),        # VMID bypass
    "opamp_noninv": ("R3", "10M", True),      # input bias resistor x10
    "rc_lowpass": ("R1", "1M", False),
    "xtal_osc": ("Y1", "80M", True),          # RT01: crystal outside the MCU's 4-25 MHz range
}


@pytest.fixture(scope="module")
def task_root(tmp_path_factory):
    return tmp_path_factory.mktemp("vb_tasks")


def _set_value(wd: str, ref: str, value: str) -> None:
    edit_design(wd, lambda d: d["components"][ref].update(value=value))
    edit_board(wd, lambda b: b.FindFootprintByReference(ref).SetValue(value))


# ------------------------------------------------------------------ generators
@pytest.mark.parametrize("family", FAMS)
def test_every_value_bounded_and_golden_inside(family):
    for s in range(40):
        g = FAMILIES[family].generate(s)
        valued = {r for r, c in g.design["components"].items() if c["value"]}
        assert valued == set(g.value_bounds), (s, valued ^ set(g.value_bounds))
        for ref, (lo, hi) in g.value_bounds.items():
            assert 0 < lo < hi and math.isfinite(hi), (s, ref, lo, hi)
        assert value_violations(g.design, g.value_bounds) == [], s


def test_crystal_frequency_bound_is_tight():
    for s in range(40):
        g = FAMILIES["xtal_osc"].generate(s)
        f = parse_value(g.design["components"]["Y1"]["value"])
        lo, hi = g.value_bounds["Y1"]
        assert lo >= f * (1 - 1.001e-3) and hi <= f * (1 + 1.001e-3)
        assert 4e6 <= f <= 25e6
        assert g.design["components"]["Y1"]["value"] in g.intent


def test_golden_from_dict_without_bounds():
    d = json.loads(FAMILIES["ldo_reg"].generate(0).to_json())
    d.pop("value_bounds")
    assert Golden.from_dict(d).value_bounds == {}


def test_value_violations_unit():
    d = {"components": {"R1": {"part": "R", "value": "10k"}, "C1": {"part": "C", "value": "1e999"}}}
    assert value_violations(d, {}) == []
    assert value_violations(d, {"R1": [1e3, 1e4]}) == []
    assert len(value_violations(d, {"R1": [1e3, 9.9e3]})) == 1
    assert len(value_violations(d, {"C1": [1e-9, 1e-6]})) == 1        # inf
    assert len(value_violations(d, {"X9": [1.0, 2.0]})) == 1           # missing ref


# ------------------------------------------------------------------ task files + tool
def test_bounds_in_meta_spec_and_task_md(task_root):
    td = build_task(task_root, "xtal_osc", 0)
    g = FAMILIES["xtal_osc"].generate(0)
    meta = json.loads(Path(td, "hidden", "meta.json").read_text())
    spec = json.loads(Path(td, "public", "spec.json").read_text())
    assert meta["value_bounds"] == spec["value_bounds"] == g.value_bounds
    md = Path(td, "public", "TASK.md").read_text()
    assert "Component values" in md and "- Y1 (XTAL" in md


def test_pcbtool_sim_reports_bound_violation(task_root, tmp_path):
    td = build_task(task_root, "xtal_osc", 0)
    wd = workdir(td, tmp_path / "w")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    run = lambda *a: subprocess.run([sys.executable, "-m", "pcbenv.tool", *a], cwd=wd, env=env,  # noqa: E731
                                    capture_output=True, text=True, timeout=120)
    ok = run("sim")
    assert ok.returncode == 0 and "PASS values" in ok.stdout, ok.stdout + ok.stderr
    assert run("set-value", "Y1", "80M").returncode == 0
    bad = run("sim")
    assert bad.returncode == 1 and "FAIL value Y1" in bad.stdout, bad.stdout
    chk = run("check")
    assert chk.returncode == 1 and "[FAIL] component values" in chk.stdout, chk.stdout


# ------------------------------------------------------------------ verifier
@pytest.mark.parametrize("family", FAMS)
def test_out_of_bound_value_fails(task_root, tmp_path, family):
    ref, new, unconstrained = OUT_OF_BOUND[family]
    td = build_task(task_root, family, 0)
    g = FAMILIES[family].generate(0)
    lo, hi = g.value_bounds[ref]
    assert not lo <= parse_value(new) <= hi
    wd = workdir(td, tmp_path / "w")
    _set_value(wd, ref, new)
    r = verify(wd, td)
    assert r.reward == 0.0 and r.checks["values"] is False, (r.checks, r.detail)
    assert ref in r.detail["values"][0]
    assert all(r.gates.values()) and r.checks["drc"] and r.checks["erc"] and r.checks["layout"], r.detail
    if unconstrained:  # only the bound sees it
        assert r.checks["spec"] is True, r.detail


def test_old_task_without_bounds_is_not_checked(task_root, tmp_path):
    """Backwards compatible: a meta.json without value_bounds grades as before."""
    import shutil
    src = build_task(task_root, "xtal_osc", 0)
    td = str(tmp_path / "old")
    shutil.copytree(src, td)
    p = Path(td, "hidden", "meta.json")
    meta = json.loads(p.read_text())
    meta.pop("value_bounds")
    p.write_text(json.dumps(meta))
    wd = workdir(td, tmp_path / "w")
    _set_value(wd, "Y1", "80M")
    r = verify(wd, td)
    assert r.reward == 1.0 and r.checks["values"] is True, r.detail


def _alt_and_verify(task_root, tmp_path, family: str, seed: int, changes: dict[str, str]):
    td = build_task(task_root, family, seed)
    g = FAMILIES[family].generate(seed)
    d = json.loads(json.dumps(g.design))
    for ref, val in changes.items():
        assert val != d["components"][ref]["value"]
        d["components"][ref]["value"] = val
    assert value_violations(d, g.value_bounds) == []
    assert all(a.passed for a in run_assertions(d, g.assertions)), "alternative must meet the spec"
    wd = workdir(td, tmp_path / "w")
    for ref, val in changes.items():
        _set_value(wd, ref, val)
    r = verify(wd, td)
    assert r.reward == 1.0, (r.gates, r.checks, r.detail)


@pytest.mark.parametrize("seed", [0, 3])
def test_ldo_alternative_divider_scores_one(task_root, tmp_path, seed):
    """Re-design the feedback divider with a different E96 Rbot (x~1.5, or /~1.5 if near the top)."""
    g = FAMILIES["ldo_reg"].generate(seed)
    r2 = parse_value(g.design["components"]["R2"]["value"])
    k = g.params["vout"] / 0.8 - 1
    r2n = nearest(E96, r2 * (1.5 if r2 < 40e3 else 1 / 1.5))
    r1n = nearest(E96, r2n * k)
    _alt_and_verify(task_root, tmp_path, "ldo_reg", seed, {"R2": format_value(r2n), "R1": format_value(r1n)})


def test_ldo_alternative_caps_score_one(task_root, tmp_path):
    g = FAMILIES["ldo_reg"].generate(0)
    c = {ref: ("22u" if g.design["components"][ref]["value"] != "22u" else "1u") for ref in ("C1", "C2")}
    _alt_and_verify(task_root, tmp_path, "ldo_reg", 0, c)


@pytest.mark.parametrize("seed", [0, 1])
def test_led_driver_alternative_resistor_scores_one(task_root, tmp_path, seed):
    """Replace the E24 series resistor by an E96 value for the same target current."""
    g = FAMILIES["led_driver"].generate(seed)
    s = g.params["strings"][0]
    vf = led_vf({"RED": 2.0, "GREEN": 2.2}[s["color"]], s["i_target"])
    exact = (g.params["vs"] - s["n_series"] * vf) / s["i_target"]
    cur = parse_value(g.design["components"][s["r"]]["value"])
    cands = sorted((v for v in (nearest(E96, exact * f) for f in (1.0, 0.98, 1.02, 0.96, 1.04)) if v != cur),
                   key=lambda v: abs(math.log(v / exact)))
    _alt_and_verify(task_root, tmp_path, "led_driver", seed, {s["r"]: format_value(cands[0])})


def test_npn_alternative_decoupling_scores_one(task_root, tmp_path):
    g = FAMILIES["npn_switch"].generate(0)
    new = "1u" if g.design["components"]["C1"]["value"] != "1u" else "100n"
    _alt_and_verify(task_root, tmp_path, "npn_switch", 0, {"C1": new})


def test_parts_used_have_value_units():
    """TASK.md formats bounds with a unit per part; every valued part is R, C, L or a crystal."""
    for f in FAMS:
        for s in range(10):
            g = FAMILIES[f].generate(s)
            for ref in g.value_bounds:
                part = g.design["components"][ref]["part"]
                assert part in ("R", "C", "L") or part.startswith("XTAL"), (f, ref, part)
                assert PARTS[part].value_required
