"""Additional generic parts registered into `pcbenv.parts.PARTS`.

Pad maps were verified against the KiCad 7 footprints in /usr/share/kicad/footprints
(`pcbnew.FootprintLoad`). KiCad convention for diodes/LEDs: pad 1 = cathode, pad 2 = anode.
SOT-23 (3-pin): BJT B=1 E=2 C=3, MOSFET G=1 S=2 D=3.

SPICE models are behavioural/macro models, accurate enough for DC operating point,
small-signal AC and simple step-response checks. They are not meant for oscillator,
thermal or large-signal-distortion studies.
"""
from __future__ import annotations

import math

from pcbenv.parts import Part, PinInfo, parse_value, register

# --------------------------------------------------------------------------- helpers

_HDR = "Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical"
_SOT23 = ["Package_TO_SOT_SMD:SOT-23", "Package_TO_SOT_SMD:SOT-23-3"]
_SOT23_5 = ["Package_TO_SOT_SMD:SOT-23-5"]


def _none(ref: str, n: dict[str, str], v: str) -> str:
    return ""


def _conn_datasheet(n: int) -> str:
    rows = "\n".join(f"| {i} | {i} | {'ground (board convention)' if i == 2 else 'signal / supply'} |" for i in range(1, n + 1))
    return (
        f"# CONN{n} — {n}-pin 2.54 mm header\n\n"
        "Generic vertical pin header used for off-board power, signal and bus connections.\n\n"
        "| Pin | Pad | Typical use |\n|---|---|---|\n" + rows + "\n\n"
        "## Notes\n- Pin 2 is ground by board convention; the function of the other pins is set by the design.\n"
        "- Rated 3 A per contact. Has no electrical model of its own (it is where external\n"
        "  supplies, signals and loads attach).\n"
    )


for _n in (3, 4):
    register(Part(
        name=f"CONN{_n}", description=f"{_n}-pin 2.54 mm header",
        pins={str(i): PinInfo(str(i), "passive") for i in range(1, _n + 1)},
        footprints=[_HDR.format(n=_n)],
        value_required=False, spice=_none, datasheet=_conn_datasheet(_n),
    ))

# --------------------------------------------------------------------------- LEDs

_VT = 0.025865  # kT/q at 27 C
LED_N = 2.0
LED_RS = 2.0


def led_is(vf10: float) -> float:
    """Saturation current giving forward voltage `vf10` at 10 mA for the LED model."""
    return 0.01 * math.exp(-(vf10 - LED_RS * 0.01) / (LED_N * _VT))


def led_vf(vf10: float, i: float) -> float:
    """Model forward voltage of an LED with nominal `vf10` (V at 10 mA) at current `i` (A)."""
    return LED_N * _VT * math.log(i / led_is(vf10)) + LED_RS * i


def _led(color: str, vf10: float, lam: str) -> None:
    model = f"PCB_LED_{color}"
    table = "\n".join(f"| {i*1e3:.0f} mA | {led_vf(vf10, i):.2f} V |" for i in (0.002, 0.005, 0.01, 0.015, 0.02))
    register(Part(
        name=f"LED_{color}", description=f"{color.lower()} indicator LED, {lam}",
        pins={"A": PinInfo("2", "passive"), "K": PinInfo("1", "passive")},
        footprints=["LED_SMD:LED_0603_1608Metric", "LED_SMD:LED_0805_2012Metric"],
        value_required=False,
        spice=lambda ref, n, v, m=model: f"D{ref} {n['A']} {n['K']} {m}",
        models=f".model {model} D(IS={led_is(vf10):.4e} N={LED_N} RS={LED_RS} CJO=20p BV=5 IBV=10u)",
        datasheet=(
            f"# LED_{color} — {color.lower()} SMD indicator LED ({lam})\n\n"
            "## Pinout\n| Pin | Pad | Function |\n|---|---|---|\n| A | 2 | anode |\n| K | 1 | cathode (marked) |\n\n"
            "## Electrical characteristics (25 C)\n"
            f"- Forward voltage Vf = {vf10:.1f} V typ at IF = 10 mA\n"
            "- Max continuous forward current 25 mA; reverse voltage max 5 V\n\n"
            "| IF | Vf (typ) |\n|---|---|\n" + table + "\n\n"
            "## Application notes\n"
            "- Always drive through a current-limiting resistor: R = (Vsupply - n*Vf) / IF for n LEDs in series.\n"
            "- Current flows anode -> cathode; reversed LEDs do not light.\n"
        ),
    ))


_led("RED", 2.0, "625 nm")
_led("GREEN", 2.2, "570 nm")

# --------------------------------------------------------------------------- Schottky

register(Part(
    name="D_SCHOTTKY", description="40 V 1 A Schottky diode",
    pins={"A": PinInfo("2", "passive"), "K": PinInfo("1", "passive")},
    footprints=["Diode_SMD:D_SOD-123", "Diode_SMD:D_SOD-323", "Diode_SMD:D_SMA"],
    value_required=False,
    spice=lambda ref, n, v: f"D{ref} {n['A']} {n['K']} PCB_SCHOTTKY",
    models=".model PCB_SCHOTTKY D(IS=3u N=1.05 RS=0.05 CJO=60p BV=40 IBV=1m)",
    datasheet=(
        "# D_SCHOTTKY — 40 V / 1 A Schottky rectifier\n\n"
        "## Pinout\n| Pin | Pad | Function |\n|---|---|---|\n| A | 2 | anode |\n| K | 1 | cathode (band) |\n\n"
        "## Electrical characteristics\n- VRRM 40 V, IF(AV) 1 A\n- Vf = 0.30 V typ at 100 mA, 0.40 V at 1 A\n"
        "- Reverse leakage 20 uA typ at 25 V\n\n"
        "## Application notes\n- Flyback / freewheel clamp across an inductive load (relay coil, solenoid, motor):\n"
        "  cathode to the positive supply side, anode to the switched (transistor) side. In normal\n"
        "  operation the diode is reverse biased; at turn-off it clamps the inductive kick.\n"
        "- Reverse polarity protection: in series with the supply, anode to the input.\n"
    ),
))

# --------------------------------------------------------------------------- NPN

register(Part(
    name="NPN", description="general-purpose NPN transistor, 40 V 200 mA, SOT-23",
    pins={"B": PinInfo("1", "input"), "E": PinInfo("2", "passive"), "C": PinInfo("3", "passive")},
    footprints=list(_SOT23),
    value_required=False,
    spice=lambda ref, n, v: f"Q{ref} {n['C']} {n['B']} {n['E']} PCB_NPN",
    models=(".model PCB_NPN NPN(IS=6.734f XTI=3 EG=1.11 VAF=74.03 BF=416.4 NE=1.259 ISE=6.734f IKF=66.78m "
            "XTB=1.5 BR=.7371 NC=2 ISC=0 IKR=0 RC=1 CJC=3.638p MJC=.3085 VJC=.75 FC=.5 CJE=4.493p "
            "MJE=.2593 VJE=.75 TR=239.5n TF=301.2p ITF=.4 VTF=4 XTF=2 RB=10)"),
    datasheet=(
        "# NPN — general-purpose NPN BJT (SOT-23)\n\n"
        "## Pinout\n| Pin | Pad | Function |\n|---|---|---|\n| B | 1 | base |\n| E | 2 | emitter |\n| C | 3 | collector |\n\n"
        "## Electrical characteristics\n- VCEO 40 V, IC max 200 mA, Ptot 250 mW\n"
        "- hFE 100–300 at IC = 10 mA, VCE = 1 V\n- VBE(on) ~0.65–0.8 V\n"
        "- VCE(sat) < 0.2 V at IC = 50 mA, IB = 5 mA\n\n"
        "## Application notes\n- Low-side switch: emitter to ground, load between supply and collector.\n"
        "- For hard saturation size the base resistor for a forced beta of ~10:\n"
        "  RB = (Vdrive - 0.75 V) / (IC / 10).\n"
        "- Add a base-emitter pull-down (10k–100k) so the transistor stays off while the driver\n"
        "  is high-impedance (e.g. MCU in reset).\n"
        "- Inductive loads need a flyback diode across the load.\n"
    ),
))

# --------------------------------------------------------------------------- NMOS

register(Part(
    name="NMOS", description="logic-level N-channel MOSFET, 30 V 2 A, SOT-23",
    pins={"G": PinInfo("1", "input"), "S": PinInfo("2", "passive"), "D": PinInfo("3", "passive")},
    footprints=list(_SOT23),
    value_required=False,
    spice=lambda ref, n, v: f"X{ref} {n['D']} {n['G']} {n['S']} PCB_NMOS",
    models=(".subckt PCB_NMOS d g s\n"
            "M1 d g s s PCB_NMOS_M L=1u W=1u\n"
            "Dbody s d PCB_NMOS_BD\n"
            "Cgs g s 250p\nCgd g d 40p\n"
            ".model PCB_NMOS_M NMOS(LEVEL=1 VTO=1.2 KP=5 LAMBDA=0.01 RD=0.02 RS=0.02)\n"
            ".model PCB_NMOS_BD D(IS=1n N=1.2 RS=0.05 BV=30 IBV=10u)\n"
            ".ends PCB_NMOS"),
    datasheet=(
        "# NMOS — logic-level N-channel MOSFET (SOT-23)\n\n"
        "## Pinout\n| Pin | Pad | Function |\n|---|---|---|\n| G | 1 | gate |\n| S | 2 | source |\n| D | 3 | drain |\n\n"
        "## Electrical characteristics\n- VDS max 30 V, ID max 2 A continuous, VGS max ±12 V\n"
        "- VGS(th) 1.2 V typ (0.8–1.5 V)\n- RDS(on) 0.10 Ω at VGS = 4.5 V; 0.15 Ω at VGS = 3.3 V; 0.25 Ω at 2.5 V\n"
        "- Ciss ~300 pF; internal body diode source -> drain\n\n"
        "## Application notes\n- Low-side switch: source to ground, load between supply and drain.\n"
        "- Gate series resistor 10–100 Ω limits ringing / driver current.\n"
        "- Gate pull-down 10k–100k to source keeps the FET off when the control input floats.\n"
        "- Inductive loads need a flyback diode across the load (cathode to supply).\n"
    ),
))

# --------------------------------------------------------------------------- LDO

LDO_VREF = 0.8
LDO_GAIN = 1e4        # error-amplifier DC gain (80 dB): regulation error 1/(gain*VREF/VOUT) <= 0.1 %
LDO_ILIM = 0.5        # pass element current limit (A)
LDO_RPASS = 0.8       # pass element small-signal resistance (ohm): ~0.25 V dropout at 300 mA


def _softplus(z: str, k: float = 0.01) -> str:
    """Smooth max(z, 0) for ngspice B sources (overflow-safe, C-infinity)."""
    return f"(max({z},0)+{k:g}*ln(1+exp(-abs({z})/{k:g})))"


# Behavioural LDO built for robust DC convergence: a finite-gain error amplifier (no hidden
# integrator, no step-like transfer), smoothly clamped between 0 V and VIN, driving the output
# through a smooth current-limited pass element I = ILIM*tanh(V/(ILIM*RPASS)). Every branch is
# smooth with non-zero derivatives, so Newton converges from the default initial point. The loop
# is algebraic (memoryless), so AC and transient analyses see an ideal fast regulator.
LDO_MODEL = (
    ".subckt PCB_LDO vin vss en fb vout\n"
    "Rq vin vss 100k\n"
    "Ren en vss 2Meg\n"
    "Bena ena vss V=0.5*(1+tanh((v(en,vss)-1.2)/0.03))\n"
    f"Bx x vss V={_softplus(f'{LDO_GAIN:g}*({LDO_VREF:g}-v(fb,vss))')}\n"
    f"Btop top vss V={_softplus('v(vin,vss)')}\n"
    f"Bo o vss V=v(ena,vss)*(v(top,vss)-{_softplus('v(top,vss)-v(x,vss)')})\n"
    f"Bpass o vout I={LDO_ILIM:g}*tanh(v(o,vout)/{LDO_ILIM * LDO_RPASS:g})\n"
    "Rdis vout vss 1Meg\n"
    ".ends PCB_LDO"
)

register(Part(
    name="LDO_ADJ", description="adjustable 300 mA LDO regulator, SOT-23-5",
    pins={
        "VIN": PinInfo("1", "power_in"), "GND": PinInfo("2", "power_in"), "EN": PinInfo("3", "input"),
        "FB": PinInfo("4", "input"), "VOUT": PinInfo("5", "power_out"),
    },
    footprints=list(_SOT23_5),
    value_required=False,
    spice=lambda ref, n, v: f"X{ref} {n['VIN']} {n['GND']} {n['EN']} {n['FB']} {n['VOUT']} PCB_LDO",
    models=LDO_MODEL,
    datasheet=(
        "# LDO_ADJ — adjustable 300 mA low-dropout regulator (SOT-23-5)\n\n"
        "## Pinout\n| Pin | Pad | Function |\n|---|---|---|\n"
        "| VIN | 1 | input supply, 2.5–16 V |\n| GND | 2 | ground |\n"
        "| EN | 3 | enable, active high. Internal 2 MΩ pull-down: floating = OFF |\n"
        "| FB | 4 | feedback; regulates to VREF = 0.800 V |\n| VOUT | 5 | regulated output |\n\n"
        "## Electrical characteristics\n- VREF = 0.800 V ±1 %\n- Output current 300 mA max; current limit ~500 mA\n"
        "- Dropout 250 mV typ at 300 mA\n- EN threshold 1.2 V (high = on); EN low or floating -> output off (0 V)\n"
        "- Quiescent current 50 µA; package dissipation max 0.5 W\n\n"
        "## Application notes\n- Output voltage is set by a divider from VOUT to FB (Rtop) and FB to GND (Rbot):\n"
        "  **VOUT = VREF × (1 + Rtop / Rbot)**. Rbot of 10k–50k is typical.\n"
        "- Connect EN to VIN for always-on operation (or drive it from logic / a pull-up). A pull-up\n"
        "  Rpu from VIN forms a divider with the internal 2 MΩ pull-down: VIN·2M/(Rpu + 2M) must exceed\n"
        "  the 1.2 V threshold at the lowest VIN.\n"
        "- Place a 1 µF–22 µF ceramic input capacitor and a 1 µF–22 µF ceramic output capacitor (the\n"
        "  output capacitor range is the stability range of the regulation loop) within\n"
        "  5 mm of the VIN and VOUT pins respectively, returned to GND.\n"
        "- Power dissipation = (VIN - VOUT) × IOUT must stay below 0.5 W.\n"
    ),
))

# --------------------------------------------------------------------------- OPAMP

OPAMP_A0 = 1e5
OPAMP_GBW = 1e6

register(Part(
    name="OPAMP", description="single rail-to-rail I/O op-amp, 1 MHz GBW, SOT-23-5",
    pins={
        "OUT": PinInfo("1", "output"), "V-": PinInfo("2", "power_in"), "IN+": PinInfo("3", "input"),
        "IN-": PinInfo("4", "input"), "V+": PinInfo("5", "power_in"),
    },
    footprints=list(_SOT23_5),
    value_required=False,
    spice=lambda ref, n, v: f"X{ref} {n['OUT']} {n['V-']} {n['IN+']} {n['IN-']} {n['V+']} PCB_OPAMP",
    models=(".subckt PCB_OPAMP out vn inp inm vp\n"
            "Rin inp inm 10Meg\n"
            "Rcp inp vn 1e10\nRcm inm vn 1e10\n"
            "Rq vp vn 50k\n"
            "Bmid mid vn V=0.5*v(vp,vn)\n"
            # input stage: 1 S transconductance, smoothly limited at +-1 mA (internal node within
            # +-100 V of mid, so Newton never sees an unbounded node); small-signal gain unchanged
            "Bg1 mid x I=1e-3*tanh(v(inp,inm)/1e-3)\n"
            f"R1 x mid {OPAMP_A0:g}\n"
            f"C1 x mid {1 / (2 * math.pi * OPAMP_A0 * OPAMP_GBW / OPAMP_A0):.6g}\n"
            # rail-to-rail output: smooth clamp between V- + 5 mV and V+ - 5 mV (C-infinity, so the
            # DC Jacobian never vanishes in saturation; v1 used a hard min/max)
            f"Bhi hi vn V=0.005+{_softplus('v(vp,vn)-0.01', 0.002)}\n"
            f"Blo c vn V=0.005+{_softplus('v(x,vn)-0.005', 0.002)}\n"
            f"Bo o vn V=v(hi,vn)-{_softplus('v(hi,vn)-v(c,vn)', 0.002)}\n"
            "Ro o out 30\n"
            ".ends PCB_OPAMP"),
    datasheet=(
        "# OPAMP — single rail-to-rail I/O operational amplifier (SOT-23-5)\n\n"
        "## Pinout\n| Pin | Pad | Function |\n|---|---|---|\n"
        "| OUT | 1 | output |\n| V- | 2 | negative supply (GND in single-supply use) |\n"
        "| IN+ | 3 | non-inverting input |\n| IN- | 4 | inverting input |\n| V+ | 5 | positive supply |\n\n"
        "## Electrical characteristics\n- Supply 1.8–5.5 V (V+ - V-); quiescent current 100 µA\n"
        "- Open-loop gain 100 dB (1e5); gain-bandwidth product 1 MHz (single pole)\n"
        "- Rail-to-rail input and output (output swings to within 5 mV of the rails, Rout 30 Ω)\n"
        "- Input bias current < 1 pA; input offset modelled as 0\n\n"
        "## Application notes\n- Non-inverting gain: G = 1 + Rf / Rg (Rf from OUT to IN-, Rg from IN- to ground).\n"
        "- Inverting gain: G = -Rf / Rin. In single-supply use bias IN+ at mid-supply (e.g. a\n"
        "  resistor divider from V+ bypassed with a capacitor) and AC-couple the input.\n"
        "- Closed-loop bandwidth ≈ 1 MHz / (noise gain).\n"
        "- Decouple V+ with 100 nF ceramic (47 nF–10 µF) to ground within 5 mm of the pin.\n"
    ),
))

# --------------------------------------------------------------------------- MCU8

MCU_PIN_C = 5e-12

# Datasheet limits / recommended ranges, shared by the datasheet text above/below and the families'
# value bounds (QA F1: a value bound must never be tighter than the datasheet's own range).
LED_IMAX = 0.025                 # LED_*: max continuous forward current
GPIO_IMAX = 8e-3                 # MCU8: max GPIO source/sink current
I2C_SINK_MAX, I2C_VOL = 3e-3, 0.4  # MCU8 open-drain sink limit at VOL
I2C_RISE_LEVELS = (0.3, 0.7)     # UM10204 rise-time definition
# single-pole RC: t(level) = -RC ln(1 - level), so 30 -> 70 % takes ln(0.7/0.3) RC = 0.8473 RC
I2C_K_RISE = math.log((1 - I2C_RISE_LEVELS[0]) / (1 - I2C_RISE_LEVELS[1]))
MCU_DECOUPLING = (47e-9, 10e-6)  # MCU8 / OPAMP: 100 nF typical
MCU_NRST_PULLUP = (2.2e3, 100e3)
MCU_RESET_CAP = (10e-9, 1e-6)
LDO_CAP = (1e-6, 22e-6)          # LDO_ADJ in/out capacitor (output: loop stability range)
LDO_RBOT_TYP = (10e3, 50e3)
NPN_BASE_PULLDOWN = (10e3, 100e3)
NMOS_GATE_SERIES = (10.0, 100.0)
NMOS_GATE_PULLDOWN = (10e3, 100e3)

register(Part(
    name="MCU8", description="generic 8-pin microcontroller, SOIC-8",
    pins={
        "NRST": PinInfo("1", "input"), "PA1": PinInfo("2", "bidir", False), "PA2": PinInfo("3", "bidir", False),
        "GND": PinInfo("4", "power_in"), "SDA": PinInfo("5", "bidir", False), "PA0": PinInfo("6", "bidir", False),
        "SCL": PinInfo("7", "bidir", False), "VDD": PinInfo("8", "power_in"),
    },
    footprints=["Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"],
    value_required=False,
    spice=lambda ref, n, v: f"X{ref} {n['NRST']} {n['PA1']} {n['PA2']} {n['GND']} {n['SDA']} {n['PA0']} {n['SCL']} {n['VDD']} PCB_MCU8",
    models=(".subckt PCB_MCU8 nrst pa1 pa2 vss sda pa0 scl vdd\n"
            "Rdd vdd vss 2.2k\nCdd vdd vss 50p\n"
            + "".join(f"C{p} {p} vss {MCU_PIN_C:g}\n" for p in ("nrst", "pa1", "pa2", "sda", "pa0", "scl"))
            + ".ends PCB_MCU8"),
    datasheet=(
        "# MCU8 — generic 8-pin microcontroller (SOIC-8)\n\n"
        "## Pinout\n| Pin | Pad | Function |\n|---|---|---|\n"
        "| NRST | 1 | active-low reset input. **No internal pull-up**: needs an external pull-up to VDD, 2.2k–100k (10k typical); optional 10 nF–1 µF to GND (100 nF typical) for a power-on reset delay |\n"
        "| PA1 | 2 | GPIO / ADC1 / XIN (crystal oscillator input) |\n| PA2 | 3 | GPIO / ADC2 / XOUT (crystal oscillator output) |\n"
        "| GND | 4 | ground |\n| SDA | 5 | I2C data (open-drain) / GPIO |\n| PA0 | 6 | GPIO / PWM output / ADC0 |\n"
        "| SCL | 7 | I2C clock (open-drain) / GPIO |\n| VDD | 8 | supply 1.8–5.5 V |\n\n"
        "## Electrical characteristics\n- Supply current 1.5 mA typ at 3.3 V\n"
        "- GPIO output: VOH ≥ VDD - 0.4 V at 8 mA source (≈50 Ω output resistance); 8 mA max per pin\n"
        "- Open-drain I2C pins sink max 3 mA at VOL = 0.4 V; no internal I2C pull-ups\n"
        "- ADC (PA0, PA1, PA2): 12-bit, full scale = VDD, input range 0..VDD (never above VDD); the pin\n"
        "  is high impedance (5 pF), so an RC anti-alias filter at the pin sets the input bandwidth\n"
        f"- Pin capacitance {MCU_PIN_C*1e12:.0f} pF per I/O; idle / reset I/O pins are high-impedance (no pulls)\n"
        "- Crystal oscillator: 4–25 MHz fundamental crystal between XIN (PA1) and XOUT (PA2), each pin\n"
        "  with a load capacitor to GND\n\n"
        "## Application notes\n- Decouple VDD with 100 nF ceramic (47 nF–10 µF) to GND within 5 mm of the VDD pin.\n"
        "- I2C pull-ups: Rp ≥ (VDD - 0.4 V) / 3 mA (sink limit) and Rp ≤ tr / (0.8473 × Cbus) (rise time),\n"
        "  where tr is the I2C rise time as defined by the I2C specification (UM10204): 30 % to 70 % of\n"
        "  VDD, max 1000 ns standard-mode / 300 ns fast-mode; 0.8473 = ln(0.7/0.3). Cbus includes\n"
        "  the 5 pF pin capacitance.\n"
        "- Crystal load caps: CL = C1·C2/(C1+C2) + Cstray, i.e. C1 = C2 = 2·(CL - Cstray).\n"
    ),
))

# --------------------------------------------------------------------------- crystals


def _xtal_spice(ref: str, n: dict[str, str], v: str) -> str:
    f = parse_value(v)
    cm = 15e-15
    lm = 1 / ((2 * math.pi * f) ** 2 * cm)
    a, b = n["1"], n["2"]
    return (f"R{ref}m {a} {ref}_x1 40\nL{ref}m {ref}_x1 {ref}_x2 {lm:.6g}\n"
            f"C{ref}m {ref}_x2 {b} {cm:g}\nC{ref}0 {a} {b} 3p")


XTAL_CL = {"XTAL": 12e-12, "XTAL_CL18": 18e-12}

for _name, _cl in XTAL_CL.items():
    register(Part(
        name=_name, description=f"2-pin quartz crystal, CL = {_cl*1e12:.0f} pF",
        pins={"1": PinInfo("1", "passive"), "2": PinInfo("2", "passive")},
        footprints=["Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm", "Crystal:Crystal_SMD_2012-2Pin_2.0x1.2mm"],
        value_required=True,
        spice=_xtal_spice,
        extra={"cl": _cl},
        datasheet=(
            f"# {_name} — 2-pin fundamental-mode quartz crystal\n\n"
            "## Pinout\n| Pin | Pad | Function |\n|---|---|---|\n| 1 | 1 | crystal terminal |\n| 2 | 2 | crystal terminal |\n\n"
            "(Non-polarised.) Value = nominal frequency, e.g. `16M`.\n\n"
            "## Electrical characteristics\n"
            f"- **Rated load capacitance CL = {_cl*1e12:.0f} pF**\n- Frequency tolerance ±20 ppm at rated CL\n"
            "- ESR ≤ 60 Ω; shunt capacitance C0 = 3 pF; drive level ≤ 100 µW\n\n"
            "## Application notes\n- Pierce oscillator: one load capacitor from each crystal pin to GND.\n"
            "  Effective load CL_eff = C1·C2/(C1+C2) + Cstray (Cstray = MCU pin + PCB capacitance).\n"
            f"  For C1 = C2: C = 2·(CL - Cstray). Must be within ±10 % of {_cl*1e12:.0f} pF or the oscillator runs off-frequency.\n"
            "- Keep traces short and the load capacitors next to the crystal.\n"
        ),
    ))

# --------------------------------------------------------------------------- inductor

register(Part(
    name="L", description="SMD power/filter inductor",
    pins={"1": PinInfo("1", "passive"), "2": PinInfo("2", "passive")},
    footprints=["Inductor_SMD:L_0805_2012Metric", "Inductor_SMD:L_1206_3216Metric"],
    value_required=True,
    spice=lambda ref, n, v: f"L{ref} {n['1']} {ref}_dcr {parse_value(v):.6g}\nR{ref}dcr {ref}_dcr {n['2']} 0.05",
    datasheet=(
        "# L — SMD inductor\n\n## Pinout\n| Pin | Pad | Function |\n|---|---|---|\n| 1 | 1 | terminal |\n| 2 | 2 | terminal |\n\n"
        "Non-polarised. Value in henries (e.g. `100u`).\n\n"
        "## Electrical characteristics\n- DCR 50 mΩ, saturation current 1 A, SRF well above 10 MHz\n\n"
        "## Application notes\n- LC low-pass: f0 = 1 / (2π·sqrt(L·C)); a series damping resistor R gives\n"
        "  Q = sqrt(L/C) / R (Q ≈ 0.707 for a maximally-flat response).\n"
    ),
))
