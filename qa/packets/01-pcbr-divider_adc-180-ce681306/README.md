# QA packet 01: `pcbr-divider_adc-180-ce681306`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| divider_adc | 180 | symptom | reduced | 3 | hard |

Task files: [`../../../tasks/train/pcbr-divider_adc-180-ce681306/public/`](../../../tasks/train/pcbr-divider_adc-180-ce681306/public/) (what the agent gets) and [`../../../tasks/train/pcbr-divider_adc-180-ce681306/hidden/`](../../../tasks/train/pcbr-divider_adc-180-ce681306/hidden/) (grader only). Why sampled: 3 faults, disputable type bom_mismatch, value near bounds: C1=680n inside [5.5e-07, 4.7e-06]; R2=64.9k near [4900, 54000].

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 0-9 V sense divider for a 1.8 V ADC

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Network analyser: −3 dB corner J1.1 → J2.1 measured at 19.97 Hz, expected 8.15 Hz to 9.961 Hz (`anti_alias_corner`).
- The assembled board does not behave like the simulated schematic: the layout's netlist disagrees with design.json.
- Incoming inspection: a part value on the layout does not match the design.json BOM.

Fix every problem (there may be more than the observations show directly).

## Design intent

# Voltage-sense divider for an ADC

Scales a 0–9 V signal on J1 (pin 1 = sensed voltage, pin 2 = GND) down so that 9 V reads as
1.62 V (90 % of a 1.8 V ADC full scale) on the ADC header J2 (pin 1 = ADC input, pin 2 = GND).

Spec: ADC voltage = 0.1800 × input ±2 %; anti-alias -3 dB corner 9.056 Hz ±10 %.

_Connection details are intentionally not repeated here: wire each part as its datasheet in `parts/` describes (pinout and application notes), so that the circuit does what the purpose, interfaces and spec above require._

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `full_scale`: DC voltage at J2.1 between 1.588 V and 1.652 V (J1.1 supplied with 9.0 V; ground = J1.2)
- `half_scale`: DC voltage at J2.1 between 793.8 mV and 826.2 mV (J1.1 supplied with 4.5 V; ground = J1.2)
- `anti_alias_corner`: -3 dB frequency from J1.1 to J2.1 between 8.15 Hz and 9.961 Hz (dc source on J1.1; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- GND (the net of J1.2): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 550 nF … 4.7 uF
- R1 (R): 21 kΩ … 170 kΩ
- R2 (R): 4.9 kΩ … 54 kΩ

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
| 1 | `wrong_filter_cap` | value | yes | C1 (filter/timing capacitor) is 680n, should be 1.5u | reward 0.0; fails spec |
| 2 | `bom_mismatch` | value | yes | board value of R2 is 64.9k, design.json says 14.3k | reward 0.0; fails consistency |
| 3 | `board_pad_swap` | board | yes | board pads of J1.1 (pad 1) and J1.2 (pad 2) carry each other's nets | reward 0.0; fails consistency, layout |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `C1` value: `680n` → `1.5u`

**design.json: connection changes** (per pin: what it connects to)

- none

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- `C1` board value `680n` → `1.5u`
- `R2` board value `64.9k` → `14.3k`

**board.kicad_pcb: pad-net changes**

- `J1` pad 1: net `GND` → `VSENSE`
- `J1` pad 2: net `VSENSE` → `GND`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `GND`: 3 track/via item(s) removed, 1 added
- net `VSENSE`: 1 track/via item(s) removed, 2 added

Golden renders (compare with 1.2; highlighted items differ):

![golden schematic](schematic_golden.svg)

![golden board](board_golden.svg)

### 2.3 Verifier verdicts

Reward is 1 only if every gate and check passes.

| stage | kind | faulted files | golden files |
|---|---|---|---|
| parse | gate | pass | pass |
| components | gate | pass | pass |
| topology | gate | pass | pass |
| consistency | gate | **FAIL** | pass |
| integrity | gate | pass | pass |
| drc | check | pass | pass |
| erc | check | pass | pass |
| spec | check | **FAIL** | pass |
| values | check | pass | pass |
| layout | check | **FAIL** | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **consistency**: board connectivity != design.json: nets only in candidate: [['C1.2', 'J1.1', 'J2.2', 'R2.2'], ['J1.2', 'R1.1']]; nets only in reference: [['C1.2', 'J1.2', 'J2.2', 'R2.2'], ['J1.1', 'R1.1']]
- **consistency**: R2: board value '64.9k' != design value '14.3k'
- **layout**: power_net_missing: no board net has the pins of golden net GND
- **spec**: anti_alias_corner: measured 19.973597498567013 expected [8.15019, 9.96134]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `full_scale` | DC voltage at J2.1 (J1.1 supplied with 9.0 V; ground = J1.2) | 1.588 V … 1.652 V | 1.625 V | ✅ | 1.625 V | ✅ |
| `half_scale` | DC voltage at J2.1 (J1.1 supplied with 4.5 V; ground = J1.2) | 793.8 mV … 826.2 mV | 812.5 mV | ✅ | 812.5 mV | ✅ |
| `anti_alias_corner` | -3 dB frequency from J1.1 to J2.1 (dc source on J1.1; ground = J1.2) | 8.15 Hz … 9.961 Hz | 19.97 Hz | ❌ | 9.055 Hz | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 550 nF … 4.7 uF | `680n` | `680n` | `1.5u` | **yes** |
| `R1` | R | 21 kΩ … 170 kΩ | `64.9k` | `64.9k` | `64.9k` |  |
| `R2` | R | 4.9 kΩ … 54 kΩ | `14.3k` | `64.9k` ⚠ out of range | `14.3k` | **yes** |

### 2.6 Layout rules

- power net `GND` (golden pins C1.2, J1.2, J2.2, R2.2): every track ≥ 0.3 mm

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

