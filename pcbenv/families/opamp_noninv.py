"""Single-supply non-inverting op-amp gain stage."""
from __future__ import annotations

import math
import random

from pcbenv.families._common import DECOUPLING, E12, E96, Bounds, Builder, band, cutoff_of, gain_at, golden, nearest, pick, series_values
from pcbenv.golden import Golden
from pcbenv.parts_lib import OPAMP_A0, OPAMP_GBW

FAMILY = "opamp_noninv"


def _a(s: complex) -> complex:
    return OPAMP_A0 / (1 + s / (2 * math.pi * OPAMP_GBW / OPAMP_A0))


def transfer(rf: float, rg: float, cf: float | None):
    def h(s: complex) -> complex:
        zf = rf if not cf else 1 / (1 / rf + s * cf)
        beta = rg / (rg + zf)
        a = _a(s)
        return a / (1 + a * beta)
    return h


def generate(seed: int) -> Golden:
    rng = random.Random(seed)
    vcc = pick(rng, [3.3, 5.0])
    gain = pick(rng, [1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0])
    b = Builder(f"x{gain:g} non-inverting amplifier", rng)
    for j in ("J1", "J2", "J3"):
        b.add(j, "CONN2")
    b.add("U1", "OPAMP")
    b.add("C1", "C", 100e-9)
    rg = pick(rng, series_values(E96, 1e3, 10e3))
    b.add("R2", "R", rg)
    b.add("R1", "R", nearest(E96, rg * (gain - 1)))
    b.add("R3", "R", pick(rng, [100e3, 220e3, 470e3, 1e6]))
    use_cf = rng.random() < 0.5
    rf = b.val("R1")
    cf = None
    if use_cf:
        bw_target = OPAMP_GBW / gain / pick(rng, [3.0, 5.0, 10.0])
        b.add("C2", "C", nearest(E12, 1 / (2 * math.pi * rf * bw_target)))
        cf = b.val("C2")
    b.net("VCC", "J1.1", "U1.V+", "C1.1")
    b.net("GND", "J1.2", "U1.V-", "C1.2", "R2.2", "R3.2", "J2.2", "J3.2")
    b.net("IN", "J2.1", "U1.IN+", "R3.1")
    b.net("OUT", "U1.OUT", "R1.1", "J3.1")
    b.net("FB", "R1.2", "R2.1", "U1.IN-")
    if cf:
        b.net("OUT", "C2.1")
        b.net("FB", "C2.2")

    h = transfer(rf, rg, cf)
    g_nom = 1 + rf / rg
    f_test = 100.0
    fc = cutoff_of(h, "high")
    vin_dc = round(0.4 * vcc / g_nom, 4)
    st = {"supply": {"pin": "J1.1", "volts": vcc}, "source": {"pin": "J2.1", "dc": vin_dc, "ac": 1.0},
          "ground_pin": "J1.2"}
    assertions = [
        {"name": "gain", "type": "ac_gain", "in_pin": "J2.1", "out_pin": "J3.1", "freq": f_test,
         **band(gain, 0.03), **st},
        {"name": "dc_out", "type": "dc_voltage", "net_pin": "J3.1", **band(g_nom * vin_dc, 0.03, 0.005), **st},
        {"name": "bandwidth", "type": "cutoff", "in_pin": "J2.1", "out_pin": "J3.1", "edge": "high",
         **band(fc, 0.10), **st},
    ]
    intent = f"""
# x{gain:g} non-inverting amplifier

Amplifies the signal on J2 (pin 1 = input, pin 2 = GND) by {gain:g} and presents it on J3
(pin 1 = output, pin 2 = GND). Single {vcc:g} V supply on J1 (pin 1 = VCC, pin 2 = GND).

- U1 (OPAMP) runs from VCC on V+ with V- on GND; C1 decouples V+ at the pin.
- The input goes straight to IN+; R3 is a bias resistor from the input to GND so the input is
  defined when nothing is connected.
- Gain is set by R1 from OUT to IN- and R2 from IN- to GND (G = 1 + R1/R2).
{"- C2 across R1 rolls the response off at about %.3g kHz (bandwidth limit)." % (fc/1e3) if cf else "- No bandwidth-limiting capacitor; the bandwidth is set by the op-amp GBW."}

Spec: gain {gain:g} ±3 % at {f_test:g} Hz; -3 dB bandwidth {fc/1e3:.3g} kHz ±10 %; DC-coupled
(input {vin_dc:g} V DC -> output {g_nom*vin_dc:.3g} V).
Component values: decoupling C1 47 nF–10 µF (100 nF typical); input bias resistor R3 47 kΩ–2.2 MΩ
(sets the input impedance).
"""
    params = {"vcc": vcc, "gain": gain, "cf": bool(cf), "bandwidth_hz": round(fc, 1)}
    vb = Bounds(FAMILY, seed)
    vb.fixed("C1", *DECOUPLING)
    vb.spec("R1", rf)            # gain (and bandwidth with C2) pinned by assertions
    vb.spec("R2", rg)
    vb.fixed("R3", 47e3, 2.2e6)  # input bias resistor = input impedance; 47k..2.2M is sane
    if cf:
        vb.spec("C2", cf)        # pinned by the bandwidth assertion
    return golden(FAMILY, seed, b, assertions, {"VCC": 0.3, "GND": 0.3},
                  [{"cap": "C1", "ic_pin": "U1.V+", "max_mm": 5.0}], intent, params, value_bounds=vb.out)


__all__ = ["generate", "transfer", "gain_at"]
