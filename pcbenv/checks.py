"""Analytic (non-SPICE) spec checks, used by `sim.run_assertions` for `type: "analytic"`.

Checks
- `xtal_load`: crystal load capacitance.
    fields: `xtal` (ref), `cstray` (F), `tol` (relative, default 0.10), optional `cl` (F; default
    the crystal part's rated CL), optional `osc_pins` [P1, P2] — the crystal's two nets must be
    exactly the nets of these pins (either orientation).
    Each crystal pin's load C = sum of capacitors (part `C`) with one pin on that pin's net and the
    other on the ground net. CL_eff = Ca*Cb/(Ca+Cb) + cstray must be within tol of CL.
"""
from __future__ import annotations

from pcbenv.parts import PARTS, parse_value


def _net_index(design: dict) -> dict[str, str]:
    idx = {}
    for name, pins in design["nets"].items():
        for p in pins:
            idx[p] = name
    return idx


def _xtal_load(design: dict, a: dict):
    from pcbenv.sim import AssertionResult, assertion_name, default_ground_pin

    name = assertion_name(a)
    comps = design["components"]
    x = a["xtal"]
    if x not in comps:
        return AssertionResult(name, False, None, "", f"no component {x}")
    part = PARTS[comps[x]["part"]]
    cl = float(a.get("cl", part.extra.get("cl", 0.0)))
    tol = float(a.get("tol", 0.10))
    exp = f"CL_eff in [{cl*(1-tol)*1e12:.2f}, {cl*(1+tol)*1e12:.2f}] pF"
    idx = _net_index(design)
    gnd = idx.get(a.get("ground_pin") or default_ground_pin(design))
    n1, n2 = idx.get(f"{x}.1"), idx.get(f"{x}.2")
    if gnd is None or n1 is None or n2 is None or n1 == n2 or gnd in (n1, n2):
        return AssertionResult(name, False, None, exp, "crystal pins not on two distinct non-ground nets")
    osc = a.get("osc_pins")
    if osc:
        want = {idx.get(p) for p in osc}
        if want != {n1, n2}:
            return AssertionResult(name, False, None, exp, f"crystal not connected between {osc[0]} and {osc[1]}")

    def load(net: str) -> float:
        total = 0.0
        for ref, c in comps.items():
            if c["part"] != "C":
                continue
            nets = {idx.get(f"{ref}.1"), idx.get(f"{ref}.2")}
            if nets == {net, gnd}:
                total += parse_value(c["value"])
        return total

    ca, cb = load(n1), load(n2)
    if ca <= 0 or cb <= 0:
        return AssertionResult(name, False, None, exp, f"missing load capacitor (Ca={ca:.3g}, Cb={cb:.3g})")
    cl_eff = ca * cb / (ca + cb) + float(a.get("cstray", 0.0))
    ok = abs(cl_eff - cl) <= tol * cl
    return AssertionResult(name, ok, cl_eff, exp, f"Ca={ca*1e12:.2f}p Cb={cb*1e12:.2f}p CL_eff={cl_eff*1e12:.2f}p")


CHECKS = {"xtal_load": _xtal_load}


def run_check(design: dict, a: dict):
    from pcbenv.sim import AssertionResult, assertion_name

    fn = CHECKS.get(a.get("check"))
    if fn is None:
        return AssertionResult(assertion_name(a), False, None, "", f"unknown check {a.get('check')!r}")
    try:
        return fn(design, a)
    except Exception as e:  # noqa: BLE001 - checks must never raise
        return AssertionResult(assertion_name(a), False, None, "", f"check error: {e}")
