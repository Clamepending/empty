"""MCU-driven NPN low-side switch for an LED or an off-board relay coil (with flyback diode)."""
from __future__ import annotations

import random

from pcbenv.families._common import (DECOUPLING, E24, NRST_PULLUP, Bounds, Builder, band, golden, led_r_min, nearest,
                                     parts_summary, pick, series_values)
from pcbenv.golden import Golden
from pcbenv.parts_lib import GPIO_IMAX, led_vf

FAMILY = "npn_switch"
VF10 = {"RED": 2.0, "GREEN": 2.2}


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vs = pick(rng, [3.3, 5.0])
    load = pick(rng, ["led", "led", "coil"])
    gpio = pick(rng, ["PA0", "PA1", "PA2"])
    b = Builder("MCU-controlled " + ("LED" if load == "led" else "relay") + " switch", rng)
    vnet = "+3V3" if vs == 3.3 else "+5V"
    b.add("J1", "CONN2")
    b.add("U1", "MCU8")
    b.add("C1", "C", pick(rng, [100e-9, 100e-9, 1e-6]))
    b.add("R1", "R", pick(rng, series_values(E24, 4.7e3, 47e3)))
    b.add("Q1", "NPN")
    b.net(vnet, "J1.1", "U1.VDD", "C1.1", "R1.1")
    b.net("GND", "J1.2", "U1.GND", "C1.2", "Q1.E")
    b.net("NRST", "R1.2", "U1.NRST")
    params: dict = {"vs": vs, "load": load, "gpio": gpio}
    if load == "led":
        color = pick(rng, ["RED", "GREEN"])
        ic = pick(rng, [0.005, 0.01, 0.015, 0.02])
        b.add("D1", f"LED_{color}")
        b.add("R3", "R", nearest(E24, (vs - led_vf(VF10[color], ic) - 0.05) / ic))
        b.net(vnet, "R3.1")
        b.net("LED_A", "R3.2", "D1.A")
        b.net("SW", "D1.K", "Q1.C")
        load_elem = "D1"
        params.update(color=color, i_load=ic)
    else:
        rcoil = pick(rng, [100.0, 150.0, 220.0, 330.0])
        ic = vs / rcoil
        b.add("J2", "CONN2")
        b.add("D1", "D_SCHOTTKY")
        b.net(vnet, "J2.1", "D1.K")
        b.net("SW", "J2.2", "D1.A", "Q1.C")
        load_elem = "J2.2"
        params.update(r_coil=rcoil, l_coil=0.01, i_load=round(ic, 6))
    ib = ic / 10
    b.add("R2", "R", nearest(E24, (vs - 0.4 - 0.75) / ib))
    b.add("R4", "R", pick(rng, series_values(E24, 10e3, 100e3)))
    b.net("CTRL", f"U1.{gpio}", "R2.1")
    b.net("BASE", "R2.2", "Q1.B", "R4.1")
    b.net("GND", "R4.2")

    sup = {"pin": "J1.1", "volts": vs}
    loads = [{"pin": "J2.1", "to": "J2.2", "r": params["r_coil"], "l": 0.01}] if load == "coil" else []
    on = {"supply": sup, "source": {"pin": f"U1.{gpio}", "dc": vs, "r": 50.0}, "ground_pin": "J1.2"}
    off = {"supply": sup, "ground_pin": "J1.2",
           "loads": loads + [{"pin": "Q1.B", "to": "J1.1", "r": 1e6}]}
    if loads:
        on["loads"] = loads
    assertions = [
        {"name": "load_on_current", "type": "dc_current", "element": load_elem, **band(ic, 0.15), **on},
        {"name": "vce_sat", "type": "dc_voltage", "net_pin": "Q1.C", "min": 0.0, "max": 0.3, **on},
        {"name": "gpio_current", "type": "dc_current", "element": "R2", "min": 0.0, "max": 0.008, **on},
        {"name": "load_off_current", "type": "dc_current", "element": load_elem, "min": 0.0, "max": 1e-4, **off},
        {"name": "vdd", "type": "dc_voltage", "net_pin": "U1.VDD", "ref_pin": "U1.GND", "min": round(0.98 * vs, 4),
         "max": round(1.02 * vs, 4), "supply": sup, "ground_pin": "J1.2"},
        {"name": "nrst_high", "type": "dc_voltage", "net_pin": "U1.NRST", "min": round(0.9 * vs, 4),
         "max": round(vs * 1.01, 4), "supply": sup, "ground_pin": "J1.2"},
    ]
    if load == "led":
        load_txt = (f"LED D1 ({params['color'].lower()}) with series resistor R3 from the supply: supply -> R3 -> "
                    f"D1 anode, D1 cathode -> Q1 collector, {ic*1e3:g} mA when on.")
    else:
        load_txt = (f"an off-board relay coil (~{params['r_coil']:g} Ω, 10 mH) plugged into J2 (pin 1 = supply, "
                    f"pin 2 = switched side to Q1 collector). Schottky D1 is the flyback clamp across the coil: "
                    f"cathode to the supply, anode to the collector.")
    intent = f"""
# MCU-controlled low-side switch

A small MCU (U1, MCU8) switches a load through an NPN low-side transistor Q1. Power ({vs:g} V) comes in
on J1 (pin 1 = +{vs:g} V, pin 2 = GND); the MCU runs from the same rail.

- U1 is decoupled by C1 at its VDD pin; NRST is held high by the pull-up R1 to VDD.
- GPIO {gpio} drives Q1's base through R2 (sized for a forced beta of about 10, keeping the pin under 8 mA);
  R4 pulls the base to ground so the load stays off while the MCU pin is high-impedance (reset/boot).
- Q1 emitter to GND; the load sits between the supply and the collector: {load_txt}

Spec: with {gpio} driven high the load current is {ic*1e3:.1f} mA ±15 % and Q1 is saturated (VCE ≤ 0.3 V);
with {gpio} high-impedance the load stays off even with 1 MΩ of leakage from the supply into the base.
Component values: decoupling C1 47 nF–10 µF (100 nF typical); NRST pull-up R1 2.2 kΩ–100 kΩ;
base pull-down R4 4.7 kΩ–220 kΩ (datasheet: 10k–100k).

{parts_summary([("supply connector", ["J1"]), ("MCU", ["U1"]), ("VDD decoupling", ["C1"]), ("reset pull-up", ["R1"]),
                ("transistor switch with base resistor and base pull-down", ["Q1", "R2", "R4"]),
                ("LED load with series resistor" if load == "led" else "relay-coil connector with flyback diode",
                 ["D1", "R3"] if load == "led" else ["J2", "D1"])])}
"""
    params["i_load"] = round(ic, 6)
    vb = Bounds(FAMILY, seed)
    vb.fixed("C1", *DECOUPLING)
    vb.fixed("R1", *NRST_PULLUP)
    # base drive pinned by load_on_current / vce_sat / gpio_current; datasheet floor = 8 mA GPIO limit
    vb.spec("R2", b.val("R2"), ds_lo=(vs - 0.75) / GPIO_IMAX)
    if "R3" in b.components:  # LED current pinned by load_on_current; datasheet floor = 25 mA LED limit
        vb.spec("R3", b.val("R3"), ds_lo=led_r_min(vs, 1, VF10[params["color"]]))
    vb.fixed("R4", 4.7e3, 220e3)  # NPN datasheet: base pull-down 10k-100k (x2 slack)
    power_nets = {vnet: 0.3, "GND": 0.3}
    decoupling = [{"cap": "C1", "ic_pin": "U1.VDD", "max_mm": 5.0}]
    return golden(FAMILY, seed, b, assertions, power_nets, decoupling, intent, params, big=True, value_bounds=vb.out)
