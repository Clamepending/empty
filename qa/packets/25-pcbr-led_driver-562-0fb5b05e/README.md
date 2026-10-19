# QA packet 25: `pcbr-led_driver-562-0fb5b05e`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| led_driver | 562 | explicit | full | 3 | hard |

Task files: [`../../../tasks/train/pcbr-led_driver-562-0fb5b05e/public/`](../../../tasks/train/pcbr-led_driver-562-0fb5b05e/public/) (what the agent gets) and [`../../../tasks/train/pcbr-led_driver-562-0fb5b05e/hidden/`](../../../tasks/train/pcbr-led_driver-562-0fb5b05e/hidden/) (grader only). Why sampled: 3 faults, disputable type narrow_power_trace.

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 1-channel LED indicator board

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Bench: current through D1 is 1.927 A, expected 4.5 mA to 5.5 mA (`string1_current`).
- The assembled board does not behave like the simulated schematic: the layout's netlist disagrees with design.json.
- Layout review: a supply trace is narrower than its required width (it runs hot at full load).

A reviewer narrowed the failure down to these areas (each needs a fix):

- the value of R1
- the board pads of D1 vs. design.json
- the routing of net VS

Fix every problem (there may be more than the observations show directly).

## Design intent

# 1-channel LED indicator board

Lights 1 indicator LEDs from a 9 V supply on J1
(pin 1 = +9 V, pin 2 = GND). Each channel is a series string of LEDs fed through its own
current-limiting resistor; the resistor sets the current from (Vs - n*Vf)/R.

- Channel 1: 1 red LED(s) at 5 mA: supply -> R1 -> D1 (anode to cathode) -> GND.

Spec: each channel's LED current within ±10 % of its target. Resistors dissipating more than
~60 mW use a 1206 footprint.

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `string1_current`: DC current through D1 between 4.5 mA and 5.5 mA (J1.1 supplied with 9.0 V; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- GND (the net of J1.2): ≥ 0.3 mm
- VS (the net of J1.1): ≥ 0.3 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- R1 (R): 380 Ω … 5.9 kΩ

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

<details><summary>Datasheet <code>parts/CONN2.md</code></summary>

````markdown
# CONN2 — 2-pin header

Pin `1` = signal/supply, pin `2` = ground by board convention.
````

</details>

<details><summary>Datasheet <code>parts/LED_RED.md</code></summary>

````markdown
# LED_RED — red SMD indicator LED (625 nm)

## Pinout
| Pin | Pad | Function |
|---|---|---|
| A | 2 | anode |
| K | 1 | cathode (marked) |

## Electrical characteristics (25 C)
- Forward voltage Vf = 2.0 V typ at IF = 10 mA
- Max continuous forward current 25 mA; reverse voltage max 5 V

| IF | Vf (typ) |
|---|---|
| 2 mA | 1.90 V |
| 5 mA | 1.95 V |
| 10 mA | 2.00 V |
| 15 mA | 2.03 V |
| 20 mA | 2.06 V |

## Application notes
- Always drive through a current-limiting resistor: R = (Vsupply - n*Vf) / IF for n LEDs in series.
- Current flows anode -> cathode; reversed LEDs do not light.
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
| 1 | `magnitude_slip` | value | yes | R1 is 1.5 (unit slip), should be 1.5k | reward 0.0; fails spec, values |
| 2 | `board_pad_swap` | board | yes | board pads of D1.A (pad 2) and D1.K (pad 1) carry each other's nets | reward 0.0; fails consistency, layout |
| 3 | `narrow_power_trace` | board | yes | 1 segment(s) of power net VS are 0.2 mm wide (required 0.3 mm) | reward 0.0; fails layout |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `R1` value: `1.5` → `1.5k`

**design.json: connection changes** (per pin: what it connects to)

- none

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- `R1` board value `1.5` → `1.5k`

**board.kicad_pcb: pad-net changes**

- `D1` pad 1: net `CH1_0` → `GND`
- `D1` pad 2: net `GND` → `CH1_0`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `CH1_0`: 5 track/via item(s) removed, 2 added
- net `GND`: 2 track/via item(s) removed, 1 added
- net `VS`: 1 track/via item(s) removed, 1 added; narrowest track 0.2 mm → 0.3 mm

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
| layout | check | **FAIL** | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **consistency**: board connectivity != design.json: nets only in candidate: [['D1.A', 'J1.2'], ['D1.K', 'R1.2']]; nets only in reference: [['D1.A', 'R1.2'], ['D1.K', 'J1.2']]
- **layout**: power_net_missing: no board net has the pins of golden net GND
- **layout**: power_width: power net VS: narrowest track 0.200 mm < required 0.3 mm
- **spec**: string1_current: measured 1.9273962893 expected [0.0045, 0.0055]
- **values**: R1: value '1.5' outside acceptable range [380, 5900]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `string1_current` | DC current through D1 (J1.1 supplied with 9.0 V; ground = J1.2) | 4.5 mA … 5.5 mA | 1.927 A | ❌ | 4.7 mA | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `R1` | R | 380 Ω … 5.9 kΩ | `1.5` ⚠ out of range | `1.5` ⚠ out of range | `1.5k` | **yes** |

### 2.6 Layout rules

- power net `GND` (golden pins D1.K, J1.2): every track ≥ 0.3 mm
- power net `VS` (golden pins J1.1, R1.1): every track ≥ 0.3 mm

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

