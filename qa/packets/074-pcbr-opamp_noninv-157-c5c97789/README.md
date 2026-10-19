# QA packet 074: `pcbr-opamp_noninv-157-c5c97789`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| opamp_noninv | 157 | symptom | reduced | 3 | hard |

Task files: [`../../../tasks/train/pcbr-opamp_noninv-157-c5c97789/public/`](../../../tasks/train/pcbr-opamp_noninv-157-c5c97789/public/) (what the agent gets) and [`../../../tasks/train/pcbr-opamp_noninv-157-c5c97789/hidden/`](../../../tasks/train/pcbr-opamp_noninv-157-c5c97789/hidden/) (grader only). Why sampled: 3 faults, connectivity fault, disputable type footprint_swap.

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: x3 non-inverting amplifier

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- The fab's DRC run reports 2 unconnected item(s).
- Bring-up: an IC supply pin shows large ripple and the board resets intermittently under load.

Fix every problem (there may be more than the observations show directly).

## Design intent

# x3 non-inverting amplifier

Amplifies the signal on J2 (pin 1 = input, pin 2 = GND) by 3 and presents it on J3
(pin 1 = output, pin 2 = GND). Single 5 V supply on J1 (pin 1 = VCC, pin 2 = GND).

Spec: gain 3 ±3 % at 100 Hz; -3 dB bandwidth 96.1 kHz ±10 %; DC-coupled
(input 0.6667 V DC -> output 2 V).
Component values: decoupling C1 47 nF–10 µF (100 nF typical); input bias resistor R3 47 kΩ–2.2 MΩ
(sets the input impedance).

_Connection details are intentionally not repeated here: wire each part as its datasheet in `parts/` describes (pinout and application notes), so that the circuit does what the purpose, interfaces and spec above require._

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `gain`: AC gain |V(J3.1)/V(J2.1)| at 100 Hz between 2.91 and 3.09 (J1.1 supplied with 5.0 V; dc source on J2.1; ground = J1.2)
- `dc_out`: DC voltage at J3.1 between 1.935 V and 2.065 V (J1.1 supplied with 5.0 V; dc source on J2.1; ground = J1.2)
- `bandwidth`: -3 dB frequency from J2.1 to J3.1 between 86.51 kHz and 105.7 kHz (J1.1 supplied with 5.0 V; dc source on J2.1; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- GND (the net of J1.2): ≥ 0.3 mm
- VCC (the net of J1.1): ≥ 0.3 mm

Decoupling: every pad of each capacitor within the given distance of the IC pin's pad:

- C1 within 5.0 mm of U1.V+

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 47 nF … 10 uF
- C2 (C): 240 pF … 2.2 nF
- R1 (R): 800 Ω … 7.5 kΩ
- R2 (R): 300 Ω … 3.6 kΩ
- R3 (R): 47 kΩ … 2.2 MΩ

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
- Decouple V+ with 100 nF ceramic to ground within 5 mm of the pin.
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
| 1 | `decap_misconnected` | connectivity | yes | C1 supply-side pin C1.1 tied to GND (cap shorted out, should be on VCC) | reward 0.0; fails layout, topology |
| 2 | `footprint_swap` | board | no | R1 footprint changed to Resistor_SMD:R_0603_1608Metric (was Resistor_SMD:R_0805_2012Metric); tracks no longer fit | reward 0.0; fails drc |
| 3 | `broken_trace` | board | no | track of net IN on F.Cu cut near (123.40, 121.01) | reward 0.0; fails drc |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `R1` footprint: `Resistor_SMD:R_0603_1608Metric` → `Resistor_SMD:R_0805_2012Metric`

**design.json: connection changes** (per pin: what it connects to)

- `C1.1`: faulted net `GND` (C1.2, J1.2, J2.2, J3.2, R2.2, R3.2, U1.V-) → golden net `VCC` (J1.1, U1.V+)

**board.kicad_pcb: footprints moved / changed**

- `R1` footprint `Resistor_SMD:R_0603_1608Metric` → `Resistor_SMD:R_0805_2012Metric`

**board.kicad_pcb: footprint values (BOM)**

- none

**board.kicad_pcb: pad-net changes**

- `C1` pad 1: net `GND` → `VCC`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `GND`: 1 track/via item(s) removed, 0 added
- net `IN`: 2 track/via item(s) removed, 1 added
- net `VCC`: 1 track/via item(s) removed, 3 added

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
| spec | check | pass | pass |
| values | check | pass | pass |
| layout | check | **FAIL** | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **drc**: 2 unconnected items
- **layout**: power_net_missing: no board net has the pins of golden net GND
- **layout**: power_net_missing: no board net has the pins of golden net VCC
- **topology**: nets only in candidate: [['C1.1', 'C1.2', 'J1.2', 'J2.2', 'J3.2', 'R2.2', 'R3.2', 'U1.V-'], ['J1.1', 'U1.V+']]; nets only in reference: [['C1.1', 'J1.1', 'U1.V+'], ['C1.2', 'J1.2', 'J2.2', 'J3.2', 'R2.2', 'R3.2', 'U1.V-']]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `gain` | AC gain \|V(J3.1)/V(J2.1)\| at 100 Hz (J1.1 supplied with 5.0 V; dc source on J2.1; ground = J1.2) | 2.91 … 3.09 | 3 | ✅ | 3 | ✅ |
| `dc_out` | DC voltage at J3.1 (J1.1 supplied with 5.0 V; dc source on J2.1; ground = J1.2) | 1.935 V … 2.065 V | 2 V | ✅ | 2 V | ✅ |
| `bandwidth` | -3 dB frequency from J2.1 to J3.1 (J1.1 supplied with 5.0 V; dc source on J2.1; ground = J1.2) | 86.51 kHz … 105.7 kHz | 96.01 kHz | ✅ | 96.01 kHz | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 47 nF … 10 uF | `100n` | `100n` | `100n` | **yes** |
| `C2` | C | 240 pF … 2.2 nF | `680p` | `680p` | `680p` |  |
| `R1` | R | 800 Ω … 7.5 kΩ | `2.1k` | `2.1k` | `2.1k` | **yes** |
| `R2` | R | 300 Ω … 3.6 kΩ | `1.05k` | `1.05k` | `1.05k` |  |
| `R3` | R | 47 kΩ … 2.2 MΩ | `470k` | `470k` | `470k` |  |

### 2.6 Layout rules

- power net `GND` (golden pins C1.2, J1.2, J2.2, J3.2, R2.2, R3.2, U1.V-): every track ≥ 0.3 mm
- power net `VCC` (golden pins C1.1, J1.1, U1.V+): every track ≥ 0.3 mm
- decoupling: `C1` within 5.0 mm of `U1.V+`

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

