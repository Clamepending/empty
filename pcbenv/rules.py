"""Datasheet design rules (hard tier, G12): engineering review checks that pcbtool does NOT run.

Every rule is stated in public material: the hard-tier datasheet addenda below (written into
`public/parts/<PART>.md` of hard-tier tasks) and the "Design rules" section of TASK.md. The
verifier runs them as the extra check `rules` only for tasks whose hidden meta carries a `rules`
context (`meta["rules"]`, written by the hard-tier generator); v1 tasks never see this check.

How a candidate design is evaluated
- DC operating points of the candidate are simulated (ngspice, reusing `sim.py`'s netlister and
  stimulus builder) under every DC stimulus condition the golden's own assertions use
  (`rules_context(golden)["scenarios"]`: supply / DC sources / loads / ground pin; AC magnitudes
  are dropped, a released open-drain source is simulated released, i.e. without a source). Stimuli come from
  the hidden meta, never from the agent's files.
- Every pin of every non-connector part is current-sensed, so pin currents and node voltages are
  available to the rules below. A design that does not simulate fails the check.
- The flyback rule uses the design's nets plus the DC operating points (diode orientation).

Rules (code: limit; violations are reported with the measured value):
- `mcu_abs_max`       MCU8 pin voltage within [GND - 0.3 V, VDD + 0.3 V]; VDD - GND <= 6.0 V
- `mcu_pin_current`   MCU8 GPIO (PA0/PA1/PA2/NRST) |I| <= 8 mA; SDA/SCL |I| <= 3 mA
- `opamp_abs_max`     OPAMP supply V+ - V- <= 5.5 V; IN+/IN- within [V- - 0.3 V, V+ + 0.3 V]
- `ldo_abs_max`       LDO_ADJ VIN <= 16 V; EN <= VIN + 0.3 V; IOUT <= 300 mA; (VIN-VOUT)*IOUT <= 0.5 W
- `nmos_abs_max`      NMOS |VGS| <= 12 V; VDS <= 30 V; ID <= 2 A
- `npn_abs_max`       NPN VCE <= 40 V; IC <= 200 mA; IB <= 20 mA
- `npn_saturation`    NPN used as a saturated switch (VCE <= 0.4 V, IC >= 1 mA): forced beta IC/IB <= 20
- `led_current`       LED forward current <= 80 % of its package maximum (0603: 20 mA, 0805: 30 mA)
- `led_reverse`       LED reverse voltage <= 5 V
- `diode_ratings`     D_SCHOTTKY reverse voltage <= 40 V, forward current <= 1 A
- `resistor_power`    R: I^2*R <= 50 % of the footprint's rating (0603 0.1 W, 0805 0.125 W, 1206 0.5 W)
- `capacitor_voltage` C: |V| <= 80 % of the footprint's rated voltage (0603 10 V, 0805 25 V, 1206 50 V)
- `flyback`           every inductive load (from the golden's assertions) has a D_SCHOTTKY directly
                      across it: one pin on each of the load's two nets, cathode on the supply side (the
                      side at the higher potential while the load is energised; v2.1: judged by the
                      load's terminals, not the connector pin labels -- see `check_flyback`)
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from pcbenv.parts import PARTS, parse_value

RULES_VERSION = 1

# ------------------------------------------------------------------ limits (stated in the addenda)
R_POWER_W = {"Resistor_SMD:R_0603_1608Metric": 0.100, "Resistor_SMD:R_0805_2012Metric": 0.125,
             "Resistor_SMD:R_1206_3216Metric": 0.500}
R_DERATING = 0.50
C_VOLTAGE_V = {"Capacitor_SMD:C_0603_1608Metric": 10.0, "Capacitor_SMD:C_0805_2012Metric": 25.0,
               "Capacitor_SMD:C_1206_3216Metric": 50.0}
C_DERATING = 0.80
LED_IF_MAX_A = {"LED_SMD:LED_0603_1608Metric": 0.020, "LED_SMD:LED_0805_2012Metric": 0.030}
LED_DERATING = 0.80
LED_VR_MAX = 5.0
MCU_VDD_MAX = 6.0
MCU_PIN_MARGIN = 0.3
MCU_GPIO_MAX_A = 0.008
MCU_I2C_MAX_A = 0.003
OPAMP_SUPPLY_MAX = 5.5
OPAMP_IN_MARGIN = 0.3
LDO_VIN_MAX = 16.0
LDO_IOUT_MAX = 0.300
LDO_PD_MAX = 0.5
NMOS_VGS_MAX = 12.0
NMOS_VDS_MAX = 30.0
NMOS_ID_MAX = 2.0
NPN_VCE_MAX = 40.0
NPN_IC_MAX = 0.200
NPN_IB_MAX = 0.020
NPN_FORCED_BETA_MAX = 20.0
NPN_SAT_VCE = 0.4
NPN_SAT_IC_MIN = 1e-3
SCHOTTKY_VR_MAX = 40.0
SCHOTTKY_IF_MAX = 1.0
EPS = 1e-9

RULE_CODES = ("mcu_abs_max", "mcu_pin_current", "opamp_abs_max", "ldo_abs_max", "nmos_abs_max", "npn_abs_max",
              "npn_saturation", "led_current", "led_reverse", "diode_ratings", "resistor_power",
              "capacitor_voltage", "flyback")


# ------------------------------------------------------------------ public text
def _r_table() -> str:
    return "\n".join(f"| {fp.split(':')[1].split('_')[1]} | {w:g} W | {w * R_DERATING * 1e3:.1f} mW |"
                     for fp, w in R_POWER_W.items())


def _c_table() -> str:
    return "\n".join(f"| {fp.split(':')[1].split('_')[1]} | {v:g} V | {v * C_DERATING:g} V |"
                     for fp, v in C_VOLTAGE_V.items())


def _led_table() -> str:
    return "\n".join(f"| {fp.split(':')[1].split('_')[1]} | {i * 1e3:g} mA | {i * LED_DERATING * 1e3:g} mA |"
                     for fp, i in LED_IF_MAX_A.items())


ADDENDA: dict[str, str] = {
    "R": ("## Ratings by footprint (high-power thick-film series used on this board)\n\n"
          "| Size | Rated power (70 C) | Design limit (50 % derating) |\n|---|---|---|\n" + _r_table() + "\n\n"
          "**Design rule:** the continuous dissipation P = I²·R of every resistor must not exceed 50 % of its\n"
          "footprint's rated power. Pick the footprint for the power, not just the value.\n"),
    "C": ("## Ratings by footprint (X7R series used on this board)\n\n"
          "| Size | Rated voltage | Design limit (80 %) |\n|---|---|---|\n" + _c_table() + "\n\n"
          "**Design rule:** the DC working voltage across a capacitor must not exceed 80 % of its rated voltage\n"
          "(MLCC capacitance collapses and reliability drops near the rating). The rating follows the footprint.\n"),
    "LED_RED": "", "LED_GREEN": "",
    "D_SCHOTTKY": (f"## Absolute maximum ratings\n- Reverse voltage {SCHOTTKY_VR_MAX:g} V, forward current "
                   f"{SCHOTTKY_IF_MAX:g} A continuous.\n\n"
                   "**Design rule (inductive loads):** every inductive load (relay coil, solenoid, motor) must have a\n"
                   "flyback diode directly across it with the cathode on the load's supply-side terminal and the\n"
                   "anode on its switched terminal. A diode elsewhere (to ground, across the transistor, both ends\n"
                   "on one net) does not clamp the turn-off spike, even though nothing is visible in DC.\n"
                   "The rule concerns the load's two terminals; which connector pin carries which terminal is\n"
                   "the connector's pinout, fixed by the design intent.\n"),
    "NPN": (f"## Absolute maximum ratings\n- VCEO {NPN_VCE_MAX:g} V, IC {NPN_IC_MAX * 1e3:g} mA continuous, "
            f"IB {NPN_IB_MAX * 1e3:g} mA.\n\n"
            f"**Design rule (switching):** when used as a saturated switch (VCE ≤ {NPN_SAT_VCE:g} V), the forced\n"
            f"beta IC/IB must be ≤ {NPN_FORCED_BETA_MAX:g} so the transistor stays saturated over hFE spread and\n"
            "temperature (the typical design point is 10). A transistor that only saturates thanks to a high\n"
            "typical hFE fails this rule.\n"),
    "NMOS": (f"## Absolute maximum ratings\n- VGS ±{NMOS_VGS_MAX:g} V (never exceed, even transiently), "
             f"VDS {NMOS_VDS_MAX:g} V, ID {NMOS_ID_MAX:g} A continuous.\n"),
    "LDO_ADJ": (f"## Absolute maximum ratings\n- VIN {LDO_VIN_MAX:g} V; EN ≤ VIN + 0.3 V (EN must never be "
                f"above VIN); output current {LDO_IOUT_MAX * 1e3:g} mA;\n  package dissipation (VIN - VOUT)·IOUT "
                f"≤ {LDO_PD_MAX:g} W.\n"),
    "OPAMP": (f"## Absolute maximum ratings\n- Supply V+ - V- ≤ {OPAMP_SUPPLY_MAX:g} V; input pins within "
              f"[V- - {OPAMP_IN_MARGIN:g} V, V+ + {OPAMP_IN_MARGIN:g} V].\n"),
    "MCU8": (f"## Absolute maximum ratings\n- VDD - GND ≤ {MCU_VDD_MAX:g} V.\n"
             f"- Any I/O pin (NRST, PA0-PA2, SDA, SCL): {-MCU_PIN_MARGIN:g} V … VDD + {MCU_PIN_MARGIN:g} V. "
             "No pin may be pulled\n  above the MCU's own VDD (e.g. by a pull-up to a higher rail): the ESD diodes "
             "conduct and\n  back-power the chip.\n"
             f"- GPIO current (PA0-PA2, NRST): {MCU_GPIO_MAX_A * 1e3:g} mA max per pin; SDA/SCL: "
             f"{MCU_I2C_MAX_A * 1e3:g} mA max sink.\n"
             "- Pin functions are fixed by the package: crystal on PA1 (XIN) / PA2 (XOUT), I2C on SDA / SCL;\n"
             "  firmware assumes the assignment given in the design intent.\n"),
    "CONN2": "", "CONN3": "", "CONN4": "",
}
ADDENDA["LED_RED"] = ADDENDA["LED_GREEN"] = (
    "## Ratings by package\n\n| Package | Max continuous IF | Design limit (80 %) |\n|---|---|---|\n" + _led_table()
    + f"\n\n**Design rule:** the forward current must not exceed 80 % of the package maximum; reverse voltage\n"
      f"≤ {LED_VR_MAX:g} V.\n")
for _c in ("CONN2", "CONN3", "CONN4"):
    ADDENDA[_c] = ("## Interface rule\nThe pin assignment of every connector is fixed by the design intent "
                   "(cable / mating board):\nswapping two connector pins breaks the interface even if the board "
                   "itself still simulates.\n")


def hard_datasheet(part: str) -> str:
    """Datasheet text for hard-tier tasks: the v1 datasheet + the ratings / design-rule addendum."""
    from pcbenv.parts import datasheet_text
    base = datasheet_text(part).rstrip() + "\n"
    add = ADDENDA.get(part, "")
    return base + ("\n" + add if add else "")


DESIGN_RULES_MD = """\
## Design rules (design review)

Besides the spec, the design must pass an engineering design review. **`pcbtool` does not check any
of this — review the design yourself** against the datasheets in `parts/` (see each part's ratings /
design-rule section) and the design intent:

- **Absolute maximum ratings** of every part under every operating condition of the spec (no MCU pin
  above its VDD + 0.3 V or below -0.3 V, op-amp inputs within the rails, LDO EN ≤ VIN, MOSFET |VGS|,
  transistor / diode voltage and current limits).
- **Current limits:** MCU pin currents, LED forward current (by LED package), transistor collector /
  base currents; a saturated NPN switch needs a forced beta IC/IB ≤ 20.
- **Power / voltage ratings:** every resistor's I²R ≤ 50 % of its footprint's rating; every capacitor's
  working voltage ≤ 80 % of its footprint's rated voltage. Footprint choice matters.
- **Inductive loads** have a flyback diode directly across the load, cathode to the supply side.
- **Interfaces and pin assignments** stated in the design intent (connector pinouts, MCU pin functions,
  which rail each part connects to) must be respected exactly, even where the circuit would still
  simulate with a different assignment.

The grader checks these rules under the spec's operating conditions. A design can pass every
`pcbtool` check and still fail review.
"""


# ------------------------------------------------------------------ context (hidden meta)
def _scenario(a: dict) -> dict:
    srcs = a.get("source")
    srcs = srcs if isinstance(srcs, list) else ([srcs] if srcs else [])
    out_src = []
    for s in srcs:
        if s.get("kind") == "release":
            continue  # an open-drain line released by the driver: DC = just the pull-up network
        s2 = {k: v for k, v in s.items() if k != "ac"}
        if s2.get("kind", "dc") == "dc" and "dc" not in s2:
            s2["dc"] = 0.0
        out_src.append(s2)
    return {"supply": a.get("supply"), "source": out_src or None, "loads": a.get("loads"),
            "ground_pin": a.get("ground_pin")}


def rules_context(golden, only: list[str] | None = None) -> dict:
    """Hidden rule context (derived from the golden). Hard tier: all rules, stored in meta["rules"].
    `only` restricts it to a subset of rule codes (all tiers: meta["rules_power"], resistor power)."""
    scen, seen = [], set()
    for a in golden.assertions:
        if a.get("type") not in ("dc_voltage", "dc_current", "ac_gain", "cutoff", "rise_time"):
            continue
        s = _scenario(a)
        if not s["supply"] and not s["source"]:
            continue
        k = json.dumps(s, sort_keys=True)
        if k not in seen:
            seen.add(k)
            scen.append(s)
    nets = golden.design["nets"]
    net_of = {p: n for n, pins in nets.items() for p in pins}
    ind, seen_l = [], set()
    for a in golden.assertions:
        for ld in a.get("loads") or []:
            if ld.get("l") is None or not ld.get("to"):
                continue
            key = tuple(sorted((ld["pin"], ld["to"])))
            if key in seen_l:
                continue
            seen_l.add(key)
            pa, pb = ld["pin"], ld["to"]
            # the supply side is the end whose net carries a diode cathode in the golden
            ks = {net_of.get(f"{r}.K") for r, c in golden.design["components"].items() if c["part"] == "D_SCHOTTKY"}
            if net_of.get(pb) in ks and net_of.get(pa) not in ks:
                pa, pb = pb, pa
            ind.append({"supply_pin": pa, "switched_pin": pb})
    ctx = {"version": RULES_VERSION, "scenarios": scen, "inductive_loads": ind}
    if only:
        ctx["only"] = sorted(only)
    return ctx


# ------------------------------------------------------------------ off-board load connectors (QA F5)
POLAR_LOAD_WORDS = ("brushed DC motor",)


def load_connectors(golden) -> list[dict]:
    """2-pin connectors whose two pins are exactly the two terminals of an off-board load in the
    golden's assertions: [{"ref", "pins", "inductive", "polar"}]. A load is polarised (a motor: the
    pin order sets the direction of rotation) if the intent describes it as one of POLAR_LOAD_WORDS
    or the family sets params["load_polar"]; relay coils, solenoids and heaters are not (the
    nmos_switch family's "solenoid/motor" load counts as a solenoid)."""
    from pcbenv.parts import PARTS as _P
    out, seen = [], set()
    polar = bool(golden.params.get("load_polar")) or any(w in golden.intent for w in POLAR_LOAD_WORDS)
    for a in golden.assertions:
        for ld in a.get("loads") or []:
            if not ld.get("to"):
                continue
            ra, rb = ld["pin"].split(".", 1)[0], ld["to"].split(".", 1)[0]
            c = golden.design["components"].get(ra)
            if ra != rb or c is None or not c["part"].startswith("CONN") or len(_P[c["part"]].pins) != 2:
                continue
            if ra in seen:
                continue
            seen.add(ra)
            out.append({"ref": ra, "pins": sorted([ld["pin"], ld["to"]]), "inductive": ld.get("l") is not None,
                        "polar": polar and ld.get("l") is not None})
    return out


def _intent_fixes_pinout(intent: str, ref: str) -> bool:
    import re
    pats = (rf"\b{ref}\b[^\n]*\bpin 1 =", rf"\|\s*{ref}\s*\|\s*1\s*\|", rf"\b{ref} pin [12]\b")
    return any(re.search(p, intent) for p in pats)


def symmetric_load_refs(golden) -> list[str]:
    """2-pin connectors of a NON-polar load whose pin order the public intent does not fix: the
    topology gate treats their two pins as interchangeable (meta["symmetric_refs"]). Every current
    family states the load connector's pinout ("J2 (pin 1 = supply, pin 2 = switched side)"), so this
    is empty for all shipped tasks; a family that leaves the coil orientation open gets it for free."""
    return sorted(c["ref"] for c in load_connectors(golden)
                  if not c["polar"] and not _intent_fixes_pinout(golden.intent, c["ref"]))


# ------------------------------------------------------------------ evaluation
@dataclass(frozen=True)
class Violation:
    code: str
    detail: str


@dataclass
class OpPoint:
    v: dict[str, float]   # pin -> voltage (net side) vs scenario ground
    i: dict[str, float]   # pin -> current INTO the part at that pin (A); only sensed pins


def _sense_pins(design: dict) -> list[str]:
    out = []
    for ref, c in sorted(design["components"].items()):
        part = PARTS[c["part"]]
        if part.name.startswith("CONN"):
            continue
        for pin in part.pins:
            out.append(f"{ref}.{pin}")
    return out


def operating_point(design: dict, scenario: dict) -> OpPoint:
    """DC operating point of `design` under `scenario`. Raises sim.SimError on failure."""
    from pcbenv import sim
    ground = scenario.get("ground_pin") or sim.default_ground_pin(design)
    sense = _sense_pins(design)
    nl = sim.Netlist(design, ground, sense)
    pins = sorted(nl.pin_node)
    nodes = sorted({nl.pin_node[p] for p in pins} - {"0"})
    exprs = [f"v({n})" for n in nodes] + [f"i({nl.sense[p]})" for p in sense]
    stim = {k: scenario.get(k) for k in ("supply", "source", "loads")}
    rows = sim._run_deck(nl.lines() + sim._stimulus_lines(nl, stim), ["op", "wrdata out.txt " + " ".join(exprs)],
                         "out.txt")
    row = rows[0]
    if len(row) != 1 + len(exprs):
        raise sim.SimError("unexpected op output shape")
    nv = {"0": 0.0}
    for k, n in enumerate(nodes):
        nv[n] = row[1 + k]
    cur = {p: row[1 + len(nodes) + k] for k, p in enumerate(sense)}
    return OpPoint({p: nv[nl.pin_node[p]] for p in pins}, cur)


def _comps(design: dict, part_prefix: str | tuple) -> list[tuple[str, dict]]:
    pre = (part_prefix,) if isinstance(part_prefix, str) else part_prefix
    return [(r, c) for r, c in sorted(design["components"].items()) if c["part"].startswith(pre)]


def _connected(design: dict, pin: str) -> bool:
    return any(pin in pins for pins in design["nets"].values())


def _fmt(x: float, unit: str) -> str:
    a = abs(x)
    for s, m in (("", 1.0), ("m", 1e-3), ("u", 1e-6)):
        if a >= m * 0.9995 or s == "u":
            return f"{x / m:.3g} {s}{unit}"
    return f"{x:.3g} {unit}"


def check_op(design: dict, op: OpPoint, tag: str) -> list[Violation]:
    """All operating-point rules for one scenario."""
    out: list[Violation] = []
    v, i = op.v, op.i

    def bad(code: str, msg: str) -> None:
        out.append(Violation(code, f"{msg} [{tag}]"))

    for ref, c in _comps(design, "MCU8"):
        g = v[f"{ref}.GND"]
        vdd = v[f"{ref}.VDD"] - g
        if vdd > MCU_VDD_MAX + EPS:
            bad("mcu_abs_max", f"{ref} VDD-GND = {vdd:.3g} V > {MCU_VDD_MAX:g} V")
        for pin in ("NRST", "PA0", "PA1", "PA2", "SDA", "SCL"):
            p = f"{ref}.{pin}"
            if not _connected(design, p):
                continue
            vp = v[p] - g
            if vp > vdd + MCU_PIN_MARGIN + 1e-6 or vp < -MCU_PIN_MARGIN - 1e-6:
                bad("mcu_abs_max", f"{p} at {vp:.3g} V outside [-0.3 V, VDD+0.3 V = {vdd + MCU_PIN_MARGIN:.3g} V]")
            lim = MCU_I2C_MAX_A if pin in ("SDA", "SCL") else MCU_GPIO_MAX_A
            ip = abs(i.get(p, 0.0))
            if ip > lim * (1 + 1e-6):
                bad("mcu_pin_current", f"{p} current {_fmt(ip, 'A')} > {_fmt(lim, 'A')}")
    for ref, c in _comps(design, "OPAMP"):
        vn, vpp = v[f"{ref}.V-"], v[f"{ref}.V+"]
        if vpp - vn > OPAMP_SUPPLY_MAX + 1e-6:
            bad("opamp_abs_max", f"{ref} supply {vpp - vn:.3g} V > {OPAMP_SUPPLY_MAX:g} V")
        for pin in ("IN+", "IN-"):
            p = f"{ref}.{pin}"
            if _connected(design, p) and not (vn - OPAMP_IN_MARGIN - 1e-6 <= v[p] <= vpp + OPAMP_IN_MARGIN + 1e-6):
                bad("opamp_abs_max", f"{p} at {v[p] - vn:.3g} V outside the rails [0, {vpp - vn:.3g} V] ±0.3 V")
    for ref, c in _comps(design, "LDO_ADJ"):
        g = v[f"{ref}.GND"]
        vin, ven, vout = v[f"{ref}.VIN"] - g, v[f"{ref}.EN"] - g, v[f"{ref}.VOUT"] - g
        iout = -i.get(f"{ref}.VOUT", 0.0)
        if vin > LDO_VIN_MAX + 1e-6:
            bad("ldo_abs_max", f"{ref} VIN {vin:.3g} V > {LDO_VIN_MAX:g} V")
        if _connected(design, f"{ref}.EN") and ven > vin + 0.3 + 1e-6:
            bad("ldo_abs_max", f"{ref} EN {ven:.3g} V > VIN + 0.3 V")
        if iout > LDO_IOUT_MAX * (1 + 1e-6):
            bad("ldo_abs_max", f"{ref} output current {_fmt(iout, 'A')} > {LDO_IOUT_MAX * 1e3:g} mA")
        pd = max(0.0, vin - vout) * max(0.0, iout)
        if pd > LDO_PD_MAX * (1 + 1e-6):
            bad("ldo_abs_max", f"{ref} dissipation {pd:.3g} W > {LDO_PD_MAX:g} W")
    for ref, c in _comps(design, "NMOS"):
        vgs, vds = v[f"{ref}.G"] - v[f"{ref}.S"], v[f"{ref}.D"] - v[f"{ref}.S"]
        idr = abs(i.get(f"{ref}.D", 0.0))
        if abs(vgs) > NMOS_VGS_MAX + 1e-6:
            bad("nmos_abs_max", f"{ref} |VGS| = {abs(vgs):.3g} V > {NMOS_VGS_MAX:g} V")
        if vds > NMOS_VDS_MAX + 1e-6:
            bad("nmos_abs_max", f"{ref} VDS {vds:.3g} V > {NMOS_VDS_MAX:g} V")
        if idr > NMOS_ID_MAX * (1 + 1e-6):
            bad("nmos_abs_max", f"{ref} ID {_fmt(idr, 'A')} > {NMOS_ID_MAX:g} A")
    for ref, c in _comps(design, "NPN"):
        vce = v[f"{ref}.C"] - v[f"{ref}.E"]
        ic, ib = i.get(f"{ref}.C", 0.0), i.get(f"{ref}.B", 0.0)
        if vce > NPN_VCE_MAX + 1e-6:
            bad("npn_abs_max", f"{ref} VCE {vce:.3g} V > {NPN_VCE_MAX:g} V")
        if abs(ic) > NPN_IC_MAX * (1 + 1e-6):
            bad("npn_abs_max", f"{ref} IC {_fmt(abs(ic), 'A')} > {NPN_IC_MAX * 1e3:g} mA")
        if abs(ib) > NPN_IB_MAX * (1 + 1e-6):
            bad("npn_abs_max", f"{ref} IB {_fmt(abs(ib), 'A')} > {NPN_IB_MAX * 1e3:g} mA")
        if 0 <= vce <= NPN_SAT_VCE and ic >= NPN_SAT_IC_MIN:
            beta = ic / ib if ib > 1e-12 else math.inf
            if beta > NPN_FORCED_BETA_MAX * (1 + 1e-6):
                bad("npn_saturation", f"{ref} saturated switch with forced beta IC/IB = {_fmt(ic, 'A')}/"
                                      f"{_fmt(ib, 'A')} = {beta:.3g} > {NPN_FORCED_BETA_MAX:g}")
    for ref, c in _comps(design, "LED_"):
        ia = i.get(f"{ref}.A", 0.0)
        lim = LED_IF_MAX_A.get(c["footprint"], min(LED_IF_MAX_A.values())) * LED_DERATING
        if ia > lim * (1 + 1e-6):
            bad("led_current", f"{ref} forward current {_fmt(ia, 'A')} > {_fmt(lim, 'A')} "
                               f"(80 % of the {c['footprint'].split(':')[1]} rating)")
        vr = v[f"{ref}.K"] - v[f"{ref}.A"]
        if vr > LED_VR_MAX + 1e-6:
            bad("led_reverse", f"{ref} reverse voltage {vr:.3g} V > {LED_VR_MAX:g} V")
    for ref, c in _comps(design, "D_SCHOTTKY"):
        ia = i.get(f"{ref}.A", 0.0)
        vr = v[f"{ref}.K"] - v[f"{ref}.A"]
        if vr > SCHOTTKY_VR_MAX + 1e-6:
            bad("diode_ratings", f"{ref} reverse voltage {vr:.3g} V > {SCHOTTKY_VR_MAX:g} V")
        if ia > SCHOTTKY_IF_MAX * (1 + 1e-6):
            bad("diode_ratings", f"{ref} forward current {_fmt(ia, 'A')} > {SCHOTTKY_IF_MAX:g} A")
    for ref, c in _comps(design, "R"):
        if c["part"] != "R":
            continue
        ir = i.get(f"{ref}.1", 0.0)
        try:
            r = parse_value(c["value"])
        except ValueError:
            continue
        p = ir * ir * r
        rating = R_POWER_W.get(c["footprint"])
        if rating is not None and p > rating * R_DERATING * (1 + 1e-6):
            bad("resistor_power", f"{ref} dissipates {p * 1e3:.3g} mW > {rating * R_DERATING * 1e3:.3g} mW "
                                  f"(50 % of {rating:g} W, {c['footprint'].split(':')[1]})")
    for ref, c in _comps(design, "C"):
        if c["part"] != "C":
            continue
        vc = abs(v[f"{ref}.1"] - v[f"{ref}.2"])
        rating = C_VOLTAGE_V.get(c["footprint"])
        if rating is not None and vc > rating * C_DERATING + 1e-6:
            bad("capacitor_voltage", f"{ref} sees {vc:.3g} V > {rating * C_DERATING:g} V "
                                     f"(80 % of {rating:g} V, {c['footprint'].split(':')[1]})")
    return out


FLYBACK_FWD_V = 0.05   # a flyback diode is never forward-biased by more than this in DC


def check_flyback(design: dict, ctx: dict, ops: list[OpPoint] | None = None) -> list[Violation]:
    """Every inductive load needs a D_SCHOTTKY directly across its two terminals (its K and A nets are
    exactly the two nets of the load's pins), cathode on the supply side. v2.1 (QA F5): the load is
    judged by its terminals, not by the connector's pin labels -- a non-polar coil plugged into a
    2-pin connector with pins 1/2 exchanged still has the diode across it. The supply side is the
    side at the higher potential while the load is energised: the diode must not be forward-biased
    (V(A) - V(K) <= FLYBACK_FWD_V) at any DC operating point `ops`; if the load is never energised in
    `ops` (or no ops are given), the cathode must be on the net of the context's supply pin."""
    net_of = {p: n for n, pins in design["nets"].items() for p in pins}
    out = []
    for ld in ctx.get("inductive_loads", []):
        ns, nw = net_of.get(ld["supply_pin"]), net_of.get(ld["switched_pin"])
        ok = False
        if ns is not None and nw is not None and ns != nw:
            for r, _ in _comps(design, "D_SCHOTTKY"):
                k, a = net_of.get(f"{r}.K"), net_of.get(f"{r}.A")
                if {k, a} != {ns, nw}:
                    continue
                rev = [op.v[f"{r}.K"] - op.v[f"{r}.A"] for op in ops or [] if f"{r}.K" in op.v and f"{r}.A" in op.v]
                if any(x < -FLYBACK_FWD_V for x in rev):
                    continue   # conducts while the load is on: across the load, but reversed
                if any(x > FLYBACK_FWD_V for x in rev) or k == ns:
                    ok = True
                    break
        if not ok:
            out.append(Violation("flyback", f"inductive load {ld['supply_pin']}-{ld['switched_pin']} has no flyback "
                                            f"diode across it (a Schottky with one pin on each of the load's two nets, "
                                            f"cathode on the supply side)"))
    return out


def run_rules(design: dict, ctx: dict) -> list[Violation]:
    """All rule violations of `design` under the hidden rule context. Never raises."""
    out: list[Violation] = []
    try:
        ops: list[OpPoint] = []
        for k, sc in enumerate(ctx.get("scenarios", [])):
            try:
                op = operating_point(design, sc)
            except Exception as e:  # noqa: BLE001
                out.append(Violation("simulation", f"operating point {k} does not simulate: {e}"[:300]))
                continue
            ops.append(op)
            out += check_op(design, op, f"condition {k}")
        out = check_flyback(design, ctx, ops) + out
    except Exception as e:  # noqa: BLE001
        out.append(Violation("error", f"rule evaluation error: {type(e).__name__}: {e}"[:300]))
    only = ctx.get("only")
    if only:  # a rule subset (e.g. the all-tier resistor power rule); evaluation failures always count
        out = [x for x in out if x.code in only or x.code in ("simulation", "error")]
    # dedupe (same violation in several scenarios), keep first
    seen, uniq = set(), []
    for x in out:
        key = (x.code, x.detail.rsplit(" [", 1)[0])
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return uniq


# ------------------------------------------------------------------ hard-tier golden preparation
R_SIZES = list(R_POWER_W)
C_SIZES = list(C_VOLTAGE_V)
LED_SIZES = list(LED_IF_MAX_A)


def harden(golden, only: list[str] | None = None):
    """Hard-tier golden: the family golden with every resistor / capacitor / LED footprint upsized
    (smallest-first) until it meets the rules above. Topology and values are unchanged.

    Returns (golden, upsized: dict ref -> (old, new footprint)). Raises ValueError if the golden
    still violates a rule (a family design that breaks a stated datasheet rule)."""
    from copy import deepcopy
    g = deepcopy(golden)
    ctx = rules_context(g, only)
    changed: dict[str, list[str]] = {}
    for _ in range(4):
        viol = run_rules(g.design, ctx)
        fix = False
        for vi in viol:
            ref = vi.detail.split(" ", 1)[0]
            c = g.design["components"].get(ref)
            if c is None:
                continue
            sizes = {"resistor_power": R_SIZES, "capacitor_voltage": C_SIZES, "led_current": LED_SIZES}.get(vi.code)
            if not sizes or c["footprint"] not in sizes:
                continue
            k = sizes.index(c["footprint"])
            if k + 1 < len(sizes):
                changed.setdefault(ref, [c["footprint"], ""])
                c["footprint"] = sizes[k + 1]
                changed[ref][1] = c["footprint"]
                fix = True
        if not fix:
            break
    viol = run_rules(g.design, ctx)
    if viol:
        raise ValueError("golden violates design rules: " + "; ".join(f"{v.code}: {v.detail}" for v in viol))
    return g, {k: tuple(v) for k, v in changed.items()}
