# QA packet 075: `pcbr2-hard-b4a48a20`

| family | tier | tool mode | hint level | intent in TASK.md | faults | latent | predicted difficulty |
|---|---|---|---|---|---|---|---|
| sys_analog_frontend | hard | full | vague | full | 4 | 2 |  |

Task files: [`../../../tasks/v2/hard/pcbr2-hard-b4a48a20/public/`](../../../tasks/v2/hard/pcbr2-hard-b4a48a20/public/) (what the agent gets) and [`../../../tasks/v2/hard/pcbr2-hard-b4a48a20/hidden/`](../../../tasks/v2/hard/pcbr2-hard-b4a48a20/hidden/) (grader only). Why sampled: vague hint, connectivity fault, disputable type bias_wrong_rail, disputable type bom_mismatch, value near bounds: C5=220n inside [4.7e-08, 1e-05], 2 latent (bias_wrong_rail, decap_wrong_rail).

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 2-channel analog front end (15 V in)

## Problem report

The first boards built from these files fail bring-up. Find and fix all problems: the design must meet its purpose and spec, the layout must match design.json, and DRC/ERC must be clean.

## Design intent

# Two-channel analog front end

Conditions two DC-coupled sensor signals (input header J2) for an off-board ADC (header J3): each
channel is a single-supply non-inverting op-amp gain stage followed by an RC anti-alias filter. LDO
U1 makes the +5V analog rail (5 V) from the 15 V input on J1; the rail also
supplies the ADC board through J3 pin 1.

Rails: +15 V (from J1) -> reverse-polarity diode -> VIN -> U1 -> +5V = 5 V.

## Connectors

| Connector | Pin | Signal |
|---|---|---|
| J1 | 1 | +15 V input |
| J1 | 2 | GND |
| J2 | 1 | channel 1 sensor input |
| J2 | 2 | GND |
| J2 | 3 | channel 2 sensor input |
| J3 | 1 | +5V (ADC supply / reference) |
| J3 | 2 | GND |
| J3 | 3 | channel 1 to ADC |
| J3 | 4 | channel 2 to ADC |

## Circuit

- Reverse-polarity protection: Schottky D1 in series with the input, anode to J1 pin 1, cathode to the protected input rail VIN.
- U1 (LDO_ADJ) regulates the 15 V input down to the 5 V rail +5V: C1 is its input capacitor (VIN to GND) and C2 its output capacitor (VOUT to GND), each at its pin; R1 from VOUT to FB and R2 from FB to GND set VOUT = 0.8 V x (1 + R1/R2); EN is tied to the input (always on).
- Channel 1: J2 pin 1 -> IN+ of op-amp U2 (R3 from IN+ to GND defines the input); R4 from OUT to IN- and R5 from IN- to GND set G = 1 + R4/R5; R6 from OUT to the ADC pin J3 pin 3 with C4 from there to GND is the anti-alias filter; C3 decouples V+ at the pin.
- Channel 2: J2 pin 3 -> IN+ of op-amp U3 (R7 from IN+ to GND defines the input); R8 from OUT to IN- and R9 from IN- to GND set G = 1 + R8/R9; C6 across R8 limits the bandwidth; R10 from OUT to the ADC pin J3 pin 4 with C7 from there to GND is the anti-alias filter; C5 decouples V+ at the pin.
- power indicator: R11 from +5V to the anode of D2, cathode to GND.

## Spec

Channel 1: gain 5.017 ±3 % at 100 Hz (G = 5.02); DC-coupled (0.3952 V in -> 1.99 V out); -3 dB bandwidth 1950 Hz ±10 % (anti-alias filter).

Channel 2: gain 4.894 ±3 % at 100 Hz (G = 5.01); DC-coupled (0.3964 V in -> 1.99 V out); -3 dB bandwidth 458.9 Hz ±10 % (anti-alias filter).

Power indicator current 2.04 mA ±15 %.

Rail +5V: 5 V ±3 % with 10 mA drawn by the ADC board from J3 pin 1, for inputs from 6 V to 15 V.

Component values: C1, C2 1 µF–22 µF (LDO datasheet); feedback Rbot R2 3.3 kΩ–150 kΩ (10k–50k typical) with R1 scaled to match; channel 1: decoupling C3 47 nF–10 µF; input bias R3 47 kΩ–2.2 MΩ; channel 2: decoupling C5 47 nF–10 µF; input bias R7 47 kΩ–2.2 MΩ.

Sub-circuits by purpose: input reverse-polarity protection (D1); 5 V regulator with input/output capacitors and feedback divider (U1, C1, C2, R1, R2); channel 1 op-amp with supply decoupling (U2, C3); channel 1 input bias and gain network (R3, R4, R5); channel 1 anti-alias filter (R6, C4); channel 2 op-amp with supply decoupling (U3, C5); channel 2 input bias and gain network (R7, R8, R9, C6); channel 2 anti-alias filter (R10, C7); power indicator LED with series resistor (D2, R11); supply connector (J1); sensor input connector (J2); ADC header (J3).

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `ch1_gain`: AC gain |V(J3.3)/V(J2.1)| at 100 Hz between 4.866 and 5.167 (J1.1 supplied with 15.0 V; 0.3952 V DC + 1.0 V AC source on J2.1; ground = J1.2)
- `ch1_dc_out`: DC voltage at J3.3 between 1.921 V and 2.05 V (J1.1 supplied with 15.0 V; 0.3952 V DC + 1.0 V AC source on J2.1; ground = J1.2)
- `ch1_bandwidth`: -3 dB frequency from J2.1 to J3.3 between 1.755 kHz and 2.145 kHz (J1.1 supplied with 15.0 V; 0.3952 V DC + 1.0 V AC source on J2.1; ground = J1.2)
- `ch2_gain`: AC gain |V(J3.4)/V(J2.3)| at 100 Hz between 4.747 and 5.041 (J1.1 supplied with 15.0 V; 0.3964 V DC + 1.0 V AC source on J2.3; ground = J1.2)
- `ch2_dc_out`: DC voltage at J3.4 between 1.921 V and 2.05 V (J1.1 supplied with 15.0 V; 0.3964 V DC + 1.0 V AC source on J2.3; ground = J1.2)
- `ch2_bandwidth`: -3 dB frequency from J2.3 to J3.4 between 413 Hz and 504.7 Hz (J1.1 supplied with 15.0 V; 0.3964 V DC + 1.0 V AC source on J2.3; ground = J1.2)
- `power_led_current`: DC current through D2 between 1.735 mA and 2.347 mA (J1.1 supplied with 15.0 V; ground = J1.2)
- `5v_rail`: DC voltage at J3.1 between 4.85 V and 5.15 V (J1.1 supplied with 15.0 V; load R=500 from J3.1 to ground; ground = J1.2)
- `5v_rail_low_vin`: DC voltage at J3.1 between 4.85 V and 5.15 V (J1.1 supplied with 6.0 V; load R=500 from J3.1 to ground; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- +5V (the net of J3.1): ≥ 0.3 mm
- GND (the net of J1.2): ≥ 0.3 mm
- VIN (the net of C1.1): ≥ 0.3 mm
- VIN_RAW (the net of J1.1): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 1 uF … 22 uF
- C2 (C): 1 uF … 22 uF
- C3 (C): 47 nF … 10 uF
- C4 (C): 3.2 nF … 42 nF
- C5 (C): 47 nF … 10 uF
- C6 (C): 310 pF … 2.7 nF
- C7 (C): 26 nF … 230 nF
- R1 (R): 17 kΩ … 790 kΩ
- R10 (R): 1.9 kΩ … 18 kΩ
- R11 (R): 110 Ω … 4.4 kΩ
- R2 (R): 3.3 kΩ … 150 kΩ
- R3 (R): 47 kΩ … 2.2 MΩ
- R4 (R): 9.2 kΩ … 100 kΩ
- R5 (R): 1.8 kΩ … 18 kΩ
- R6 (R): 1.8 kΩ … 22 kΩ
- R7 (R): 47 kΩ … 2.2 MΩ
- R8 (R): 1.2 kΩ … 15 kΩ
- R9 (R): 320 Ω … 4.5 kΩ

Board rules: 2 copper layers, clearance 0.2 mm, min track 0.2 mm, vias 0.6/0.3 mm, copper-to-edge 0.3 mm. DRC must be clean with no unconnected items.

## Design rules (design review)

Besides the spec, the design must pass an engineering design review. **`pcbtool` does not check any
of this — review the design yourself** against the datasheets in `parts/` (see each part's ratings /
design-rule section) and the design intent:

- **Absolute maximum ratings** of every part under every operating condition of the spec (no MCU pin
  above its VDD + 0.3 V or below -0.3 V, op-amp inputs within the rails, LDO EN ≤ VIN, MOSFET |VGS|,
  transistor / diode voltage and current limits).
- **Current limits:** MCU pin currents, LED forward current (by LED package), transistor collector /
  base currents; a saturated NPN switch needs a forced beta IC/IB ≤ 20.
- **Power / voltage ratings:** every resistor's I²R ≤ 50 % of its footprint's rating; every capacitor's
  working voltage ≤ 80 % of its footprint's rated voltage. Footprint choice matters.
- **Inductive loads** have a flyback diode directly across the load, cathode to the supply side.
- **Interfaces and pin assignments** stated in the design intent (connector pinouts, MCU pin functions,
  which rail each part connects to) must be respected exactly, even where the circuit would still
  simulate with a different assignment.

The grader checks these rules under the spec's operating conditions. A design can pass every
`pcbtool` check and still fail review.

**Decoupling** (graded as part of `layout`; `pcbtool` does not check it, `spec.json` lists it under `design_rules`): each capacitor's pad on the IC pin's net must reach that pin within the given length of copper path (shortest path along the net's tracks, vias and pads, pad centre to pad centre), and every pad of the capacitor must lie within the given straight-line distance of the pin:

- C1 within 8.0 mm of copper path of U1.VIN (and within 5.0 mm straight-line)
- C2 within 8.0 mm of copper path of U1.VOUT (and within 5.0 mm straight-line)
- C3 within 8.0 mm of copper path of U2.V+ (and within 5.0 mm straight-line)
- C5 within 8.0 mm of copper path of U3.V+ (and within 5.0 mm straight-line)

## Deliverable

- Edit only `design.json` (the schematic of record) and `board.kicad_pcb` (the layout).
- Do not add, remove or rename components; keep each component's part.
- Keep the two files consistent: same connectivity, values and footprints on both.
- Values: `<number><SI prefix><unit>` such as `4.7k`, `100n`, `10kΩ`, `1meg`; unit letters, if any, must match the part (R: Ω/ohm/R, C: F, L: H, crystal: Hz); no spaces or control characters inside (full grammar: "Value notation" in `parts/R.md`, `parts/C.md`, ...).
- Do not change the board outline, add zones, or add DRC exclusions.
- Footprints must be unmodified library footprints from the part's allowed list (see `parts/<PART>.md`).
- Grading is pass/fail: topology, consistency, DRC, ERC, spec, component values, layout and the design rules above must all pass.

## Tools

Run `pcbtool <command>` inside this directory (you may also edit the two files directly).

Read-only:
- `pcbtool show` — components, values, footprints, positions and nets
- `pcbtool netlist` — design nets vs. board pad nets, with differences highlighted
- `pcbtool drc` — KiCad DRC under the canonical rules (the same rules the grader uses)
- `pcbtool erc` — electrical rule check of design.json
- `pcbtool sim` — run the spec assertions (spec.json) on design.json
- `pcbtool parts [PART]` — list parts / print a part's datasheet (also in `parts/`)
- `pcbtool check` — all of the above in one summary

Mutating (each keeps design.json and board.kicad_pcb consistent and saves both):
- `pcbtool set-value REF VALUE`
- `pcbtool set-footprint REF LIB:FOOTPRINT`
- `pcbtool connect REF.PIN NET` / `pcbtool disconnect REF.PIN`
- `pcbtool move REF X Y ROT` (absolute mm, degrees; tracks do not follow)
- `pcbtool unroute NET` / `pcbtool route NET [--width W]` (re-routes the whole net)
- `pcbtool sync` — push design.json connectivity and values onto the board pads
````

### 1.2 Public files

The agent also gets `design.json`, `board.kicad_pcb`, `spec.json` and the part datasheets below, plus the `pcbtool` commands listed in TASK.md (DRC, ERC, simulation of the public assertions, value-range check). Renders of the faulted files:

![faulted schematic](schematic_faulted.svg)

![faulted board](board_faulted.svg)

<details><summary>Datasheet <code>parts/C.md</code></summary>

````markdown
# C — ceramic capacitor

Two-terminal non-polarised capacitor. Pins `1`, `2`. Value in farads.

## Value notation (all parts)

A value is `<number><SI prefix?><unit?>`, e.g. `4.7k`, `100n`, `2.2u`, `10R`, `1meg`, `1.5e3`:
- number: digits with an optional decimal point and an optional exponent (`1e3`); no sign, no
  digit grouping, no RKM notation (`4k7`);
- SI prefix (case-sensitive): `p` `n` `u`/`µ`/`μ` (micro) `m` (milli) `k`/`K` `M`/`meg`/`MEG` (mega) `G`;
  an exponent and a prefix together (`1e3k`) are rejected;
- unit letters, optional, must match the part: R `Ω`/`ohm`/`Ohm`/`R`; C `F`; L `H`; crystals `Hz`;
  other parts none (`100nH` on a capacitor is rejected);
- no whitespace or control characters inside the value (leading/trailing spaces are ignored).

design.json and the board must carry the same value; they are compared as numbers (`1k` == `1000`).

## Ratings by footprint (X7R series used on this board)

| Size | Rated voltage | Design limit (80 %) |
|---|---|---|
| 0603 | 10 V | 8 V |
| 0805 | 25 V | 20 V |
| 1206 | 50 V | 40 V |

**Design rule:** the DC working voltage across a capacitor must not exceed 80 % of its rated voltage
(MLCC capacitance collapses and reliability drops near the rating). The rating follows the footprint.
````

</details>

<details><summary>Datasheet <code>parts/CONN2.md</code></summary>

````markdown
# CONN2 — 2-pin header

Pin `1` = signal/supply, pin `2` = ground by board convention.

## Interface rule
The pin assignment of every connector is fixed by the design intent (cable / mating board):
swapping two connector pins breaks the interface even if the board itself still simulates.
````

</details>

<details><summary>Datasheet <code>parts/CONN3.md</code></summary>

````markdown
# CONN3 — 3-pin 2.54 mm header

Generic vertical pin header used for off-board power, signal and bus connections.

| Pin | Pad | Typical use |
|---|---|---|
| 1 | 1 | signal / supply |
| 2 | 2 | ground (board convention) |
| 3 | 3 | signal / supply |

## Notes
- Pin 2 is ground by board convention; the function of the other pins is set by the design.
- Rated 3 A per contact. Has no electrical model of its own (it is where external
  supplies, signals and loads attach).

## Interface rule
The pin assignment of every connector is fixed by the design intent (cable / mating board):
swapping two connector pins breaks the interface even if the board itself still simulates.
````

</details>

<details><summary>Datasheet <code>parts/CONN4.md</code></summary>

````markdown
# CONN4 — 4-pin 2.54 mm header

Generic vertical pin header used for off-board power, signal and bus connections.

| Pin | Pad | Typical use |
|---|---|---|
| 1 | 1 | signal / supply |
| 2 | 2 | ground (board convention) |
| 3 | 3 | signal / supply |
| 4 | 4 | signal / supply |

## Notes
- Pin 2 is ground by board convention; the function of the other pins is set by the design.
- Rated 3 A per contact. Has no electrical model of its own (it is where external
  supplies, signals and loads attach).

## Interface rule
The pin assignment of every connector is fixed by the design intent (cable / mating board):
swapping two connector pins breaks the interface even if the board itself still simulates.
````

</details>

<details><summary>Datasheet <code>parts/D_SCHOTTKY.md</code></summary>

````markdown
# D_SCHOTTKY — 40 V / 1 A Schottky rectifier

## Pinout
| Pin | Pad | Function |
|---|---|---|
| A | 2 | anode |
| K | 1 | cathode (band) |

## Electrical characteristics
- VRRM 40 V, IF(AV) 1 A
- Vf = 0.30 V typ at 100 mA, 0.40 V at 1 A
- Reverse leakage 20 uA typ at 25 V

## Application notes
- Flyback / freewheel clamp across an inductive load (relay coil, solenoid, motor):
  cathode to the positive supply side, anode to the switched (transistor) side. In normal
  operation the diode is reverse biased; at turn-off it clamps the inductive kick.
- Reverse polarity protection: in series with the supply, anode to the input.

## Absolute maximum ratings
- Reverse voltage 40 V, forward current 1 A continuous.

**Design rule (inductive loads):** every inductive load (relay coil, solenoid, motor) must have a
flyback diode directly across it with the cathode on the load's supply-side terminal and the
anode on its switched terminal. A diode elsewhere (to ground, across the transistor, both ends
on one net) does not clamp the turn-off spike, even though nothing is visible in DC.
````

</details>

<details><summary>Datasheet <code>parts/LDO_ADJ.md</code></summary>

````markdown
# LDO_ADJ — adjustable 300 mA low-dropout regulator (SOT-23-5)

## Pinout
| Pin | Pad | Function |
|---|---|---|
| VIN | 1 | input supply, 2.5–16 V |
| GND | 2 | ground |
| EN | 3 | enable, active high. Internal 2 MΩ pull-down: floating = OFF |
| FB | 4 | feedback; regulates to VREF = 0.800 V |
| VOUT | 5 | regulated output |

## Electrical characteristics
- VREF = 0.800 V ±1 %
- Output current 300 mA max; current limit ~500 mA
- Dropout 250 mV typ at 300 mA
- EN threshold 1.2 V (high = on); EN low or floating -> output off (0 V)
- Quiescent current 50 µA; package dissipation max 0.5 W

## Application notes
- Output voltage is set by a divider from VOUT to FB (Rtop) and FB to GND (Rbot):
  **VOUT = VREF × (1 + Rtop / Rbot)**. Rbot of 10k–50k is typical.
- Connect EN to VIN for always-on operation (or drive it from logic / a pull-up). A pull-up
  Rpu from VIN forms a divider with the internal 2 MΩ pull-down: VIN·2M/(Rpu + 2M) must exceed
  the 1.2 V threshold at the lowest VIN.
- Place a 1 µF–22 µF ceramic input capacitor and a 1 µF–22 µF ceramic output capacitor (the
  output capacitor range is the stability range of the regulation loop) within
  5 mm of the VIN and VOUT pins respectively, returned to GND.
- Power dissipation = (VIN - VOUT) × IOUT must stay below 0.5 W.

## Absolute maximum ratings
- VIN 16 V; EN ≤ VIN + 0.3 V (EN must never be above VIN); output current 300 mA;
  package dissipation (VIN - VOUT)·IOUT ≤ 0.5 W.
````

</details>

<details><summary>Datasheet <code>parts/LED_RED.md</code></summary>

````markdown
# LED_RED — red SMD indicator LED (625 nm)

## Pinout
| Pin | Pad | Function |
|---|---|---|
| A | 2 | anode |
| K | 1 | cathode (marked) |

## Electrical characteristics (25 C)
- Forward voltage Vf = 2.0 V typ at IF = 10 mA
- Max continuous forward current 25 mA; reverse voltage max 5 V

| IF | Vf (typ) |
|---|---|
| 2 mA | 1.90 V |
| 5 mA | 1.95 V |
| 10 mA | 2.00 V |
| 15 mA | 2.03 V |
| 20 mA | 2.06 V |

## Application notes
- Always drive through a current-limiting resistor: R = (Vsupply - n*Vf) / IF for n LEDs in series.
- Current flows anode -> cathode; reversed LEDs do not light.

## Ratings by package

| Package | Max continuous IF | Design limit (80 %) |
|---|---|---|
| 0603 | 20 mA | 16 mA |
| 0805 | 30 mA | 24 mA |

**Design rule:** the forward current must not exceed 80 % of the package maximum; reverse voltage
≤ 5 V.
````

</details>

<details><summary>Datasheet <code>parts/OPAMP.md</code></summary>

````markdown
# OPAMP — single rail-to-rail I/O operational amplifier (SOT-23-5)

## Pinout
| Pin | Pad | Function |
|---|---|---|
| OUT | 1 | output |
| V- | 2 | negative supply (GND in single-supply use) |
| IN+ | 3 | non-inverting input |
| IN- | 4 | inverting input |
| V+ | 5 | positive supply |

## Electrical characteristics
- Supply 1.8–5.5 V (V+ - V-); quiescent current 100 µA
- Open-loop gain 100 dB (1e5); gain-bandwidth product 1 MHz (single pole)
- Rail-to-rail input and output (output swings to within 5 mV of the rails, Rout 30 Ω)
- Input bias current < 1 pA; input offset modelled as 0

## Application notes
- Non-inverting gain: G = 1 + Rf / Rg (Rf from OUT to IN-, Rg from IN- to ground).
- Inverting gain: G = -Rf / Rin. In single-supply use bias IN+ at mid-supply (e.g. a
  resistor divider from V+ bypassed with a capacitor) and AC-couple the input.
- Closed-loop bandwidth ≈ 1 MHz / (noise gain).
- Decouple V+ with 100 nF ceramic (47 nF–10 µF) to ground within 5 mm of the pin.

## Absolute maximum ratings
- Supply V+ - V- ≤ 5.5 V; input pins within [V- - 0.3 V, V+ + 0.3 V].
````

</details>

<details><summary>Datasheet <code>parts/R.md</code></summary>

````markdown
# R — resistor

Two-terminal resistor. Pins `1`, `2` (non-polarised). Value in ohms.

## Value notation (all parts)

A value is `<number><SI prefix?><unit?>`, e.g. `4.7k`, `100n`, `2.2u`, `10R`, `1meg`, `1.5e3`:
- number: digits with an optional decimal point and an optional exponent (`1e3`); no sign, no
  digit grouping, no RKM notation (`4k7`);
- SI prefix (case-sensitive): `p` `n` `u`/`µ`/`μ` (micro) `m` (milli) `k`/`K` `M`/`meg`/`MEG` (mega) `G`;
  an exponent and a prefix together (`1e3k`) are rejected;
- unit letters, optional, must match the part: R `Ω`/`ohm`/`Ohm`/`R`; C `F`; L `H`; crystals `Hz`;
  other parts none (`100nH` on a capacitor is rejected);
- no whitespace or control characters inside the value (leading/trailing spaces are ignored).

design.json and the board must carry the same value; they are compared as numbers (`1k` == `1000`).

## Ratings by footprint (high-power thick-film series used on this board)

| Size | Rated power (70 C) | Design limit (50 % derating) |
|---|---|---|
| 0603 | 0.1 W | 50.0 mW |
| 0805 | 0.125 W | 62.5 mW |
| 1206 | 0.5 W | 250.0 mW |

**Design rule:** the continuous dissipation P = I²·R of every resistor must not exceed 50 % of its
footprint's rated power. Pick the footprint for the power, not just the value.
````

</details>

## 2. Reviewer-only (hidden from the agent)

### 2.1 Injected faults

| # | type | category | DRC/ERC-invisible | latent (pcbtool-clean) | detail | verifier, this fault alone |
|---|---|---|---|---|---|---|
| 1 | `bias_wrong_rail` | latent | yes | **yes** | C4.2 returned to VIN_RAW instead of GND | reward 0.0; fails topology |
| 2 | `decap_wrong_rail` | latent | yes | **yes** | C3 sits at U2.V+ but decouples VIN instead of +5V | reward 0.0; fails layout, topology |
| 3 | `swapped_ic_pins` | connectivity | yes |  | U2.IN+ and U2.IN- connections exchanged | reward 0.0; fails spec, topology |
| 4 | `bom_mismatch` | value | yes |  | board value of C5 is 220n, design.json says 100n | reward 0.0; fails consistency |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- none

**design.json: connection changes** (per pin: what it connects to)

- `C3.1`: faulted net `VIN` (C1.1, D1.K, U1.EN, U1.VIN) → golden net `+5V` (C2.1, C5.1, J3.1, R1.1, R11.1, U1.VOUT, U2.V+, U3.V+)
- `C4.2`: faulted net `VIN_RAW` (D1.A, J1.1) → golden net `GND` (C1.2, C2.2, C3.2, C5.2, C7.2, D2.K, J1.2, J2.2, J3.2, R2.2, R3.2, R5.2, R7.2, R9.2, U1.GND, U2.V-, U3.V-)
- `U2.IN+`: faulted net `Net-(R4-Pad2)` (R4.2, R5.1) → golden net `IN1` (J2.1, R3.1)
- `U2.IN-`: faulted net `Net-(J2-Pad1)` (J2.1, R3.1) → golden net `FB1` (R4.2, R5.1)

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- `C5` board value `220n` → `100n`

**board.kicad_pcb: pad-net changes**

- `C3` pad 1: net `VIN` → `+5V`
- `C4` pad 1: net `Net-(C4-Pad1)` → `ADC1`
- `C4` pad 2: net `VIN_RAW` → `GND`
- `C6` pad 1: net `Net-(C6-Pad1)` → `AMP2`
- `C6` pad 2: net `Net-(C6-Pad2)` → `FB2`
- `C7` pad 1: net `Net-(C7-Pad1)` → `ADC2`
- `D2` pad 2: net `Net-(D2-Pad2)` → `LED_D2_A`
- `J2` pad 1: net `Net-(J2-Pad1)` → `IN1`
- `J2` pad 3: net `Net-(J2-Pad3)` → `IN2`
- `J3` pad 3: net `Net-(C4-Pad1)` → `ADC1`
- `J3` pad 4: net `Net-(C7-Pad1)` → `ADC2`
- `R1` pad 2: net `Net-(R1-Pad2)` → `FB_U1`
- `R10` pad 1: net `Net-(C6-Pad1)` → `AMP2`
- `R10` pad 2: net `Net-(C7-Pad1)` → `ADC2`
- `R11` pad 2: net `Net-(D2-Pad2)` → `LED_D2_A`
- `R2` pad 1: net `Net-(R1-Pad2)` → `FB_U1`
- `R3` pad 1: net `Net-(J2-Pad1)` → `IN1`
- `R4` pad 1: net `Net-(R4-Pad1)` → `AMP1`
- `R4` pad 2: net `Net-(R4-Pad2)` → `FB1`
- `R5` pad 1: net `Net-(R4-Pad2)` → `FB1`
- `R6` pad 1: net `Net-(R4-Pad1)` → `AMP1`
- `R6` pad 2: net `Net-(C4-Pad1)` → `ADC1`
- `R7` pad 1: net `Net-(J2-Pad3)` → `IN2`
- `R8` pad 1: net `Net-(C6-Pad1)` → `AMP2`
- `R8` pad 2: net `Net-(C6-Pad2)` → `FB2`
- `R9` pad 1: net `Net-(C6-Pad2)` → `FB2`
- `U1` pad 4: net `Net-(R1-Pad2)` → `FB_U1`
- `U2` pad 1: net `Net-(R4-Pad1)` → `AMP1`
- `U2` pad 3: net `Net-(R4-Pad2)` → `IN1`
- `U2` pad 4: net `Net-(J2-Pad1)` → `FB1`
- `U3` pad 1: net `Net-(C6-Pad1)` → `AMP2`
- `U3` pad 3: net `Net-(J2-Pad3)` → `IN2`
- `U3` pad 4: net `Net-(C6-Pad2)` → `FB2`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `+5V`: 9 track/via item(s) removed, 12 added
- net `ADC1`: 0 track/via item(s) removed, 3 added
- net `ADC2`: 0 track/via item(s) removed, 8 added
- net `AMP1`: 0 track/via item(s) removed, 9 added
- net `AMP2`: 0 track/via item(s) removed, 11 added
- net `FB1`: 0 track/via item(s) removed, 5 added
- net `FB2`: 0 track/via item(s) removed, 7 added
- net `FB_U1`: 0 track/via item(s) removed, 3 added
- net `GND`: 19 track/via item(s) removed, 17 added
- net `IN1`: 0 track/via item(s) removed, 3 added
- net `IN2`: 0 track/via item(s) removed, 3 added
- net `LED_D2_A`: 0 track/via item(s) removed, 2 added
- net `Net-(C4-Pad1)`: 3 track/via item(s) removed, 0 added
- net `Net-(C6-Pad1)`: 11 track/via item(s) removed, 0 added
- net `Net-(C6-Pad2)`: 7 track/via item(s) removed, 0 added
- net `Net-(C7-Pad1)`: 8 track/via item(s) removed, 0 added
- net `Net-(D2-Pad2)`: 2 track/via item(s) removed, 0 added
- net `Net-(J2-Pad1)`: 14 track/via item(s) removed, 0 added
- net `Net-(J2-Pad3)`: 3 track/via item(s) removed, 0 added
- net `Net-(R1-Pad2)`: 3 track/via item(s) removed, 0 added
- net `Net-(R4-Pad1)`: 9 track/via item(s) removed, 0 added
- net `Net-(R4-Pad2)`: 10 track/via item(s) removed, 0 added
- net `VIN`: 6 track/via item(s) removed, 0 added
- net `VIN_RAW`: 4 track/via item(s) removed, 0 added

Golden renders (compare with 1.2; highlighted items differ):

![golden schematic](schematic_golden.svg)

![golden board](board_golden.svg)

### 2.3 Verifier verdicts

Reward is 1 only if every gate and check passes.

| stage | kind | faulted files | golden files |
|---|---|---|---|
| parse | gate | pass | pass |
| components | gate | pass | pass |
| topology | gate | **FAIL** | pass |
| consistency | gate | **FAIL** | pass |
| integrity | gate | pass | pass |
| drc | check | pass | pass |
| erc | check | pass | pass |
| spec | check | **FAIL** | pass |
| values | check | pass | pass |
| layout | check | **FAIL** | pass |
| rules | check | pass | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **consistency**: C5: board value '220n' != design value '100n'
- **layout**: decoupling: C3 has no pad connected by copper to U2.V+
- **layout_skipped**: no board net has the pins of golden net +5V (connectivity differs: see topology)
- **layout_skipped**: no board net has the pins of golden net GND (connectivity differs: see topology)
- **layout_skipped**: no board net has the pins of golden net VIN (connectivity differs: see topology)
- **layout_skipped**: no board net has the pins of golden net VIN_RAW (connectivity differs: see topology)
- **spec**: ch1_gain: measured 5.955557284397138e-07 expected [4.86615, 5.16715]
- **spec**: ch1_dc_out: measured 0.0049958542065 expected [1.92073, 2.04984]
- **topology**: nets only in candidate: [['C1.1', 'C3.1', 'D1.K', 'U1.EN', 'U1.VIN'], ['C1.2', 'C2.2', 'C3.2', 'C5.2', 'C7.2', 'D2.K', 'J1.2', 'J2.2', 'J3.2', 'R2.2', 'R3.2', 'R5.2', 'R7.2', 'R9.2', 'U1.GND', 'U2.V-', 'U3.V-'], ['C2.1', 'C5.1', 'J3.1', 'R1.1', 'R11.1', 'U1.VOUT', 'U2.V+', 'U3.V+'], ['C4.2', 'D1.A', 'J1.1'], ['J2.1', 'R3.1', 'U2.IN-'], ['R4.2', 'R5.1', 'U2.IN+']]; nets only in reference: [['C1.1', 'D1.K', 'U1.EN', 'U1.VIN'], ['C1.2', 'C2.2', 'C3.2', 'C4.2', 'C5.2', 'C7.2', 'D2.K', 'J1.2', 'J2.2', 'J3.2', 'R2.2', 'R3.2', 'R5.2', 'R7.2', 'R9.2', 'U1.GND', 'U2.V-', 'U3.V-'], ['C2.1', 'C3.1', 'C5.1', 'J3.1', 'R1.1', 'R11.1', 'U1.VOUT', 'U2.V+', 'U3.V+'], ['D1.A', 'J1.1'], ['J2.1', 'R3.1', 'U2.IN+'], ['R4.2', 'R5.1', 'U2.IN-']]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `ch1_gain` | AC gain \|V(J3.3)/V(J2.1)\| at 100 Hz (J1.1 supplied with 15.0 V; 0.3952 V DC + 1.0 V AC source on J2.1; ground = J1.2) | 4.866 … 5.167 | 595.6 n | ❌ | 5.017 | ✅ |
| `ch1_dc_out` | DC voltage at J3.3 (J1.1 supplied with 15.0 V; 0.3952 V DC + 1.0 V AC source on J2.1; ground = J1.2) | 1.921 V … 2.05 V | 4.996 mV | ❌ | 1.985 V | ✅ |
| `ch1_bandwidth` | -3 dB frequency from J2.1 to J3.3 (J1.1 supplied with 15.0 V; 0.3952 V DC + 1.0 V AC source on J2.1; ground = J1.2) | 1.755 kHz … 2.145 kHz | 1.941 kHz | ✅ | 1.95 kHz | ✅ |
| `ch2_gain` | AC gain \|V(J3.4)/V(J2.3)\| at 100 Hz (J1.1 supplied with 15.0 V; 0.3964 V DC + 1.0 V AC source on J2.3; ground = J1.2) | 4.747 … 5.041 | 4.894 | ✅ | 4.894 | ✅ |
| `ch2_dc_out` | DC voltage at J3.4 (J1.1 supplied with 15.0 V; 0.3964 V DC + 1.0 V AC source on J2.3; ground = J1.2) | 1.921 V … 2.05 V | 1.986 V | ✅ | 1.986 V | ✅ |
| `ch2_bandwidth` | -3 dB frequency from J2.3 to J3.4 (J1.1 supplied with 15.0 V; 0.3964 V DC + 1.0 V AC source on J2.3; ground = J1.2) | 413 Hz … 504.7 Hz | 458.8 Hz | ✅ | 458.8 Hz | ✅ |
| `power_led_current` | DC current through D2 (J1.1 supplied with 15.0 V; ground = J1.2) | 1.735 mA … 2.347 mA | 2.039 mA | ✅ | 2.039 mA | ✅ |
| `5v_rail` | DC voltage at J3.1 (J1.1 supplied with 15.0 V; load R=500 from J3.1 to ground; ground = J1.2) | 4.85 V … 5.15 V | 4.96 V | ✅ | 4.96 V | ✅ |
| `5v_rail_low_vin` | DC voltage at J3.1 (J1.1 supplied with 6.0 V; load R=500 from J3.1 to ground; ground = J1.2) | 4.85 V … 5.15 V | 4.96 V | ✅ | 4.96 V | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 1 uF … 22 uF | `4.7u` | `4.7u` | `4.7u` |  |
| `C2` | C | 1 uF … 22 uF | `10u` | `10u` | `10u` |  |
| `C3` | C | 47 nF … 10 uF | `1u` | `1u` | `1u` | **yes** |
| `C4` | C | 3.2 nF … 42 nF | `12n` | `12n` | `12n` | **yes** |
| `C5` | C | 47 nF … 10 uF | `100n` | `220n` | `100n` | **yes** |
| `C6` | C | 310 pF … 2.7 nF | `820p` | `820p` | `820p` |  |
| `C7` | C | 26 nF … 230 nF | `68n` | `68n` | `68n` |  |
| `R1` | R | 17 kΩ … 790 kΩ | `102k` | `102k` | `102k` |  |
| `R10` | R | 1.9 kΩ … 18 kΩ | `5.1k` | `5.1k` | `5.1k` |  |
| `R11` | R | 110 Ω … 4.4 kΩ | `1.5k` | `1.5k` | `1.5k` |  |
| `R2` | R | 3.3 kΩ … 150 kΩ | `19.6k` | `19.6k` | `19.6k` |  |
| `R3` | R | 47 kΩ … 2.2 MΩ | `1M` | `1M` | `1M` |  |
| `R4` | R | 9.2 kΩ … 100 kΩ | `27.4k` | `27.4k` | `27.4k` |  |
| `R5` | R | 1.8 kΩ … 18 kΩ | `6.81k` | `6.81k` | `6.81k` |  |
| `R6` | R | 1.8 kΩ … 22 kΩ | `6.8k` | `6.8k` | `6.8k` |  |
| `R7` | R | 47 kΩ … 2.2 MΩ | `220k` | `220k` | `220k` |  |
| `R8` | R | 1.2 kΩ … 15 kΩ | `4.53k` | `4.53k` | `4.53k` |  |
| `R9` | R | 320 Ω … 4.5 kΩ | `1.13k` | `1.13k` | `1.13k` |  |

### 2.6 Layout rules

- power net `+5V` (golden pins C2.1, C3.1, C5.1, J3.1, R1.1, R11.1, U1.VOUT, U2.V+, U3.V+): every track ≥ 0.3 mm
- power net `GND` (golden pins C1.2, C2.2, C3.2, C4.2, C5.2, C7.2, D2.K, J1.2, J2.2, J3.2, R2.2, R3.2, R5.2, R7.2, R9.2, U1.GND, U2.V-, U3.V-): every track ≥ 0.3 mm
- power net `VIN` (golden pins C1.1, D1.K, U1.EN, U1.VIN): every track ≥ 0.3 mm
- power net `VIN_RAW` (golden pins D1.A, J1.1): every track ≥ 0.3 mm
- decoupling: `C1` within 8.0 mm of copper path (and 5.0 mm straight-line) of `U1.VIN`
- decoupling: `C2` within 8.0 mm of copper path (and 5.0 mm straight-line) of `U1.VOUT`
- decoupling: `C3` within 8.0 mm of copper path (and 5.0 mm straight-line) of `U2.V+`
- decoupling: `C5` within 8.0 mm of copper path (and 5.0 mm straight-line) of `U3.V+`

### 2.7 Latent faults and their public evidence

A latent fault leaves `pcbtool check` clean; the agent can only find it by reading the public text. For each one: the generator's evidence claim, then every evidence group the generator's fairness gate requires (`pcbenv/faults/latent.py:evidence_groups`) with the exact public line it matched. Judge whether that text really lets an engineer infer the requirement (`task_fair`, `rule_stated_clearly`).

**Fault 1: `bias_wrong_rail`** — C4.2 returned to VIN_RAW instead of GND

- detected by: `topology`
- generator's evidence claim: design intent (full text kept): bias / bypass / reset parts returned to GND; MCU8 / OPAMP application notes
- evidence group `line:C4&GND`: matched `line:C4&GND` in `TASK.md`:
  > - Channel 1: J2 pin 1 -> IN+ of op-amp U2 (R3 from IN+ to GND defines the input); R4 from OUT to IN- and R5 from IN- to GND set G = 1 + R4/R5; R6 from OUT to the ADC pin J3 pin 3 with C4 from there to GND is the anti-alias filter; C3 decouples V+ at the pin.

**Fault 2: `decap_wrong_rail`** — C3 sits at U2.V+ but decouples VIN instead of +5V

- detected by: `topology`
- generator's evidence claim: TASK.md Design rules / spec.json design_rules: each decoupling cap is named with its IC pin
- evidence group `- C3 within`: matched `- C3 within` in `TASK.md`:
  > - C3 within 8.0 mm of copper path of U2.V+ (and within 5.0 mm straight-line)
- evidence group `U2.V+`: matched `U2.V+` in `TASK.md` (also in `spec.json`):
  > - C3 within 8.0 mm of copper path of U2.V+ (and within 5.0 mm straight-line)


### 2.8 Design rules (`rules` check, not run by pcbtool)

Scope: all datasheet rules (hard tier); 5 operating condition(s) from the spec's stimuli; 32 rule quantities evaluated per design. Rows shown: violated on either side, on a part a fault touches (if ≥ 5 % of its limit or changed by ≥ 5 points or by a footprint change), or at ≥ 80% of the limit. Values are the worst case over the conditions (computed with `pcbenv.rules.operating_point`; limits from `pcbenv/rules.py`, stated in `parts/<PART>.md` and TASK.md "Design rules").

| rule | subject | quantity | limit | faulted (of limit) | golden (of limit) | shown because | worst condition (faulted) |
|---|---|---|---|---|---|---|---|
| `capacitor_voltage` | `C3` | \|V\| | 40 V | 1206: 14.89 V of 40 V (37%) | 1206: 4.96 V of 40 V (12%) | fault target | cond 1 |
| `capacitor_voltage` | `C4` | \|V\| | 20 V | 0805: 15 V of 20 V (75%) | 0805: 1.985 V of 20 V (10%) | fault target | cond 0 |
| `capacitor_voltage` | `C5` | \|V\| | 20 V | 0805: 4.96 V of 20 V (25%) | 0805: 4.96 V of 20 V (25%) | fault target | cond 0 |
| `ldo_abs_max` | `U1` | VIN | 16 V | 14.89 V (93%) | 14.89 V (93%) | near limit | cond 1 |
| `opamp_abs_max` | `U2` | V+ - V- | 5.5 V | 4.96 V (90%) | 4.96 V (90%) | fault target | cond 0 |
| `opamp_abs_max` | `U3` | V+ - V- | 5.5 V | 4.96 V (90%) | 4.96 V (90%) | near limit | cond 0 |

Rule violations reported by the verifier: faulted: none; golden: none.

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?
5. **rule_stated_clearly**: is every design rule / layout rule / latent requirement this task grades (2.7–2.9) stated in the public material clearly enough that an engineer would apply it the way the grader does (limit, which part, which condition)? Normal-tier tasks: answer for the resistor-power rule (`yes` if no rule is involved).
6. **layout_rule_reasonable**: hard_layout tasks only (else `n/a`): are the layout-rule limits and their geometric definitions (2.9) defensible engineering practice for this board, i.e. would you reject the faulted layout in a design review, and accept the golden one?

