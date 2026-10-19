"""Automated pre-screen analyses over the TRAIN split (never holdout) backing qa/self_review.md.

    python3 qa/prescreen/analyses.py > qa/prescreen/analyses.txt

Sections:
 A. faults detected ONLY by the `values` check (spec, DRC, ERC, layout all clean when the fault is alone)
 B. mcu_i2c SDA/SCL pull-up bounds vs the MCU8 datasheet rule Rp >= (VDD - 0.4 V) / 3 mA
 C. narrow_power_trace faults by family / net (signal-level nets vs real supply nets)
 D. TASK.md wording of AC stimuli ("dc source on ...")
 E. value faults applied alone: smallest relative violation of a spec window (is the fault marginal?)
 F. E24 alternatives: does one of the two nearest E24 values to the golden value pass?
 G. led_driver: resistors over the stated 60 mW / 1206 rule, golden and faulted footprints
 H. alternative-but-equivalent LED string topologies vs the topology gate
"""
from __future__ import annotations

import copy
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pcbenv import design as D  # noqa: E402
from pcbenv import layout, sim  # noqa: E402
from pcbenv.checks import value_violations  # noqa: E402
from pcbenv.parts import format_value, parse_value  # noqa: E402

rows = [json.loads(l) for l in (ROOT / "tasks" / "manifest.jsonl").read_text().splitlines() if l.strip()]
rows = [r for r in rows if r["split"] == "train"]
TR = ROOT / "tasks" / "train"


def meta(tid):
    return json.loads((TR / tid / "hidden" / "meta.json").read_text())


def golden(tid):
    return json.loads((TR / tid / "hidden" / "golden_design.json").read_text())


print(f"train tasks: {len(rows)}\n")

# ---------------------------------------------------------------- A
print("## A. faults whose ONLY failing check (fault alone on the golden) is `values`")
cnt = Counter()
for r in rows:
    m = None
    for i, (f, a) in enumerate(zip(r["faults"], r["alone"])):
        if a["failing"] == ["values"]:
            m = m or meta(r["id"])
            d = m["faults"][i]["data"]
            cnt[f["type"]] += 1
            print(f"  {r['id']:34s} {f['type']:20s} {d['ref']} = {d.get('value')} (golden {d['golden_value']}), "
                  f"bounds {m['value_bounds'][d['ref']]}")
print(f"  total {sum(cnt.values())}: {dict(cnt)}\n")

# ---------------------------------------------------------------- B
print("## B. mcu_i2c SDA/SCL pull-ups: value_bounds minimum vs datasheet minimum (VDD-0.4)/3mA")
n = bad = 0
for r in rows:
    if r["family"] != "mcu_i2c":
        continue
    m = meta(r["id"])
    vdd = m["assertions"][0]["supply"]["volts"]
    rmin = (vdd - 0.4) / 3e-3
    for a in m["assertions"]:
        if a["type"] == "dc_current":
            lo, hi = m["value_bounds"][a["element"]]
            n += 1
            if lo > rmin * 1.05:
                bad += 1
                if bad <= 8:
                    print(f"  {r['id']} {a['element']}: datasheet min {rmin:.0f} ohm, bound min {lo:.0f} ohm "
                          f"(values in between pass the spec but fail `values`)")
print(f"  {bad}/{n} pull-ups have a bound minimum > 1.05x the datasheet minimum\n")

# ---------------------------------------------------------------- C
print("## C. narrow_power_trace faults by family and net")
c = Counter()
for r in rows:
    for f in meta(r["id"])["faults"]:
        if f["type"] == "narrow_power_trace":
            c[(r["family"], f["detail"].split("power net ")[1].split(" ")[0])] += 1
for k, v in sorted(c.items()):
    print(f"  {v:3d} {k[0]:14s} {k[1]}")
print(f"  on signal-level families (divider_adc, rc_lowpass): "
      f"{sum(v for k, v in c.items() if k[0] in ('divider_adc', 'rc_lowpass'))}\n")

# ---------------------------------------------------------------- D
print("## D. AC stimuli described as 'dc source' in TASK.md")
ac = acdc = 0
for r in rows:
    m = meta(r["id"])
    md = (TR / r["id"] / "public" / "TASK.md").read_text()
    srcs = [s for a in m["assertions"] for s in ([a["source"]] if isinstance(a.get("source"), dict)
                                                  else (a.get("source") or []))]
    if any("ac" in s and "kind" not in s for s in srcs):
        ac += 1
        acdc += "dc source on" in md
print(f"  tasks with an AC-stimulus assertion: {ac}; TASK.md says 'dc source on ...' for it: {acdc}\n")

# ---------------------------------------------------------------- E / F
E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8,
       7.5, 8.2, 9.1]


def rel_violation(a, res):
    if "min" not in a and "max" not in a:
        return 0.0 if res.passed else math.inf
    m = res.measured
    if m is None:
        return math.inf
    lo, hi = a.get("min", -math.inf), a.get("max", math.inf)
    if lo <= m <= hi:
        return 0.0
    ref = lo if m < lo else hi
    return abs(m - ref) / max(abs(ref), 1e-30)


viol = []
e24 = Counter()
e24_fail = []
for r in rows:
    m = meta(r["id"])
    g = golden(r["id"])
    A = m["assertions"]
    for f in m["faults"]:
        d = f.get("data") or {}
        if f["category"] != "value" or f["type"] == "bom_mismatch":
            continue
        ch = {d["ref"]: d["value"]} if "ref" in d and "value" in d else {}
        mm = re.match(r"(\w+) and (\w+) values swapped \(\w+=(\S+), \w+=(\S+)\)", f["detail"])
        if mm:
            ch = {mm.group(1): mm.group(3), mm.group(2): mm.group(4)}
        dd = copy.deepcopy(g)
        for k, v in ch.items():
            dd["components"][k]["value"] = v
        res = {x.name: x for x in sim.run_assertions(dd, A)}
        v = max([rel_violation(a, res[sim.assertion_name(a)]) for a in A] + [0.0])
        viol.append((v, r["id"], f["detail"]))
        if len(ch) == 1:
            ref = next(iter(ch))
            gv = parse_value(g["components"][ref]["value"])
            dec = 10 ** math.floor(math.log10(gv))
            cands = sorted({e * dec * k for e in E24 for k in (0.1, 1, 10)}, key=lambda x: abs(math.log(x / gv)))[:2]
            ok = False
            for cv in cands:
                d2 = copy.deepcopy(g)
                d2["components"][ref]["value"] = format_value(cv)
                ok = ok or (sim.all_pass(d2, A) and not value_violations(d2, m.get("value_bounds") or {}))
            e24["pass" if ok else "fail"] += 1
            if not ok:
                e24_fail.append((r["id"], ref, g["components"][ref]["value"], [format_value(x) for x in cands]))
viol.sort()
print("## E. value faults applied alone: relative violation of the worst spec window")
print(f"  value faults: {len(viol)}; spec-clean (caught only by `values`): {sum(1 for v in viol if v[0] == 0)}; "
      f"violation 0-5 %: {sum(1 for v in viol if 0 < v[0] < 0.05)}; 5-15 %: {sum(1 for v in viol if .05 <= v[0] < .15)}")
for v in [x for x in viol if x[0] > 0][:6]:
    print(f"  {v[0]:.1%} {v[1]} {v[2]}")
print()
print("## F. nearest-two E24 values to the golden value of each value-faulted ref (rest golden)")
print(f"  at least one passes: {e24['pass']}; none passes: {e24['fail']}")
for x in e24_fail[:10]:
    print("  ", x)
print()

# ---------------------------------------------------------------- G
print("## G. led_driver: resistors over 60 mW (TASK.md: 'Resistors dissipating more than ~60 mW use a 1206 footprint')")
hot = gbad = fbad = 0
for r in rows:
    if r["family"] != "led_driver":
        continue
    m, g = meta(r["id"]), golden(r["id"])
    f = json.loads((TR / r["id"] / "public" / "design.json").read_text())
    a0 = m["assertions"][0]
    rs = [x for x, cc in g["components"].items() if cc["part"] == "R"]
    probes = [{"type": "dc_current", "element": x, "name": x, "min": 0, "max": 10, "supply": a0["supply"],
               "ground_pin": a0.get("ground_pin", "J1.2")} for x in rs]
    for res in sim.run_assertions(g, probes):
        p = res.measured ** 2 * parse_value(g["components"][res.name]["value"])
        if p > 0.06:
            hot += 1
            gbad += "1206" not in g["components"][res.name]["footprint"]
            fbad += "1206" not in f["components"][res.name]["footprint"]
print(f"  resistors > 60 mW: {hot}; golden not on 1206: {gbad}; faulted public design not on 1206: {fbad}")
print("  (the verifier has no footprint-power check: see self_review.md finding F5 for a 1.0-scoring 0805 repair)\n")

# ---------------------------------------------------------------- H
print("## H. electrically equivalent LED-string rewirings vs the topology gate (pcbr-led_driver-312-8e5d8552)")
tid = "pcbr-led_driver-312-8e5d8552"
g, m = golden(tid), meta(tid)
a = copy.deepcopy(g)
n = a["nets"]
n["VS"].remove("R2.1"); n["VS"].append("D3.A"); n["CH2_0"] = ["D3.K", "R2.2"]
n["GND"].remove("D3.K"); n["GND"].append("R2.1")
b = copy.deepcopy(g)
n = b["nets"]
n["CH3_0"] = ["R3.2", "D5.A"]; n["CH3_1"] = ["D5.K", "D4.A"]; n["GND"].remove("D5.K"); n["GND"].append("D4.K")
for name, d in (("channel 2 resistor moved to the low side", a), ("channel 3 LEDs D4/D5 (both LED_RED) swapped", b)):
    D.validate(d)
    res = sim.run_assertions(d, m["assertions"])
    print(f"  {name}: spec all pass = {all(x.passed for x in res)}; topology gate accepts = "
          f"{layout.same_topology(D.partition(d), D.partition(g), m['ref_parts'])}")
