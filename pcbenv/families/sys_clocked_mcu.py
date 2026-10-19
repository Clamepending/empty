"""Composite (hard tier): crystal-clocked MCU board -- protected input -> LDO rail -> MCU8 with
decoupling, reset, crystal + load capacitors, I2C pull-ups + bus header, status LED and power LED."""
from __future__ import annotations

import random

from pcbenv.families._blocks import (Composite, crystal, hard_board, i2c, input_protection, ldo, ldo_budget, led_gpio,
                                     led_rail, mcu, pick, rail_assertions, rail_name)
from pcbenv.golden import Golden

FAMILY = "sys_clocked_mcu"
TIER = "hard"


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vin = pick(rng, [5.0, 9.0, 12.0])
    vdd = pick(rng, [3.3, 3.3, 2.5])
    c = Composite(FAMILY, seed, f"crystal-clocked MCU board ({vin:g} V in)", rng)
    c.params.update(vin=vin, vdd=vdd)
    rail = rail_name(vdd)
    j1 = c.b.add(c.ref("J"), "CONN2")
    c.b.net("GND", f"{j1}.2")
    c.connectors += [(j1, "1", f"+{vin:g} V input"), (j1, "2", "GND")]
    vin_net = input_protection(c, j1, vin, bulk=rng.random() < 0.5)
    reg = ldo(c, vin, vdd, vin_net, rail, drop=0.4)
    va = reg["vout_nominal"]
    m = mcu(c, vdd, rail)
    u = m["u"]
    crystal(c, u, vdd)
    bus = i2c(c, u, va, rail)
    led_gpio(c, u, "PA0", va, "status")
    pl = led_rail(c, rail, va, "power")
    i_board = vdd / 2.2e3 + 0.005 + pl["i"]
    i_ext = pick(rng, ldo_budget(vin, vdd, i_board, [0.005, 0.01, 0.02, 0.05, 0.1]))
    rail_assertions(c, reg, f"{bus['j']}.1", i_ext, "the off-board I2C devices")
    c.power("VIN", 0.3)
    c.power(rail, 0.3)
    c.power("GND", 0.3)
    c.params.update(i_ext=i_ext, vout_nominal=reg["vout_nominal"])
    head = f"""
# Crystal-clocked MCU board

MCU {u} runs from a {c.params['freq']}Hz crystal and talks to off-board I2C devices on header {bus['j']},
which it also powers. Power ({vin:g} V) enters on {j1} through a reverse-polarity diode; LDO {reg['u']}
makes the {rail} rail ({vdd:g} V). A status LED on PA0 and an always-on power LED show the board state.

Rails: +{vin:g} V (from {j1}) -> reverse-polarity diode -> VIN -> {reg['u']} -> {rail} = {vdd:g} V.
"""
    w, h = hard_board(len(c.b.components))
    return c.golden(head, (w, h))
