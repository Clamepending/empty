"""Composite (hard tier): DC motor controller -- motor supply -> LDO logic rail -> MCU8 (decoupling,
reset) whose PWM pin drives a low-side NMOS (gate resistor, pull-down, Schottky flyback across the
motor connector), with a current-sense shunt + RC filter into an ADC pin, an I2C telemetry header,
a status LED and an optional power LED."""
from __future__ import annotations

import random

from pcbenv.families._blocks import (Composite, hard_board, i2c, ldo, ldo_budget, led_gpio, led_rail, lowside_motor, mcu,
                                     pick, rail_assertions, rail_name)
from pcbenv.golden import Golden

FAMILY = "sys_motor_ctrl"
TIER = "hard"


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vin = pick(rng, [9.0, 12.0, 15.0])
    vdd = pick(rng, [5.0, 5.0, 3.3])
    c = Composite(FAMILY, seed, f"{vin:g} V DC motor controller", rng)
    c.params.update(vin=vin, vdd=vdd)
    rail = rail_name(vdd)
    vmot = f"+{vin:g}V"
    j1 = c.b.add(c.ref("J"), "CONN2")
    c.b.net(vmot, f"{j1}.1")
    c.b.net("GND", f"{j1}.2")
    c.connectors += [(j1, "1", f"+{vin:g} V motor / board supply input"), (j1, "2", "GND")]
    reg = ldo(c, vin, vdd, vmot, rail)
    va = reg["vout_nominal"]
    m = mcu(c, vdd, rail)
    u = m["u"]
    mot = lowside_motor(c, u, "PA0", "PA1", va, vin, vmot)
    bus = i2c(c, u, va, rail)
    led_gpio(c, u, "PA2", va, "fault")
    i_board = vdd / 2.2e3 + 0.005 + 0.001
    if rng.random() < 0.5:
        pl = led_rail(c, rail, va, "power")
        i_board += pl["i"]
    i_ext = pick(rng, ldo_budget(vin, vdd, i_board, [0.005, 0.01, 0.02]))
    rail_assertions(c, reg, f"{bus['j']}.1", i_ext, "the telemetry host interface")
    c.power(rail, 0.3)
    c.params.update(i_ext=i_ext, vout_nominal=reg["vout_nominal"])
    head = f"""
# {vin:g} V DC motor controller

Drives a brushed DC motor ({mot['jm']}) from the +{vin:g} V supply on {j1} with a low-side MOSFET under
PWM control of MCU {u}, measures the motor current through a shunt on an ADC pin, reports over I2C
(header {bus['j']}) and shows a fault LED. LDO {reg['u']} makes the {rail} logic rail ({vdd:g} V) from the
motor supply.

Rails: +{vin:g} V (from {j1}: motor, LDO input) -> {reg['u']} -> {rail} = {vdd:g} V (MCU, I2C, LEDs).
"""
    w, h = hard_board(len(c.b.components), 1.05)
    return c.golden(head, (w, h))
