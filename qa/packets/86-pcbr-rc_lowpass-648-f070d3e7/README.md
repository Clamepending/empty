# QA packet 86: `pcbr-rc_lowpass-648-f070d3e7`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| rc_lowpass | 648 | vague | reduced | 1 | medium |

Task files: [`../../../tasks/train/pcbr-rc_lowpass-648-f070d3e7/public/`](../../../tasks/train/pcbr-rc_lowpass-648-f070d3e7/public/) (what the agent gets) and [`../../../tasks/train/pcbr-rc_lowpass-648-f070d3e7/hidden/`](../../../tasks/train/pcbr-rc_lowpass-648-f070d3e7/hidden/) (grader only). Why sampled: vague hint.

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 2nd-order LC low-pass filter

## Problem report

The first boards built from these files fail bring-up. Find and fix all problems: the design must meet its purpose and spec, the layout must match design.json, and DRC/ERC must be clean.

## Design intent

# 2nd-order LC low-pass filter

Removes high-frequency content from the signal entering on J1 (pin 1 = input, pin 2 = GND) and
delivers the filtered signal on J2 (pin 1 = output, pin 2 = GND). Grounds of J1 and J2 are common.

Spec: order 2; -3 dB corner 1.695e+04 Hz ±10 %; passband gain ≈ 1.000 at fc/20;
attenuation at 10·fc: gain 0.0108 ±25 %.

_Connection details are intentionally not repeated here: wire each part as its datasheet in `parts/` describes (pinout and application notes), so that the circuit does what the purpose, interfaces and spec above require._

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `cutoff`: -3 dB frequency from J1.1 to J2.1 between 15.26 kHz and 18.65 kHz (dc source on J1.1; ground = J1.2)
- `passband_gain`: AC gain |V(J2.1)/V(J1.1)| at 847.5 Hz between 969.8 m and 1.03 (dc source on J1.1; ground = J1.2)
- `stopband_gain`: AC gain |V(J2.1)/V(J1.1)| at 169.5 kHz between 8.096 m and 13.49 m (dc source on J1.1; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- GND (the net of J1.2): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 430 nF … 3.7 uF
- L1 (L): 22 uH … 230 uH
- R1 (R): 3.4 Ω … 34 Ω

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

<details><summary>Datasheet <code>parts/L.md</code></summary>

````markdown
# L — SMD inductor

## Pinout
| Pin | Pad | Function |
|---|---|---|
| 1 | 1 | terminal |
| 2 | 2 | terminal |

Non-polarised. Value in henries (e.g. `100u`).

## Electrical characteristics
- DCR 50 mΩ, saturation current 1 A, SRF well above 10 MHz

## Application notes
- LC low-pass: f0 = 1 / (2π·sqrt(L·C)); a series damping resistor R gives
  Q = sqrt(L/C) / R (Q ≈ 0.707 for a maximally-flat response).
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
| 1 | `clearance_violation` | board | no | track stub of net GND on F.Cu ends 0.08 mm from net IN at (119.96, 110.96) | reward 0.0; fails drc |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- none

**design.json: connection changes** (per pin: what it connects to)

- none

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- none

**board.kicad_pcb: pad-net changes**

- none

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `GND`: 1 track/via item(s) removed, 0 added

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
| consistency | gate | pass | pass |
| integrity | gate | pass | pass |
| drc | check | **FAIL** | pass |
| erc | check | pass | pass |
| spec | check | pass | pass |
| values | check | pass | pass |
| layout | check | pass | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **drc**: clearance: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.0830 mm) @ (119.0, 112.0)
- **drc**: clearance: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.0428 mm) @ (119.0, 112.0)

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `cutoff` | -3 dB frequency from J1.1 to J2.1 (dc source on J1.1; ground = J1.2) | 15.26 kHz … 18.65 kHz | 16.94 kHz | ✅ | 16.94 kHz | ✅ |
| `passband_gain` | AC gain \|V(J2.1)/V(J1.1)\| at 847.5 Hz (dc source on J1.1; ground = J1.2) | 969.8 m … 1.03 | 999.8 m | ✅ | 999.8 m | ✅ |
| `stopband_gain` | AC gain \|V(J2.1)/V(J1.1)\| at 169.5 kHz (dc source on J1.1; ground = J1.2) | 8.096 m … 13.49 m | 10.79 m | ✅ | 10.79 m | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 430 nF … 3.7 uF | `1.2u` | `1.2u` | `1.2u` |  |
| `L1` | L | 22 uH … 230 uH | `68u` | `68u` | `68u` |  |
| `R1` | R | 3.4 Ω … 34 Ω | `11` | `11` | `11` |  |

### 2.6 Layout rules

- power net `GND` (golden pins C1.2, J1.2, J2.2): every track ≥ 0.3 mm

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

