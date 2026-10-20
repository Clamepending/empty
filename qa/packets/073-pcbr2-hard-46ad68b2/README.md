# QA packet 073: `pcbr2-hard-46ad68b2`

| family | tier | tool mode | hint level | intent in TASK.md | faults | latent | predicted difficulty |
|---|---|---|---|---|---|---|---|
| sys_analog_frontend | hard | no_autoroute | symptom | full | 5 | 3 |  |

Task files: [`../../../tasks/v2/hard/pcbr2-hard-46ad68b2/public/`](../../../tasks/v2/hard/pcbr2-hard-46ad68b2/public/) (what the agent gets) and [`../../../tasks/v2/hard/pcbr2-hard-46ad68b2/hidden/`](../../../tasks/v2/hard/pcbr2-hard-46ad68b2/hidden/) (grader only). Why sampled: 5 faults, disputable type bias_wrong_rail, disputable type decap_swapped, value near bounds: C5=10n near [1.3e-08, 1.3e-07], 3 latent (bias_wrong_rail, capacitor_underrated, decap_swapped), no_autoroute.

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 2-channel analog front end (12 V in)

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Network analyser: −3 dB corner J2.1 → J3.3 measured at 2.34 kHz, expected 448.2 Hz to 547.8 Hz (`ch1_bandwidth`).
- The fab's DRC run rejects the layout: 6 error(s) (5× clearance, 1× hole_clearance).

Fix every problem (there may be more than the observations show directly).

## Design intent

# Two-channel analog front end

Conditions two DC-coupled sensor signals (input header J2) for an off-board ADC (header J3): each
channel is a single-supply non-inverting op-amp gain stage followed by an RC anti-alias filter. LDO
U1 makes the +5V analog rail (5 V) from the 12 V input on J1; the rail also
supplies the ADC board through J3 pin 1.

Rails: +12 V (from J1) -> reverse-polarity diode -> VIN -> U1 -> +5V = 5 V.

## Connectors

| Connector | Pin | Signal |
|---|---|---|
| J1 | 1 | +12 V input |
| J1 | 2 | GND |
| J2 | 1 | channel 1 sensor input |
| J2 | 2 | GND |
| J2 | 3 | channel 2 sensor input |
| J3 | 1 | +5V (ADC supply / reference) |
| J3 | 2 | GND |
| J3 | 3 | channel 1 to ADC |
| J3 | 4 | channel 2 to ADC |

## Circuit

- Reverse-polarity protection: Schottky D1 in series with the input, anode to J1 pin 1, cathode to the protected input rail VIN; C1 is a bulk capacitor on VIN.
- U1 (LDO_ADJ) regulates the 12 V input down to the 5 V rail +5V: C2 is its input capacitor (VIN to GND) and C3 its output capacitor (VOUT to GND), each at its pin; R1 from VOUT to FB and R2 from FB to GND set VOUT = 0.8 V x (1 + R1/R2); EN is tied to the input (always on).
- Channel 1: J2 pin 1 -> IN+ of op-amp U2 (R3 from IN+ to GND defines the input); R4 from OUT to IN- and R5 from IN- to GND set G = 1 + R4/R5; R6 from OUT to the ADC pin J3 pin 3 with C5 from there to GND is the anti-alias filter; C4 decouples V+ at the pin.
- Channel 2: J2 pin 3 -> IN+ of op-amp U3 (R7 from IN+ to GND defines the input); R8 from OUT to IN- and R9 from IN- to GND set G = 1 + R8/R9; R10 from OUT to the ADC pin J3 pin 4 with C7 from there to GND is the anti-alias filter; C6 decouples V+ at the pin.
- power indicator: R11 from +5V to the anode of D2, cathode to GND.

## Spec

Channel 1: gain 1.961 ±3 % at 100 Hz (G = 2); DC-coupled (0.995 V in -> 1.99 V out); -3 dB bandwidth 498 Hz ±10 % (anti-alias filter).

Channel 2: gain 2.46 ±3 % at 100 Hz (G = 2.5); DC-coupled (0.7949 V in -> 1.99 V out); -3 dB bandwidth 530.5 Hz ±10 % (anti-alias filter).

Power indicator current 3.05 mA ±15 %.

Rail +5V: 5 V ±3 % with 1 mA drawn by the ADC board from J3 pin 1, for inputs from 6 V to 12 V.

Component values: input bulk capacitor C1 1 µF–22 µF; C2, C3 1 µF–22 µF (LDO datasheet); feedback Rbot R2 3.3 kΩ–150 kΩ (10k–50k typical) with R1 scaled to match; channel 1: decoupling C4 47 nF–10 µF; input bias R3 47 kΩ–2.2 MΩ; channel 2: decoupling C6 47 nF–10 µF; input bias R7 47 kΩ–2.2 MΩ.

Sub-circuits by purpose: input reverse-polarity protection and bulk capacitor (D1, C1); 5 V regulator with input/output capacitors and feedback divider (U1, C2, C3, R1, R2); channel 1 op-amp with supply decoupling (U2, C4); channel 1 input bias and gain network (R3, R4, R5); channel 1 anti-alias filter (R6, C5); channel 2 op-amp with supply decoupling (U3, C6); channel 2 input bias and gain network (R7, R8, R9); channel 2 anti-alias filter (R10, C7); power indicator LED with series resistor (D2, R11); supply connector (J1); sensor input connector (J2); ADC header (J3).

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `ch1_gain`: AC gain |V(J3.3)/V(J2.1)| at 100 Hz between 1.902 and 2.02 (J1.1 supplied with 12.0 V; 0.995 V DC + 1.0 V AC source on J2.1; ground = J1.2)
- `ch1_dc_out`: DC voltage at J3.3 between 1.925 V and 2.055 V (J1.1 supplied with 12.0 V; 0.995 V DC + 1.0 V AC source on J2.1; ground = J1.2)
- `ch1_bandwidth`: -3 dB frequency from J2.1 to J3.3 between 448.2 Hz and 547.8 Hz (J1.1 supplied with 12.0 V; 0.995 V DC + 1.0 V AC source on J2.1; ground = J1.2)
- `ch2_gain`: AC gain |V(J3.4)/V(J2.3)| at 100 Hz between 2.386 and 2.534 (J1.1 supplied with 12.0 V; 0.7949 V DC + 1.0 V AC source on J2.3; ground = J1.2)
- `ch2_dc_out`: DC voltage at J3.4 between 1.925 V and 2.055 V (J1.1 supplied with 12.0 V; 0.7949 V DC + 1.0 V AC source on J2.3; ground = J1.2)
- `ch2_bandwidth`: -3 dB frequency from J2.3 to J3.4 between 477.5 Hz and 583.6 Hz (J1.1 supplied with 12.0 V; 0.7949 V DC + 1.0 V AC source on J2.3; ground = J1.2)
- `power_led_current`: DC current through D2 between 2.593 mA and 3.508 mA (J1.1 supplied with 12.0 V; ground = J1.2)
- `5v_rail`: DC voltage at J3.1 between 4.85 V and 5.15 V (J1.1 supplied with 12.0 V; load R=5000 from J3.1 to ground; ground = J1.2)
- `5v_rail_low_vin`: DC voltage at J3.1 between 4.85 V and 5.15 V (J1.1 supplied with 6.0 V; load R=5000 from J3.1 to ground; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- +5V (the net of J3.1): ≥ 0.3 mm
- GND (the net of J1.2): ≥ 0.3 mm
- VIN (the net of C1.1): ≥ 0.3 mm
- VIN_RAW (the net of J1.1): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 1 uF … 22 uF
- C2 (C): 1 uF … 22 uF
- C3 (C): 1 uF … 22 uF
- C4 (C): 47 nF … 10 uF
- C5 (C): 13 nF … 130 nF
- C6 (C): 47 nF … 10 uF
- C7 (C): 39 nF … 490 nF
- R1 (R): 17 kΩ … 790 kΩ
- R10 (R): 610 Ω … 5.1 kΩ
- R11 (R): 110 Ω … 3.5 kΩ
- R2 (R): 3.3 kΩ … 150 kΩ
- R3 (R): 47 kΩ … 2.2 MΩ
- R4 (R): 1.2 kΩ … 14 kΩ
- R5 (R): 1.4 kΩ … 12 kΩ
- R6 (R): 2 kΩ … 22 kΩ
- R7 (R): 47 kΩ … 2.2 MΩ
- R8 (R): 1.3 kΩ … 16 kΩ
- R9 (R): 700 Ω … 9.1 kΩ

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

- C2 within 8.0 mm of copper path of U1.VIN (and within 5.0 mm straight-line)
- C3 within 8.0 mm of copper path of U1.VOUT (and within 5.0 mm straight-line)
- C4 within 8.0 mm of copper path of U2.V+ (and within 5.0 mm straight-line)
- C6 within 8.0 mm of copper path of U3.V+ (and within 5.0 mm straight-line)

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

**Tool mode for this task: `no_autoroute`** (`tools.json`). `pcbtool route` and `pcbtool sync` are
disabled: after changing connectivity or footprints, edit the tracks (`segment` / `via` items) in
`board.kicad_pcb` yourself, or move parts with `pcbtool move`. All other commands work.
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
| 1 | `capacitor_underrated` | latent | yes | **yes** | C1 capacitor footprint downsized C_0805_2012Metric -> C_0603_1608Metric; it now exceeds the rating of the smaller part | reward 0.0; fails rules |
| 2 | `bias_wrong_rail` | latent | yes | **yes** | R3.2 returned to VIN_RAW instead of GND | reward 0.0; fails rules, topology |
| 3 | `decap_swapped` | latent | yes | **yes** | C2 and C6 exchange rails: C2 sits at U1.VIN but decouples +5V, C6 sits at U3.V+ but decouples VIN | reward 0.0; fails layout, rules, topology |
| 4 | `wrong_filter_cap` | value | yes |  | C5 (filter/timing capacitor) is 10n, should be 47n | reward 0.0; fails spec, values |
| 5 | `short_between_nets` | board | no |  | track of net IN1 on F.Cu runs into net AMP1 at (125.30, 123.90) | reward 0.0; fails drc |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `C1` footprint: `Capacitor_SMD:C_0603_1608Metric` → `Capacitor_SMD:C_0805_2012Metric`
- `C5` value: `10n` → `47n`

**design.json: connection changes** (per pin: what it connects to)

- `C2.1`: faulted net `+5V` (C3.1, C4.1, J3.1, R1.1, R11.1, U1.VOUT, U2.V+, U3.V+) → golden net `VIN` (C1.1, D1.K, U1.EN, U1.VIN)
- `C6.1`: faulted net `VIN` (C1.1, D1.K, U1.EN, U1.VIN) → golden net `+5V` (C3.1, C4.1, J3.1, R1.1, R11.1, U1.VOUT, U2.V+, U3.V+)
- `R3.2`: faulted net `VIN_RAW` (D1.A, J1.1) → golden net `GND` (C1.2, C2.2, C3.2, C4.2, C5.2, C6.2, C7.2, D2.K, J1.2, J2.2, J3.2, R2.2, R5.2, R7.2, R9.2, U1.GND, U2.V-, U3.V-)

**board.kicad_pcb: footprints moved / changed**

- `C1` footprint `Capacitor_SMD:C_0603_1608Metric` → `Capacitor_SMD:C_0805_2012Metric`

**board.kicad_pcb: footprint values (BOM)**

- `C5` board value `10n` → `47n`

**board.kicad_pcb: pad-net changes**

- `C2` pad 1: net `+5V` → `VIN`
- `C5` pad 1: net `Net-(C5-Pad1)` → `ADC1`
- `C6` pad 1: net `VIN` → `+5V`
- `C7` pad 1: net `Net-(C7-Pad1)` → `ADC2`
- `D2` pad 2: net `Net-(D2-Pad2)` → `LED_D2_A`
- `J2` pad 1: net `Net-(J2-Pad1)` → `IN1`
- `J2` pad 3: net `Net-(J2-Pad3)` → `IN2`
- `J3` pad 3: net `Net-(C5-Pad1)` → `ADC1`
- `J3` pad 4: net `Net-(C7-Pad1)` → `ADC2`
- `R1` pad 2: net `Net-(R1-Pad2)` → `FB_U1`
- `R10` pad 1: net `Net-(R8-Pad1)` → `AMP2`
- `R10` pad 2: net `Net-(C7-Pad1)` → `ADC2`
- `R11` pad 2: net `Net-(D2-Pad2)` → `LED_D2_A`
- `R2` pad 1: net `Net-(R1-Pad2)` → `FB_U1`
- `R3` pad 1: net `Net-(J2-Pad1)` → `IN1`
- `R3` pad 2: net `VIN_RAW` → `GND`
- `R4` pad 1: net `Net-(R4-Pad1)` → `AMP1`
- `R4` pad 2: net `Net-(R4-Pad2)` → `FB1`
- `R5` pad 1: net `Net-(R4-Pad2)` → `FB1`
- `R6` pad 1: net `Net-(R4-Pad1)` → `AMP1`
- `R6` pad 2: net `Net-(C5-Pad1)` → `ADC1`
- `R7` pad 1: net `Net-(J2-Pad3)` → `IN2`
- `R8` pad 1: net `Net-(R8-Pad1)` → `AMP2`
- `R8` pad 2: net `Net-(R8-Pad2)` → `FB2`
- `R9` pad 1: net `Net-(R8-Pad2)` → `FB2`
- `U1` pad 4: net `Net-(R1-Pad2)` → `FB_U1`
- `U2` pad 1: net `Net-(R4-Pad1)` → `AMP1`
- `U2` pad 3: net `Net-(J2-Pad1)` → `IN1`
- `U2` pad 4: net `Net-(R4-Pad2)` → `FB1`
- `U3` pad 1: net `Net-(R8-Pad1)` → `AMP2`
- `U3` pad 3: net `Net-(J2-Pad3)` → `IN2`
- `U3` pad 4: net `Net-(R8-Pad2)` → `FB2`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `+5V`: 16 track/via item(s) removed, 7 added
- net `ADC1`: 0 track/via item(s) removed, 3 added
- net `ADC2`: 0 track/via item(s) removed, 5 added
- net `AMP1`: 0 track/via item(s) removed, 7 added
- net `AMP2`: 0 track/via item(s) removed, 6 added
- net `FB1`: 0 track/via item(s) removed, 4 added
- net `FB2`: 0 track/via item(s) removed, 3 added
- net `FB_U1`: 0 track/via item(s) removed, 4 added
- net `GND`: 10 track/via item(s) removed, 9 added
- net `IN1`: 0 track/via item(s) removed, 2 added
- net `IN2`: 0 track/via item(s) removed, 8 added
- net `LED_D2_A`: 0 track/via item(s) removed, 1 added
- net `Net-(C5-Pad1)`: 3 track/via item(s) removed, 0 added
- net `Net-(C7-Pad1)`: 5 track/via item(s) removed, 0 added
- net `Net-(D2-Pad2)`: 1 track/via item(s) removed, 0 added
- net `Net-(J2-Pad1)`: 3 track/via item(s) removed, 0 added
- net `Net-(J2-Pad3)`: 8 track/via item(s) removed, 0 added
- net `Net-(R1-Pad2)`: 4 track/via item(s) removed, 0 added
- net `Net-(R4-Pad1)`: 7 track/via item(s) removed, 0 added
- net `Net-(R4-Pad2)`: 4 track/via item(s) removed, 0 added
- net `Net-(R8-Pad1)`: 6 track/via item(s) removed, 0 added
- net `Net-(R8-Pad2)`: 3 track/via item(s) removed, 0 added
- net `VIN`: 13 track/via item(s) removed, 9 added
- net `VIN_RAW`: 8 track/via item(s) removed, 4 added

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
| consistency | gate | pass | pass |
| integrity | gate | pass | pass |
| drc | check | **FAIL** | pass |
| erc | check | pass | pass |
| spec | check | **FAIL** | pass |
| values | check | **FAIL** | pass |
| layout | check | **FAIL** | pass |
| rules | check | **FAIL** | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **drc**: clearance: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.0000 mm) @ (125.3, 123.9)
- **drc**: clearance: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.0000 mm) @ (126.3, 122.9)
- **drc**: clearance: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.0000 mm) @ (125.0, 123.0)
- **drc**: clearance: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.0000 mm) @ (125.0, 123.0)
- **drc**: hole_clearance: Hole clearance violation (board setup constraints hole clearance 0.2500 mm; actual 0.0000 mm) @ (124.3, 122.2)
- **drc**: clearance: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.1027 mm) @ (124.3, 122.2)
- **layout**: decoupling: C2 has no pad connected by copper to U1.VIN
- **layout**: decoupling: C6 has no pad connected by copper to U3.V+
- **layout_skipped**: no board net has the pins of golden net +5V (connectivity differs: see topology)
- **layout_skipped**: no board net has the pins of golden net GND (connectivity differs: see topology)
- **layout_skipped**: no board net has the pins of golden net VIN (connectivity differs: see topology)
- **layout_skipped**: no board net has the pins of golden net VIN_RAW (connectivity differs: see topology)
- **rules**: capacitor_voltage: C1 sees 11.9 V > 8 V (80 % of 10 V, C_0603_1608Metric) [condition 0]
- **rules**: capacitor_voltage: C6 sees 11.9 V > 8 V (80 % of 10 V, C_0603_1608Metric) [condition 0]
- **rules**: opamp_abs_max: U2.IN+ at 11.8 V outside the rails [0, 4.97 V] ±0.3 V [condition 1]
- **rules**: opamp_abs_max: U2.IN+ at 5.92 V outside the rails [0, 4.97 V] ±0.3 V [condition 4]
- **spec**: ch1_bandwidth: measured 2339.893741241772 expected [448.182, 547.778]
- **topology**: nets only in candidate: [['C1.1', 'C6.1', 'D1.K', 'U1.EN', 'U1.VIN'], ['C1.2', 'C2.2', 'C3.2', 'C4.2', 'C5.2', 'C6.2', 'C7.2', 'D2.K', 'J1.2', 'J2.2', 'J3.2', 'R2.2', 'R5.2', 'R7.2', 'R9.2', 'U1.GND', 'U2.V-', 'U3.V-'], ['C2.1', 'C3.1', 'C4.1', 'J3.1', 'R1.1', 'R11.1', 'U1.VOUT', 'U2.V+', 'U3.V+'], ['D1.A', 'J1.1', 'R3.2']]; nets only in reference: [['C1.1', 'C2.1', 'D1.K', 'U1.EN', 'U1.VIN'], ['C1.2', 'C2.2', 'C3.2', 'C4.2', 'C5.2', 'C6.2', 'C7.2', 'D2.K', 'J1.2', 'J2.2', 'J3.2', 'R2.2', 'R3.2', 'R5.2', 'R7.2', 'R9.2', 'U1.GND', 'U2.V-', 'U3.V-'], ['C3.1', 'C4.1', 'C6.1', 'J3.1', 'R1.1', 'R11.1', 'U1.VOUT', 'U2.V+', 'U3.V+'], ['D1.A', 'J1.1']]
- **values**: C5: value '10n' outside acceptable range [1.3e-08, 1.3e-07]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `ch1_gain` | AC gain \|V(J3.3)/V(J2.1)\| at 100 Hz (J1.1 supplied with 12.0 V; 0.995 V DC + 1.0 V AC source on J2.1; ground = J1.2) | 1.902 … 2.02 | 1.998 | ✅ | 1.961 | ✅ |
| `ch1_dc_out` | DC voltage at J3.3 (J1.1 supplied with 12.0 V; 0.995 V DC + 1.0 V AC source on J2.1; ground = J1.2) | 1.925 V … 2.055 V | 1.99 V | ✅ | 1.99 V | ✅ |
| `ch1_bandwidth` | -3 dB frequency from J2.1 to J3.3 (J1.1 supplied with 12.0 V; 0.995 V DC + 1.0 V AC source on J2.1; ground = J1.2) | 448.2 Hz … 547.8 Hz | 2.34 kHz | ❌ | 497.9 Hz | ✅ |
| `ch2_gain` | AC gain \|V(J3.4)/V(J2.3)\| at 100 Hz (J1.1 supplied with 12.0 V; 0.7949 V DC + 1.0 V AC source on J2.3; ground = J1.2) | 2.386 … 2.534 | 2.46 | ✅ | 2.46 | ✅ |
| `ch2_dc_out` | DC voltage at J3.4 (J1.1 supplied with 12.0 V; 0.7949 V DC + 1.0 V AC source on J2.3; ground = J1.2) | 1.925 V … 2.055 V | 1.99 V | ✅ | 1.99 V | ✅ |
| `ch2_bandwidth` | -3 dB frequency from J2.3 to J3.4 (J1.1 supplied with 12.0 V; 0.7949 V DC + 1.0 V AC source on J2.3; ground = J1.2) | 477.5 Hz … 583.6 Hz | 530.4 Hz | ✅ | 530.4 Hz | ✅ |
| `power_led_current` | DC current through D2 (J1.1 supplied with 12.0 V; ground = J1.2) | 2.593 mA … 3.508 mA | 3.047 mA | ✅ | 3.047 mA | ✅ |
| `5v_rail` | DC voltage at J3.1 (J1.1 supplied with 12.0 V; load R=5000 from J3.1 to ground; ground = J1.2) | 4.85 V … 5.15 V | 4.972 V | ✅ | 4.972 V | ✅ |
| `5v_rail_low_vin` | DC voltage at J3.1 (J1.1 supplied with 6.0 V; load R=5000 from J3.1 to ground; ground = J1.2) | 4.85 V … 5.15 V | 4.972 V | ✅ | 4.972 V | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 1 uF … 22 uF | `22u` | `22u` | `22u` | **yes** |
| `C2` | C | 1 uF … 22 uF | `10u` | `10u` | `10u` | **yes** |
| `C3` | C | 1 uF … 22 uF | `4.7u` | `4.7u` | `4.7u` |  |
| `C4` | C | 47 nF … 10 uF | `100n` | `100n` | `100n` |  |
| `C5` | C | 13 nF … 130 nF | `10n` ⚠ out of range | `10n` ⚠ out of range | `47n` | **yes** |
| `C6` | C | 47 nF … 10 uF | `100n` | `100n` | `100n` | **yes** |
| `C7` | C | 39 nF … 490 nF | `150n` | `150n` | `150n` |  |
| `R1` | R | 17 kΩ … 790 kΩ | `71.5k` | `71.5k` | `71.5k` |  |
| `R10` | R | 610 Ω … 5.1 kΩ | `2k` | `2k` | `2k` |  |
| `R11` | R | 110 Ω … 3.5 kΩ | `1k` | `1k` | `1k` |  |
| `R2` | R | 3.3 kΩ … 150 kΩ | `13.7k` | `13.7k` | `13.7k` |  |
| `R3` | R | 47 kΩ … 2.2 MΩ | `220k` | `220k` | `220k` | **yes** |
| `R4` | R | 1.2 kΩ … 14 kΩ | `4.87k` | `4.87k` | `4.87k` |  |
| `R5` | R | 1.4 kΩ … 12 kΩ | `4.87k` | `4.87k` | `4.87k` |  |
| `R6` | R | 2 kΩ … 22 kΩ | `6.8k` | `6.8k` | `6.8k` |  |
| `R7` | R | 47 kΩ … 2.2 MΩ | `100k` | `100k` | `100k` |  |
| `R8` | R | 1.3 kΩ … 16 kΩ | `4.12k` | `4.12k` | `4.12k` |  |
| `R9` | R | 700 Ω … 9.1 kΩ | `2.74k` | `2.74k` | `2.74k` |  |

### 2.6 Layout rules

- power net `+5V` (golden pins C3.1, C4.1, C6.1, J3.1, R1.1, R11.1, U1.VOUT, U2.V+, U3.V+): every track ≥ 0.3 mm
- power net `GND` (golden pins C1.2, C2.2, C3.2, C4.2, C5.2, C6.2, C7.2, D2.K, J1.2, J2.2, J3.2, R2.2, R3.2, R5.2, R7.2, R9.2, U1.GND, U2.V-, U3.V-): every track ≥ 0.3 mm
- power net `VIN` (golden pins C1.1, C2.1, D1.K, U1.EN, U1.VIN): every track ≥ 0.3 mm
- power net `VIN_RAW` (golden pins D1.A, J1.1): every track ≥ 0.3 mm
- decoupling: `C2` within 8.0 mm of copper path (and 5.0 mm straight-line) of `U1.VIN`
- decoupling: `C3` within 8.0 mm of copper path (and 5.0 mm straight-line) of `U1.VOUT`
- decoupling: `C4` within 8.0 mm of copper path (and 5.0 mm straight-line) of `U2.V+`
- decoupling: `C6` within 8.0 mm of copper path (and 5.0 mm straight-line) of `U3.V+`

### 2.7 Latent faults and their public evidence

A latent fault leaves `pcbtool check` clean; the agent can only find it by reading the public text. For each one: the generator's evidence claim, then every evidence group the generator's fairness gate requires (`pcbenv/faults/latent.py:evidence_groups`) with the exact public line it matched. Judge whether that text really lets an engineer infer the requirement (`task_fair`, `rule_stated_clearly`).

**Fault 1: `capacitor_underrated`** — C1 capacitor footprint downsized C_0805_2012Metric -> C_0603_1608Metric; it now exceeds the rating of the smaller part

- detected by: `rules`; rule violations it causes: capacitor_voltage: C1 sees 11.9 V > 8 V (80 % of 10 V, C_0603_1608Metric) [condition 0]
- generator's evidence claim: parts/C.md voltage rating by footprint + 80 % rule; rail voltages in the intent; TASK.md Design rules
- evidence group `the DC working voltage across a capacitor must not exceed 80 %`: matched `the DC working voltage across a capacitor must not exceed 80 %` in `parts/C.md`:
  > **Design rule:** the DC working voltage across a capacitor must not exceed 80 % of its rated voltage
- evidence group `| 0603 |`: matched `| 0603 |` in `parts/C.md` (also in `parts/LED_RED.md`, `parts/R.md`):
  > \| 0603 \| 10 V \| 8 V \|

**Fault 2: `bias_wrong_rail`** — R3.2 returned to VIN_RAW instead of GND

- detected by: `topology`; rule violations it causes: opamp_abs_max: U2.IN+ at 11.8 V outside the rails [0, 4.97 V] ±0.3 V [condition 1]; opamp_abs_max: U2.IN+ at 5.92 V outside the rails [0, 4.97 V] ±0.3 V [condition 4]
- generator's evidence claim: design intent (full text kept): bias / bypass / reset parts returned to GND; MCU8 / OPAMP application notes
- evidence group `line:R3&GND`: matched `line:R3&GND` in `TASK.md`:
  > - Channel 1: J2 pin 1 -> IN+ of op-amp U2 (R3 from IN+ to GND defines the input); R4 from OUT to IN- and R5 from IN- to GND set G = 1 + R4/R5; R6 from OUT to the ADC pin J3 pin 3 with C5 from there to GND is the anti-alias filter; C4 decouples V+ at the pin.

**Fault 3: `decap_swapped`** — C2 and C6 exchange rails: C2 sits at U1.VIN but decouples +5V, C6 sits at U3.V+ but decouples VIN

- detected by: `topology`; rule violations it causes: capacitor_voltage: C6 sees 11.9 V > 8 V (80 % of 10 V, C_0603_1608Metric) [condition 0]
- generator's evidence claim: spec.json / TASK.md decoupling rules name each cap's IC pin (C1 at U1.VIN, C2 at U1.VOUT)
- evidence group `- C2 within`: matched `- C2 within` in `TASK.md`:
  > - C2 within 8.0 mm of copper path of U1.VIN (and within 5.0 mm straight-line)
- evidence group `- C6 within`: matched `- C6 within` in `TASK.md`:
  > - C6 within 8.0 mm of copper path of U3.V+ (and within 5.0 mm straight-line)


### 2.8 Design rules (`rules` check, not run by pcbtool)

Scope: all datasheet rules (hard tier); 5 operating condition(s) from the spec's stimuli; 32 rule quantities evaluated per design. Rows shown: violated on either side, on a part a fault touches (if ≥ 5 % of its limit or changed by ≥ 5 points or by a footprint change), or at ≥ 80% of the limit. Values are the worst case over the conditions (computed with `pcbenv.rules.operating_point`; limits from `pcbenv/rules.py`, stated in `parts/<PART>.md` and TASK.md "Design rules").

| rule | subject | quantity | limit | faulted (of limit) | golden (of limit) | shown because | worst condition (faulted) |
|---|---|---|---|---|---|---|---|
| `capacitor_voltage` | `C1` | \|V\| | per package / condition, see cells | 0603: 11.9 V of 8 V (149%) ❌ | 0805: 11.9 V of 20 V (59%) | violated | cond 1 |
| `capacitor_voltage` | `C2` | \|V\| | 40 V | 1206: 4.972 V of 40 V (12%) | 1206: 11.9 V of 40 V (30%) | fault target | cond 0 |
| `capacitor_voltage` | `C5` | \|V\| | 8 V | 0603: 4.952 V of 8 V (62%) | 0603: 1.99 V of 8 V (25%) | fault target | cond 1 |
| `capacitor_voltage` | `C6` | \|V\| | 8 V | 0603: 11.9 V of 8 V (149%) ❌ | 0603: 4.972 V of 8 V (62%) | violated | cond 1 |
| `opamp_abs_max` | `U2` | V+ - V- | 5.5 V | 4.972 V (90%) | 4.972 V (90%) | near limit | cond 0 |
| `opamp_abs_max` | `U2.IN+` | input vs rails (ratio: overshoot / 0.3 V) | -0.3 … 5.27 V | 11.79 V of -0.3 … 5.27 V (2274%) ❌ | 995 mV of -0.3 … 5.27 V (0%) | violated | cond 3 |
| `opamp_abs_max` | `U3` | V+ - V- | 5.5 V | 4.972 V (90%) | 4.972 V (90%) | near limit | cond 0 |

Rule violations reported by the verifier: faulted: capacitor_voltage: C1 sees 11.9 V > 8 V (80 % of 10 V, C_0603_1608Metric) [condition 0]; capacitor_voltage: C6 sees 11.9 V > 8 V (80 % of 10 V, C_0603_1608Metric) [condition 0]; opamp_abs_max: U2.IN+ at 11.8 V outside the rails [0, 4.97 V] ±0.3 V [condition 1]; opamp_abs_max: U2.IN+ at 5.92 V outside the rails [0, 4.97 V] ±0.3 V [condition 4]; golden: none.

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?
5. **rule_stated_clearly**: is every design rule / layout rule / latent requirement this task grades (2.7–2.9) stated in the public material clearly enough that an engineer would apply it the way the grader does (limit, which part, which condition)? Normal-tier tasks: answer for the resistor-power rule (`yes` if no rule is involved).
6. **layout_rule_reasonable**: hard_layout tasks only (else `n/a`): are the layout-rule limits and their geometric definitions (2.9) defensible engineering practice for this board, i.e. would you reject the faulted layout in a design review, and accept the golden one?

