"""Composite (hard tier): two-channel analog front end -- input -> LDO analog rail -> two
single-supply non-inverting op-amp gain stages (decoupling, input bias, optional bandwidth cap)
each followed by an RC anti-alias filter into an ADC header; power LED."""
from __future__ import annotations

import random

from pcbenv.families._blocks import (Composite, hard_board, input_protection, ldo, ldo_budget, led_rail, opamp_channel,
                                     pick, rail_assertions, rail_name)
from pcbenv.golden import Golden

FAMILY = "sys_analog_frontend"
TIER = "hard"


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vin = pick(rng, [9.0, 12.0, 15.0])
    vcc = pick(rng, [5.0, 5.0, 3.3])
    c = Composite(FAMILY, seed, f"2-channel analog front end ({vin:g} V in)", rng)
    c.params.update(vin=vin, vcc=vcc)
    rail = rail_name(vcc)
    j1 = c.b.add(c.ref("J"), "CONN2")
    jin = c.b.add(c.ref("J"), "CONN3")
    jadc = c.b.add(c.ref("J"), "CONN4")
    c.b.net("GND", f"{j1}.2", f"{jin}.2", f"{jadc}.2")
    c.connectors += [(j1, "1", f"+{vin:g} V input"), (j1, "2", "GND"),
                     (jin, "1", "channel 1 sensor input"), (jin, "2", "GND"), (jin, "3", "channel 2 sensor input"),
                     (jadc, "1", f"{rail} (ADC supply / reference)"), (jadc, "2", "GND"),
                     (jadc, "3", "channel 1 to ADC"), (jadc, "4", "channel 2 to ADC")]
    protect = rng.random() < 0.5
    if protect:
        vin_net = input_protection(c, j1, vin, bulk=rng.random() < 0.5)
    else:
        vin_net = "VIN"
        c.b.net(vin_net, f"{j1}.1")
    reg = ldo(c, vin, vcc, vin_net, rail, drop=0.4 if protect else 0.0)
    c.b.net(rail, f"{jadc}.1")
    for k, (ip, op) in enumerate(((f"{jin}.1", f"{jadc}.3"), (f"{jin}.3", f"{jadc}.4")), 1):
        opamp_channel(c, k, reg["vout_nominal"], rail, jin, ip, jadc, op)
    pl = led_rail(c, rail, reg["vout_nominal"], "power")
    i_board = 2 * vcc / 50e3 + pl["i"]
    i_ext = pick(rng, ldo_budget(vin, vcc, i_board, [0.001, 0.002, 0.005, 0.01]))
    rail_assertions(c, reg, f"{jadc}.1", i_ext, "the ADC board")
    c.power(vin_net, 0.3)
    c.power(rail, 0.3)
    c.power("GND", 0.3)
    c.groups += [("supply connector", [j1]), ("sensor input connector", [jin]), ("ADC header", [jadc])]
    c.params.update(i_ext=i_ext, vout_nominal=reg["vout_nominal"], protected=protect)
    head = f"""
# Two-channel analog front end

Conditions two DC-coupled sensor signals (input header {jin}) for an off-board ADC (header {jadc}): each
channel is a single-supply non-inverting op-amp gain stage followed by an RC anti-alias filter. LDO
{reg['u']} makes the {rail} analog rail ({vcc:g} V) from the {vin:g} V input on {j1}; the rail also
supplies the ADC board through {jadc} pin 1.

Rails: +{vin:g} V (from {j1}){" -> reverse-polarity diode -> VIN" if protect else ""} -> {reg['u']} -> {rail} = {vcc:g} V.
"""
    w, h = hard_board(len(c.b.components))
    return c.golden(head, (w, h))
