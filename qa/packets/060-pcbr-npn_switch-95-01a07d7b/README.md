# QA packet 060: `pcbr-npn_switch-95-01a07d7b`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| npn_switch | 95 | vague | reduced | 2 | hard |

Task files: [`../../../tasks/train/pcbr-npn_switch-95-01a07d7b/public/`](../../../tasks/train/pcbr-npn_switch-95-01a07d7b/public/) (what the agent gets) and [`../../../tasks/train/pcbr-npn_switch-95-01a07d7b/hidden/`](../../../tasks/train/pcbr-npn_switch-95-01a07d7b/hidden/) (grader only). Why sampled: vague hint, connectivity fault, value near bounds: R4=270k near [4700, 220000].

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: MCU-controlled LED switch

## Problem report

The first boards built from these files fail bring-up. Find and fix all problems: the design must meet its purpose and spec, the layout must match design.json, and DRC/ERC must be clean.

## Design intent

# MCU-controlled low-side switch

A small MCU (U1, MCU8) switches a load through an NPN low-side transistor Q1. Power (3.3 V) comes in
on J1 (pin 1 = +3.3 V, pin 2 = GND); the MCU runs from the same rail.

Spec: with PA0 driven high the load current is 5.0 mA ±15 % and Q1 is saturated (VCE ≤ 0.3 V);
with PA0 high-impedance the load stays off even with 1 MΩ of leakage from the supply into the base.
Component values: decoupling C1 47 nF–10 µF (100 nF typical); NRST pull-up R1 2.2 kΩ–100 kΩ;
base pull-down R4 4.7 kΩ–220 kΩ (datasheet: 10k–100k).

_Connection details are intentionally not repeated here: wire each part as its datasheet in `parts/` describes (pinout and application notes), so that the circuit does what the purpose, interfaces and spec above require._

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `load_on_current`: DC current through D1 between 4.25 mA and 5.75 mA (J1.1 supplied with 3.3 V; dc source on U1.PA0; ground = J1.2)
- `vce_sat`: DC voltage at Q1.C between 0 V and 300 mV (J1.1 supplied with 3.3 V; dc source on U1.PA0; ground = J1.2)
- `gpio_current`: DC current through R2 between 0 A and 8 mA (J1.1 supplied with 3.3 V; dc source on U1.PA0; ground = J1.2)
- `load_off_current`: DC current through D1 between 0 A and 100 uA (J1.1 supplied with 3.3 V; load R=1e+06 from Q1.B to J1.1; ground = J1.2)
- `vdd`: DC voltage at U1.VDD relative to U1.GND between 3.234 V and 3.366 V (J1.1 supplied with 3.3 V; ground = J1.2)
- `nrst_high`: DC voltage at U1.NRST between 2.97 V and 3.333 V (J1.1 supplied with 3.3 V; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- +3V3 (the net of J1.1): ≥ 0.3 mm
- GND (the net of J1.2): ≥ 0.3 mm

Decoupling: every pad of each capacitor within the given distance of the IC pin's pad:

- C1 within 5.0 mm of U1.VDD

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 47 nF … 10 uF
- R1 (R): 2.2 kΩ … 100 kΩ
- R2 (R): 1.6 kΩ … 14 kΩ
- R3 (R): 88 Ω … 720 Ω
- R4 (R): 4.7 kΩ … 220 kΩ

Board rules: 2 copper layers, clearance 0.2 mm, min track 0.2 mm, vias 0.6/0.3 mm, copper-to-edge 0.3 mm. DRC must be clean with no unconnected items.

## Deliverable

- Edit only `design.json` (the schematic of record) and `board.kicad_pcb` (the layout).
- Do not add, remove or rename components; keep each component's part.
- Keep the two files consistent: same connectivity, values and footprints on both.
- Do not change the board outline, add zones, or add DRC exclusions.
- Footprints must be unmodified library footprints from the part's allowed list (see `parts/<PART>.md`).
- Grading is pass/fail: topology, consistency, DRC, ERC, spec, component values and layout must all pass.

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
````

</details>

<details><summary>Datasheet <code>parts/CONN2.md</code></summary>

````markdown
# CONN2 — 2-pin header

Pin `1` = signal/supply, pin `2` = ground by board convention.
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
````

</details>

<details><summary>Datasheet <code>parts/MCU8.md</code></summary>

````markdown
# MCU8 — generic 8-pin microcontroller (SOIC-8)

## Pinout
| Pin | Pad | Function |
|---|---|---|
| NRST | 1 | active-low reset input. **No internal pull-up**: needs an external 10k pull-up to VDD (optional 100 nF to GND) |
| PA1 | 2 | GPIO / XIN (crystal oscillator input) |
| PA2 | 3 | GPIO / XOUT (crystal oscillator output) |
| GND | 4 | ground |
| SDA | 5 | I2C data (open-drain) / GPIO |
| PA0 | 6 | GPIO / PWM output |
| SCL | 7 | I2C clock (open-drain) / GPIO |
| VDD | 8 | supply 1.8–5.5 V |

## Electrical characteristics
- Supply current 1.5 mA typ at 3.3 V
- GPIO output: VOH ≥ VDD - 0.4 V at 8 mA source (≈50 Ω output resistance); 8 mA max per pin
- Open-drain I2C pins sink max 3 mA at VOL = 0.4 V; no internal I2C pull-ups
- Pin capacitance 5 pF per I/O; idle / reset I/O pins are high-impedance (no pulls)
- Crystal oscillator: 4–25 MHz fundamental crystal between XIN (PA1) and XOUT (PA2), each pin
  with a load capacitor to GND

## Application notes
- Decouple VDD with 100 nF ceramic to GND within 5 mm of the VDD pin.
- I2C pull-ups: Rp ≥ (VDD - 0.4 V) / 3 mA and Rp ≤ tr / (2.2 × Cbus) for a 10–90 % rise time tr
  (Cbus includes the 5 pF pin capacitance).
- Crystal load caps: CL = C1·C2/(C1+C2) + Cstray, i.e. C1 = C2 = 2·(CL - Cstray).
````

</details>

<details><summary>Datasheet <code>parts/NPN.md</code></summary>

````markdown
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
````

</details>

<details><summary>Datasheet <code>parts/R.md</code></summary>

````markdown
# R — resistor

Two-terminal resistor. Pins `1`, `2` (non-polarised). Value in ohms.
````

</details>

## 2. Reviewer-only (hidden from the agent)

### 2.1 Injected faults

| # | type | category | DRC/ERC-invisible | detail | verifier, this fault alone |
|---|---|---|---|---|---|
| 1 | `reversed_polarity` | connectivity | yes | D1 anode/cathode reversed | reward 0.0; fails spec, topology |
| 2 | `wrong_pull_resistor` | value | yes | R4 (pull-up/pull-down resistor) is 270k, should be 13k | reward 0.0; fails values |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `R4` value: `270k` → `13k`

**design.json: connection changes** (per pin: what it connects to)

- `D1.A`: faulted net `SW` (Q1.C) → golden net `LED_A` (R3.2)
- `D1.K`: faulted net `LED_A` (R3.2) → golden net `SW` (Q1.C)

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- `R4` board value `270k` → `13k`

**board.kicad_pcb: pad-net changes**

- `D1` pad 1: net `LED_A` → `SW`
- `D1` pad 2: net `SW` → `LED_A`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `LED_A`: 2 track/via item(s) removed, 1 added
- net `SW`: 7 track/via item(s) removed, 10 added

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
| drc | check | pass | pass |
| erc | check | pass | pass |
| spec | check | **FAIL** | pass |
| values | check | **FAIL** | pass |
| layout | check | pass | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **spec**: load_on_current: measured 3.0521414044e-13 expected [0.00425, 0.00575]
- **topology**: nets only in candidate: [['D1.A', 'Q1.C'], ['D1.K', 'R3.2']]; nets only in reference: [['D1.A', 'R3.2'], ['D1.K', 'Q1.C']]
- **values**: R4: value '270k' outside acceptable range [4700, 220000]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `load_on_current` | DC current through D1 (J1.1 supplied with 3.3 V; dc source on U1.PA0; ground = J1.2) | 4.25 mA … 5.75 mA | 3.052e-13 A | ❌ | 4.713 mA | ✅ |
| `vce_sat` | DC voltage at Q1.C (J1.1 supplied with 3.3 V; dc source on U1.PA0; ground = J1.2) | 0 V … 300 mV | 22.53 mV | ✅ | 77.04 mV | ✅ |
| `gpio_current` | DC current through R2 (J1.1 supplied with 3.3 V; dc source on U1.PA0; ground = J1.2) | 0 A … 8 mA | 604 uA | ✅ | 593.7 uA | ✅ |
| `load_off_current` | DC current through D1 (J1.1 supplied with 3.3 V; load R=1e+06 from Q1.B to J1.1; ground = J1.2) | 0 A … 100 uA | 3.055e-13 A | ✅ | 6.288 pA | ✅ |
| `vdd` | DC voltage at U1.VDD relative to U1.GND (J1.1 supplied with 3.3 V; ground = J1.2) | 3.234 V … 3.366 V | 3.3 V | ✅ | 3.3 V | ✅ |
| `nrst_high` | DC voltage at U1.NRST (J1.1 supplied with 3.3 V; ground = J1.2) | 2.97 V … 3.333 V | 3.3 V | ✅ | 3.3 V | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 47 nF … 10 uF | `100n` | `100n` | `100n` |  |
| `R1` | R | 2.2 kΩ … 100 kΩ | `30k` | `30k` | `30k` |  |
| `R2` | R | 1.6 kΩ … 14 kΩ | `4.3k` | `4.3k` | `4.3k` |  |
| `R3` | R | 88 Ω … 720 Ω | `270` | `270` | `270` |  |
| `R4` | R | 4.7 kΩ … 220 kΩ | `270k` ⚠ out of range | `270k` ⚠ out of range | `13k` | **yes** |

### 2.6 Layout rules

- power net `+3V3` (golden pins C1.1, J1.1, R1.1, R3.1, U1.VDD): every track ≥ 0.3 mm
- power net `GND` (golden pins C1.2, J1.2, Q1.E, R4.2, U1.GND): every track ≥ 0.3 mm
- decoupling: `C1` within 5.0 mm of `U1.VDD`

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

