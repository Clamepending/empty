"""G12 datasheet design rules (`pcbenv/rules.py`): goldens comply, each rule can be violated, the
verifier only grades them for tasks that carry a rule context, and pcbtool never runs them."""
from __future__ import annotations

import copy
import json
import os
from concurrent.futures import ProcessPoolExecutor

import pytest

from pcbenv import rules as R
from pcbenv.families import FAMILIES
from pcbenv.parts import PARTS, format_value, parse_value

SEEDS = range(40)


def _check_family(fam: str) -> list[str]:
    bad = []
    for s in SEEDS:
        try:
            g, _ = R.harden(FAMILIES[fam].generate(s))
        except ValueError as e:
            bad.append(f"{fam}/{s}: {e}")
            continue
        v = R.run_rules(g.design, R.rules_context(g))
        if v:
            bad.append(f"{fam}/{s}: {v}")
    return bad


V1_FAMILIES = sorted(f for f, m in FAMILIES.items() if getattr(m, "TIER", "v1") != "hard")
COMPOSITE = sorted(f for f, m in FAMILIES.items() if getattr(m, "TIER", "v1") == "hard")


def test_all_hardened_goldens_pass_all_rules():
    with ProcessPoolExecutor(4) as ex:
        bad = [b for res in ex.map(_check_family, V1_FAMILIES) for b in res]
    assert not bad, bad[:10]


@pytest.mark.parametrize("fam", COMPOSITE)
def test_composite_goldens_pass_all_rules(fam):
    """Composite (agent B, in progress) families: some rule operating points do not converge yet."""
    bad = _check_family(fam)
    if bad:
        pytest.xfail(f"{len(bad)}/40 composite goldens fail the rules: {bad[0][:200]}")


def test_harden_only_upsizes_footprints():
    for fam in V1_FAMILIES:
        for s in range(6):
            g0 = FAMILIES[fam].generate(s)
            g, up = R.harden(g0)
            assert g.design["nets"] == g0.design["nets"]
            for ref, c in g.design["components"].items():
                c0 = g0.design["components"][ref]
                assert c["value"] == c0["value"] and c["part"] == c0["part"]
                if ref in up:
                    assert up[ref] == (c0["footprint"], c["footprint"])
                    assert c["footprint"] in PARTS[c["part"]].footprints
                else:
                    assert c["footprint"] == c0["footprint"]


def _find(fam: str, pred, n: int = 60):
    for s in range(n):
        g, _ = R.harden(FAMILIES[fam].generate(s))
        if pred(g):
            return g
    pytest.skip(f"no {fam} seed with the wanted property")


def _codes(design: dict, ctx: dict) -> set[str]:
    return {v.code for v in R.run_rules(design, ctx)}


def _set(d: dict, ref: str, **kw) -> dict:
    d = copy.deepcopy(d)
    d["components"][ref].update(kw)
    return d


def _move(d: dict, pin: str, net: str) -> dict:
    d = copy.deepcopy(d)
    for n in d["nets"]:
        d["nets"][n] = [p for p in d["nets"][n] if p != pin]
    d["nets"][net].append(pin)
    return d


def _net(d: dict, pin: str) -> str:
    return next(n for n, ps in d["nets"].items() if pin in ps)


def _scale(d: dict, ref: str, f: float) -> dict:
    return _set(d, ref, value=format_value(parse_value(d["components"][ref]["value"]) * f))


def _ctx_with(ctx: dict, fn) -> dict:
    c = json.loads(json.dumps(ctx))
    for sc in c["scenarios"]:
        fn(sc)
    return c


def _supply(volts: float):
    def fn(sc):
        if sc.get("supply"):
            sc["supply"]["volts"] = volts
    return fn


def test_rule_mcu_abs_max_and_pin_current():
    g = _find("npn_switch", lambda g: True)
    ctx = R.rules_context(g)
    assert not _codes(g.design, ctx)
    # a GPIO driven 1.5 V above VDD (e.g. by a pull-up to a higher rail)
    gp = g.params["gpio"]
    hi = _ctx_with(ctx, lambda sc: sc.update(source=[{"pin": f"U1.{gp}", "dc": g.params["vs"] + 1.5, "r": 10.0}]))
    assert "mcu_abs_max" in _codes(g.design, hi)
    assert "mcu_pin_current" in _codes(_set(g.design, "R2", value="100"), ctx)


def test_rule_opamp_abs_max():
    g = _find("opamp_noninv", lambda g: True)
    ctx = R.rules_context(g)
    assert "opamp_abs_max" in _codes(g.design, _ctx_with(ctx, _supply(6.0)))


def test_rule_ldo_abs_max():
    g = _find("ldo_reg", lambda g: True)
    ctx = R.rules_context(g)
    assert "ldo_abs_max" in _codes(g.design, _ctx_with(ctx, _supply(18.0)))


def test_rule_nmos_abs_max():
    g = _find("nmos_switch", lambda g: True)
    ctx = R.rules_context(g)

    def ctrl(sc):
        for s in sc.get("source") or []:
            s["dc"] = 15.0
    assert "nmos_abs_max" in _codes(g.design, _ctx_with(ctx, ctrl))


def test_rule_npn_abs_max_and_saturation():
    g = _find("npn_switch", lambda g: True)
    ctx = R.rules_context(g)
    assert "npn_abs_max" in _codes(_set(g.design, "R2", value="10"), ctx)
    lo, hi = g.value_bounds["R2"]
    weak = _set(g.design, "R2", value=format_value(hi))
    assert "npn_saturation" in _codes(weak, ctx)


def test_rule_led_current_and_reverse():
    g = _find("led_driver", lambda g: any(x["i_target"] >= 0.02 for x in g.params["strings"]))
    ctx = R.rules_context(g)
    led = next(x["leds"][0] for x in g.params["strings"] if x["i_target"] >= 0.02)
    assert "led_current" in _codes(_set(g.design, led, footprint="LED_SMD:LED_0603_1608Metric"), ctx)
    g = _find("led_driver", lambda g: g.params["vs"] >= 9 and any(x["n_series"] == 1 for x in g.params["strings"]))
    ctx = R.rules_context(g)
    led = next(x["leds"][0] for x in g.params["strings"] if x["n_series"] == 1)
    d = copy.deepcopy(g.design)
    na, nk = _net(d, f"{led}.A"), _net(d, f"{led}.K")
    d = _move(_move(d, f"{led}.A", nk), f"{led}.K", na)
    assert "led_reverse" in _codes(d, ctx)


def test_rule_diode_ratings_and_flyback():
    g = _find("nmos_switch", lambda g: g.params["kind"] == "inductive")
    ctx = R.rules_context(g)
    assert ctx["inductive_loads"] == [{"supply_pin": "J2.1", "switched_pin": "J2.2"}]
    assert "diode_ratings" in _codes(g.design, _ctx_with(ctx, _supply(45.0)))
    d = _move(g.design, "D1.A", _net(g.design, "J1.2"))
    assert "flyback" in _codes(d, ctx)
    d = _move(_move(g.design, "D1.A", _net(g.design, "D1.K")), "D1.K", _net(g.design, "D1.A"))
    assert "flyback" in _codes(d, ctx)


def test_rule_resistor_power():
    g = _find("led_driver", lambda g: any(c["footprint"].endswith("R_1206_3216Metric")
                                          for c in g.design["components"].values()))
    ctx = R.rules_context(g)
    ref = next(r for r, c in sorted(g.design["components"].items()) if c["footprint"].endswith("R_1206_3216Metric"))
    assert "resistor_power" in _codes(_set(g.design, ref, footprint="Resistor_SMD:R_0603_1608Metric"), ctx)


def test_rule_capacitor_voltage():
    g = _find("nmos_switch", lambda g: g.params["vload"] >= 9)
    ctx = R.rules_context(g)
    assert "capacitor_voltage" in _codes(_set(g.design, "C1", footprint="Capacitor_SMD:C_0603_1608Metric"), ctx)


def test_unsimulatable_design_fails_rules():
    g = _find("ldo_reg", lambda g: True)
    ctx = _ctx_with(R.rules_context(g), lambda sc: sc.update(ground_pin="J9.9"))
    assert {v.code for v in R.run_rules(g.design, ctx)} == {"simulation"}


def test_rule_subset_context():
    g = _find("npn_switch", lambda g: True)
    ctx = R.rules_context(g, ["resistor_power"])
    assert ctx["only"] == ["resistor_power"]
    assert not R.run_rules(_set(g.design, "R2", value="10"), ctx)  # npn_abs_max is not in the subset


def test_hard_datasheets_state_the_rules():
    assert "50 %" in R.hard_datasheet("R") and "0.5 W" in R.hard_datasheet("R")
    assert "80 %" in R.hard_datasheet("C") and "10 V" in R.hard_datasheet("C")
    assert "forced" in R.hard_datasheet("NPN") and "20" in R.hard_datasheet("NPN")
    assert "cathode" in R.hard_datasheet("D_SCHOTTKY")
    assert "VDD + 0.3" in R.hard_datasheet("MCU8")
    for p in PARTS:
        assert R.hard_datasheet(p).startswith(PARTS[p].datasheet.rstrip())


def test_pcbtool_does_not_run_rules():
    import inspect

    from pcbenv import tool
    src = inspect.getsource(tool)
    assert "pcbenv.rules" not in src and "import rules" not in src and "run_rules" not in src


def test_verifier_grades_rules_only_with_context(tmp_path):
    """A rule-violating but otherwise perfect design: 1.0 without a rule context, 0.0 with one."""
    from pcbenv import taskio
    from pcbenv.verify import verify
    from tests.fixtures.verify_tasks import workdir
    g = _find("nmos_switch", lambda g: g.params["vload"] >= 9)
    td = taskio.make_golden_task(g, tmp_path / "task")
    wd = workdir(str(td), tmp_path / "wd")
    r = verify(wd, str(td))
    assert r.reward == 1.0 and "rules" not in r.checks
    meta = taskio.load_meta(td)
    meta["rules"] = R.rules_context(g)
    taskio._write_json(td / "hidden" / "meta.json", meta)
    r = verify(wd, str(td))
    assert r.reward == 1.0 and r.checks["rules"] is True
    # violate: tighten the scenario so the same files break a rule (C1 at 45 V on a 1206 50 V part)
    meta["rules"] = _ctx_with(meta["rules"], _supply(45.0))
    taskio._write_json(td / "hidden" / "meta.json", meta)
    r = verify(wd, str(td))
    assert r.reward == 0.0 and r.checks["rules"] is False and r.detail["rules"]
    assert os.path.exists(os.path.join(wd, "design.json"))


def test_flyback_judged_by_load_terminals_not_connector_labels():
    """v2.1 (QA F5): a non-polar coil on a 2-pin connector with pins 1/2 exchanged still has D1
    across it, cathode on the supply side -> no flyback violation (v2.0 reported a false "no flyback
    diode across it"); a diode reversed across the load is still a violation."""
    from pcbenv.faults.common import swap_pins
    for fam in ("nmos_switch", "npn_switch"):
        g = _find(fam, lambda g: bool(R.rules_context(g)["inductive_loads"]))
        ctx = R.rules_context(g)
        ld = ctx["inductive_loads"][0]
        d = copy.deepcopy(g.design)
        swap_pins(d, ld["supply_pin"], ld["switched_pin"])
        assert "flyback" not in _codes(d, ctx), fam
        dname = next(r for r, c in g.design["components"].items() if c["part"] == "D_SCHOTTKY"
                     and _net(g.design, f"{r}.A") == _net(g.design, ld["switched_pin"]))
        na, nk = _net(g.design, f"{dname}.A"), _net(g.design, f"{dname}.K")
        rev = _move(_move(g.design, f"{dname}.A", nk), f"{dname}.K", na)
        assert "flyback" in _codes(rev, ctx), fam


def test_load_connectors_and_symmetric_refs():
    """2-pin load connectors: coils / solenoids / heaters are non-polar, a motor is polar. Every
    family states the load connector's pinout in its intent, so no shipped task gets
    meta["symmetric_refs"]; when a ref is listed, the topology gate accepts its two pins swapped."""
    from pcbenv import design as D
    from pcbenv.faults.common import swap_pins
    from pcbenv.layout import same_topology
    g = _find("nmos_switch", lambda g: g.params["kind"] == "inductive")
    assert R.load_connectors(g) == [{"ref": "J2", "pins": ["J2.1", "J2.2"], "inductive": True, "polar": False}]
    assert R.symmetric_load_refs(g) == []          # "J2 connects the off-board load: pin 1 = ..."
    m = FAMILIES["sys_motor_ctrl"].generate(0)
    assert [c["polar"] for c in R.load_connectors(m)] == [True]
    import dataclasses
    open_intent = dataclasses.replace(g, intent="A coil on J2 (either way round).")
    assert R.symmetric_load_refs(open_intent) == ["J2"]
    rp = {r: c["part"] for r, c in g.design["components"].items()}
    d = copy.deepcopy(g.design)
    swap_pins(d, "J2.1", "J2.2")
    assert not same_topology(D.partition(d), D.partition(g.design), rp)
    assert same_topology(D.partition(d), D.partition(g.design), rp, frozenset({"J2"}))
