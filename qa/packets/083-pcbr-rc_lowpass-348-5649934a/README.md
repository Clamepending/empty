# QA packet 083: `pcbr-rc_lowpass-348-5649934a`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| rc_lowpass | 348 | symptom | reduced | 2 | medium |

Task files: [`../../../tasks/train/pcbr-rc_lowpass-348-5649934a/public/`](../../../tasks/train/pcbr-rc_lowpass-348-5649934a/public/) (what the agent gets) and [`../../../tasks/train/pcbr-rc_lowpass-348-5649934a/hidden/`](../../../tasks/train/pcbr-rc_lowpass-348-5649934a/hidden/) (grader only). Why sampled: connectivity fault, value near bounds: C1=10n near [5.8e-10, 7.8e-09].

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 2nd-order RC low-pass filter

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- `cutoff`: no valid measurement — the circuit does not reach a sensible operating point.
- Network analyser: gain J1.1 → J2.1 at 724.3 Hz is 0, expected 0.9689 to 1.029 (`passband_gain`).
- Network analyser: gain J1.1 → J2.1 at 144.9 kHz is 0, expected 0.02011 to 0.03352 (`stopband_gain`).
- Schematic ERC reports 1× single_pin_net.

Fix every problem (there may be more than the observations show directly).

## Design intent

# 2nd-order RC low-pass filter

Removes high-frequency content from the signal entering on J1 (pin 1 = input, pin 2 = GND) and
delivers the filtered signal on J2 (pin 1 = output, pin 2 = GND). Grounds of J1 and J2 are common.

Spec: order 2; -3 dB corner 1.449e+04 Hz ±10 %; passband gain ≈ 0.999 at fc/20;
attenuation at 10·fc: gain 0.0268 ±25 %.

_Connection details are intentionally not repeated here: wire each part as its datasheet in `parts/` describes (pinout and application notes), so that the circuit does what the purpose, interfaces and spec above require._

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `cutoff`: -3 dB frequency from J1.1 to J2.1 between 13.04 kHz and 15.94 kHz (dc source on J1.1; ground = J1.2)
- `passband_gain`: AC gain |V(J2.1)/V(J1.1)| at 724.3 Hz between 968.9 m and 1.029 (dc source on J1.1; ground = J1.2)
- `stopband_gain`: AC gain |V(J2.1)/V(J1.1)| at 144.9 kHz between 20.11 m and 33.52 m (dc source on J1.1; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- GND (the net of J1.2): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 580 pF … 7.8 nF
- C2 (C): 85 pF … 870 pF
- R1 (R): 1.1 kΩ … 8.9 kΩ
- R2 (R): 9.7 kΩ … 100 kΩ

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
| 1 | `pin_to_wrong_net` | connectivity | no | R1.1 tied to net GND instead of IN | reward 0.0; fails erc, layout, spec, topology |
| 2 | `wrong_filter_cap` | value | yes | C1 (filter/timing capacitor) is 10n, should be 2.2n | reward 0.0; fails spec, values |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `C1` value: `10n` → `2.2n`

**design.json: connection changes** (per pin: what it connects to)

- `R1.1`: faulted net `GND` (C1.2, C2.2, J1.2, J2.2) → golden net `IN` (J1.1)

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- `C1` board value `10n` → `2.2n`

**board.kicad_pcb: pad-net changes**

- `R1` pad 1: net `GND` → `IN`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `GND`: 2 track/via item(s) removed, 0 added
- net `IN`: 0 track/via item(s) removed, 1 added

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

- **erc**: single_pin_net: net 'IN' (J1.1) has a single pin
- **layout**: power_net_missing: no board net has the pins of golden net GND
- **spec**: cutoff: measured None expected [13037.8643, 15935.1674] no -3 dB crossing in sweep
- **spec**: passband_gain: measured 0.0 expected [0.96895, 1.02888]
- **spec**: stopband_gain: measured 0.0 expected [0.020114, 0.033523]
- **topology**: nets only in candidate: [['C1.2', 'C2.2', 'J1.2', 'J2.2', 'R1.1'], ['J1.1']]; nets only in reference: [['C1.2', 'C2.2', 'J1.2', 'J2.2'], ['J1.1', 'R1.1']]
- **values**: C1: value '10n' outside acceptable range [5.8e-10, 7.8e-09]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `cutoff` | -3 dB frequency from J1.1 to J2.1 (dc source on J1.1; ground = J1.2) | 13.04 kHz … 15.94 kHz | — | ❌ | 14.49 kHz | ✅ |
| `passband_gain` | AC gain \|V(J2.1)/V(J1.1)\| at 724.3 Hz (dc source on J1.1; ground = J1.2) | 968.9 m … 1.029 | 0 | ❌ | 998.9 m | ✅ |
| `stopband_gain` | AC gain \|V(J2.1)/V(J1.1)\| at 144.9 kHz (dc source on J1.1; ground = J1.2) | 20.11 m … 33.52 m | 0 | ❌ | 26.82 m | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 580 pF … 7.8 nF | `10n` ⚠ out of range | `10n` ⚠ out of range | `2.2n` | **yes** |
| `C2` | C | 85 pF … 870 pF | `220p` | `220p` | `220p` |  |
| `R1` | R | 1.1 kΩ … 8.9 kΩ | `3k` | `3k` | `3k` | **yes** |
| `R2` | R | 9.7 kΩ … 100 kΩ | `30k` | `30k` | `30k` |  |

### 2.6 Layout rules

- power net `GND` (golden pins C1.2, C2.2, J1.2, J2.2): every track ≥ 0.3 mm

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

