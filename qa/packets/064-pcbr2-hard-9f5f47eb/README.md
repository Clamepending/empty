# QA packet 064: `pcbr2-hard-9f5f47eb`

| family | tier | tool mode | hint level | intent in TASK.md | faults | latent | predicted difficulty |
|---|---|---|---|---|---|---|---|
| mcu_i2c | hard | full | symptom | full | 5 | 2 |  |

Task files: [`../../../tasks/v2/hard/pcbr2-hard-9f5f47eb/public/`](../../../tasks/v2/hard/pcbr2-hard-9f5f47eb/public/) (what the agent gets) and [`../../../tasks/v2/hard/pcbr2-hard-9f5f47eb/hidden/`](../../../tasks/v2/hard/pcbr2-hard-9f5f47eb/hidden/) (grader only). Why sampled: 5 faults, connectivity fault, disputable type bias_wrong_rail, disputable type bom_mismatch, disputable type connector_pin_swap, value near bounds: R1=13k inside [2200, 100000], 2 latent (bias_wrong_rail, connector_pin_swap).

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: MCU with I2C bus (standard-mode)

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Bench: U1.NRST reads 0 V, expected 2.97 V to 3.333 V (`nrst_high`).
- Schematic ERC reports 1× unconnected_required.
- Incoming inspection: a part value on the layout does not match the design.json BOM.

Fix every problem (there may be more than the observations show directly).

## Design intent

# MCU with I2C bus header

An MCU (U1, MCU8) running from 3.3 V (J1: pin 1 = +3.3 V, pin 2 = GND) acts as I2C controller
for off-board devices on the 4-pin bus header J2 (pin 1 = VDD, pin 2 = GND, pin 3 = SDA, pin 4 = SCL).

- C1 decouples VDD at U1's VDD pin; C2 is an additional bulk capacitor on VDD.
- NRST has no internal pull-up: R1 pulls it up to VDD and C3 to GND gives a power-on reset delay.
- SDA (U1.SDA -> J2.3) and SCL (U1.SCL -> J2.4) are open-drain; R2 (SDA) and R3 (SCL) are the bus pull-ups
  to VDD.

Bus: standard-mode I2C with up to 50 pF of off-board bus capacitance per line (plus 5 pF
MCU pin capacitance). Spec: I2C rise time (30–70 % of VDD, as defined by UM10204) ≤ 1000 ns
on both lines (nominal 839 ns), pull-up current ≤ 3 mA with a line held at VOL = 0.4 V,
NRST ≥ 0.9·VDD.
Component values: decoupling C1 47 nF–10 µF (100 nF typical); NRST pull-up R1 2.2 kΩ–100 kΩ; bulk C2 1 µF–22 µF; reset delay C3 10 nF–1 µF;
I2C pull-ups R2, R3 anywhere in the datasheet range (VDD-0.4 V)/3 mA .. tr/(0.8473·Cbus) that meets the spec.

Sub-circuits by purpose: supply connector (J1); MCU (U1); VDD decoupling (C1, C2); reset pull-up and power-on delay (R1, C3); I2C bus pull-ups (R2, R3); I2C bus header (J2).

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `vdd`: DC voltage at U1.VDD relative to U1.GND between 3.234 V and 3.366 V (J1.1 supplied with 3.3 V; ground = J1.2)
- `nrst_high`: DC voltage at U1.NRST between 2.97 V and 3.333 V (J1.1 supplied with 3.3 V; ground = J1.2)
- `sda_rise_time`: 30-70 % transition time at U1.SDA between 0 s and 1 us (J1.1 supplied with 3.3 V; open-drain driver releasing the line on U1.SDA; load C=5e-11 from J2.3 to ground; load C=5e-11 from J2.4 to ground; ground = J1.2)
- `sda_sink_current`: DC current through R2 between 0 A and 3 mA (J1.1 supplied with 3.3 V; 0.4 V DC source on U1.SDA; ground = J1.2)
- `scl_rise_time`: 30-70 % transition time at U1.SCL between 0 s and 1 us (J1.1 supplied with 3.3 V; open-drain driver releasing the line on U1.SCL; load C=5e-11 from J2.3 to ground; load C=5e-11 from J2.4 to ground; ground = J1.2)
- `scl_sink_current`: DC current through R3 between 0 A and 3 mA (J1.1 supplied with 3.3 V; 0.4 V DC source on U1.SCL; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- +3V3 (the net of J1.1): ≥ 0.3 mm
- GND (the net of J1.2): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 47 nF … 10 uF
- C2 (C): 1 uF … 22 uF
- C3 (C): 10 nF … 1 uF
- R1 (R): 2.2 kΩ … 100 kΩ
- R2 (R): 960 Ω … 52 kΩ
- R3 (R): 960 Ω … 65 kΩ

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

- C1 within 6.0 mm of copper path of U1.VDD (and within 5.0 mm straight-line)

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

<details><summary>Datasheet <code>parts/MCU8.md</code></summary>

````markdown
# MCU8 — generic 8-pin microcontroller (SOIC-8)

## Pinout
| Pin | Pad | Function |
|---|---|---|
| NRST | 1 | active-low reset input. **No internal pull-up**: needs an external pull-up to VDD, 2.2k–100k (10k typical); optional 10 nF–1 µF to GND (100 nF typical) for a power-on reset delay |
| PA1 | 2 | GPIO / ADC1 / XIN (crystal oscillator input) |
| PA2 | 3 | GPIO / ADC2 / XOUT (crystal oscillator output) |
| GND | 4 | ground |
| SDA | 5 | I2C data (open-drain) / GPIO |
| PA0 | 6 | GPIO / PWM output / ADC0 |
| SCL | 7 | I2C clock (open-drain) / GPIO |
| VDD | 8 | supply 1.8–5.5 V |

## Electrical characteristics
- Supply current 1.5 mA typ at 3.3 V
- GPIO output: VOH ≥ VDD - 0.4 V at 8 mA source (≈50 Ω output resistance); 8 mA max per pin
- Open-drain I2C pins sink max 3 mA at VOL = 0.4 V; no internal I2C pull-ups
- ADC (PA0, PA1, PA2): 12-bit, full scale = VDD, input range 0..VDD (never above VDD); the pin
  is high impedance (5 pF), so an RC anti-alias filter at the pin sets the input bandwidth
- Pin capacitance 5 pF per I/O; idle / reset I/O pins are high-impedance (no pulls)
- Crystal oscillator: 4–25 MHz fundamental crystal between XIN (PA1) and XOUT (PA2), each pin
  with a load capacitor to GND

## Application notes
- Decouple VDD with 100 nF ceramic (47 nF–10 µF) to GND within 5 mm of the VDD pin.
- I2C pull-ups: Rp ≥ (VDD - 0.4 V) / 3 mA (sink limit) and Rp ≤ tr / (0.8473 × Cbus) (rise time),
  where tr is the I2C rise time as defined by the I2C specification (UM10204): 30 % to 70 % of
  VDD, max 1000 ns standard-mode / 300 ns fast-mode; 0.8473 = ln(0.7/0.3). Cbus includes
  the 5 pF pin capacitance.
- Crystal load caps: CL = C1·C2/(C1+C2) + Cstray, i.e. C1 = C2 = 2·(CL - Cstray).

## Absolute maximum ratings
- VDD - GND ≤ 6 V.
- Any I/O pin (NRST, PA0-PA2, SDA, SCL): -0.3 V … VDD + 0.3 V. No pin may be pulled
  above the MCU's own VDD (e.g. by a pull-up to a higher rail): the ESD diodes conduct and
  back-power the chip.
- GPIO current (PA0-PA2, NRST): 8 mA max per pin; SDA/SCL: 3 mA max sink.
- Pin functions are fixed by the package: crystal on PA1 (XIN) / PA2 (XOUT), I2C on SDA / SCL;
  firmware assumes the assignment given in the design intent.
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
| 1 | `connector_pin_swap` | latent | yes | **yes** | connector J2 pins 3 and 4 exchanged (pinout fixed by the intent) | reward 0.0; fails topology |
| 2 | `bias_wrong_rail` | latent | yes | **yes** | C3.2 returned to +3V3 instead of GND | reward 0.0; fails topology |
| 3 | `swapped_ic_pins` | connectivity | no |  | U1.NRST and U1.PA0 connections exchanged | reward 0.0; fails erc, spec, topology |
| 4 | `magnitude_slip` | value | yes |  | C1 is 100p (unit slip), should be 100n | reward 0.0; fails values |
| 5 | `bom_mismatch` | value | yes |  | board value of R1 is 13k, design.json says 27k | reward 0.0; fails consistency |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `C1` value: `100p` → `100n`

**design.json: connection changes** (per pin: what it connects to)

- `C3.2`: faulted net `+3V3` (C1.1, C2.1, J1.1, J2.1, R1.1, R2.1, R3.1, U1.VDD) → golden net `GND` (C1.2, C2.2, J1.2, J2.2, U1.GND)
- `J2.3`: faulted net `SCL` (R3.2, U1.SCL) → golden net `SDA` (R2.2, U1.SDA)
- `J2.4`: faulted net `SDA` (R2.2, U1.SDA) → golden net `SCL` (R3.2, U1.SCL)
- `U1.NRST`: faulted unconnected → golden net `NRST` (C3.1, R1.2)
- `U1.PA0`: faulted net `NRST` (C3.1, R1.2) → golden unconnected

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- `C1` board value `100p` → `100n`
- `R1` board value `13k` → `27k`

**board.kicad_pcb: pad-net changes**

- `C3` pad 2: net `+3V3` → `GND`
- `J2` pad 3: net `SCL` → `SDA`
- `J2` pad 4: net `SDA` → `SCL`
- `U1` pad 1: net `(none)` → `NRST`
- `U1` pad 6: net `NRST` → `(none)`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `+3V3`: 15 track/via item(s) removed, 4 added
- net `GND`: 7 track/via item(s) removed, 13 added
- net `NRST`: 7 track/via item(s) removed, 2 added
- net `SCL`: 3 track/via item(s) removed, 3 added
- net `SDA`: 4 track/via item(s) removed, 5 added

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
| erc | check | **FAIL** | pass |
| spec | check | **FAIL** | pass |
| values | check | **FAIL** | pass |
| layout | check | pass | pass |
| rules | check | pass | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **consistency**: R1: board value '13k' != design value '27k'
- **erc**: unconnected_required: U1.NRST must be connected
- **layout_skipped**: no board net has the pins of golden net +3V3 (connectivity differs: see topology)
- **layout_skipped**: no board net has the pins of golden net GND (connectivity differs: see topology)
- **spec**: nrst_high: measured 0.0 expected [2.97, 3.333]
- **topology**: nets only in candidate: [['C1.1', 'C2.1', 'C3.2', 'J1.1', 'J2.1', 'R1.1', 'R2.1', 'R3.1', 'U1.VDD'], ['C1.2', 'C2.2', 'J1.2', 'J2.2', 'U1.GND'], ['C3.1', 'R1.2', 'U1.PA0'], ['J2.3', 'R3.2', 'U1.SCL'], ['J2.4', 'R2.2', 'U1.SDA']]; nets only in reference: [['C1.1', 'C2.1', 'J1.1', 'J2.1', 'R1.1', 'R2.1', 'R3.1', 'U1.VDD'], ['C1.2', 'C2.2', 'C3.2', 'J1.2', 'J2.2', 'U1.GND'], ['C3.1', 'R1.2', 'U1.NRST'], ['J2.3', 'R2.2', 'U1.SDA'], ['J2.4', 'R3.2', 'U1.SCL']]
- **values**: C1: value '100p' outside acceptable range [4.7e-08, 1e-05]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `vdd` | DC voltage at U1.VDD relative to U1.GND (J1.1 supplied with 3.3 V; ground = J1.2) | 3.234 V … 3.366 V | 3.3 V | ✅ | 3.3 V | ✅ |
| `nrst_high` | DC voltage at U1.NRST (J1.1 supplied with 3.3 V; ground = J1.2) | 2.97 V … 3.333 V | 0 V | ❌ | 3.3 V | ✅ |
| `sda_rise_time` | 30-70 % transition time at U1.SDA (J1.1 supplied with 3.3 V; open-drain driver releasing the line on U1.SDA; load C=5e-11 from J2.3 to ground; load C=5e-11 from J2.4 to ground; ground = J1.2) | 0 s … 1 us | 838.1 ns | ✅ | 838.1 ns | ✅ |
| `sda_sink_current` | DC current through R2 (J1.1 supplied with 3.3 V; 0.4 V DC source on U1.SDA; ground = J1.2) | 0 A … 3 mA | 161.1 uA | ✅ | 161.1 uA | ✅ |
| `scl_rise_time` | 30-70 % transition time at U1.SCL (J1.1 supplied with 3.3 V; open-drain driver releasing the line on U1.SCL; load C=5e-11 from J2.3 to ground; load C=5e-11 from J2.4 to ground; ground = J1.2) | 0 s … 1 us | 838.1 ns | ✅ | 838.1 ns | ✅ |
| `scl_sink_current` | DC current through R3 (J1.1 supplied with 3.3 V; 0.4 V DC source on U1.SCL; ground = J1.2) | 0 A … 3 mA | 161.1 uA | ✅ | 161.1 uA | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 47 nF … 10 uF | `100p` ⚠ out of range | `100p` ⚠ out of range | `100n` | **yes** |
| `C2` | C | 1 uF … 22 uF | `1u` | `1u` | `1u` |  |
| `C3` | C | 10 nF … 1 uF | `100n` | `100n` | `100n` | **yes** |
| `R1` | R | 2.2 kΩ … 100 kΩ | `27k` | `13k` | `27k` | **yes** |
| `R2` | R | 960 Ω … 52 kΩ | `18k` | `18k` | `18k` |  |
| `R3` | R | 960 Ω … 65 kΩ | `18k` | `18k` | `18k` |  |

### 2.6 Layout rules

- power net `+3V3` (golden pins C1.1, C2.1, J1.1, J2.1, R1.1, R2.1, R3.1, U1.VDD): every track ≥ 0.3 mm
- power net `GND` (golden pins C1.2, C2.2, C3.2, J1.2, J2.2, U1.GND): every track ≥ 0.3 mm
- decoupling: `C1` within 6.0 mm of copper path (and 5.0 mm straight-line) of `U1.VDD`

### 2.7 Latent faults and their public evidence

A latent fault leaves `pcbtool check` clean; the agent can only find it by reading the public text. For each one: the generator's evidence claim, then every evidence group the generator's fairness gate requires (`pcbenv/faults/latent.py:evidence_groups`) with the exact public line it matched. Judge whether that text really lets an engineer infer the requirement (`task_fair`, `rule_stated_clearly`).

**Fault 1: `connector_pin_swap`** — connector J2 pins 3 and 4 exchanged (pinout fixed by the intent)

- detected by: `topology`
- generator's evidence claim: design intent: connector pinouts (pin n = function), kept at every hint level
- evidence group `J2.3` / `| J2 | 3 |` / `J2 pin 3`: matched `J2.3` in `TASK.md` (also in `spec.json`):
  > - SDA (U1.SDA -> J2.3) and SCL (U1.SCL -> J2.4) are open-drain; R2 (SDA) and R3 (SCL) are the bus pull-ups
- evidence group `J2.4` / `| J2 | 4 |` / `J2 pin 4`: matched `J2.4` in `TASK.md` (also in `spec.json`):
  > - SDA (U1.SDA -> J2.3) and SCL (U1.SCL -> J2.4) are open-drain; R2 (SDA) and R3 (SCL) are the bus pull-ups

**Fault 2: `bias_wrong_rail`** — C3.2 returned to +3V3 instead of GND

- detected by: `topology`
- generator's evidence claim: design intent (full text kept): bias / bypass / reset parts returned to GND; MCU8 / OPAMP application notes
- evidence group `line:C3&GND`: matched `line:C3&GND` in `TASK.md`:
  > - NRST has no internal pull-up: R1 pulls it up to VDD and C3 to GND gives a power-on reset delay.


### 2.8 Design rules (`rules` check, not run by pcbtool)

Scope: all datasheet rules (hard tier); 4 operating condition(s) from the spec's stimuli; 15 rule quantities evaluated per design. Rows shown: violated on either side, on a part a fault touches (if ≥ 5 % of its limit or changed by ≥ 5 points or by a footprint change), or at ≥ 80% of the limit. Values are the worst case over the conditions (computed with `pcbenv.rules.operating_point`; limits from `pcbenv/rules.py`, stated in `parts/<PART>.md` and TASK.md "Design rules").

| rule | subject | quantity | limit | faulted (of limit) | golden (of limit) | shown because | worst condition (faulted) |
|---|---|---|---|---|---|---|---|
| `capacitor_voltage` | `C1` | \|V\| | 40 V | 1206: 3.3 V of 40 V (8%) | 1206: 3.3 V of 40 V (8%) | fault target | cond 0 |
| `capacitor_voltage` | `C3` | \|V\| | 20 V | 0805: 356.4 nV of 20 V (0%) | 0805: 3.3 V of 20 V (16%) | fault target | cond 0 |
| `mcu_abs_max` | `U1` | VDD-GND | 6 V | 3.3 V (55%) | 3.3 V (55%) | fault target | cond 0 |
| `mcu_pin_current` | `U1.SCL` | \|I\| | 3 mA | 161.1 uA (5%) | 161.1 uA (5%) | fault target | cond 3 |
| `mcu_pin_current` | `U1.SDA` | \|I\| | 3 mA | 161.1 uA (5%) | 161.1 uA (5%) | fault target | cond 2 |

Rule violations reported by the verifier: faulted: none; golden: none.

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?
5. **rule_stated_clearly**: is every design rule / layout rule / latent requirement this task grades (2.7–2.9) stated in the public material clearly enough that an engineer would apply it the way the grader does (limit, which part, which condition)? Normal-tier tasks: answer for the resistor-power rule (`yes` if no rule is involved).
6. **layout_rule_reasonable**: hard_layout tasks only (else `n/a`): are the layout-rule limits and their geometric definitions (2.9) defensible engineering practice for this board, i.e. would you reject the faulted layout in a design review, and accept the golden one?

