"""Reusable sub-circuit blocks for the composite (hard-tier) families.

A `Composite` wraps a `Builder` and accumulates, per block, the parts/nets, the spec assertions,
value bounds, decoupling requirements, power nets and the intent text (purpose lines, the pin
assignment table rows and component-value notes). Blocks allocate reference designators in order
(`ref("R")` -> R1, R2, ...), so a composite reads like a hand-drawn schematic.

All stimulus comes from the assertions (supply on the input connector, GPIO drive as a 50-ohm
source on the MCU pin, loads on connectors), exactly as in the v1 families. Every block's sizing
follows the generic part datasheets (`pcbenv/parts_lib.py`), and its value bounds follow the
`Bounds` policy (never tighter than a datasheet limit).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from pcbenv.families._common import (BULK, DECOUPLING, E6, E12, E24, E96, NRST_PULLUP, RESET_CAP, Bounds, Builder, band,
                                     led_r_min, nearest, pick, series_values, sig2_up)
from pcbenv.golden import Golden
from pcbenv.parts_lib import (GPIO_IMAX, I2C_K_RISE, I2C_RISE_LEVELS, I2C_SINK_MAX, I2C_VOL, LDO_VREF, MCU_PIN_C,
                              NMOS_GATE_PULLDOWN, NPN_BASE_PULLDOWN, led_vf)

VF10 = {"LED_RED": 2.0, "LED_GREEN": 2.2}
GPIO_R = 50.0                       # MCU8 GPIO output resistance (datasheet: ~50 ohm)
R_FP = ["Resistor_SMD:R_0603_1608Metric", "Resistor_SMD:R_0805_2012Metric", "Resistor_SMD:R_1206_3216Metric"]
C_FP = ["Capacitor_SMD:C_0603_1608Metric", "Capacitor_SMD:C_0805_2012Metric", "Capacitor_SMD:C_1206_3216Metric"]
# footprint ratings used by the hard-tier design rules (pcbenv/rules.py): resistor power (W) and
# capacitor voltage (V), both derated; goldens always pick a footprint with margin
R_POWER = {R_FP[0]: 0.100, R_FP[1]: 0.125, R_FP[2]: 0.500}
C_VOLT = {C_FP[0]: 10.0, C_FP[1]: 25.0, C_FP[2]: 50.0}


def fmt_v(v: float) -> str:
    return f"{v:g} V"


def rail_name(v: float) -> str:
    return "+" + (f"{v:g}".replace(".", "V") if v % 1 else f"{v:g}V")


@dataclass
class Composite:
    family: str
    seed: int
    title: str
    rng: random.Random
    b: Builder = None  # type: ignore[assignment]
    vb: Bounds = None  # type: ignore[assignment]
    assertions: list[dict] = field(default_factory=list)
    decoupling: list[dict] = field(default_factory=list)
    power_nets: dict[str, float] = field(default_factory=dict)
    purpose: list[str] = field(default_factory=list)        # intent bullet lines (connection detail)
    groups: list[tuple[str, list[str]]] = field(default_factory=list)  # sub-circuits by purpose
    connectors: list[tuple[str, str, str]] = field(default_factory=list)  # (ref, pin, signal)
    mcu_pins: list[tuple[str, str]] = field(default_factory=list)       # (pin, function)
    values: list[str] = field(default_factory=list)          # component-value requirement notes
    spec: list[str] = field(default_factory=list)            # spec lines
    params: dict = field(default_factory=dict)
    roles: dict[str, list[str]] = field(default_factory=dict)  # fault-injector roles (faults/values.py)
    _n: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.b = Builder(self.title, self.rng)
        self.vb = Bounds(self.family, self.seed)

    # ------------------------------------------------------------ helpers
    def ref(self, prefix: str) -> str:
        self._n[prefix] = self._n.get(prefix, 0) + 1
        return f"{prefix}{self._n[prefix]}"

    def resistor(self, value: float, power_w: float = 0.0) -> str:
        """A resistor whose footprint keeps I^2 R <= 40 % of its rating."""
        ok = [fp for fp in R_FP if power_w <= 0.4 * R_POWER[fp]]
        return self.b.add(self.ref("R"), "R", value, pick(self.rng, ok))

    def capacitor(self, value: float, v_max: float) -> str:
        """A ceramic capacitor whose footprint is rated >= 1.6x the highest voltage across it."""
        ok = [fp for fp in C_FP if v_max <= 0.6 * C_VOLT[fp]]
        return self.b.add(self.ref("C"), "C", value, pick(self.rng, ok))

    def role(self, name: str, *refs: str) -> None:
        self.roles.setdefault(name, []).extend(r for r in refs if r)

    def power(self, net: str, w: float) -> None:
        self.power_nets[net] = max(w, self.power_nets.get(net, 0.0))

    def stim(self, vin: float, **kw) -> dict:
        d = {"supply": {"pin": "J1.1", "volts": vin}, "ground_pin": "J1.2"}
        d.update(kw)
        return d

    def golden(self, intent_head: str, board: tuple[float, float]) -> Golden:
        from pcbenv.families._common import MAX_PATH_MM_COMPOSITE, check_bounds, parts_summary, with_path_limit
        design = self.b.design()
        vb = {k: list(v) for k, v in sorted(self.vb.out.items())}
        check_bounds(design, vb)
        conn = "\n".join(f"| {r} | {p} | {s} |" for r, p, s in self.connectors)
        mcu = "\n".join(f"| {p} | {f} |" for p, f in self.mcu_pins)
        intent = intent_head.strip() + "\n\n"
        intent += "## Connectors\n\n| Connector | Pin | Signal |\n|---|---|---|\n" + conn + "\n\n"
        if self.mcu_pins:
            intent += ("## MCU pin assignment (firmware-fixed)\n\n| MCU pin | Function |\n|---|---|\n" + mcu + "\n\n")
        intent += "## Circuit\n\n" + "\n".join(self.purpose) + "\n\n"
        # spec lines are plain paragraphs (not "- " bullets): the reduced intent of symptom / vague
        # tasks drops bullets (connection details) but must keep the whole spec
        intent += "## Spec\n\n" + "\n\n".join(x[2:] if x.startswith("- ") else x for x in self.spec) + "\n\n"
        intent += "Component values: " + "; ".join(self.values) + ".\n\n"
        intent += parts_summary(self.groups) + "\n"
        self.params["parts"] = len(design["components"])
        self.params["roles"] = {k: list(v) for k, v in sorted(self.roles.items())}
        if self.vb.limits:
            self.params["datasheet_limits"] = {k: list(v) for k, v in sorted(self.vb.limits.items())}
        return Golden(family=self.family, seed=self.seed, design=design, assertions=self.assertions,
                      power_nets=dict(sorted(self.power_nets.items())), decoupling=with_path_limit(self.decoupling, MAX_PATH_MM_COMPOSITE), intent=intent,
                      params=self.params, board_w_mm=float(board[0]), board_h_mm=float(board[1]), value_bounds=vb)


# ---------------------------------------------------------------- blocks

def input_protection(c: Composite, jref: str, vin: float, bulk: bool) -> str:
    """Series Schottky (anode to the connector) against reverse polarity, optional bulk capacitor
    after it. Returns the protected input net name."""
    d = c.b.add(c.ref("D"), "D_SCHOTTKY")
    c.b.net("VIN_RAW", f"{jref}.1", f"{d}.A")
    c.b.net("VIN", f"{d}.K")
    refs = [d]
    if bulk:
        cb = c.capacitor(pick(c.rng, [4.7e-6, 10e-6, 22e-6]), vin)
        c.b.net("VIN", f"{cb}.1")
        c.b.net("GND", f"{cb}.2")
        c.vb.fixed(cb, *BULK)
        refs.append(cb)
        c.values.append(f"input bulk capacitor {cb} 1 µF–22 µF")
    c.purpose.append(f"- Reverse-polarity protection: Schottky {d} in series with the input, anode to {jref} pin 1, "
                     f"cathode to the protected input rail VIN" + (f"; {refs[1]} is a bulk capacitor on VIN." if bulk else "."))
    c.groups.append(("input reverse-polarity protection" + (" and bulk capacitor" if bulk else ""), refs))
    c.power("VIN_RAW", 0.3)
    return "VIN"


def ldo(c: Composite, vin: float, vout: float, vin_net: str, rail: str, drop: float = 0.0) -> dict:
    """LDO_ADJ from `vin_net` to `rail`: input/output caps at the pins, FB divider, EN to VIN (or a
    pull-up). The rail assertions are added by `rail_assertions` once the load pin exists."""
    rng, b = c.rng, c.b
    u = b.add(c.ref("U"), "LDO_ADJ")
    cin = c.capacitor(pick(rng, [1e-6, 2.2e-6, 4.7e-6, 10e-6]), vin)
    cout = c.capacitor(pick(rng, [1e-6, 2.2e-6, 4.7e-6, 10e-6]), vout)
    rbot = pick(rng, series_values(E96, 10e3, 49.9e3))
    rt, rb = c.ref("R"), c.ref("R")
    b.add(rt, "R", nearest(E96, rbot * (vout / LDO_VREF - 1)), pick(rng, R_FP))
    b.add(rb, "R", rbot, pick(rng, R_FP))
    en_pull = rng.random() < 0.35
    b.net(vin_net, f"{u}.VIN", f"{cin}.1")
    b.net("GND", f"{u}.GND", f"{cin}.2", f"{cout}.2", f"{rb}.2")
    b.net(rail, f"{u}.VOUT", f"{cout}.1", f"{rt}.1")
    b.net(f"FB_{u}", f"{rt}.2", f"{rb}.1", f"{u}.FB")
    vin_min = round(max(vout + 0.6, 2.5) + drop, 3)   # `drop`: series protection diode ahead of the LDO
    ren = None
    if en_pull:
        ren = c.resistor(pick(rng, series_values(E6, 10e3, 470e3)))
        b.net(vin_net, f"{ren}.1")
        b.net(f"EN_{u}", f"{ren}.2", f"{u}.EN")
        c.vb.fixed(ren, 1.0, max(1e6, sig2_up(2e6 * (vin_min / 1.2 - 1))))
    else:
        b.net(vin_net, f"{u}.EN")
    vact = LDO_VREF * (1 + b.val(rt) / b.val(rb))
    c.role("feedback", rt, rb)
    c.role("pull", ren)
    c.decoupling += [{"cap": cin, "ic_pin": f"{u}.VIN", "max_mm": 5.0}, {"cap": cout, "ic_pin": f"{u}.VOUT", "max_mm": 5.0}]
    c.vb.fixed(cin, *BULK)
    c.vb.fixed(cout, *BULK)
    k = vout / LDO_VREF - 1
    c.vb.fixed(rb, 3.3e3, 150e3)
    c.vb.fixed(rt, float(f"{3.3e3 * k:.2g}"), float(f"{150e3 * k:.2g}"))
    en_txt = (f"EN is pulled up to the input through {ren}" if ren else "EN is tied to the input (always on)")
    c.purpose += [f"- {u} (LDO_ADJ) regulates the {fmt_v(vin)} input down to the {fmt_v(vout)} rail {rail}: {cin} is "
                  f"its input capacitor (VIN to GND) and {cout} its output capacitor (VOUT to GND), each at its pin; "
                  f"{rt} from VOUT to FB and {rb} from FB to GND set VOUT = 0.8 V x (1 + {rt}/{rb}); {en_txt}."]
    c.groups.append((f"{fmt_v(vout)} regulator with input/output capacitors and feedback divider",
                     [u, cin, cout, rt, rb] + ([ren] if ren else [])))
    c.values.append(f"{cin}, {cout} 1 µF–22 µF (LDO datasheet); feedback Rbot {rb} 3.3 kΩ–150 kΩ (10k–50k typical) "
                    f"with {rt} scaled to match" + (f"; EN pull-up {ren} keeps EN above 1.2 V at the lowest input" if ren else ""))
    return {"u": u, "cin": cin, "cout": cout, "rt": rt, "rb": rb, "vout_nominal": round(vact, 4), "vin_min": vin_min,
            "vin": vin, "vout": vout, "rail": rail}


def rail_assertions(c: Composite, reg: dict, load_pin: str, i_ext: float, what: str) -> None:
    """Rail voltage ±3 % at `load_pin` with an off-board load `i_ext` there, at the nominal and at
    the minimum input voltage (on top of the board's own consumption)."""
    vout = reg["vout"]
    loads = [{"pin": load_pin, "r": round(vout / i_ext, 3)}] if i_ext > 0 else []
    tag = rail_name(vout)[1:].lower()
    for name, v in (("rail", reg["vin"]), ("rail_low_vin", reg["vin_min"])):
        c.assertions.append({"name": f"{tag}_{name}", "type": "dc_voltage", "net_pin": load_pin, **band(vout, 0.03),
                             **c.stim(v, **({"loads": loads} if loads else {}))})
    ref, pin = load_pin.split(".")
    c.spec.append(f"- Rail {reg['rail']}: {fmt_v(vout)} ±3 % with {i_ext*1e3:.0f} mA drawn by {what} from {ref} pin "
                  f"{pin}, for inputs from {reg['vin_min']:g} V to {reg['vin']:g} V.")


def mcu(c: Composite, vdd: float, rail: str) -> dict:
    """MCU8 with VDD decoupling at the pin, NRST pull-up (+ optional reset-delay cap)."""
    rng, b = c.rng, c.b
    u = b.add(c.ref("U"), "MCU8")
    cd = c.capacitor(pick(rng, [100e-9, 100e-9, 100e-9, 1e-6]), vdd)
    rn = c.resistor(pick(rng, series_values(E24, 4.7e3, 47e3)))
    b.net(rail, f"{u}.VDD", f"{cd}.1", f"{rn}.1")
    b.net("GND", f"{u}.GND", f"{cd}.2")
    b.net(f"NRST_{u}", f"{rn}.2", f"{u}.NRST")
    crst = None
    if rng.random() < 0.5:
        crst = c.capacitor(100e-9, vdd)
        b.net(f"NRST_{u}", f"{crst}.1")
        b.net("GND", f"{crst}.2")
        c.vb.fixed(crst, *RESET_CAP)
    c.decoupling.append({"cap": cd, "ic_pin": f"{u}.VDD", "max_mm": 5.0})
    c.vb.fixed(cd, *DECOUPLING)
    c.vb.fixed(rn, *NRST_PULLUP)
    c.role("pull", rn)
    st = c.stim(c.params["vin"])
    c.assertions += [
        {"name": "mcu_vdd", "type": "dc_voltage", "net_pin": f"{u}.VDD", "ref_pin": f"{u}.GND",
         "min": round(vdd * 0.97, 4), "max": round(vdd * 1.03, 4), **st},
        {"name": "nrst_high", "type": "dc_voltage", "net_pin": f"{u}.NRST", "min": round(vdd * 0.9, 4),
         "max": round(vdd * 1.04, 4), **st},
    ]
    c.mcu_pins += [("VDD", f"supply, {rail} rail"), ("GND", "ground"), ("NRST", "reset input, held high (no internal pull-up)")]
    c.purpose.append(f"- {u} (MCU8) runs from {rail}; {cd} decouples VDD at the pin; {rn} pulls NRST up to {rail}"
                     + (f" and {crst} from NRST to GND gives a power-on reset delay." if crst else "."))
    c.groups.append(("MCU with VDD decoupling and reset pull-up" + (" / reset delay" if crst else ""),
                     [u, cd, rn] + ([crst] if crst else [])))
    c.spec.append(f"- MCU supply {fmt_v(vdd)} ±3 % at its VDD/GND pins; NRST ≥ 0.9·VDD.")
    c.values.append(f"MCU decoupling {cd} 47 nF–10 µF (100 nF typical); NRST pull-up {rn} 2.2 kΩ–100 kΩ"
                    + (f"; reset delay {crst} 10 nF–1 µF" if crst else ""))
    return {"u": u, "cdec": cd, "rnrst": rn}


def i2c(c: Composite, u: str, vdd: float, rail: str, header_rail_pin: bool = True) -> dict:
    """I2C pull-ups for SDA/SCL to `rail` and a 4-pin bus header (VDD, GND, SDA, SCL)."""
    rng, b = c.rng, c.b
    while True:
        mode = pick(rng, ["standard", "fast"])
        tr_max = 1000e-9 if mode == "standard" else 300e-9
        cbus = pick(rng, [30e-12, 50e-12, 100e-12, 150e-12, 200e-12, 300e-12, 400e-12])
        ctot = cbus + MCU_PIN_C
        rmin = (vdd - I2C_VOL) / I2C_SINK_MAX
        rmax = tr_max / (I2C_K_RISE * ctot)
        cands = [r for r in series_values(E24, 100.0, 100e3) if max(rmin * 1.05, 0.55 * rmax) <= r <= 0.85 * rmax]
        if cands:
            break
    rp = pick(rng, cands)
    j = b.add(c.ref("J"), "CONN4")
    rsda, rscl = c.resistor(rp), c.resistor(rp)
    b.net(rail, f"{rsda}.1", f"{rscl}.1", f"{j}.1")
    b.net("GND", f"{j}.2")
    b.net("SDA", f"{u}.SDA", f"{rsda}.2", f"{j}.3")
    b.net("SCL", f"{u}.SCL", f"{rscl}.2", f"{j}.4")
    sup = c.stim(c.params["vin"])
    bus = [{"pin": f"{j}.3", "c": cbus}, {"pin": f"{j}.4", "c": cbus}]
    for line, pin, r in (("sda", f"{u}.SDA", rsda), ("scl", f"{u}.SCL", rscl)):
        c.assertions.append({"name": f"{line}_rise_time", "type": "rise_time", "net_pin": pin, "min": 0.0, "max": tr_max,
                             "levels": list(I2C_RISE_LEVELS), "tstop": round(8 * tr_max, 12), **sup, "loads": bus,
                             "source": {"pin": pin, "kind": "release", "r_on": 10.0}})
        c.assertions.append({"name": f"{line}_sink_current", "type": "dc_current", "element": r, "min": 0.0,
                             "max": I2C_SINK_MAX, **sup, "source": {"pin": pin, "dc": I2C_VOL, "r": 1e-3}})
        c.vb.spec(r, rp, ds_lo=rmin, ds_hi=rmax)
    c.role("pull", rsda, rscl)
    c.connectors += [(j, "1", f"{rail} (bus supply)"), (j, "2", "GND"), (j, "3", "SDA"), (j, "4", "SCL")]
    c.mcu_pins += [("SDA", f"I2C data -> {j} pin 3"), ("SCL", f"I2C clock -> {j} pin 4")]
    c.purpose.append(f"- I2C: SDA ({u}.SDA -> {j}.3) and SCL ({u}.SCL -> {j}.4) are open-drain with pull-ups "
                     f"{rsda} (SDA) and {rscl} (SCL) to {rail}; {j} pin 1 supplies {rail} to the off-board devices.")
    c.groups.append(("I2C bus pull-ups and bus header", [rsda, rscl, j]))
    c.spec.append(f"- I2C {mode}-mode, up to {cbus*1e12:.0f} pF off-board capacitance per line (+5 pF pin): rise "
                  f"time (30–70 % of VDD, UM10204) ≤ {tr_max*1e9:.0f} ns; pull-up current ≤ 3 mA at VOL = 0.4 V.")
    c.values.append(f"I2C pull-ups {rsda}, {rscl} within the datasheet range (VDD-0.4 V)/3 mA .. tr/(0.8473·Cbus) "
                    f"that meets the spec")
    c.params.update(i2c_mode=mode, cbus_pf=round(cbus * 1e12), rpullup=rp)
    return {"j": j, "rsda": rsda, "rscl": rscl}


def led_gpio(c: Composite, u: str, pin: str, vdd: float, what: str) -> dict:
    """GPIO -> series resistor -> LED -> GND, 2-5 mA."""
    rng, b = c.rng, c.b
    d = b.add(c.ref("D"), pick(rng, ["LED_RED", "LED_GREEN"]))
    vf10 = VF10[b.components[d]["part"]]
    it = pick(rng, [2e-3, 3e-3, 4e-3, 5e-3])
    r = c.resistor(nearest(E24, (vdd - led_vf(vf10, it)) / it - GPIO_R))
    b.net(f"LED_{pin}", f"{u}.{pin}", f"{r}.1")
    b.net(f"LED_{d}_A", f"{r}.2", f"{d}.A")
    b.net("GND", f"{d}.K")
    i_act = _led_current(vdd, b.val(r) + GPIO_R, vf10)
    c.assertions.append({"name": f"{what}_led_current", "type": "dc_current", "element": d, **band(i_act, 0.15),
                         **c.stim(c.params["vin"], source={"pin": f"{u}.{pin}", "dc": vdd, "r": GPIO_R})})
    c.vb.spec(r, b.val(r), ds_lo=led_r_min(vdd, 1, vf10, i_max=GPIO_IMAX))
    c.role("led_res", r)
    c.mcu_pins.append((pin, f"{what} LED drive (push-pull, high = on)"))
    c.purpose.append(f"- {pin} drives the {what} LED {d} through {r} ({u}.{pin} -> {r} -> {d} anode, cathode to GND).")
    c.groups.append((f"{what} LED with series resistor", [d, r]))
    c.spec.append(f"- {what.capitalize()} LED current {i_act*1e3:.2f} mA ±15 % with {pin} high.")
    return {"d": d, "r": r}


def led_rail(c: Composite, rail: str, vrail: float, what: str) -> dict:
    """Always-on indicator: rail -> resistor -> LED -> GND, 1-3 mA."""
    rng, b = c.rng, c.b
    d = b.add(c.ref("D"), pick(rng, ["LED_RED", "LED_GREEN"]))
    vf10 = VF10[b.components[d]["part"]]
    it = pick(rng, [1e-3, 2e-3, 3e-3])
    rv = nearest(E24, (vrail - led_vf(vf10, it)) / it)
    r = c.resistor(rv, it * it * rv)
    b.net(rail, f"{r}.1")
    b.net(f"LED_{d}_A", f"{r}.2", f"{d}.A")
    b.net("GND", f"{d}.K")
    i_act = _led_current(vrail, b.val(r), vf10)
    c.assertions.append({"name": f"{what}_led_current", "type": "dc_current", "element": d, **band(i_act, 0.15),
                         **c.stim(c.params["vin"])})
    c.vb.spec(r, b.val(r), ds_lo=led_r_min(vrail, 1, vf10))
    c.role("led_res", r)
    c.purpose.append(f"- {what} indicator: {r} from {rail} to the anode of {d}, cathode to GND.")
    c.groups.append((f"{what} indicator LED with series resistor", [d, r]))
    c.spec.append(f"- {what.capitalize()} indicator current {i_act*1e3:.2f} mA ±15 %.")
    return {"d": d, "r": r, "i": i_act, "vf10": vf10}


def led_npn(c: Composite, u: str, pin: str, vdd: float, vsup: float, sup_net: str, what: str) -> dict:
    """GPIO -> base resistor -> NPN low-side switch for an LED fed from `sup_net` (5-15 mA)."""
    rng, b = c.rng, c.b
    q = b.add(c.ref("Q"), "NPN")
    d = b.add(c.ref("D"), pick(rng, ["LED_RED", "LED_GREEN"]))
    vf10 = VF10[b.components[d]["part"]]
    ic = pick(rng, [5e-3, 8e-3, 10e-3, 12e-3])
    rlv = nearest(E24, (vsup - led_vf(vf10, ic) - 0.05) / ic)
    rl = c.resistor(rlv, ic * ic * rlv)
    ib = ic / 10
    rbv = nearest(E24, (vdd - 0.75) / ib - GPIO_R)
    rbase = c.resistor(rbv)
    rpd = c.resistor(pick(rng, series_values(E24, 10e3, 100e3)))
    b.net(sup_net, f"{rl}.1")
    b.net(f"LED_{d}_A", f"{rl}.2", f"{d}.A")
    b.net(f"SW_{q}", f"{d}.K", f"{q}.C")
    b.net("GND", f"{q}.E", f"{rpd}.2")
    b.net(f"CTRL_{pin}", f"{u}.{pin}", f"{rbase}.1")
    b.net(f"BASE_{q}", f"{rbase}.2", f"{q}.B", f"{rpd}.1")
    i_act = _led_current(vsup - 0.05, b.val(rl), vf10)
    on = c.stim(c.params["vin"], source={"pin": f"{u}.{pin}", "dc": vdd, "r": GPIO_R})
    off = c.stim(c.params["vin"], loads=[{"pin": f"{q}.B", "to": f"{u}.VDD", "r": 1e6}])
    c.assertions += [
        {"name": f"{what}_led_on_current", "type": "dc_current", "element": d, **band(i_act, 0.15), **on},
        {"name": f"{what}_vce_sat", "type": "dc_voltage", "net_pin": f"{q}.C", "ref_pin": f"{q}.E", "min": 0.0, "max": 0.3, **on},
        {"name": f"{what}_gpio_current", "type": "dc_current", "element": rbase, "min": 0.0, "max": GPIO_IMAX, **on},
        {"name": f"{what}_led_off_current", "type": "dc_current", "element": d, "min": 0.0, "max": 1e-4, **off},
    ]
    c.vb.spec(rl, b.val(rl), ds_lo=led_r_min(vsup, 1, vf10, v_switch=0.05))
    c.vb.spec(rbase, b.val(rbase), ds_lo=(vdd - 0.75) / GPIO_IMAX)
    c.vb.fixed(rpd, 4.7e3, 220e3)
    c.role("led_res", rl)
    c.role("pull", rpd)
    c.role("base_res", rbase)   # not a v1 fault role; listed for audits
    c.mcu_pins.append((pin, f"{what} LED switch drive (high = on, high-impedance in reset)"))
    c.purpose.append(f"- {what.capitalize()} LED {d} is fed from {sup_net} through {rl} and switched on its cathode by "
                     f"NPN {q} (emitter to GND); {pin} drives the base through {rbase} (forced beta about 10, GPIO "
                     f"under 8 mA) and {rpd} pulls the base to GND so the LED is off while {pin} floats.")
    c.groups.append((f"{what} LED switched by an NPN transistor (base resistor, base pull-down, LED resistor)",
                     [q, rbase, rpd, d, rl]))
    c.spec.append(f"- {what.capitalize()} LED: {i_act*1e3:.1f} mA ±15 % with {pin} high, {q} saturated (VCE ≤ 0.3 V), "
                  f"GPIO current ≤ 8 mA; off (< 0.1 mA) with {pin} floating even with 1 MΩ leakage from VDD "
                  f"into the base.")
    c.values.append(f"base pull-down {rpd} 4.7 kΩ–220 kΩ (datasheet: 10k–100k)")
    return {"q": q, "d": d, "rl": rl, "rbase": rbase, "rpd": rpd}


def adc_divider(c: Composite, u: str, pin: str, vdd: float, what: str) -> dict:
    """Sense connector -> divider -> anti-alias cap -> MCU ADC pin (90 % of full scale at vmax)."""
    rng, b = c.rng, c.b
    vmax = pick(rng, [v for v in (5.0, 9.0, 12.0, 15.0, 24.0, 30.0) if v > vdd * 1.2])
    f_aa = pick(rng, [10.0, 50.0, 100.0, 500.0])
    ratio_t = 0.9 * vdd / vmax
    j = b.add(c.ref("J"), "CONN2")
    rbot = pick(rng, series_values(E96, 10e3, 100e3))
    r1, r2 = c.ref("R"), c.ref("R")
    b.add(r1, "R", nearest(E96, rbot * (1 / ratio_t - 1)), pick(rng, R_FP))
    b.add(r2, "R", rbot, pick(rng, R_FP))
    rv1, rv2 = b.val(r1), b.val(r2)
    rth = rv1 * rv2 / (rv1 + rv2)
    ca = c.capacitor(nearest(E12, 1 / (2 * math.pi * rth * f_aa)), vdd)
    cv = b.val(ca)
    b.net(f"SENSE_{j}", f"{j}.1", f"{r1}.1")
    b.net("GND", f"{j}.2", f"{r2}.2", f"{ca}.2")
    b.net(f"ADC_{pin}", f"{r1}.2", f"{r2}.1", f"{ca}.1", f"{u}.{pin}")
    from pcbenv.families._common import cutoff_of

    def h(s: complex) -> complex:
        return (rv2 / (rv1 + rv2)) / (1 + s * rth * (cv + MCU_PIN_C))

    fc = cutoff_of(h, "high")
    st = c.stim(c.params["vin"])
    c.assertions += [
        {"name": f"{what}_full_scale", "type": "dc_voltage", "net_pin": f"{u}.{pin}", **band(ratio_t * vmax, 0.02),
         **st, "source": {"pin": f"{j}.1", "dc": vmax}},
        {"name": f"{what}_half_scale", "type": "dc_voltage", "net_pin": f"{u}.{pin}", **band(ratio_t * vmax / 2, 0.02),
         **st, "source": {"pin": f"{j}.1", "dc": vmax / 2}},
        {"name": f"{what}_anti_alias_corner", "type": "cutoff", "in_pin": f"{j}.1", "out_pin": f"{u}.{pin}",
         "edge": "high", **band(fc, 0.10), **st, "source": {"pin": f"{j}.1", "ac": 1.0}},
    ]
    c.vb.spec(r1, rv1)
    c.vb.spec(r2, rv2)
    c.vb.spec(ca, cv)
    c.role("feedback", r1, r2)
    c.role("filter_cap", ca)
    c.connectors += [(j, "1", f"{what} input, 0–{vmax:g} V"), (j, "2", "GND")]
    c.mcu_pins.append((pin, f"ADC input: {what} (scaled so {vmax:g} V reads 90 % of full scale)"))
    c.purpose.append(f"- {what.capitalize()} input: {r1} from {j} pin 1 to the ADC node, {r2} from the ADC node to "
                     f"GND, {ca} from the ADC node to GND (anti-alias); the ADC node goes to {u}.{pin}.")
    c.groups.append((f"{what} scaling divider with anti-alias capacitor", [r1, r2, ca]))
    c.groups.append((f"{what} input connector", [j]))
    c.spec.append(f"- {what.capitalize()}: {u}.{pin} = {ratio_t:.4f} × input ±2 % ({vmax:g} V -> {ratio_t*vmax:.3g} V); "
                  f"anti-alias -3 dB corner {fc:.4g} Hz ±10 %.")
    c.params.update({f"{what}_vmax": vmax, f"{what}_fc_hz": round(fc, 3)})
    return {"j": j, "r1": r1, "r2": r2, "c": ca}


def _led_current(v: float, r: float, vf10: float) -> float:
    """Solve (v - Vf(i)) / r = i for the LED model (bisection)."""
    lo, hi = 1e-7, max(1e-6, v / r)
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        if (v - led_vf(vf10, mid)) / r > mid:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


__all__ = ["Composite", "input_protection", "ldo", "rail_assertions", "mcu", "i2c", "led_gpio", "led_rail", "led_npn", "adc_divider", "rail_name", "fmt_v",
           "GPIO_R", "VF10", "NMOS_GATE_PULLDOWN", "NPN_BASE_PULLDOWN", "E6", "E12", "E24", "E96", "BULK", "band", "pick",
           "nearest", "series_values"]


def hard_board(n_parts: int, scale: float = 1.0) -> tuple[float, float]:
    """Board size for a composite with `n_parts` parts (routing room for 2-layer escape)."""
    w = min(90.0, max(50.0, round((28 + 1.5 * n_parts) * scale)))
    h = min(70.0, max(40.0, round((22 + 1.0 * n_parts) * scale)))
    return float(w), float(h)


def ldo_budget(vin: float, vout: float, i_board: float, choices: list[float]) -> list[float]:
    """Off-board load currents that keep the LDO dissipation (VIN-VOUT)*I under 0.4 W (datasheet
    0.5 W) and the output current under 250 mA (datasheet 300 mA)."""
    return [i for i in choices if (vin - vout) * (i + i_board) <= 0.4 and i + i_board <= 0.25] or [min(choices)]


def lowside_motor(c: Composite, u: str, pwm_pin: str, adc_pin: str, vdd: float, vmot: float, vmot_net: str) -> dict:
    """MCU PWM -> gate resistor -> logic-level NMOS low-side switch for an off-board DC motor (R+L)
    with a Schottky flyback clamp across the motor connector, gate pull-down, a current-sense shunt
    in the source leg and an RC filter from the shunt into an ADC pin, plus a bulk capacitor."""
    rng, b = c.rng, c.b
    iload = pick(rng, [0.2, 0.3, 0.5, 0.75, 1.0])
    rs_v = pick(rng, [r for r in (0.1, 0.15, 0.22, 0.33, 0.47) if iload * iload * r <= 0.2 and iload * r <= 0.35])
    rmot = round(vmot / iload - rs_v - 0.15, 3)
    jm = b.add(c.ref("J"), "CONN2")
    q = b.add(c.ref("Q"), "NMOS")
    d = b.add(c.ref("D"), "D_SCHOTTKY", footprint="Diode_SMD:D_SMA" if iload > 0.5 else None)
    rg = c.resistor(pick(rng, series_values(E24, 10.0, 100.0)))
    rpd = c.resistor(pick(rng, series_values(E24, 10e3, 100e3)))
    rs = b.add(c.ref("R"), "R", rs_v, R_FP[2])
    rf = c.resistor(pick(rng, series_values(E24, 1e3, 10e3)))
    f_s = pick(rng, [100.0, 200.0, 500.0, 1000.0])
    cf = c.capacitor(nearest(E12, 1 / (2 * math.pi * b.val(rf) * f_s)), vdd)
    cb = c.capacitor(pick(rng, [4.7e-6, 10e-6, 22e-6]), vmot)
    b.net(vmot_net, f"{jm}.1", f"{d}.K", f"{cb}.1")
    b.net("GND", f"{cb}.2", f"{rs}.2", f"{rpd}.2", f"{cf}.2")
    b.net("MOTOR_SW", f"{jm}.2", f"{q}.D", f"{d}.A")
    b.net("ISENSE", f"{q}.S", f"{rs}.1", f"{rf}.1")
    b.net(f"PWM_{pwm_pin}", f"{u}.{pwm_pin}", f"{rg}.1")
    b.net("GATE", f"{rg}.2", f"{q}.G", f"{rpd}.1")
    b.net(f"ADC_{adc_pin}", f"{rf}.2", f"{cf}.1", f"{u}.{adc_pin}")
    rfv, cfv = b.val(rf), b.val(cf)
    fc = 1 / (2 * math.pi * rfv * (cfv + MCU_PIN_C))
    motor = {"pin": f"{jm}.1", "to": f"{jm}.2", "r": rmot, "l": 0.005}
    on = c.stim(c.params["vin"], source={"pin": f"{u}.{pwm_pin}", "dc": vdd, "r": GPIO_R}, loads=[motor])
    off = c.stim(c.params["vin"], loads=[motor, {"pin": f"{q}.G", "to": "J1.1", "r": 10e6}])
    vds_max = round(max(0.1, iload * 0.4), 3)
    c.assertions += [
        {"name": "motor_on_current", "type": "dc_current", "element": f"{jm}.2", **band(iload, 0.05), **on},
        {"name": "vds_on", "type": "dc_voltage", "net_pin": f"{q}.D", "ref_pin": f"{q}.S", "min": 0.0, "max": vds_max, **on},
        {"name": "motor_off_current", "type": "dc_current", "element": f"{jm}.2", "min": 0.0, "max": 1e-4, **off},
        {"name": "gate_drive_current", "type": "dc_current", "element": rg, "min": 0.0, "max": 1e-3, **on},
        {"name": "current_sense_voltage", "type": "dc_voltage", "net_pin": f"{u}.{adc_pin}", **band(iload * rs_v, 0.07), **on},
        {"name": "current_sense_corner", "type": "cutoff", "in_pin": f"{rs}.1", "out_pin": f"{u}.{adc_pin}", "edge": "high",
         **band(fc, 0.10), **c.stim(c.params["vin"], source={"pin": f"{rs}.1", "ac": 1.0})},
    ]
    c.vb.fixed(rg, 4.7, 220.0)
    c.vb.fixed(rpd, 4.7e3, 220e3)
    c.vb.spec(rs, rs_v)
    c.vb.spec(rf, rfv)
    c.vb.spec(cf, cfv)
    c.vb.fixed(cb, *BULK)
    c.role("pull", rpd)
    c.role("filter_cap", cf)
    w = 0.5 if iload > 0.5 else 0.4
    for n in (vmot_net, "MOTOR_SW", "ISENSE", "GND"):
        c.power(n, w)
    c.connectors += [(jm, "1", f"motor + (+{vmot:g} V)"), (jm, "2", "motor - (switched return)")]
    c.mcu_pins += [(pwm_pin, "PWM motor drive (high = motor on)"),
                   (adc_pin, f"ADC input: motor current sense, V = I x {rs_v:g} Ω")]
    c.purpose += [
        f"- Motor switch: logic-level NMOS {q} with its source on the sense node ISENSE and its drain on the switched "
        f"motor return ({jm} pin 2); {pwm_pin} drives the gate through {rg} and {rpd} pulls the gate to GND so the motor "
        f"is off while the MCU is in reset; Schottky {d} clamps the motor's inductive kick: cathode to {jm} pin 1 "
        f"(+{vmot:g} V), anode to {jm} pin 2; {cb} is the bulk capacitor across the motor supply.",
        f"- Current sense: shunt {rs} from ISENSE to GND; {rf} from ISENSE to {u}.{adc_pin} with {cf} from "
        f"{u}.{adc_pin} to GND filters the sense voltage.",
    ]
    c.groups += [("motor switch: MOSFET, gate resistor and gate pull-down", [q, rg, rpd]),
                 ("motor connector, flyback diode and motor-supply bulk capacitor", [jm, d, cb]),
                 ("current-sense shunt and RC filter into the ADC", [rs, rf, cf])]
    c.spec += [
        f"- Motor (~{rmot:g} Ω, 5 mH): {pwm_pin} high -> {iload:g} A ±5 % with VDS ≤ {vds_max:g} V and gate-drive current "
        f"≤ 1 mA; {pwm_pin} floating -> motor off (< 0.1 mA) even with 10 MΩ leakage from +{vmot:g} V to the gate.",
        f"- Current sense: {u}.{adc_pin} reads {iload*rs_v*1e3:.0f} mV ±7 % at {iload:g} A; sense filter -3 dB corner "
        f"{fc:.4g} Hz ±10 %.",
        f"- Motor-current traces ({vmot_net}, motor return, ISENSE, GND) at least {w} mm wide.",
    ]
    c.values += [f"gate series resistor {rg} 4.7 Ω–220 Ω (datasheet: 10–100 Ω)",
                 f"gate pull-down {rpd} 4.7 kΩ–220 kΩ (datasheet: 10k–100k)",
                 f"motor-supply bulk capacitor {cb} 1 µF–22 µF"]
    c.params.update(iload=iload, rshunt=rs_v, rmotor=rmot, sense_fc_hz=round(fc, 3))
    return {"q": q, "d": d, "jm": jm, "rs": rs}


def crystal(c: Composite, u: str, vdd: float) -> dict:
    """Crystal between XIN (PA1) and XOUT (PA2) with a load capacitor from each pin to GND."""
    from pcbenv.parts import PARTS
    rng, b = c.rng, c.b
    while True:
        part = pick(rng, ["XTAL", "XTAL_CL18"])
        cl = PARTS[part].extra["cl"]
        cstray = pick(rng, [2e-12, 2.5e-12, 3e-12, 4e-12, 5e-12])
        cv = nearest(E24, 2 * (cl - cstray))
        if abs(cv / 2 + cstray - cl) <= 0.05 * cl:
            break
    freq = pick(rng, ["8M", "12M", "16M", "20M", "24M", "25M"])
    y = b.add(c.ref("Y"), part, freq)
    c1 = b.add(c.ref("C"), "C", cv, C_FP[0])
    c2 = b.add(c.ref("C"), "C", cv, C_FP[0])
    b.net("XIN", f"{u}.PA1", f"{y}.1", f"{c1}.1")
    b.net("XOUT", f"{u}.PA2", f"{y}.2", f"{c2}.1")
    b.net("GND", f"{c1}.2", f"{c2}.2")
    c.assertions.append({"name": "xtal_load_capacitance", "type": "analytic", "check": "xtal_load", "xtal": y, "cl": cl,
                         "cstray": cstray, "tol": 0.10, "osc_pins": [f"{u}.PA1", f"{u}.PA2"], "ground_pin": "J1.2"})
    c.vb.exact(y, b.val(y), 1e-3)
    c.vb.spec(c1, cv)
    c.vb.spec(c2, cv)
    c.role("filter_cap", c1, c2)
    c.mcu_pins += [("PA1", f"XIN: {freq}Hz crystal"), ("PA2", f"XOUT: {freq}Hz crystal")]
    c.purpose.append(f"- Clock: crystal {y} ({part}, rated CL {cl*1e12:.0f} pF) between XIN (PA1) and XOUT (PA2); load "
                     f"capacitor {c1} from XIN to GND and {c2} from XOUT to GND, next to the crystal.")
    c.groups.append(("crystal oscillator: crystal and load capacitors", [y, c1, c2]))
    c.spec += [f"- Crystal: CL_eff = C·C'/(C+C') + Cstray within ±10 % of {cl*1e12:.0f} pF (Cstray = {cstray*1e12:g} pF "
               f"from the layout estimate).",
               f"- Clock: {y} must be a {freq}Hz crystal (value `{freq}`, ±0.1 %): the firmware's clock tree assumes "
               f"exactly this frequency; MCU8 supports 4–25 MHz crystals."]
    c.params.update(xtal=part, freq=freq, cl_pf=cl * 1e12, cstray_pf=cstray * 1e12)
    return {"y": y, "c1": c1, "c2": c2}


def opamp_channel(c: Composite, k: int, vcc: float, rail: str, jin: str, in_pin: str, jout: str, out_pin: str) -> dict:
    """Single-supply non-inverting gain stage + RC anti-alias filter into an ADC header pin."""
    from pcbenv.families._common import cutoff_of, gain_at
    from pcbenv.families.opamp_noninv import transfer
    from pcbenv.parts_lib import OPAMP_GBW
    rng, b = c.rng, c.b
    gain = pick(rng, [2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0])
    u = b.add(c.ref("U"), "OPAMP")
    cd = c.capacitor(pick(rng, [100e-9, 100e-9, 1e-6]), vcc)
    rbias = c.resistor(pick(rng, [100e3, 220e3, 470e3, 1e6]))
    rf, rg = c.ref("R"), c.ref("R")
    rgv = pick(rng, series_values(E96, 1e3, 10e3))
    b.add(rf, "R", nearest(E96, rgv * (gain - 1)), pick(rng, R_FP))
    b.add(rg, "R", rgv, pick(rng, R_FP))
    use_cf = rng.random() < 0.4
    cf = None
    rfv = b.val(rf)
    if use_cf:
        bw = OPAMP_GBW / gain / pick(rng, [3.0, 5.0])
        cf = c.capacitor(nearest(E12, 1 / (2 * math.pi * rfv * bw)), vcc)
    bw_amp = OPAMP_GBW / gain
    f_aa = pick(rng, [f for f in (500.0, 1e3, 2e3, 5e3) if f <= bw_amp / 20])
    raa = c.resistor(pick(rng, series_values(E24, 1e3, 10e3)))
    caa = c.capacitor(nearest(E12, 1 / (2 * math.pi * b.val(raa) * f_aa)), vcc)
    n_in, n_fb, n_amp = f"IN{k}", f"FB{k}", f"AMP{k}"
    b.net(rail, f"{u}.V+", f"{cd}.1")
    b.net("GND", f"{u}.V-", f"{cd}.2", f"{rbias}.2", f"{rg}.2", f"{caa}.2")
    b.net(n_in, in_pin, f"{u}.IN+", f"{rbias}.1")
    b.net(n_amp, f"{u}.OUT", f"{rf}.1", f"{raa}.1")
    b.net(n_fb, f"{rf}.2", f"{rg}.1", f"{u}.IN-")
    b.net(f"ADC{k}", f"{raa}.2", f"{caa}.1", out_pin)
    if cf:
        b.net(n_amp, f"{cf}.1")
        b.net(n_fb, f"{cf}.2")
    amp = transfer(rfv, rgv, b.val(cf) if cf else None)
    raav, caav = b.val(raa), b.val(caa)

    def h(s: complex) -> complex:
        return amp(s) / (1 + s * raav * caav)

    g_nom = 1 + rfv / rgv
    f_test = 100.0
    g_test = gain_at(h, f_test)
    fc = cutoff_of(h, "high")
    vin_dc = round(0.4 * vcc / g_nom, 4)
    st = c.stim(c.params["vin"], source={"pin": in_pin, "dc": vin_dc, "ac": 1.0})
    c.assertions += [
        {"name": f"ch{k}_gain", "type": "ac_gain", "in_pin": in_pin, "out_pin": out_pin, "freq": f_test,
         **band(g_test, 0.03), **st},
        {"name": f"ch{k}_dc_out", "type": "dc_voltage", "net_pin": out_pin, **band(g_nom * vin_dc, 0.03, 0.005), **st},
        {"name": f"ch{k}_bandwidth", "type": "cutoff", "in_pin": in_pin, "out_pin": out_pin, "edge": "high",
         **band(fc, 0.10), **st},
    ]
    c.decoupling.append({"cap": cd, "ic_pin": f"{u}.V+", "max_mm": 5.0})
    c.vb.fixed(cd, *DECOUPLING)
    c.vb.fixed(rbias, 47e3, 2.2e6)
    c.vb.spec(rf, rfv)
    c.vb.spec(rg, rgv)
    if cf:
        c.vb.spec(cf, b.val(cf))
    c.vb.spec(raa, raav)
    c.vb.spec(caa, caav)
    c.role("feedback", rf, rg)
    c.role("filter_cap", caa, cf)
    c.purpose.append(
        f"- Channel {k}: {in_pin.replace('.', ' pin ')} -> IN+ of op-amp {u} ({rbias} from IN+ to GND defines the input); "
        f"{rf} from OUT to IN- and {rg} from IN- to GND set G = 1 + {rf}/{rg}"
        + (f"; {cf} across {rf} limits the bandwidth" if cf else "")
        + f"; {raa} from OUT to the ADC pin {out_pin.replace('.', ' pin ')} with {caa} from there to GND is the "
        f"anti-alias filter; {cd} decouples V+ at the pin.")
    c.groups += [(f"channel {k} op-amp with supply decoupling", [u, cd]),
                 (f"channel {k} input bias and gain network", [rbias, rf, rg] + ([cf] if cf else [])),
                 (f"channel {k} anti-alias filter", [raa, caa])]
    c.spec.append(f"- Channel {k}: gain {g_test:.4g} ±3 % at {f_test:g} Hz (G = {g_nom:.3g}); DC-coupled ({vin_dc:g} V "
                  f"in -> {g_nom*vin_dc:.3g} V out); -3 dB bandwidth {fc:.4g} Hz ±10 % (anti-alias filter).")
    c.values.append(f"channel {k}: decoupling {cd} 47 nF–10 µF; input bias {rbias} 47 kΩ–2.2 MΩ")
    c.params[f"ch{k}"] = {"gain": gain, "fc_hz": round(fc, 2), "cf": bool(cf)}
    return {"u": u, "cd": cd}
