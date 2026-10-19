"""LED driver: 1-4 LED strings, each with a series current-limiting resistor."""
from __future__ import annotations

import random

from pcbenv.families._common import E24, Builder, band, golden, nearest, pick
from pcbenv.golden import Golden
from pcbenv.parts_lib import led_vf

FAMILY = "led_driver"
VF10 = {"RED": 2.0, "GREEN": 2.2}


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vs = pick(rng, [3.3, 5.0, 9.0, 12.0])
    n_str = rng.randint(1, 4)
    b = Builder(f"{n_str}-channel LED indicator board", rng)
    b.add("J1", "CONN2")
    supply = "VS" if vs != 3.3 else "+3V3"
    b.net(supply, "J1.1")
    b.net("GND", "J1.2")
    strings = []
    dn = 0
    for s in range(1, n_str + 1):
        color = pick(rng, ["RED", "GREEN"])
        i = pick(rng, [0.002, 0.005, 0.01, 0.015, 0.02])
        vf = led_vf(VF10[color], i)
        kmax = max(1, min(3, int((vs - 0.8) // vf)))
        k = rng.randint(1, kmax)
        r = nearest(E24, (vs - k * vf) / i)
        p_r = i * i * r
        fp = "Resistor_SMD:R_1206_3216Metric" if p_r > 0.06 else None
        rref = b.add(f"R{s}", "R", r, fp)
        leds = []
        for _ in range(k):
            dn += 1
            leds.append(b.add(f"D{dn}", f"LED_{color}"))
        b.net(supply, f"{rref}.1")
        prev = f"{rref}.2"
        for j, d in enumerate(leds):
            b.net(f"CH{s}_{j}", prev, f"{d}.A")
            prev = f"{d}.K"
        b.net("GND", prev)
        i_act = (vs - k * led_vf(VF10[color], i)) / r
        strings.append({"color": color, "leds": leds, "r": rref, "i_target": i, "n_series": k,
                        "i_nominal": round(i_act, 6)})
    st = {"supply": {"pin": "J1.1", "volts": vs}, "ground_pin": "J1.2"}
    assertions = []
    for s, info in enumerate(strings, 1):
        assertions.append({"name": f"string{s}_current", "type": "dc_current", "element": info["leds"][-1],
                           **band(info["i_target"], 0.10), **st})
    total = sum(x["i_target"] for x in strings)
    w = 0.5 if total > 0.1 else 0.3
    lines = []
    for s, info in enumerate(strings, 1):
        chain = " -> ".join(f"{d} (anode to cathode)" for d in info["leds"])
        lines.append(f"- Channel {s}: {info['n_series']} {info['color'].lower()} LED(s) at "
                     f"{info['i_target']*1e3:g} mA: supply -> {info['r']} -> {chain} -> GND.")
    intent = f"""
# {n_str}-channel LED indicator board

Lights {sum(x['n_series'] for x in strings)} indicator LEDs from a {vs:g} V supply on J1
(pin 1 = +{vs:g} V, pin 2 = GND). Each channel is a series string of LEDs fed through its own
current-limiting resistor; the resistor sets the current from (Vs - n*Vf)/R.

{chr(10).join(lines)}

Spec: each channel's LED current within ±10 % of its target. Resistors dissipating more than
~60 mW use a 1206 footprint.
"""
    params = {"vs": vs, "strings": strings}
    return golden(FAMILY, seed, b, assertions, {supply: w, "GND": w}, [], intent, params)
