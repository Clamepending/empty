# QA packet 014: `pcbr2-normal-64adf6f3`

| family | tier | tool mode | hint level | intent in TASK.md | faults | latent | predicted difficulty |
|---|---|---|---|---|---|---|---|
| led_driver | normal | full | explicit | full | 3 | 0 | hard |

Task files: [`../../../tasks/v2/normal/pcbr2-normal-64adf6f3/public/`](../../../tasks/v2/normal/pcbr2-normal-64adf6f3/public/) (what the agent gets) and [`../../../tasks/v2/normal/pcbr2-normal-64adf6f3/hidden/`](../../../tasks/v2/normal/pcbr2-normal-64adf6f3/hidden/) (grader only). Why sampled: 3 faults, disputable type footprint_swap, disputable type narrow_power_trace, value near bounds: R2=91 near [100, 700].

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 2-channel LED indicator board

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Bench: current through D6 is 53.6 mA, expected 18 mA to 22 mA (`string2_current`).
- The fab's DRC run reports 2 unconnected item(s).
- Layout review: a track on a net with a required minimum width (see the layout rules) is narrower than that width.

A reviewer narrowed the failure down to these areas (each needs a fix):

- the value of R2
- the routing of net GND
- the footprint of D4 and its tracks

Fix every problem (there may be more than the observations show directly).

## Design intent

# 2-channel LED indicator board

Lights 6 indicator LEDs from a 12 V supply on J1
(pin 1 = +12 V, pin 2 = GND). Each channel is a series string of LEDs fed through its own
current-limiting resistor; the resistor sets the current from (Vs - n*Vf)/R.

- Channel 1: 3 green LED(s) at 10 mA: supply -> R1 -> D1 (anode to cathode) -> D2 (anode to cathode) -> D3 (anode to cathode) -> GND.
- Channel 2: 3 green LED(s) at 20 mA: supply -> R2 -> D4 (anode to cathode) -> D5 (anode to cathode) -> D6 (anode to cathode) -> GND.

Spec: each channel's LED current within ±10 % of its target. Resistors dissipating more than
~60 mW use a 1206 footprint.

Sub-circuits by purpose: supply connector (J1); channel 1 current-limiting resistor and LED string (R1, D1, D2, D3); channel 2 current-limiting resistor and LED string (R2, D4, D5, D6).

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `string1_current`: DC current through D3 between 9 mA and 11 mA (J1.1 supplied with 12.0 V; ground = J1.2)
- `string2_current`: DC current through D6 between 18 mA and 22 mA (J1.1 supplied with 12.0 V; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- GND (the net of J1.2): ≥ 0.3 mm
- VS (the net of J1.1): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- R1 (R): 150 Ω … 1.7 kΩ
- R2 (R): 100 Ω … 700 Ω

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

<details><summary>Datasheet <code>parts/CONN2.md</code></summary>

````markdown
# CONN2 — 2-pin header

Pin `1` = signal/supply, pin `2` = ground by board convention.
````

</details>

<details><summary>Datasheet <code>parts/LED_GREEN.md</code></summary>

````markdown
# LED_GREEN — green SMD indicator LED (570 nm)

## Pinout
| Pin | Pad | Function |
|---|---|---|
| A | 2 | anode |
| K | 1 | cathode (marked) |

## Electrical characteristics (25 C)
- Forward voltage Vf = 2.2 V typ at IF = 10 mA
- Max continuous forward current 25 mA; reverse voltage max 5 V

| IF | Vf (typ) |
|---|---|
| 2 mA | 2.10 V |
| 5 mA | 2.15 V |
| 10 mA | 2.20 V |
| 15 mA | 2.23 V |
| 20 mA | 2.26 V |

## Application notes
- Always drive through a current-limiting resistor: R = (Vsupply - n*Vf) / IF for n LEDs in series.
- Current flows anode -> cathode; reversed LEDs do not light.
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
| 1 | `wrong_led_resistor` | value | yes |  | R2 (LED current-limiting resistor) is 91, should be 270 | reward 0.0; fails rules, spec, values |
| 2 | `narrow_power_trace` | board | yes |  | 2 segment(s) of power net GND are 0.2 mm wide (required 0.3 mm) | reward 0.0; fails layout |
| 3 | `footprint_swap` | board | no |  | D4 footprint changed to LED_SMD:LED_0603_1608Metric (was LED_SMD:LED_0805_2012Metric); tracks no longer fit | reward 0.0; fails drc |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `D4` footprint: `LED_SMD:LED_0603_1608Metric` → `LED_SMD:LED_0805_2012Metric`
- `R2` value: `91` → `270`

**design.json: connection changes** (per pin: what it connects to)

- none

**board.kicad_pcb: footprints moved / changed**

- `D4` footprint `LED_SMD:LED_0603_1608Metric` → `LED_SMD:LED_0805_2012Metric`

**board.kicad_pcb: footprint values (BOM)**

- `R2` board value `91` → `270`

**board.kicad_pcb: pad-net changes**

- `D1` pad 1: net `Net-(D1-Pad1)` → `CH1_1`
- `D1` pad 2: net `Net-(D1-Pad2)` → `CH1_0`
- `D2` pad 1: net `Net-(D2-Pad1)` → `CH1_2`
- `D2` pad 2: net `Net-(D1-Pad1)` → `CH1_1`
- `D3` pad 2: net `Net-(D2-Pad1)` → `CH1_2`
- `D5` pad 1: net `Net-(D5-Pad1)` → `CH2_2`
- `D5` pad 2: net `Net-(D4-Pad1)` → `CH2_1`
- `D6` pad 2: net `Net-(D5-Pad1)` → `CH2_2`
- `R1` pad 2: net `Net-(D1-Pad2)` → `CH1_0`
- `R2` pad 2: net `Net-(D4-Pad2)` → `CH2_0`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `CH1_0`: 0 track/via item(s) removed, 5 added
- net `CH1_1`: 0 track/via item(s) removed, 1 added
- net `CH1_2`: 0 track/via item(s) removed, 1 added
- net `CH2_0`: 0 track/via item(s) removed, 1 added
- net `CH2_1`: 0 track/via item(s) removed, 2 added
- net `CH2_2`: 0 track/via item(s) removed, 2 added
- net `GND`: 2 track/via item(s) removed, 2 added; narrowest track 0.2 mm → 0.3 mm
- net `Net-(D1-Pad1)`: 1 track/via item(s) removed, 0 added
- net `Net-(D1-Pad2)`: 5 track/via item(s) removed, 0 added
- net `Net-(D2-Pad1)`: 1 track/via item(s) removed, 0 added
- net `Net-(D4-Pad1)`: 2 track/via item(s) removed, 0 added
- net `Net-(D4-Pad2)`: 1 track/via item(s) removed, 0 added
- net `Net-(D5-Pad1)`: 2 track/via item(s) removed, 0 added

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
| spec | check | **FAIL** | pass |
| values | check | **FAIL** | pass |
| layout | check | **FAIL** | pass |
| rules | check | **FAIL** | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **drc**: 2 unconnected items
- **layout**: power_width: power net GND: narrowest track 0.200 mm < required 0.3 mm
- **rules**: resistor_power: R2 dissipates 261 mW > 250 mW (50 % of 0.5 W, R_1206_3216Metric) [condition 0]
- **spec**: string2_current: measured 0.053602017979 expected [0.018, 0.022]
- **values**: R2: value '91' outside acceptable range [100, 700]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `string1_current` | DC current through D3 (J1.1 supplied with 12.0 V; ground = J1.2) | 9 mA … 11 mA | 9.656 mA | ✅ | 9.656 mA | ✅ |
| `string2_current` | DC current through D6 (J1.1 supplied with 12.0 V; ground = J1.2) | 18 mA … 22 mA | 53.6 mA | ❌ | 19.41 mA | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `R1` | R | 150 Ω … 1.7 kΩ | `560` | `560` | `560` |  |
| `R2` | R | 100 Ω … 700 Ω | `91` ⚠ out of range | `91` ⚠ out of range | `270` | **yes** |

### 2.6 Layout rules

- power net `GND` (golden pins D3.K, D6.K, J1.2): every track ≥ 0.3 mm
- power net `VS` (golden pins J1.1, R1.1, R2.1): every track ≥ 0.3 mm

### 2.8 Design rules (`rules` check, not run by pcbtool)

Scope: resistor power only (`rules_power`, all v2 tiers); 1 operating condition(s) from the spec's stimuli; 2 rule quantities evaluated per design. Rows shown: violated on either side, on a part a fault touches (if ≥ 5 % of its limit or changed by ≥ 5 points or by a footprint change), or at ≥ 80% of the limit. Values are the worst case over the conditions (computed with `pcbenv.rules.operating_point`; limits from `pcbenv/rules.py`, stated in `parts/<PART>.md` and TASK.md "Design rules").

| rule | subject | quantity | limit | faulted (of limit) | golden (of limit) | shown because | worst condition (faulted) |
|---|---|---|---|---|---|---|---|
| `resistor_power` | `R1` | I²R | 62.5 mW | 0805: 52.22 mW of 62.5 mW (84%) | 0805: 52.22 mW of 62.5 mW (84%) | near limit | cond 0 |
| `resistor_power` | `R2` | I²R | 250 mW | 1206: 261.5 mW of 250 mW (105%) ❌ | 1206: 101.7 mW of 250 mW (41%) | violated | cond 0 |

Rule violations reported by the verifier: faulted: resistor_power: R2 dissipates 261 mW > 250 mW (50 % of 0.5 W, R_1206_3216Metric) [condition 0]; golden: none.

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?
5. **rule_stated_clearly**: is every design rule / layout rule / latent requirement this task grades (2.7–2.9) stated in the public material clearly enough that an engineer would apply it the way the grader does (limit, which part, which condition)? Normal-tier tasks: answer for the resistor-power rule (`yes` if no rule is involved).
6. **layout_rule_reasonable**: hard_layout tasks only (else `n/a`): are the layout-rule limits and their geometric definitions (2.9) defensible engineering practice for this board, i.e. would you reject the faulted layout in a design review, and accept the golden one?

