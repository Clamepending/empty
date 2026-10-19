# QA packet 42: `pcbr-nmos_switch-164-a3e65927`

| family | seed | hint level | intent in TASK.md | faults | predicted difficulty |
|---|---|---|---|---|---|
| nmos_switch | 164 | explicit | full | 3 | hard |

Task files: [`../../../tasks/train/pcbr-nmos_switch-164-a3e65927/public/`](../../../tasks/train/pcbr-nmos_switch-164-a3e65927/public/) (what the agent gets) and [`../../../tasks/train/pcbr-nmos_switch-164-a3e65927/hidden/`](../../../tasks/train/pcbr-nmos_switch-164-a3e65927/hidden/) (grader only). Why sampled: 3 faults, connectivity fault, disputable type narrow_power_trace, value near bounds: R2=270k near [4700, 220000].

**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could find and fix the problems from it; then check section 2 (faults, reference fix, verifier verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of section 1.

## 1. What the agent sees

### 1.1 TASK.md (verbatim)

````markdown
# Task: 5 V low-side MOSFET switch

## Problem report

The first boards built from these files fail bring-up. Observations so far:

- Bench: current through J2.2 is 4.987 pA, expected 475 mA to 525 mA (`load_on_current`).
- Bench: current through R1 is 44.61 mA, expected 0 A to 1 mA (`ctrl_current_on`).
- Layout review: a supply trace is narrower than its required width (it runs hot at full load).

A reviewer narrowed the failure down to these areas (each needs a fix):

- the connections of Q1.G / Q1.D
- the value of R2
- the routing of net +5V

Fix every problem (there may be more than the observations show directly).

## Design intent

# 5 V low-side MOSFET switch

A 5 V logic signal switches a 0.5 A load from a 5 V supply.
J1 is the input header: pin 1 = +5 V, pin 2 = GND, pin 3 = CTRL (logic input).
J2 connects the off-board load: pin 1 = +5 V, pin 2 = switched return to the MOSFET drain.
The load is an inductive load (solenoid/motor, ~10 Ω) with Schottky D1 as flyback clamp across J2: cathode to the supply pin, anode to the switched pin.

- Q1 (logic-level NMOS) has its source on GND and drain on the switched node (J2 pin 2).
- CTRL drives the gate through series resistor R1; R2 pulls the gate to GND so the load is off
  when CTRL is floating.
- C1 is a bulk capacitor across the load supply at the input header.

Spec: CTRL = 5 V -> load current 0.5 A ±5 % with VDS ≤ 0.2 V; CTRL floating ->
load off (< 0.1 mA) even with 10 MΩ of leakage from the supply to the gate. Load-current
traces (supply, switched node, GND) at least 0.5 mm wide.
Component values: gate series R1 4.7 Ω–220 Ω (datasheet: 10–100 Ω); gate pull-down R2 4.7 kΩ–220 kΩ
(datasheet: 10k–100k); bulk C1 1 µF–22 µF.

## Spec

The design must satisfy these assertions (`pcbtool sim` runs them; full definitions in `spec.json`):

- `load_on_current`: DC current through J2.2 between 475 mA and 525 mA (J1.1 supplied with 5.0 V; dc source on J1.3; load R=10 L=0.005 from J2.1 to J2.2; ground = J1.2)
- `vds_on`: DC voltage at Q1.D between 0 V and 200 mV (J1.1 supplied with 5.0 V; dc source on J1.3; load R=10 L=0.005 from J2.1 to J2.2; ground = J1.2)
- `load_off_current`: DC current through J2.2 between 0 A and 100 uA (J1.1 supplied with 5.0 V; load R=10 L=0.005 from J2.1 to J2.2; load R=1e+07 from Q1.G to J1.1; ground = J1.2)
- `ctrl_current_on`: DC current through R1 between 0 A and 1 mA (J1.1 supplied with 5.0 V; dc source on J1.3; load R=10 L=0.005 from J2.1 to J2.2; ground = J1.2)

Layout: every track of these nets must be at least the given width:

- +5V (the net of J1.1): ≥ 0.5 mm
- GND (the net of J1.2): ≥ 0.5 mm
- SW (the net of J2.2): ≥ 0.5 mm

Component values: each value must lie in its acceptable range (inclusive; `value_bounds` in `spec.json`). Ranges come from the datasheets and the design intent; values the assertions already pin down get a wide sanity range, and the assertions still apply:

- C1 (C): 1 uF … 22 uF
- R1 (R): 4.7 Ω … 220 Ω
- R2 (R): 4.7 kΩ … 220 kΩ

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

<details><summary>Datasheet <code>parts/CONN3.md</code></summary>

````markdown
# CONN3 — 3-pin 2.54 mm header

Generic vertical pin header used for off-board power, signal and bus connections.

| Pin | Pad | Typical use |
|---|---|---|
| 1 | 1 | signal / supply |
| 2 | 2 | ground (board convention) |
| 3 | 3 | signal / supply |

## Notes
- Pin 2 is ground by board convention; the function of the other pins is set by the design.
- Rated 3 A per contact. Has no electrical model of its own (it is where external
  supplies, signals and loads attach).
````

</details>

<details><summary>Datasheet <code>parts/D_SCHOTTKY.md</code></summary>

````markdown
# D_SCHOTTKY — 40 V / 1 A Schottky rectifier

## Pinout
| Pin | Pad | Function |
|---|---|---|
| A | 2 | anode |
| K | 1 | cathode (band) |

## Electrical characteristics
- VRRM 40 V, IF(AV) 1 A
- Vf = 0.30 V typ at 100 mA, 0.40 V at 1 A
- Reverse leakage 20 uA typ at 25 V

## Application notes
- Flyback / freewheel clamp across an inductive load (relay coil, solenoid, motor):
  cathode to the positive supply side, anode to the switched (transistor) side. In normal
  operation the diode is reverse biased; at turn-off it clamps the inductive kick.
- Reverse polarity protection: in series with the supply, anode to the input.
````

</details>

<details><summary>Datasheet <code>parts/NMOS.md</code></summary>

````markdown
# NMOS — logic-level N-channel MOSFET (SOT-23)

## Pinout
| Pin | Pad | Function |
|---|---|---|
| G | 1 | gate |
| S | 2 | source |
| D | 3 | drain |

## Electrical characteristics
- VDS max 30 V, ID max 2 A continuous, VGS max ±12 V
- VGS(th) 1.2 V typ (0.8–1.5 V)
- RDS(on) 0.10 Ω at VGS = 4.5 V; 0.15 Ω at VGS = 3.3 V; 0.25 Ω at 2.5 V
- Ciss ~300 pF; internal body diode source -> drain

## Application notes
- Low-side switch: source to ground, load between supply and drain.
- Gate series resistor 10–100 Ω limits ringing / driver current.
- Gate pull-down 10k–100k to source keeps the FET off when the control input floats.
- Inductive loads need a flyback diode across the load (cathode to supply).
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
| 1 | `transistor_pinout` | connectivity | yes | Q1.G and Q1.D connections exchanged (pinout error) | reward 0.0; fails layout, spec, topology |
| 2 | `wrong_pull_resistor` | value | yes | R2 (pull-up/pull-down resistor) is 270k, should be 13k | reward 0.0; fails values |
| 3 | `narrow_power_trace` | board | yes | 3 segment(s) of power net +5V are 0.2 mm wide (required 0.5 mm) | reward 0.0; fails layout |

### 2.2 Reference fix (faulted → golden)

The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). Any repair that passes every gate and check scores 1.0; it need not be byte-identical.

**design.json: component changes**

- `R2` value: `270k` → `13k`

**design.json: connection changes** (per pin: what it connects to)

- `Q1.D`: faulted net `GATE` (R1.2, R2.1) → golden net `SW` (D1.A, J2.2)
- `Q1.G`: faulted net `SW` (D1.A, J2.2) → golden net `GATE` (R1.2, R2.1)

**board.kicad_pcb: footprints moved / changed**

- none

**board.kicad_pcb: footprint values (BOM)**

- `R2` board value `270k` → `13k`

**board.kicad_pcb: pad-net changes**

- `Q1` pad 1: net `SW` → `GATE`
- `Q1` pad 3: net `GATE` → `SW`

**board.kicad_pcb: nets re-routed** (track/via geometry differs)

- net `+5V`: 3 track/via item(s) removed, 3 added; narrowest track 0.2 mm → 0.5 mm
- net `GATE`: 2 track/via item(s) removed, 1 added
- net `SW`: 2 track/via item(s) removed, 2 added

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
| values | check | **FAIL** | pass |
| layout | check | **FAIL** | pass |
| **reward** | | **0** | **1** |

Verifier messages on the faulted files:

- **layout**: power_width: power net +5V: narrowest track 0.200 mm < required 0.5 mm
- **layout**: power_net_missing: no board net has the pins of golden net SW
- **spec**: load_on_current: measured 4.9873494007e-12 expected [0.475, 0.525]
- **spec**: ctrl_current_on: measured 0.0446059541 expected [0.0, 0.001]
- **topology**: nets only in candidate: [['D1.A', 'J2.2', 'Q1.G'], ['Q1.D', 'R1.2', 'R2.1']]; nets only in reference: [['D1.A', 'J2.2', 'Q1.D'], ['Q1.G', 'R1.2', 'R2.1']]
- **values**: R2: value '270k' outside acceptable range [4700, 220000]

### 2.4 Spec assertions before / after

| assertion | what | allowed | faulted: measured | | golden: measured | |
|---|---|---|---|---|---|---|
| `load_on_current` | DC current through J2.2 (J1.1 supplied with 5.0 V; dc source on J1.3; load R=10 L=0.005 from J2.1 to J2.2; ground = J1.2) | 475 mA … 525 mA | 4.987 pA | ❌ | 495.3 mA | ✅ |
| `vds_on` | DC voltage at Q1.D (J1.1 supplied with 5.0 V; dc source on J1.3; load R=10 L=0.005 from J2.1 to J2.2; ground = J1.2) | 0 V … 200 mV | 4.133 mV | ✅ | 46.34 mV | ✅ |
| `load_off_current` | DC current through J2.2 (J1.1 supplied with 5.0 V; load R=10 L=0.005 from J2.1 to J2.2; load R=1e+07 from Q1.G to J1.1; ground = J1.2) | 0 A … 100 uA | 4.995 pA | ✅ | 1.005 nA | ✅ |
| `ctrl_current_on` | DC current through R1 (J1.1 supplied with 5.0 V; dc source on J1.3; load R=10 L=0.005 from J2.1 to J2.2; ground = J1.2) | 0 A … 1 mA | 44.61 mA | ❌ | 381.3 uA | ✅ |

### 2.5 Value bounds

Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.

| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |
|---|---|---|---|---|---|---|
| `C1` | C | 1 uF … 22 uF | `3.3u` | `3.3u` | `3.3u` |  |
| `R1` | R | 4.7 Ω … 220 Ω | `62` | `62` | `62` |  |
| `R2` | R | 4.7 kΩ … 220 kΩ | `270k` ⚠ out of range | `270k` ⚠ out of range | `13k` | **yes** |

### 2.6 Layout rules

- power net `+5V` (golden pins C1.1, D1.K, J1.1, J2.1): every track ≥ 0.5 mm
- power net `GND` (golden pins C1.2, J1.2, Q1.S, R2.2): every track ≥ 0.5 mm
- power net `SW` (golden pins D1.A, J2.2, Q1.D): every track ≥ 0.5 mm

## 3. Review

Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to `review-<initials>.yaml` here, without looking at the first form). Questions to answer:

1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate and fix every injected fault? Is anything required that is not stated (a value with no assertion and no published range, a connection only the golden reveals)?
2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?
3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons given in 2.3?
4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject (e.g. a different E-series value that meets intent but fails an assertion window or value bound; keeping a swapped footprint and re-routing; a different valid placement)?

