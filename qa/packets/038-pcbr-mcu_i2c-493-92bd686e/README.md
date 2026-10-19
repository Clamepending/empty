# QA packet 038: `pcbr-mcu_i2c-493-92bd686e`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| mcu_i2c | 493 | explicit | full | 3 | medium |

Task files: [`../../../tasks/train/pcbr-mcu_i2c-493-92bd686e/public/`](../../../tasks/train/pcbr-mcu_i2c-493-92bd686e/public/) (what the agent gets) and [`../../../tasks/train/pcbr-mcu_i2c-493-92bd686e/hidden/`](../../../tasks/train/pcbr-mcu_i2c-493-92bd686e/hidden/) (grader only). Why sampled: 3 faults, connectivity fault, disputable type narrow_power_trace.

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: MCU with I2C bus (fast-mode)

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Schematic ERC reports 1× unconnected_required.
- The fab's DRC run rejects the layout: 1 error(s) (1× clearance).
- Layout review: a supply trace is narrower than its required width (it runs hot at full load).

A reviewer narrowed the failure down to these areas (each needs a fix):

- how C1 is connected
- the routing of net GND
- the routing of net SDA near net SCL

Fix every problem (there may be more than the observations show directly).

## Design intent

# MCU with I2C bus header

An MCU (U1, MCU8) running from 3.3 V (J1: pin 1 = +3.3 V, pin 2 = GND) acts as I2C controller
for off-board devices on the 4-pin bus header J2 (pin 1 = VDD, pin 2 = GND, pin 3 = SDA, pin 4 = SCL).

- C1 decouples VDD at U1's VDD pin.
- NRST has no internal pull-up: R1 pulls it up to VDD.
- SDA (U1.SDA -> J2.3) and SCL (U1.SCL -> J2.4) are open-drain; R2 (SDA) and R3 (SCL) are the bus pull-ups
  to VDD.

Bus: fast-mode I2C with up to 30 pF of off-board bus capacitance per line (plus 5 pF
MCU pin capacitance). Spec: 10–90 % rise time ≤ 300 ns on both lines (nominal
208 ns), pull-up current ≤ 3 mA with a line held at VOL = 0.4 V, NRST ≥ 0.9·VDD.
Component values: decoupling C1 47 nF–10 µF (100 nF typical); NRST pull-up R1 2.2 kΩ–100 kΩ.

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `vdd`: DC voltage at U1.VDD relative to U1.GND between 3.234 V and 3.366 V (J1.1 supplied with 3.3 V; ground = J1.2)
- `nrst_high`: DC voltage at U1.NRST between 2.97 V and 3.333 V (J1.1 supplied with 3.3 V; ground = J1.2)
- `sda_rise_time`: 10-90 % transition time at U1.SDA between 0 s and 300 ns (J1.1 supplied with 3.3 V; release source on U1.SDA; load C=3e-11 from J2.3 to ground; load C=3e-11 from J2.4 to ground; ground = J1.2)
- `sda_sink_current`: DC current through R2 between 0 A and 3 mA (J1.1 supplied with 3.3 V; dc source on U1.SDA; ground = J1.2)
- `scl_rise_time`: 10-90 % transition time at U1.SCL between 0 s and 300 ns (J1.1 supplied with 3.3 V; release source on U1.SCL; load C=3e-11 from J2.3 to ground; load C=3e-11 from J2.4 to ground; ground = J1.2)
- `scl_sink_current`: DC current through R3 between 0 A and 3 mA (J1.1 supplied with 3.3 V; dc source on U1.SCL; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- +3V3 (the net of J1.1): ≥ 0.3 mm
- GND (the net of J1.2): ≥ 0.3 mm

Decoupling: every pad of each capacitor within the given distance of the IC pin's pad:

- C1 within 5.0 mm of U1.VDD

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 47 nF … 10 uF
- R1 (R): 2.2 kΩ … 100 kΩ
- R2 (R): 830 Ω … 10 kΩ
- R3 (R): 700 Ω … 7.1 kΩ

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
| 1 | `decap_misconnected` | connectivity | no | C1 supply-side pin C1.1 not connected (should be on +3V3) | reward 0.0; fails erc, layout, topology |
| 2 | `narrow_power_trace` | board | yes | 2 segment(s) of power net GND are 0.2 mm wide (required 0.3 mm) | reward 0.0; fails layout |
| 3 | `clearance_violation` | board | no | track stub of net SDA on F.Cu ends 0.12 mm from net SCL at (124.72, 115.02) | reward 0.0; fails drc |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- none

**design.json: connection changes** (per pin: what it connects to)

- `C1.1`: faulted unconnected → golden net `+3V3` (J1.1, J2.1, R1.1, R2.1, R3.1, U1.VDD)

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- none

**board.kicad_pcb: pad-net changes**

- `C1` pad 1: net `(none)` → `+3V3`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `+3V3`: 5 track/via item(s) removed, 8 added
- net `GND`: 2 track/via item(s) removed, 2 added; narrowest track 0.2 mm → 0.3 mm
- net `SDA`: 1 track/via item(s) removed, 0 added

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
| erc | check | **FAIL** | pass |
| spec | check | pass | pass |
| values | check | pass | pass |
| layout | check | **FAIL** | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **drc**: clearance: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.1250 mm) @ (125.2, 115.5)
- **erc**: unconnected_required: C1.1 must be connected
- **layout**: power_net_missing: no board net has the pins of golden net +3V3
- **layout**: power_width: power net GND: narrowest track 0.200 mm < required 0.3 mm
- **topology**: nets only in candidate: [['J1.1', 'J2.1', 'R1.1', 'R2.1', 'R3.1', 'U1.VDD']]; nets only in reference: [['C1.1', 'J1.1', 'J2.1', 'R1.1', 'R2.1', 'R3.1', 'U1.VDD']]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `vdd` | DC voltage at U1.VDD relative to U1.GND (J1.1 supplied with 3.3 V; ground = J1.2) | 3.234 V … 3.366 V | 3.3 V | ✅ | 3.3 V | ✅ |
| `nrst_high` | DC voltage at U1.NRST (J1.1 supplied with 3.3 V; ground = J1.2) | 2.97 V … 3.333 V | 3.3 V | ✅ | 3.3 V | ✅ |
| `sda_rise_time` | 10-90 % transition time at U1.SDA (J1.1 supplied with 3.3 V; release source on U1.SDA; load C=3e-11 from J2.3 to ground; load C=3e-11 from J2.4 to ground; ground = J1.2) | 0 s … 300 ns | 207.6 ns | ✅ | 207.6 ns | ✅ |
| `sda_sink_current` | DC current through R2 (J1.1 supplied with 3.3 V; dc source on U1.SDA; ground = J1.2) | 0 A … 3 mA | 1.074 mA | ✅ | 1.074 mA | ✅ |
| `scl_rise_time` | 10-90 % transition time at U1.SCL (J1.1 supplied with 3.3 V; release source on U1.SCL; load C=3e-11 from J2.3 to ground; load C=3e-11 from J2.4 to ground; ground = J1.2) | 0 s … 300 ns | 207.6 ns | ✅ | 207.6 ns | ✅ |
| `scl_sink_current` | DC current through R3 (J1.1 supplied with 3.3 V; dc source on U1.SCL; ground = J1.2) | 0 A … 3 mA | 1.074 mA | ✅ | 1.074 mA | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 47 nF … 10 uF | `100n` | `100n` | `100n` | **yes** |
| `R1` | R | 2.2 kΩ … 100 kΩ | `30k` | `30k` | `30k` |  |
| `R2` | R | 830 Ω … 10 kΩ | `2.7k` | `2.7k` | `2.7k` |  |
| `R3` | R | 700 Ω … 7.1 kΩ | `2.7k` | `2.7k` | `2.7k` |  |

### 2.6 Layout rules

- power net `+3V3` (golden pins C1.1, J1.1, J2.1, R1.1, R2.1, R3.1, U1.VDD): every track ≥ 0.3 mm
- power net `GND` (golden pins C1.2, J1.2, J2.2, U1.GND): every track ≥ 0.3 mm
- decoupling: `C1` within 5.0 mm of `U1.VDD`

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

