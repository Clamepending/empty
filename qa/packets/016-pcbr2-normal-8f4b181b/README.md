# QA packet 016: `pcbr2-normal-8f4b181b`

| family | tier | tool mode | hint level | intent in TASK.md | faults | latent | predicted difficulty |
|---|---|---|---|---|---|---|---|
| led_driver | normal | full | explicit | full | 3 | 0 | hard |

Task files: [`../../../tasks/v2/normal/pcbr2-normal-8f4b181b/public/`](../../../tasks/v2/normal/pcbr2-normal-8f4b181b/public/) (what the agent gets) and [`../../../tasks/v2/normal/pcbr2-normal-8f4b181b/hidden/`](../../../tasks/v2/normal/pcbr2-normal-8f4b181b/hidden/) (grader only). Why sampled: 3 faults, connectivity fault, disputable type bom_mismatch, value near bounds: R2=100 inside [40, 700]; R1=150 inside [26, 270].

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 2-channel LED indicator board

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- LED D2 never lights (`string2_current`: 3.3e-13 A; expected 4.5 mA to 5.5 mA).
- Incoming inspection: a part value on the layout does not match the design.json BOM.

A reviewer narrowed the failure down to these areas (each needs a fix):

- the connections of D2.A / D2.K
- the value of R2
- the value of R1 on the board vs. design.json

Fix every problem (there may be more than the observations show directly).

## Design intent

# 2-channel LED indicator board

Lights 2 indicator LEDs from a 3.3 V supply on J1
(pin 1 = +3.3 V, pin 2 = GND). Each channel is a series string of LEDs fed through its own
current-limiting resistor; the resistor sets the current from (Vs - n*Vf)/R.

- Channel 1: 1 green LED(s) at 15 mA: supply -> R1 -> D1 (anode to cathode) -> GND.
- Channel 2: 1 green LED(s) at 5 mA: supply -> R2 -> D2 (anode to cathode) -> GND.

Spec: each channel's LED current within ±10 % of its target. Resistors dissipating more than
~60 mW use a 1206 footprint.

Sub-circuits by purpose: supply connector (J1); channel 1 current-limiting resistor and LED string (R1, D1); channel 2 current-limiting resistor and LED string (R2, D2).

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `string1_current`: DC current through D1 between 13.5 mA and 16.5 mA (J1.1 supplied with 3.3 V; ground = J1.2)
- `string2_current`: DC current through D2 between 4.5 mA and 5.5 mA (J1.1 supplied with 3.3 V; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- +3V3 (the net of J1.1): ≥ 0.3 mm
- GND (the net of J1.2): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- R1 (R): 26 Ω … 270 Ω
- R2 (R): 40 Ω … 700 Ω

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
| 1 | `reversed_polarity` | connectivity | yes |  | D2 anode/cathode reversed | reward 0.0; fails spec, topology |
| 2 | `wrong_led_resistor` | value | yes |  | R2 (LED current-limiting resistor) is 100, should be 220 | reward 0.0; fails spec |
| 3 | `bom_mismatch` | value | yes |  | board value of R1 is 150, design.json says 68 | reward 0.0; fails consistency |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `R2` value: `100` → `220`

**design.json: connection changes** (per pin: what it connects to)

- `D2.A`: faulted net `GND` (D1.K, J1.2) → golden net `CH2_0` (R2.2)
- `D2.K`: faulted net `Net-(D2-Pad1)` (R2.2) → golden net `GND` (D1.K, J1.2)

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- `R1` board value `150` → `68`
- `R2` board value `100` → `220`

**board.kicad_pcb: pad-net changes**

- `D1` pad 2: net `Net-(D1-Pad2)` → `CH1_0`
- `D2` pad 1: net `Net-(D2-Pad1)` → `GND`
- `D2` pad 2: net `GND` → `CH2_0`
- `R1` pad 2: net `Net-(D1-Pad2)` → `CH1_0`
- `R2` pad 2: net `Net-(D2-Pad1)` → `CH2_0`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `CH1_0`: 0 track/via item(s) removed, 1 added
- net `CH2_0`: 0 track/via item(s) removed, 1 added
- net `GND`: 2 track/via item(s) removed, 1 added
- net `Net-(D1-Pad2)`: 1 track/via item(s) removed, 0 added
- net `Net-(D2-Pad1)`: 2 track/via item(s) removed, 0 added

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
| consistency | gate | **FAIL** | pass |
| integrity | gate | pass | pass |
| drc | check | pass | pass |
| erc | check | pass | pass |
| spec | check | **FAIL** | pass |
| values | check | pass | pass |
| layout | check | pass | pass |
| rules | check | pass | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **consistency**: R1: board value '150' != design value '68'
- **layout_skipped**: no board net has the pins of golden net GND (connectivity differs: see topology)
- **spec**: string2_current: measured 3.2999848657e-13 expected [0.0045, 0.0055]
- **topology**: nets only in candidate: [['D1.K', 'D2.A', 'J1.2'], ['D2.K', 'R2.2']]; nets only in reference: [['D1.K', 'D2.K', 'J1.2'], ['D2.A', 'R2.2']]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `string1_current` | DC current through D1 (J1.1 supplied with 3.3 V; ground = J1.2) | 13.5 mA … 16.5 mA | 15.67 mA | ✅ | 15.67 mA | ✅ |
| `string2_current` | DC current through D2 (J1.1 supplied with 3.3 V; ground = J1.2) | 4.5 mA … 5.5 mA | 3.3e-13 A | ❌ | 5.197 mA | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `R1` | R | 26 Ω … 270 Ω | `68` | `150` | `68` | **yes** |
| `R2` | R | 40 Ω … 700 Ω | `100` | `100` | `220` | **yes** |

### 2.6 Layout rules

- power net `+3V3` (golden pins J1.1, R1.1, R2.1): every track ≥ 0.3 mm
- power net `GND` (golden pins D1.K, D2.K, J1.2): every track ≥ 0.3 mm

### 2.8 Design rules (`rules` check, not run by pcbtool)

Scope: resistor power only (`rules_power`, all v2 tiers); 1 operating condition(s) from the spec's stimuli; 2 rule quantities evaluated per design. Rows shown: violated on either side, on a part a fault touches (if ≥ 5 % of its limit or changed by ≥ 5 points or by a footprint change), or at ≥ 80% of the limit. Values are the worst case over the conditions (computed with `pcbenv.rules.operating_point`; limits from `pcbenv/rules.py`, stated in `parts/<PART>.md` and TASK.md "Design rules").

| rule | subject | quantity | limit | faulted (of limit) | golden (of limit) | shown because | worst condition (faulted) |
|---|---|---|---|---|---|---|---|
| `resistor_power` | `R1` | I²R | 250 mW | 1206: 16.69 mW of 250 mW (7%) | 1206: 16.69 mW of 250 mW (7%) | fault target | cond 0 |
| `resistor_power` | `R2` | I²R | 62.5 mW | 0805: 0 W of 62.5 mW (0%) | 0805: 5.943 mW of 62.5 mW (10%) | fault target | cond 0 |

Rule violations reported by the verifier: faulted: none; golden: none.

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?
5. **rule_stated_clearly**: is every design rule / layout rule / latent requirement this task grades (2.7–2.9) stated in the public material clearly enough that an engineer would apply it the way the grader does (limit, which part, which condition)? Normal-tier tasks: answer for the resistor-power rule (`yes` if no rule is involved).
6. **layout_rule_reasonable**: hard_layout tasks only (else `n/a`): are the layout-rule limits and their geometric definitions (2.9) defensible engineering practice for this board, i.e. would you reject the faulted layout in a design review, and accept the golden one?

