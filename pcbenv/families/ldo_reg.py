"""Adjustable LDO regulator: input header, LDO, in/out caps, feedback divider, output header."""
from __future__ import annotations

import random

from pcbenv.families._common import E6, E24, E96, Builder, band, golden, nearest, pick, series_values
from pcbenv.golden import Golden
from pcbenv.parts_lib import led_vf

FAMILY = "ldo_reg"
VREF = 0.8


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vout = pick(rng, [1.2, 1.5, 1.8, 2.5, 2.8, 3.0, 3.3, 5.0])
    vin = pick(rng, [v for v in (3.3, 5.0, 9.0, 12.0) if v >= vout + 1.0])
    iload = pick(rng, [i for i in (0.02, 0.05, 0.1, 0.15, 0.2, 0.25) if (vin - vout) * i <= 0.45] or [0.02])
    en_mode = pick(rng, ["tie", "tie", "pullup"])
    indicator = rng.random() < 0.4

    b = Builder(f"{vout:g} V LDO regulator", rng)
    b.add("J1", "CONN2")
    b.add("J2", "CONN2")
    b.add("U1", "LDO_ADJ")
    b.add("C1", "C", pick(rng, [1e-6, 2.2e-6, 4.7e-6, 10e-6]))
    b.add("C2", "C", pick(rng, [1e-6, 2.2e-6, 4.7e-6, 10e-6]))
    rbot = pick(rng, series_values(E96, 10e3, 49.9e3))
    b.add("R2", "R", rbot)
    b.add("R1", "R", nearest(E96, rbot * (vout / VREF - 1)))
    vin_net, vout_net = "VIN", "+" + (f"{vout:g}".replace(".", "V") if vout % 1 else f"{vout:g}V")
    b.net(vin_net, "J1.1", "U1.VIN", "C1.1")
    b.net("GND", "J1.2", "U1.GND", "C1.2", "C2.2", "R2.2", "J2.2")
    b.net(vout_net, "U1.VOUT", "C2.1", "R1.1", "J2.1")
    b.net("FB", "R1.2", "R2.1", "U1.FB")
    if en_mode == "tie":
        b.net(vin_net, "U1.EN")
    else:
        b.add("R3", "R", pick(rng, series_values(E6, 10e3, 470e3)))
        b.net(vin_net, "R3.1")
        b.net("EN", "R3.2", "U1.EN")
    led_i = 0.0
    if indicator:
        color = pick(rng, ["RED", "GREEN"])
        vf10 = 2.0 if color == "RED" else 2.2
        if vout > vf10 + 0.5:
            led_i = pick(rng, [1e-3, 2e-3])
            b.add("D1", f"LED_{color}")
            b.add("R4", "R", nearest(E24, (vout - led_vf(vf10, led_i)) / led_i))
            b.net(vout_net, "R4.1")
            b.net("LED", "R4.2", "D1.A")
            b.net("GND", "D1.K")
            led_i = (vout - led_vf(vf10, led_i)) / b.val("R4")

    vout_act = VREF * (1 + b.val("R1") / b.val("R2"))
    rload = round(vout / iload, 3)
    st = {"supply": {"pin": "J1.1", "volts": vin}, "loads": [{"pin": "J2.1", "r": rload}], "ground_pin": "J1.2"}
    st_min = {"supply": {"pin": "J1.1", "volts": round(max(vout + 0.6, 2.5), 3)}, "loads": [{"pin": "J2.1", "r": rload}],
              "ground_pin": "J1.2"}
    assertions = [
        {"name": "vout_loaded", "type": "dc_voltage", "net_pin": "J2.1", **band(vout, 0.03), **st},
        {"name": "vout_low_vin", "type": "dc_voltage", "net_pin": "J2.1", **band(vout, 0.03), **st_min},
        {"name": "load_current", "type": "dc_current", "element": "J2.1", **band(iload, 0.05), **st},
    ]
    if led_i:
        assertions.append({"name": "indicator_current", "type": "dc_current", "element": "D1",
                           **band(led_i, 0.15), **st})
    w = 0.5 if iload >= 0.1 else 0.3
    power_nets = {vin_net: w, vout_net: w, "GND": w}
    decoupling = [{"cap": "C1", "ic_pin": "U1.VIN", "max_mm": 5.0}, {"cap": "C2", "ic_pin": "U1.VOUT", "max_mm": 5.0}]
    en_txt = ("EN is tied directly to VIN so the regulator is always on." if en_mode == "tie" else
              "EN is pulled up to VIN through R3 so the regulator is on whenever input power is present.")
    intent = f"""
# {vout:g} V LDO regulator

Converts a {vin:g} V input (J1: pin 1 = +{vin:g} V, pin 2 = GND) into a regulated {vout:g} V rail
(J2: pin 1 = +{vout:g} V, pin 2 = GND) able to deliver {iload*1e3:.0f} mA.

- U1 (LDO_ADJ) takes its input on VIN with C1 as the input capacitor from VIN to GND, placed at the pin.
- C2 is the output capacitor from VOUT to GND, placed at the VOUT pin.
- The output voltage is programmed by a divider: R1 from VOUT down to the FB pin, R2 from FB to GND
  (VOUT = 0.8 V x (1 + R1/R2)).
- {en_txt}
{"- An indicator LED D1 with series resistor R4 lights from the output rail (about %.1f mA)." % (led_i*1e3) if led_i else ""}

Spec: output {vout:g} V ±3 % at {iload*1e3:.0f} mA load, for input voltages from {max(vout+0.6, 2.5):g} V up to {vin:g} V.
Supply and ground traces carrying the load current must be at least {w} mm wide.
"""
    params = {"vout": vout, "vin": vin, "iload": iload, "en_mode": en_mode, "indicator": bool(led_i),
              "vout_nominal": round(vout_act, 4)}
    return golden(FAMILY, seed, b, assertions, power_nets, decoupling, intent, params)
