# NPN — general-purpose NPN BJT (SOT-23)

## Pinout
| Pin | Pad | Function |
|---|---|---|
| B | 1 | base |
| E | 2 | emitter |
| C | 3 | collector |

## Electrical characteristics
- VCEO 40 V, IC max 200 mA, Ptot 250 mW
- hFE 100–300 at IC = 10 mA, VCE = 1 V
- VBE(on) ~0.65–0.8 V
- VCE(sat) < 0.2 V at IC = 50 mA, IB = 5 mA

## Application notes
- Low-side switch: emitter to ground, load between supply and collector.
- For hard saturation size the base resistor for a forced beta of ~10:
  RB = (Vdrive - 0.75 V) / (IC / 10).
- Add a base-emitter pull-down (10k–100k) so the transistor stays off while the driver
  is high-impedance (e.g. MCU in reset).
- Inductive loads need a flyback diode across the load.

## Absolute maximum ratings
- VCEO 40 V, IC 200 mA continuous, IB 20 mA.

**Design rule (switching):** when used as a saturated switch (VCE ≤ 0.4 V), the forced
beta IC/IB must be ≤ 20 so the transistor stays saturated over hFE spread and
temperature (the typical design point is 10). A transistor that only saturates thanks to a high
typical hFE fails this rule.
