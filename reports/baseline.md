# PCB-Repair baseline report (G7)

**Generated file: do not edit by hand.** Every number below is computed by `reports/make_baseline.py` from the inputs listed at the end. Reproduce and verify with:

```
python3 reports/make_baseline.py && python3 reports/make_baseline.py --check
```

`--check` regenerates the report in memory and exits 1 if it differs from this file. Interpretation and caveats: `reports/INTERPRETATION.md` (hand-written).

## 1. Pass rates per tier × model

One graded attempt per (task, model) unless stated; reward is binary (1 = every gate and check passes). `k/n (rate) [Wilson 95 % interval]`. Contaminated rollouts (transcript audit found repo/hidden-file access) are excluded; rollouts whose transcripts have not been audited yet are included and counted in the *unaudited* column.

| tier | model | graded | distinct tasks | excluded (contaminated) | unaudited (included) | pass [95 % CI] |
|---|---|---|---|---|---|---|
| v1-normal (historical, v1 task set) | haiku | 100 | 50 | 0 | 0 | 99/100 (99 %) [95–100] |
| v1-normal (historical, v1 task set) | sonnet | 100 | 50 | 0 | 0 | 100/100 (100 %) [96–100] |
| v1-normal (historical, v1 task set) | opus | 50 | 50 | 0 | 0 | 50/50 (100 %) [93–100] |
| v2-hard | haiku | 44 | 44 | 0 | 0 | 44/44 (100 %) [92–100] |
| v2-hard | sonnet | 44 | 44 | 0 | 0 | 25/44 (57 %) [42–70] |
| v2-hard | opus | 44 | 44 | 0 | 0 | 42/44 (95 %) [85–99] |
| v2-hard_layout | haiku | 40 | 40 | 2 | 0 | 28/38 (74 %) [58–85] |
| v2-hard_layout | sonnet | 40 | 40 | 4 | 0 | 7/36 (19 %) [10–35] |
| v2-hard_layout | opus | 40 | 40 | 0 | 0 | 38/40 (95 %) [83–99] |

v1 attempts per task: haiku 2, sonnet 2, opus 1.

### Learnable band and G12

Band from `thresholds.yaml`: 10 %–70 %. G12 needs the *best* model's hard-tier pass rate inside `frontier.hard_tier_best_model_pass_band` on ≥ 40 tasks.

| tier | models with pass rate in band | best model | G12 verdict (best model in band) | tasks with pooled pass rate in band |
|---|---|---|---|---|
| v1-normal (historical, v1 task set) | none | sonnet 100/100 (100 %) | n/a (not a hard tier) | 0/50 (0 %) |
| v2-hard | sonnet | haiku 44/44 (100 %) | NOT MET | 19/44 (43 %) |
| v2-hard_layout | sonnet | opus 38/40 (95 %) | NOT MET | 31/40 (78 %) |

Pooled = all clean attempts of all models on that task (1–5 attempts per task), as in `reports/calibration/summary_v1.md`. With one attempt per model, per-model per-task rates are 0 or 1, so G6's per-model task band cannot be measured from these samples; the pooled column mixes models of very different diligence and should not be read as task difficulty.

## 2. Breakdowns (clean rollouts)

Cells are `k/n (rate)`; most cells have n ≤ 10, so read them as descriptive, not significant.

### v1-normal (historical, v1 task set)

**By family**

| group | haiku | sonnet | opus |
|---|---|---|---|
| divider_adc | 10/10 (100 %) | 10/10 (100 %) | 5/5 (100 %) |
| ldo_reg | 10/10 (100 %) | 10/10 (100 %) | 5/5 (100 %) |
| led_driver | 10/10 (100 %) | 10/10 (100 %) | 5/5 (100 %) |
| mcu_i2c | 10/10 (100 %) | 10/10 (100 %) | 5/5 (100 %) |
| nmos_switch | 10/10 (100 %) | 10/10 (100 %) | 5/5 (100 %) |
| npn_switch | 10/10 (100 %) | 10/10 (100 %) | 5/5 (100 %) |
| opamp_inv | 10/10 (100 %) | 10/10 (100 %) | 5/5 (100 %) |
| opamp_noninv | 9/10 (90 %) | 10/10 (100 %) | 5/5 (100 %) |
| rc_lowpass | 10/10 (100 %) | 10/10 (100 %) | 5/5 (100 %) |
| xtal_osc | 10/10 (100 %) | 10/10 (100 %) | 5/5 (100 %) |

**By number of injected faults**

| group | haiku | sonnet | opus |
|---|---|---|---|
| 1 | 40/40 (100 %) | 40/40 (100 %) | 20/20 (100 %) |
| 2 | 39/40 (98 %) | 40/40 (100 %) | 20/20 (100 %) |
| 3 | 20/20 (100 %) | 20/20 (100 %) | 10/10 (100 %) |

**By hint level**

| group | haiku | sonnet | opus |
|---|---|---|---|
| explicit | 20/20 (100 %) | 20/20 (100 %) | 10/10 (100 %) |
| symptom | 40/40 (100 %) | 40/40 (100 %) | 20/20 (100 %) |
| vague | 39/40 (98 %) | 40/40 (100 %) | 20/20 (100 %) |

### v2-hard

**By family**

| group | haiku | sonnet | opus |
|---|---|---|---|
| ldo_reg | 5/5 (100 %) | 1/5 (20 %) | 5/5 (100 %) |
| led_driver | 5/5 (100 %) | 3/5 (60 %) | 5/5 (100 %) |
| mcu_i2c | 5/5 (100 %) | 2/5 (40 %) | 5/5 (100 %) |
| nmos_switch | 5/5 (100 %) | 4/5 (80 %) | 5/5 (100 %) |
| npn_switch | 5/5 (100 %) | 4/5 (80 %) | 5/5 (100 %) |
| sys_analog_frontend | 5/5 (100 %) | 4/5 (80 %) | 5/5 (100 %) |
| sys_clocked_mcu | 5/5 (100 %) | 4/5 (80 %) | 5/5 (100 %) |
| sys_motor_ctrl | 5/5 (100 %) | 2/5 (40 %) | 3/5 (60 %) |
| sys_sensor_node | 4/4 (100 %) | 1/4 (25 %) | 4/4 (100 %) |

**By number of injected faults**

| group | haiku | sonnet | opus |
|---|---|---|---|
| 3 | 13/13 (100 %) | 10/13 (77 %) | 13/13 (100 %) |
| 4 | 13/13 (100 %) | 4/13 (31 %) | 11/13 (85 %) |
| 5 | 9/9 (100 %) | 5/9 (56 %) | 9/9 (100 %) |
| 6 | 9/9 (100 %) | 6/9 (67 %) | 9/9 (100 %) |

**By hint level**

| group | haiku | sonnet | opus |
|---|---|---|---|
| symptom | 22/22 (100 %) | 12/22 (55 %) | 21/22 (95 %) |
| vague | 22/22 (100 %) | 13/22 (59 %) | 21/22 (95 %) |

**By tool mode**

| group | haiku | sonnet | opus |
|---|---|---|---|
| full | 28/28 (100 %) | 15/28 (54 %) | 26/28 (93 %) |
| no_autoroute | 16/16 (100 %) | 10/16 (62 %) | 16/16 (100 %) |

**By latent fault type present in the task** (a task counts once per latent type it contains)

| latent fault type | haiku | sonnet | opus |
|---|---|---|---|
| bias_wrong_rail | 9/9 (100 %) | 6/9 (67 %) | 9/9 (100 %) |
| capacitor_underrated | 17/17 (100 %) | 9/17 (53 %) | 17/17 (100 %) |
| connector_pin_swap | 17/17 (100 %) | 11/17 (65 %) | 15/17 (88 %) |
| decap_swapped | 5/5 (100 %) | 3/5 (60 %) | 4/5 (80 %) |
| decap_wrong_rail | 10/10 (100 %) | 2/10 (20 %) | 10/10 (100 %) |
| flyback_misplaced | 8/8 (100 %) | 6/8 (75 %) | 7/8 (88 %) |
| led_underrated | 5/5 (100 %) | 3/5 (60 %) | 5/5 (100 %) |
| mcu_pin_swap | 7/7 (100 %) | 4/7 (57 %) | 7/7 (100 %) |
| protection_bypassed | 2/2 (100 %) | 2/2 (100 %) | 2/2 (100 %) |
| pullup_wrong_rail | 2/2 (100 %) | 1/2 (50 %) | 2/2 (100 %) |
| resistor_underrated | 7/7 (100 %) | 3/7 (43 %) | 7/7 (100 %) |
| weak_base_drive | 6/6 (100 %) | 4/6 (67 %) | 6/6 (100 %) |

### v2-hard_layout

**By family**

| group | haiku | sonnet | opus |
|---|---|---|---|
| sys_clocked_mcu | 14/16 (88 %) | 2/17 (12 %) | 15/17 (88 %) |
| sys_motor_ctrl | 14/22 (64 %) | 5/19 (26 %) | 23/23 (100 %) |

**By number of injected faults**

| group | haiku | sonnet | opus |
|---|---|---|---|
| 3 | 10/11 (91 %) | 2/10 (20 %) | 12/12 (100 %) |
| 4 | 9/13 (69 %) | 3/11 (27 %) | 12/13 (92 %) |
| 5 | 7/10 (70 %) | 1/10 (10 %) | 10/10 (100 %) |
| 6 | 2/4 (50 %) | 1/5 (20 %) | 4/5 (80 %) |

**By hint level**

| group | haiku | sonnet | opus |
|---|---|---|---|
| symptom | 16/20 (80 %) | 4/20 (20 %) | 20/21 (95 %) |
| vague | 12/18 (67 %) | 3/16 (19 %) | 18/19 (95 %) |

**By tool mode**

| group | haiku | sonnet | opus |
|---|---|---|---|
| full | 1/2 (50 %) | 0/2 (0 %) | 2/2 (100 %) |
| no_autoroute | 27/36 (75 %) | 7/34 (21 %) | 36/38 (95 %) |

**By latent fault type present in the task** (a task counts once per latent type it contains)

| latent fault type | haiku | sonnet | opus |
|---|---|---|---|
| analog_near_switch | 4/6 (67 %) | 1/4 (25 %) | 6/6 (100 %) |
| bias_wrong_rail | 7/7 (100 %) | 2/6 (33 %) | 7/7 (100 %) |
| capacitor_underrated | 5/6 (83 %) | 1/6 (17 %) | 6/6 (100 %) |
| connector_pin_swap | 6/8 (75 %) | 0/8 (0 %) | 9/9 (100 %) |
| crystal_far | 4/5 (80 %) | 1/6 (17 %) | 5/6 (83 %) |
| crystal_via | 8/9 (89 %) | 1/9 (11 %) | 9/9 (100 %) |
| decap_long_path | 9/12 (75 %) | 1/13 (8 %) | 11/13 (85 %) |
| kelvin_sense_tap | 9/13 (69 %) | 3/12 (25 %) | 13/13 (100 %) |
| mcu_pin_swap | 3/9 (33 %) | 3/8 (38 %) | 9/9 (100 %) |
| protection_bypassed | 4/5 (80 %) | 1/6 (17 %) | 4/6 (67 %) |
| pullup_wrong_rail | 3/3 (100 %) | 0/2 (0 %) | 3/3 (100 %) |
| switch_loop_spread | 3/7 (43 %) | 2/7 (29 %) | 8/8 (100 %) |

## 3. Failure taxonomy (clean failed rollouts)

Which gates/checks fail, per model. `pcbtool check` runs consistency, DRC, ERC, the spec simulation, value bounds and layout locally; it never runs `rules` (datasheet design rules), `layout_rules` (board-geometry rules) or `topology` (comparison with the hidden golden), and in the hard tiers the decoupling-path part of `layout` is stated in TASK.md but not run by pcbtool. Buckets (first match wins): gate failure → any pcbtool-visible check failed → topology failed → only unrun rules failed.

### v1-normal (historical, v1 task set)

| check | haiku | sonnet | opus |
|---|---|---|---|
| failed rollouts | 1/100 | 0/100 | 0/50 |
| `layout` failed | 1 | 0 | 0 |
| `topology` failed | 1 | 0 | 0 |

**Diligence buckets** (failed rollouts per model)

| bucket | haiku | sonnet | opus |
|---|---|---|---|
| submitted with a pcbtool-visible failure | 1 | 0 | 0 |

Failures invisible to `pcbtool check` (latent connectivity or unrun rules): haiku 0/1 (0 %).

### v2-hard

| check | haiku | sonnet | opus |
|---|---|---|---|
| failed rollouts | 0/44 | 19/44 | 2/44 |
| `layout` failed | 0 | 6 | 2 |
| `rules` failed | 0 | 14 | 0 |
| `topology` failed | 0 | 9 | 0 |

**Diligence buckets** (failed rollouts per model)

| bucket | haiku | sonnet | opus |
|---|---|---|---|
| latent connectivity left (topology only + unrun rules) | 0 | 9 | 0 |
| only rules pcbtool does not run | 0 | 10 | 2 |

Failures invisible to `pcbtool check` (latent connectivity or unrun rules): sonnet 19/19 (100 %), opus 2/2 (100 %).

### v2-hard_layout

| check | haiku | sonnet | opus |
|---|---|---|---|
| failed rollouts | 10/38 | 29/36 | 2/40 |
| `drc` failed | 6 | 0 | 0 |
| `erc` failed | 1 | 0 | 0 |
| `layout` failed | 4 | 14 | 2 |
| `layout_rules` failed | 8 | 21 | 0 |
| `rules` failed | 1 | 1 | 0 |
| `spec` failed | 1 | 0 | 0 |
| `topology` failed | 2 | 2 | 0 |

**Diligence buckets** (failed rollouts per model)

| bucket | haiku | sonnet | opus |
|---|---|---|---|
| latent connectivity left (topology only + unrun rules) | 1 | 2 | 0 |
| only rules pcbtool does not run | 2 | 27 | 2 |
| submitted with a pcbtool-visible failure | 7 | 0 | 0 |

Failures invisible to `pcbtool check` (latent connectivity or unrun rules): haiku 3/10 (30 %), sonnet 29/29 (100 %), opus 2/2 (100 %).

## 4. Contamination exclusions

A rollout is excluded when the transcript audit (`reports/calibration/grade.py:audit`) finds an action touching the repository, hidden task files or other workdirs. Reason = text before the first ':' of the first recorded violation.

| tier | job | model | task | reward (excluded) | reason |
|---|---|---|---|---|---|
| v2-hard_layout | 55 | sonnet | pcbr2-hard_layout-11f2f9c8 | 0.0 | repo path |
| v2-hard_layout | 56 | sonnet | pcbr2-hard_layout-bb5ffc1c | 0.0 | repo path |
| v2-hard_layout | 77 | sonnet | pcbr2-hard_layout-f7d8d9c0 | 1.0 | repo path |
| v2-hard_layout | 78 | sonnet | pcbr2-hard_layout-d813ab04 | 0.0 | repo path |
| v2-hard_layout | 117 | haiku | pcbr2-hard_layout-1f2c9491 | 0.0 | repo path |
| v2-hard_layout | 118 | haiku | pcbr2-hard_layout-00100f79 | 0.0 | repo path |

Audit coverage:

| tier | graded | audited | not yet audited | contaminated |
|---|---|---|---|---|
| v1-normal (historical, v1 task set) | 250 | 250 | 0 | 0 |
| v2-hard | 132 | 132 | 0 | 0 |
| v2-hard_layout | 120 | 120 | 0 | 6 |

## 5. Oracle and gate controls

Calibration samples (oracle = golden files restored into the agent's workdir and re-verified at grading time; manifest gates = recorded at generation time):

| tier | oracle 1.0 at grading (rollouts) | manifest golden 1.0 | manifest faulted 0.0 | manifest oracle repair 1.0 |
|---|---|---|---|---|
| v1-normal (historical, v1 task set) | not recorded | 50/50 | 50/50 | 50/50 |
| v2-hard | 132/132 | 44/44 | 44/44 | 44/44 |
| v2-hard_layout | 120/120 | 40/40 | 40/40 | 40/40 |

Full shipped set re-verified after the DRC-rules fix (`reports/v2/recheck_all_tasks_after_drc_fix.jsonl`):

| split | tasks | faulted = 0.0 | oracle = 1.0 |
|---|---|---|---|
| v2/hard | 362 | 362 | 362 |
| v2/hard_holdout | 90 | 90 | 90 |
| v2/hard_layout | 154 | 154 | 154 |
| v2/hard_layout_holdout | 39 | 39 | 39 |
| v2/normal | 655 | 655 | 655 |
| v2/normal_holdout | 164 | 164 | 164 |
| **all** | 1464 | 1464 | 1464 |

Orchestrator test run (`reports/v2/orchestrator_test_run.txt`): 1030 tests passed across 18 files, 0 file(s) with failures.

## 6. Served model ids

- v2-hard: `claude-haiku-5-5`, `claude-opus-5-5`, `claude-sonnet-5-5` (confirmed from transcripts, `reports/calibration/v2hard/FINDINGS.md`).
- v1-normal, v2-hard_layout: not recorded in committed files; rollouts carry only the alias (haiku / sonnet / opus).
- All runs: one attempt per task per model (v1: see §1), reasoning effort = medium, same agent harness, opaque per-job workdirs.

## 7. Calibration sample composition

| tier | distinct tasks | from holdout | families | latent faults per task | not in manifest |
|---|---|---|---|---|---|
| v1-normal (historical, v1 task set) | 50 | 0 | 10 | – | 0 |
| v2-hard | 44 | 0 | 9 | 2–3 | 0 |
| v2-hard_layout | 40 | 0 | 2 | 2–3 | 0 |

## 8. Task set (from `tasks/manifest.jsonl`)

| tier | tasks | train | holdout | families | fault types | fault instances | latent faults (share of instances) | layout-latent faults | tasks with ≥1 DRC/ERC-invisible fault |
|---|---|---|---|---|---|---|---|---|---|
| normal | 819 | 655 | 164 (20 %) | 10 | 19 | 1494 | 0 (0 %) | 0 | 674 (82 %) |
| hard | 452 | 362 | 90 (20 %) | 9 | 32 | 1949 | 1020 (52 %) | 0 | 452 (100 %) |
| hard_layout | 193 | 154 | 39 (20 %) | 2 | 31 | 830 | 458 (55 %) | 265 | 193 (100 %) |
| **all v2** | 1464 | 1171 | 293 |  | 38 | 4273 |  |  |  |

v1 (historical, git `b1a1255`): 818 tasks, 164 holdout, 10 families, 19 fault types.

**By family** (tasks)

| family | normal | hard | hard_layout |
|---|---|---|---|
| divider_adc | 83 | – | – |
| ldo_reg | 82 | 10 | – |
| led_driver | 82 | 12 | – |
| mcu_i2c | 82 | 10 | – |
| nmos_switch | 81 | 17 | – |
| npn_switch | 81 | 22 | – |
| opamp_inv | 82 | – | – |
| opamp_noninv | 82 | – | – |
| rc_lowpass | 82 | – | – |
| sys_analog_frontend | – | 89 | – |
| sys_clocked_mcu | – | 101 | 84 |
| sys_motor_ctrl | – | 96 | 109 |
| sys_sensor_node | – | 95 | – |
| xtal_osc | 82 | – | – |

**By faults per task** (tasks)

| faults per task | normal | hard | hard_layout |
|---|---|---|---|
| 1 | 345 | – | – |
| 2 | 273 | – | – |
| 3 | 201 | 111 | 46 |
| 4 | – | 161 | 74 |
| 5 | – | 108 | 42 |
| 6 | – | 72 | 31 |

**By hint level** (tasks)

| hint level | normal | hard | hard_layout |
|---|---|---|---|
| explicit | 258 | – | – |
| symptom | 311 | 225 | 97 |
| vague | 250 | 227 | 96 |

**By tool mode** (tasks)

| tool mode | normal | hard | hard_layout |
|---|---|---|---|
| full | – | 276 | 24 |
| full (no tools.json) | 819 | – | – |
| no_autoroute | – | 176 | 169 |

**Fault instances by type**

| fault type | category | normal | hard | hard_layout |
|---|---|---|---|---|
| `board_pad_swap` | board | 73 | 43 | 20 |
| `broken_trace` | board | 105 | 47 | 26 |
| `clearance_violation` | board | 84 | 30 | 16 |
| `decap_moved_far` | board | 83 | 5 | 9 |
| `footprint_swap` | board | 85 | 41 | 17 |
| `narrow_power_trace` | board | 84 | 33 | 20 |
| `short_between_nets` | board | 84 | 28 | 13 |
| `decap_misconnected` | connectivity | 58 | 11 | 17 |
| `floating_pin` | connectivity | 109 | 91 | 32 |
| `pin_to_wrong_net` | connectivity | 84 | 21 | 12 |
| `reversed_polarity` | connectivity | 60 | 33 | 24 |
| `swapped_ic_pins` | connectivity | 69 | 75 | 22 |
| `transistor_pinout` | connectivity | 50 | 52 | 14 |
| `analog_near_switch` | latent | – | – | 39 |
| `bias_wrong_rail` | latent | – | 144 | 21 |
| `capacitor_underrated` | latent | – | 163 | 22 |
| `connector_pin_swap` | latent | – | 126 | 45 |
| `crystal_far` | latent | – | – | 35 |
| `crystal_via` | latent | – | – | 38 |
| `decap_long_path` | latent | – | – | 67 |
| `decap_swapped` | latent | – | 63 | – |
| `decap_wrong_rail` | latent | – | 116 | – |
| `flyback_misplaced` | latent | – | 57 | – |
| `kelvin_sense_tap` | latent | – | – | 49 |
| `led_underrated` | latent | – | 16 | – |
| `mcu_pin_swap` | latent | – | 136 | 53 |
| `protection_bypassed` | latent | – | 84 | 36 |
| `pullup_wrong_rail` | latent | – | 37 | 16 |
| `resistor_underrated` | latent | – | 42 | – |
| `switch_loop_spread` | latent | – | – | 37 |
| `weak_base_drive` | latent | – | 36 | – |
| `bom_mismatch` | value | 119 | 60 | 13 |
| `interacting_value` | value | – | 28 | – |
| `magnitude_slip` | value | 98 | 53 | 17 |
| `wrong_feedback_resistor` | value | 57 | 68 | 32 |
| `wrong_filter_cap` | value | 86 | 64 | 19 |
| `wrong_led_resistor` | value | 50 | 87 | 31 |
| `wrong_pull_resistor` | value | 56 | 59 | 18 |

## 9. Red team (G5)

Scripted runs (`redteam/runs/*.txt`, output of `redteam/run_scripted.py`):

| run | tasks | attacks | applications | blocked | hacks | timeouts / attack errors |
|---|---|---|---|---|---|---|
| round 1, fixture (final) | 90 | 19 | 1000 | 1000 | 0 | 0 / 0 |
| round 2, shipped v1, run 1 (superseded) | 677 | 38 | 1200 | 1196 | 4 | 0 / 0 |
| round 2, shipped v1, run 2 (superseded) | 678 | 38 | 1200 | 1199 | 1 | 0 / 0 |
| round 2, shipped v1 (final) | 677 | 38 | 1200 | 1200 | 0 | 0 / 0 |
| round 3, v2 normal/hard/hard_layout | 666 | 51 | 1300 | 1236 | 0 | 10 / 54 |
| round 3, v2 retry of errored/timed-out | no summary yet (run in progress or empty) |  |  |  |  |  |

Non-superseded scripted applications: **3500** (3436 completed and blocked, 64 timed out or hit an attack-script error and so prove nothing either way), hacks: **0**. Superseded runs found hacks that were fixed before the final run of the same round.

Agent / hand attempts:

| source | attempts | kinds | fake attempts reaching 1.0 (hacks) |
|---|---|---|---|
| round 1: scripted low-effort policies via the harness (exploits.md) | 96 | – | 0 |
| round 2: hand attempts (`redteam/runs/hand_attempts.txt`) | 28 | fake 15, minimal-legit 5, probe 8 | 0 |
| round 3: hand attempts on v2 hard/hard_layout (exploits.md RT75) | 24 | ? | ? |

Agent/hand attempts total: **148**. Reward-1.0 episodes from `minimal-legit` attempts or round-1 policies are genuine (cheap but correct) repairs, not hacks.

Exploit ledger (`redteam/exploits.md` summary tables; BLOCKED rows omitted):

| id | first verdict | latest verdict |
|---|---|---|
| RT01 | EXPERT-DISAGREES | FIXED (v2) |
| RT30 | EXPLOIT (latent) | FIXED (v2) |
| RT31 | EXPERT-DISAGREES | FIXED (v2) |
| RT32 | EXPERT-DISAGREES | FIXED (v2) |
| RT33 | FALSE-NEGATIVE | FIXED (v2) |
| RT34 | LEAK | LEAK |
| RT35 | LEAK | LEAK |
| RT36 | LEAK | LEAK |
| RT37 | LEAK (risk, not run) | MITIGATED (v2) |
| RT59 | EXPERT-DISAGREES | FIXED (v2) |
| RT70 | LEAK | LEAK |
| RT76 | ROBUSTNESS (fails closed) | ROBUSTNESS (fails closed) |

Findings ever rated EXPLOIT or EXPERT-DISAGREES (verifier gave 1.0 to something an expert rejects, or an exploitable gap): 5; latest verdict FIXED: 5; still open: none. Open LEAK items are listed above.

## Inputs

sha256 prefixes of the exact bytes read:

| input | sha256[:16] |
|---|---|
| `git b1a1255:tasks/manifest.jsonl` | 4468a8a1ff8b8330 |
| `redteam/exploits.md` | fcfd118c09269ea4 |
| `redteam/runs/fixture_n1000_seed0.txt` | fa0f7ba4d28abc55 |
| `redteam/runs/hand_attempts.txt` | fd611aec47c6f392 |
| `redteam/runs/shipped_n1200_seed0.txt` | 5dd9c4c4585d5d41 |
| `redteam/runs/shipped_run1_superseded.txt` | 4ba0bb24c3e5f0a5 |
| `redteam/runs/shipped_run2_superseded.txt` | b3caf42bab05b121 |
| `redteam/runs/v2_n1300_seed0.txt` | f798bf59dcf3424a |
| `redteam/runs/v2_n1300_seed0_retry.txt` | cc0e378c12603edd |
| `reports/calibration/rollouts.jsonl` | 98aaed3ece7aa91f |
| `reports/calibration/v2hard/FINDINGS.md` | 61da848b5a34e9e4 |
| `reports/calibration/v2hard/rollouts.jsonl` | 07aad45a9fb9ba7f |
| `reports/calibration/v2hard_layout/rollouts.jsonl` | 4e0a0d3c6bad5bf9 |
| `reports/v2/orchestrator_test_run.txt` | dd43909acce0dba5 |
| `reports/v2/recheck_all_tasks_after_drc_fix.jsonl` | 4b91d133eb3588b4 |
| `tasks/manifest.jsonl` | 0b5a75b610ddb8d4 |
| `thresholds.yaml` | e35d74557dca9a1c |
