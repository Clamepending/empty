# QA packet 63: `pcbr-opamp_inv-326-89619a3d`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| opamp_inv | 326 | symptom | reduced | 3 | hard |

Task files: [`../../../tasks/train/pcbr-opamp_inv-326-89619a3d/public/`](../../../tasks/train/pcbr-opamp_inv-326-89619a3d/public/) (what the agent gets) and [`../../../tasks/train/pcbr-opamp_inv-326-89619a3d/hidden/`](../../../tasks/train/pcbr-opamp_inv-326-89619a3d/hidden/) (grader only). Why sampled: 3 faults, connectivity fault, disputable type decap_moved_far, value near bounds: R3=680k near [4700, 470000].

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: inverting x22 AC amplifier

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Bench: J3.1 reads 3.295 V, expected 1.601 V to 1.7 V (`dc_bias_out`).
- Network analyser: gain J2.1 → J3.1 at 1 kHz is 0.0001577, expected 21.38 to 22.7 (`midband_gain`).
- Network analyser: −3 dB corner J2.1 → J3.1 measured at 2.535 Hz, expected 49.61 Hz to 67.12 Hz (`low_cutoff`).
- Schematic ERC reports 1× unconnected_required.
- Layout review: a decoupling capacitor sits too far from the IC pin it decouples.

Fix every problem (there may be more than the observations show directly).

## Design intent

# Inverting x22 AC amplifier (single supply)

Amplifies an AC signal on J2 (pin 1 = input, pin 2 = GND) with a gain of -22 and outputs it on
J3 (pin 1 = output, pin 2 = GND), centred at mid-supply. Single 3.3 V supply on J1
(pin 1 = VCC, pin 2 = GND).

Spec: output DC level VCC/2 ±3 %; |gain| 22 ±3 % at 1 kHz; low -3 dB corner 58.4 Hz ±15 %.
Component values: decoupling C1 47 nF–10 µF (100 nF typical); bias divider R3, R4 4.7 kΩ–470 kΩ each;
VMID bypass C3 470 nF–47 µF.

_Connection details are intentionally not repeated here: wire each part as its datasheet in `parts/` describes (pinout and application notes), so that the circuit does what the purpose, interfaces and spec above require._

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `dc_bias_out`: DC voltage at J3.1 between 1.601 V and 1.7 V (J1.1 supplied with 3.3 V; dc source on J2.1; ground = J1.2)
- `midband_gain`: AC gain |V(J3.1)/V(J2.1)| at 1 kHz between 21.38 and 22.7 (J1.1 supplied with 3.3 V; dc source on J2.1; ground = J1.2)
- `low_cutoff`: -3 dB frequency from J2.1 to J3.1 between 49.61 Hz and 67.12 Hz (J1.1 supplied with 3.3 V; dc source on J2.1; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- GND (the net of J1.2): ≥ 0.3 mm
- VCC (the net of J1.1): ≥ 0.3 mm

Decoupling: every pad of each capacitor within the given distance of the IC pin's pad:

- C1 within 5.0 mm of U1.V+

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 47 nF … 10 uF
- C2 (C): 86 nF … 1.1 uF
- C3 (C): 470 nF … 47 uF
- R1 (R): 3 kΩ … 21 kΩ
- R2 (R): 52 kΩ … 480 kΩ
- R3 (R): 4.7 kΩ … 470 kΩ
- R4 (R): 4.7 kΩ … 470 kΩ

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
| 1 | `floating_pin` | connectivity | no | U1.IN- left unconnected (should be on SUM) | reward 0.0; fails erc, spec, topology |
| 2 | `wrong_pull_resistor` | value | yes | R3 (pull-up/pull-down resistor) is 680k, should be 68k | reward 0.0; fails spec, values |
| 3 | `decap_moved_far` | board | yes | C1 placed at (114.0, 130.5), 13.8 mm from U1.V+ (max 5.0 mm) | reward 0.0; fails layout |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `R3` value: `680k` → `68k`

**design.json: connection changes** (per pin: what it connects to)

- `U1.IN-`: faulted unconnected → golden net `SUM` (R1.2, R2.1)

**board.kicad_pcb: footprints moved / changed**

- `C1` moved (114.00, 130.50, -90°, F) → (122.00, 122.00, -90°, F), 11.67 mm

**board.kicad_pcb: footprint values (BOM)**

- `R3` board value `680k` → `68k`

**board.kicad_pcb: pad-net changes**

- `U1` pad 4: net `(none)` → `SUM`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `GND`: 5 track/via item(s) removed, 7 added
- net `SUM`: 0 track/via item(s) removed, 2 added
- net `VCC`: 3 track/via item(s) removed, 2 added

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
| erc | check | **FAIL** | pass |
| spec | check | **FAIL** | pass |
| values | check | **FAIL** | pass |
| layout | check | **FAIL** | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **erc**: unconnected_required: U1.IN- must be connected
- **layout**: decoupling: C1.1 is 13.78 mm from U1.V+ (max 5.0 mm)
- **layout**: decoupling: C1.2 is 14.82 mm from U1.V+ (max 5.0 mm)
- **spec**: dc_bias_out: measured 3.2949999293 expected [1.6005, 1.6995]
- **spec**: midband_gain: measured 0.00015766188458117713 expected [21.3792, 22.7016]
- **spec**: low_cutoff: measured 2.5350509862667727 expected [49.6098, 67.1192]
- **topology**: nets only in candidate: [['R1.2', 'R2.1']]; nets only in reference: [['R1.2', 'R2.1', 'U1.IN-']]
- **values**: R3: value '680k' outside acceptable range [4700, 470000]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `dc_bias_out` | DC voltage at J3.1 (J1.1 supplied with 3.3 V; dc source on J2.1; ground = J1.2) | 1.601 V … 1.7 V | 3.295 V | ❌ | 1.65 V | ✅ |
| `midband_gain` | AC gain \|V(J3.1)/V(J2.1)\| at 1 kHz (J1.1 supplied with 3.3 V; dc source on J2.1; ground = J1.2) | 21.38 … 22.7 | 157.7 u | ❌ | 22.04 | ✅ |
| `low_cutoff` | -3 dB frequency from J2.1 to J3.1 (J1.1 supplied with 3.3 V; dc source on J2.1; ground = J1.2) | 49.61 Hz … 67.12 Hz | 2.535 Hz | ❌ | 58.38 Hz | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 47 nF … 10 uF | `100n` | `100n` | `100n` | **yes** |
| `C2` | C | 86 nF … 1.1 uF | `330n` | `330n` | `330n` |  |
| `C3` | C | 470 nF … 47 uF | `4.7u` | `4.7u` | `4.7u` |  |
| `R1` | R | 3 kΩ … 21 kΩ | `8.25k` | `8.25k` | `8.25k` |  |
| `R2` | R | 52 kΩ … 480 kΩ | `182k` | `182k` | `182k` |  |
| `R3` | R | 4.7 kΩ … 470 kΩ | `680k` ⚠ out of range | `680k` ⚠ out of range | `68k` | **yes** |
| `R4` | R | 4.7 kΩ … 470 kΩ | `68k` | `68k` | `68k` |  |

### 2.6 Layout rules

- power net `GND` (golden pins C1.2, C3.2, J1.2, J2.2, J3.2, R4.2, U1.V-): every track ≥ 0.3 mm
- power net `VCC` (golden pins C1.1, J1.1, R3.1, U1.V+): every track ≥ 0.3 mm
- decoupling: `C1` within 5.0 mm of `U1.V+`

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

