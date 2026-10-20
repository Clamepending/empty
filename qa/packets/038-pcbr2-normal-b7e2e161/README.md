# QA packet 038: `pcbr2-normal-b7e2e161`

| family | tier | tool mode | hint level | intent in TASK.md | faults | latent | predicted difficulty |
|---|---|---|---|---|---|---|---|
| opamp_inv | normal | full | explicit | full | 3 | 0 | hard |

Task files: [`../../../tasks/v2/normal/pcbr2-normal-b7e2e161/public/`](../../../tasks/v2/normal/pcbr2-normal-b7e2e161/public/) (what the agent gets) and [`../../../tasks/v2/normal/pcbr2-normal-b7e2e161/hidden/`](../../../tasks/v2/normal/pcbr2-normal-b7e2e161/hidden/) (grader only). Why sampled: 3 faults, connectivity fault, disputable type decap_moved_far, value near bounds: R2=162k inside [92000, 740000].

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: inverting x15 AC amplifier

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Bench: J3.1 reads 5.007 mV, expected 2.425 V to 2.575 V (`dc_bias_out`).
- Network analyser: gain J2.1 → J3.1 at 1 kHz is 0.0001685, expected 14.49 to 15.39 (`midband_gain`).
- Network analyser: −3 dB corner J2.1 → J3.1 measured at 9.083 Hz, expected 85.46 Hz to 115.6 Hz (`low_cutoff`).
- Layout review: a decoupling capacitor sits too far from the IC pin it decouples.

A reviewer narrowed the failure down to these areas (each needs a fix):

- the connections of U1.IN+ / U1.IN-
- the value of R2
- the placement of C1

Fix every problem (there may be more than the observations show directly).

## Design intent

# Inverting x15 AC amplifier (single supply)

Amplifies an AC signal on J2 (pin 1 = input, pin 2 = GND) with a gain of -15 and outputs it on
J3 (pin 1 = output, pin 2 = GND), centred at mid-supply. Single 5 V supply on J1
(pin 1 = VCC, pin 2 = GND).

- U1 (OPAMP): V+ on VCC (decoupled by C1 at the pin), V- on GND.
- Mid-supply reference: equal resistors R3 (VCC to VMID) and R4 (VMID to GND), bypassed by C3 to GND;
  VMID drives the non-inverting input.
- The input is AC-coupled: J2 pin 1 -> C2 -> R1 -> IN-. R2 is the feedback resistor from OUT to IN-.
  Gain = -R2/R1; the coupling capacitor sets the low cut-off 1/(2π·R1·C2) ≈ 100 Hz.

Spec: output DC level VCC/2 ±3 %; |gain| 14.9 ±3 % at 1 kHz; low -3 dB corner 101 Hz ±15 %.
Component values: decoupling C1 47 nF–10 µF (100 nF typical); bias divider R3, R4 4.7 kΩ–470 kΩ each;
VMID bypass C3 470 nF–47 µF.

Sub-circuits by purpose: supply connector (J1); op-amp with supply decoupling (U1, C1); mid-supply bias divider and bypass (R3, R4, C3); input coupling capacitor (C2); gain-setting input and feedback resistors (R1, R2); input connector (J2); output connector (J3).

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `dc_bias_out`: DC voltage at J3.1 between 2.425 V and 2.575 V (J1.1 supplied with 5.0 V; 1.0 V AC source on J2.1; ground = J1.2)
- `midband_gain`: AC gain |V(J3.1)/V(J2.1)| at 1 kHz between 14.49 and 15.39 (J1.1 supplied with 5.0 V; 1.0 V AC source on J2.1; ground = J1.2)
- `low_cutoff`: -3 dB frequency from J2.1 to J3.1 between 85.46 Hz and 115.6 Hz (J1.1 supplied with 5.0 V; 1.0 V AC source on J2.1; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- GND (the net of J1.2): ≥ 0.3 mm
- VCC (the net of J1.1): ≥ 0.3 mm

Decoupling: each capacitor's pad on the IC pin's net must reach the IC pin's pad within the given length of copper path (shortest path along that net's tracks, vias and pads, pad centre to pad centre; a cap wired to the pin the long way round does not decouple it), and every pad of the capacitor must lie within the given straight-line distance of the IC pin's pad:

- C1 within 6.0 mm of copper path of U1.V+ (and within 5.0 mm straight-line)

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 47 nF … 10 uF
- C2 (C): 27 nF … 280 nF
- C3 (C): 470 nF … 47 uF
- R1 (R): 5.2 kΩ … 55 kΩ
- R2 (R): 92 kΩ … 740 kΩ
- R3 (R): 4.7 kΩ … 470 kΩ
- R4 (R): 4.7 kΩ … 470 kΩ

Resistor power rule: every resistor's continuous dissipation I²·R must stay at or below 50 % of its
footprint's rated power (0603 0.1 W, 0805 0.125 W, 1206 0.5 W; see `parts/R.md`). The grader checks
this under the spec's operating conditions; `pcbtool` does not.

Board rules: 2 copper layers, clearance 0.2 mm, min track 0.2 mm, vias 0.6/0.3 mm, copper-to-edge 0.3 mm. DRC must be clean with no unconnected items.

## Deliverable

- Edit only `design.json` (the schematic of record) and `board.kicad_pcb` (the layout).
- Do not add, remove or rename components; keep each component's part.
- Keep the two files consistent: same connectivity, values and footprints on both.
- Values: `<number><SI prefix><unit>` such as `4.7k`, `100n`, `10kΩ`, `1meg`; unit letters, if any, must match the part (R: Ω/ohm/R, C: F, L: H, crystal: Hz); no spaces or control characters inside (full grammar: "Value notation" in `parts/R.md`, `parts/C.md`, ...).
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
- Decouple V+ with 100 nF ceramic (47 nF–10 µF) to ground within 5 mm of the pin.
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
| 1 | `swapped_ic_pins` | connectivity | yes |  | U1.IN+ and U1.IN- connections exchanged | reward 0.0; fails spec, topology |
| 2 | `wrong_feedback_resistor` | value | yes |  | R2 (gain/divider-setting resistor) is 162k, should be 237k | reward 0.0; fails spec |
| 3 | `decap_moved_far` | board | yes |  | C1 placed at (114.0, 126.5), 10.1 mm from U1.V+ (max 5.0 mm) | reward 0.0; fails layout |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `R2` value: `162k` → `237k`

**design.json: connection changes** (per pin: what it connects to)

- `U1.IN+`: faulted net `Net-(R1-Pad2)` (R1.2, R2.1) → golden net `VMID` (C3.1, R3.2, R4.1)
- `U1.IN-`: faulted net `VMID` (C3.1, R3.2, R4.1) → golden net `SUM` (R1.2, R2.1)

**board.kicad_pcb: footprints moved / changed**

- `C1` moved (114.00, 126.50, 0°, F) → (125.00, 126.00, 0°, F), 11.01 mm

**board.kicad_pcb: footprint values (BOM)**

- `R2` board value `162k` → `237k`

**board.kicad_pcb: pad-net changes**

- `C2` pad 2: net `Net-(C2-Pad2)` → `IN_AC`
- `R1` pad 1: net `Net-(C2-Pad2)` → `IN_AC`
- `R1` pad 2: net `Net-(R1-Pad2)` → `SUM`
- `R2` pad 1: net `Net-(R1-Pad2)` → `SUM`
- `U1` pad 3: net `Net-(R1-Pad2)` → `VMID`
- `U1` pad 4: net `VMID` → `SUM`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `GND`: 6 track/via item(s) removed, 9 added
- net `IN_AC`: 0 track/via item(s) removed, 2 added
- net `Net-(C2-Pad2)`: 2 track/via item(s) removed, 0 added
- net `Net-(R1-Pad2)`: 8 track/via item(s) removed, 0 added
- net `SUM`: 0 track/via item(s) removed, 3 added
- net `VCC`: 7 track/via item(s) removed, 2 added
- net `VMID`: 10 track/via item(s) removed, 2 added

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
| values | check | pass | pass |
| layout | check | **FAIL** | pass |
| rules | check | pass | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **layout**: decoupling: C1.1 is 11.86 mm from U1.V+ (max 5.0 mm)
- **layout**: decoupling: C1.2 is 10.06 mm from U1.V+ (max 5.0 mm)
- **layout**: decoupling: C1 reaches U1.V+ through 12.79 mm of copper (max 6.0 mm)
- **spec**: dc_bias_out: measured 0.0050073499526 expected [2.425, 2.575]
- **spec**: midband_gain: measured 0.0001684507375703555 expected [14.4943, 15.3909]
- **spec**: low_cutoff: measured 9.082714185990794 expected [85.4625, 115.626]
- **topology**: nets only in candidate: [['C3.1', 'R3.2', 'R4.1', 'U1.IN-'], ['R1.2', 'R2.1', 'U1.IN+']]; nets only in reference: [['C3.1', 'R3.2', 'R4.1', 'U1.IN+'], ['R1.2', 'R2.1', 'U1.IN-']]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `dc_bias_out` | DC voltage at J3.1 (J1.1 supplied with 5.0 V; 1.0 V AC source on J2.1; ground = J1.2) | 2.425 V … 2.575 V | 5.007 mV | ❌ | 2.5 V | ✅ |
| `midband_gain` | AC gain \|V(J3.1)/V(J2.1)\| at 1 kHz (J1.1 supplied with 5.0 V; 1.0 V AC source on J2.1; ground = J1.2) | 14.49 … 15.39 | 168.5 u | ❌ | 14.94 | ✅ |
| `low_cutoff` | -3 dB frequency from J2.1 to J3.1 (J1.1 supplied with 5.0 V; 1.0 V AC source on J2.1; ground = J1.2) | 85.46 Hz … 115.6 Hz | 9.083 Hz | ❌ | 100.6 Hz | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 47 nF … 10 uF | `100n` | `100n` | `100n` | **yes** |
| `C2` | C | 27 nF … 280 nF | `100n` | `100n` | `100n` |  |
| `C3` | C | 470 nF … 47 uF | `10u` | `10u` | `10u` |  |
| `R1` | R | 5.2 kΩ … 55 kΩ | `15.8k` | `15.8k` | `15.8k` |  |
| `R2` | R | 92 kΩ … 740 kΩ | `162k` | `162k` | `237k` | **yes** |
| `R3` | R | 4.7 kΩ … 470 kΩ | `43k` | `43k` | `43k` |  |
| `R4` | R | 4.7 kΩ … 470 kΩ | `43k` | `43k` | `43k` |  |

### 2.6 Layout rules

- power net `GND` (golden pins C1.2, C3.2, J1.2, J2.2, J3.2, R4.2, U1.V-): every track ≥ 0.3 mm
- power net `VCC` (golden pins C1.1, J1.1, R3.1, U1.V+): every track ≥ 0.3 mm
- decoupling: `C1` within 6.0 mm of copper path (and 5.0 mm straight-line) of `U1.V+`

### 2.8 Design rules (`rules` check, not run by pcbtool)

Scope: resistor power only (`rules_power`, all v2 tiers); 1 operating condition(s) from the spec's stimuli; 4 rule quantities evaluated per design. Rows shown: violated on either side, on a part a fault touches (if ≥ 5 % of its limit or changed by ≥ 5 points or by a footprint change), or at ≥ 80% of the limit. Values are the worst case over the conditions (computed with `pcbenv.rules.operating_point`; limits from `pcbenv/rules.py`, stated in `parts/<PART>.md` and TASK.md "Design rules").

- no rule quantity is violated, touched by a fault, or within 80 % of a limit

Rule violations reported by the verifier: faulted: none; golden: none.

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?
5. **rule_stated_clearly**: is every design rule / layout rule / latent requirement this task grades (2.7–2.9) stated in the public material clearly enough that an engineer would apply it the way the grader does (limit, which part, which condition)? Normal-tier tasks: answer for the resistor-power rule (`yes` if no rule is involved).
6. **layout_rule_reasonable**: hard_layout tasks only (else `n/a`): are the layout-rule limits and their geometric definitions (2.9) defensible engineering practice for this board, i.e. would you reject the faulted layout in a design review, and accept the golden one?

