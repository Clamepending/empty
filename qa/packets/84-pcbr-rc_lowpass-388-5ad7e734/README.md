# QA packet 84: `pcbr-rc_lowpass-388-5ad7e734`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| rc_lowpass | 388 | explicit | full | 2 | medium |

Task files: [`../../../tasks/train/pcbr-rc_lowpass-388-5ad7e734/public/`](../../../tasks/train/pcbr-rc_lowpass-388-5ad7e734/public/) (what the agent gets) and [`../../../tasks/train/pcbr-rc_lowpass-388-5ad7e734/hidden/`](../../../tasks/train/pcbr-rc_lowpass-388-5ad7e734/hidden/) (grader only). Why sampled: disputable type bom_mismatch, value near bounds: R1=1.5k inside [960, 8400].

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 2nd-order RC low-pass filter

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Network analyser: −3 dB corner J1.1 → J2.1 measured at 709 Hz, expected 421.8 Hz to 515.5 Hz (`cutoff`).
- Network analyser: gain J1.1 → J2.1 at 4.687 kHz is 0.1496, expected 0.02011 to 0.03352 (`stopband_gain`).
- Incoming inspection: a part value on the layout does not match the design.json BOM.

A reviewer narrowed the failure down to these areas (each needs a fix):

- the value of R1 on the board vs. design.json
- the value of R2

Fix every problem (there may be more than the observations show directly).

## Design intent

# 2nd-order RC low-pass filter

Removes high-frequency content from the signal entering on J1 (pin 1 = input, pin 2 = GND) and
delivers the filtered signal on J2 (pin 1 = output, pin 2 = GND). Grounds of J1 and J2 are common.

Topology: two cascaded RC sections: R1 from the input to MID with C1 from MID to GND, then R2 (≈10x R1, to limit loading) from MID to the output with C2 from the output to GND.

Spec: order 2; -3 dB corner 468.7 Hz ±10 %; passband gain ≈ 0.999 at fc/20;
attenuation at 10·fc: gain 0.0268 ±25 %.

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `cutoff`: -3 dB frequency from J1.1 to J2.1 between 421.8 Hz and 515.5 Hz (dc source on J1.1; ground = J1.2)
- `passband_gain`: AC gain |V(J2.1)/V(J1.1)| at 23.43 Hz between 968.9 m and 1.029 (dc source on J1.1; ground = J1.2)
- `stopband_gain`: AC gain |V(J2.1)/V(J1.1)| at 4.687 kHz between 20.11 m and 33.52 m (dc source on J1.1; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- GND (the net of J1.2): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 24 nF … 190 nF
- C2 (C): 1.8 nF … 24 nF
- R1 (R): 960 Ω … 8.4 kΩ
- R2 (R): 8.2 kΩ … 82 kΩ

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
| 1 | `bom_mismatch` | value | yes | board value of R1 is 1.5k, design.json says 3k | reward 0.0; fails consistency |
| 2 | `magnitude_slip` | value | yes | R2 is 30 (unit slip), should be 30k | reward 0.0; fails spec, values |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `R2` value: `30` → `30k`

**design.json: connection changes** (per pin: what it connects to)

- none

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- `R1` board value `1.5k` → `3k`
- `R2` board value `30` → `30k`

**board.kicad_pcb: pad-net changes**

- none

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- none

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
| values | check | **FAIL** | pass |
| layout | check | pass | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **consistency**: R1: board value '1.5k' != design value '3k'
- **spec**: cutoff: measured 709.0003021340344 expected [421.8134, 515.5497]
- **spec**: stopband_gain: measured 0.1496102122852666 expected [0.020114, 0.033523]
- **values**: R2: value '30' outside acceptable range [8200, 82000]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `cutoff` | -3 dB frequency from J1.1 to J2.1 (dc source on J1.1; ground = J1.2) | 421.8 Hz … 515.5 Hz | 709 Hz | ❌ | 468.5 Hz | ✅ |
| `passband_gain` | AC gain \|V(J2.1)/V(J1.1)\| at 23.43 Hz (dc source on J1.1; ground = J1.2) | 968.9 m … 1.029 | 999.5 m | ✅ | 998.9 m | ✅ |
| `stopband_gain` | AC gain \|V(J2.1)/V(J1.1)\| at 4.687 kHz (dc source on J1.1; ground = J1.2) | 20.11 m … 33.52 m | 149.6 m | ❌ | 26.82 m | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 24 nF … 190 nF | `68n` | `68n` | `68n` |  |
| `C2` | C | 1.8 nF … 24 nF | `6.8n` | `6.8n` | `6.8n` |  |
| `R1` | R | 960 Ω … 8.4 kΩ | `3k` | `1.5k` | `3k` | **yes** |
| `R2` | R | 8.2 kΩ … 82 kΩ | `30` ⚠ out of range | `30` ⚠ out of range | `30k` | **yes** |

### 2.6 Layout rules

- power net `GND` (golden pins C1.2, C2.2, J1.2, J2.2): every track ≥ 0.3 mm

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

