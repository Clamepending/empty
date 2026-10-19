"""Composite (hard tier): sensor node -- input -> LDO rail -> MCU8 with decoupling, reset, I2C
pull-ups + bus header, status LED (GPIO or NPN-switched from the input rail), and a scaled
voltage-sense divider with anti-alias filter into an ADC pin; optional power LED."""
from __future__ import annotations

import random

from pcbenv.families._blocks import (Composite, adc_divider, hard_board, i2c, input_protection, ldo, ldo_budget, led_gpio,
                                     led_npn, led_rail, mcu, pick, rail_assertions, rail_name)
from pcbenv.golden import Golden

FAMILY = "sys_sensor_node"
TIER = "hard"


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vin = pick(rng, [9.0, 12.0, 15.0])
    vdd = pick(rng, [3.3, 3.3, 3.0, 2.5])
    c = Composite(FAMILY, seed, f"{vin:g} V sensor node", rng)
    c.params.update(vin=vin, vdd=vdd)
    rail = rail_name(vdd)
    j1 = c.b.add(c.ref("J"), "CONN2")
    c.b.net("GND", f"{j1}.2")
    c.connectors += [(j1, "1", f"+{vin:g} V input"), (j1, "2", "GND")]
    vin_net = input_protection(c, j1, vin, bulk=rng.random() < 0.6)
    reg = ldo(c, vin, vdd, vin_net, rail, drop=0.4)
    va = reg["vout_nominal"]  # the rail as built (E96 divider), used for the electrical sizing below
    m = mcu(c, vdd, rail)
    u = m["u"]
    bus = i2c(c, u, va, rail)
    npn = rng.random() < 0.5
    if npn:
        led_npn(c, u, "PA0", va, vin, "VIN", "status")
    else:
        led_gpio(c, u, "PA0", va, "status")
    adc_divider(c, u, "PA1", vdd, "external voltage")
    i_board = vdd / 2.2e3 + 0.005
    pl = led_rail(c, rail, va, "power")
    i_board += pl["i"]
    i_ext = pick(rng, ldo_budget(vin, vdd, i_board, [0.005, 0.01, 0.02, 0.03, 0.05]))
    rail_assertions(c, reg, f"{bus['j']}.1", i_ext, "the off-board I2C devices")
    c.power("VIN", 0.3)
    c.power(rail, 0.3)
    c.power("GND", 0.3)
    c.params.update(status_led="npn" if npn else "gpio", i_ext=i_ext, vout_nominal=reg["vout_nominal"])
    head = f"""
# {vin:g} V sensor node

A sensor node board. Power enters on {j1} at +{vin:g} V; LDO {reg['u']} makes the {rail} rail
({vdd:g} V) for MCU {u}, the I2C bus pull-ups and the I2C bus header {bus['j']} (which also powers the
off-board sensors). The MCU reads an external voltage through a scaled, filtered divider on an ADC
pin and shows its state on a status LED{" switched by an NPN transistor from the +%g V input" % vin if npn else ""}.

Rails: +{vin:g} V (from {j1}) -> reverse-polarity diode -> VIN -> {reg['u']} -> {rail} = {vdd:g} V.
"""
    w, h = hard_board(len(c.b.components))
    return c.golden(head, (w, h))
