# Expert QA packets (G9, v2 tasks)

100 review packets for TRAIN tasks only (the `*_holdout` splits are never read or sampled), built by `python3 -m pcbenv.qa build --n 100 --out qa/packets --seed 7 --mix normal=60,hard=25,hard_layout=15`. Tally with `python3 -m pcbenv.qa tally qa/packets`.

Tiers: normal 60 (of 655 train tasks), hard 25 (of 362 train tasks), hard_layout 15 (of 154 train tasks).

## Instructions for reviewers

You are a qualified electrical engineer checking that this benchmark is fair and graded correctly. You do **not** need KiCad: each packet's `README.md` has everything (TASK.md verbatim, datasheets, renders, the hidden faults, the reference fix as a diff, the verifier's verdicts and, for the hard tiers, the design-rule and layout-rule numbers before and after).

- **Time budget:** about 5 minutes per normal packet, 10 per hard / hard_layout packet. If a packet needs more than twice that, mark `unsure` and say why in `notes`; that is itself a finding.
- **Order:** read section 1 (agent's view) first and form your own opinion of what is wrong. Then read section 2 and compare.
- **Tiers:** `normal` = visible faults (pcbtool finds most of them). `hard` adds the `rules` check (datasheet design rules stated in TASK.md "Design rules" and `parts/*.md`, NOT run by pcbtool) and **latent** faults that leave `pcbtool check` clean and can only be found by reading the public text (section 2.7 quotes the exact sentence the generator relies on). `hard_layout` adds the `layout_rules` check (Kelvin sense, switching-loop area, crystal path / vias, analog-switching separation; decoupling copper path under `layout`), with metrics in 2.9 and the loop / paths drawn on the board renders. `no_autoroute` tasks disable `pcbtool route` / `sync` (hand-edited tracks).
- **What to look for:**
  - The task demands something the public material does not state (hidden requirement, ambiguous connection, a value with no assertion and no published range, a latent fault whose quoted evidence does not really imply the requirement).
  - The injected fault is not actually a fault (e.g. a value change that is still within a sensible engineering tolerance; a footprint that is equally valid; a decap distance or loop area that is fine in practice).
  - A design / layout rule an expert would dispute (limit too tight or too loose, wrong definition, a rule that real datasheets do not impose).
  - The golden/reference design is itself wrong or poor practice.
  - The verifier fails the faulted files for the wrong reason, or would reject a valid alternative repair (different E-series value, re-routing instead of restoring, keeping an allowed footprint, a different but compliant layout).
  - The verdict on the golden is anything but reward 1.
- **Form:** fill `review.yaml` (first reviewer). The second reviewer copies `qa/review_template.yaml` to `review-<initials>.yaml` in the same packet dir, **without reading the first form**. v2 adds `rule_stated_clearly: yes|no` and `layout_rule_reasonable: yes|no|n/a` (`n/a` outside hard_layout).
- Unfilled fields count as pending; you can stop and resume at any time.

## Acceptance rule

- Two independent EEs review every packet.
- Per reviewer, at least 95% of completed packets have `verifier_verdict_agrees: yes`, `reference_fix_correct: yes` and `task_fair: yes` (computed by `tally`).
- Every disputed packet (any `no`/`unsure` incl. `rule_stated_clearly: no` / `layout_rule_reasonable: no`, any rejected alternative fix, or the two reviewers disagreeing) must be resolved before sign-off: the orchestrator decides whether the **task** (regenerate / drop it, fix the TASK.md writer or fault injector) or the **verifier** (assertion window, value bound, rule limit, alt_partitions, check logic) is wrong, fixes it in the owning module, regenerates the affected tasks and packets, and the disputing reviewer re-reviews them. No task ships with an open dispute.
- The 95% threshold is not yet in `thresholds.yaml` (orchestrator-owned); proposed key `qa.ee_verifier_agreement_min: 0.95`.
- Human sign-off is founder-owned. [`self_review_v2.md`](self_review_v2.md) is a pre-screen of 15 v2 packets by the QA agent (not a substitute); read its findings before starting, they list the cases most likely to be disputed. ([`self_review.md`](self_review.md) is the v1 pre-screen, kept for history; its packet numbers refer to the deleted v1 packets.)

## Sample composition

| family | normal | hard | hard_layout | total |
|---|---|---|---|---|
| `divider_adc` | 6 | 0 | 0 | 6 |
| `ldo_reg` | 6 | 1 | 0 | 7 |
| `led_driver` | 5 | 2 | 0 | 7 |
| `mcu_i2c` | 5 | 2 | 0 | 7 |
| `nmos_switch` | 5 | 3 | 0 | 8 |
| `npn_switch` | 6 | 3 | 0 | 9 |
| `opamp_inv` | 7 | 0 | 0 | 7 |
| `opamp_noninv` | 7 | 0 | 0 | 7 |
| `rc_lowpass` | 6 | 0 | 0 | 6 |
| `sys_analog_frontend` | 0 | 4 | 0 | 4 |
| `sys_clocked_mcu` | 0 | 2 | 6 | 8 |
| `sys_motor_ctrl` | 0 | 3 | 9 | 12 |
| `sys_sensor_node` | 0 | 5 | 0 | 5 |
| `xtal_osc` | 7 | 0 | 0 | 7 |

| hint level | normal | hard | hard_layout | total |
|---|---|---|---|---|
| `explicit` | 21 | 0 | 0 | 21 |
| `symptom` | 15 | 10 | 5 | 30 |
| `vague` | 24 | 15 | 10 | 49 |

| tool mode | normal | hard | hard_layout | total |
|---|---|---|---|---|
| `full` | 60 | 10 | 2 | 72 |
| `no_autoroute` | 0 | 15 | 13 | 28 |

| faults per task | normal | hard | hard_layout | total |
|---|---|---|---|---|
| `1` | 10 | 0 | 0 | 10 |
| `2` | 13 | 0 | 0 | 13 |
| `3` | 37 | 4 | 2 | 43 |
| `4` | 0 | 4 | 3 | 7 |
| `5` | 0 | 8 | 5 | 13 |
| `6` | 0 | 9 | 5 | 14 |

| fault type (packets containing it) | normal | hard | hard_layout | total |
|---|---|---|---|---|
| `analog_near_switch` | 0 | 0 | 3 | 3 |
| `bias_wrong_rail` | 0 | 10 | 4 | 14 |
| `board_pad_swap` | 5 | 2 | 2 | 9 |
| `bom_mismatch` | 26 | 12 | 4 | 42 |
| `broken_trace` | 4 | 2 | 1 | 7 |
| `capacitor_underrated` | 0 | 6 | 0 | 6 |
| `clearance_violation` | 6 | 0 | 1 | 7 |
| `connector_pin_swap` | 0 | 9 | 5 | 14 |
| `crystal_far` | 0 | 0 | 3 | 3 |
| `crystal_via` | 0 | 0 | 2 | 2 |
| `decap_long_path` | 0 | 0 | 9 | 9 |
| `decap_misconnected` | 6 | 0 | 1 | 7 |
| `decap_moved_far` | 10 | 0 | 1 | 11 |
| `decap_swapped` | 0 | 7 | 0 | 7 |
| `decap_wrong_rail` | 0 | 3 | 0 | 3 |
| `floating_pin` | 6 | 5 | 2 | 13 |
| `flyback_misplaced` | 0 | 3 | 0 | 3 |
| `footprint_swap` | 15 | 4 | 3 | 22 |
| `interacting_value` | 0 | 5 | 0 | 5 |
| `kelvin_sense_tap` | 0 | 0 | 2 | 2 |
| `led_underrated` | 0 | 2 | 0 | 2 |
| `magnitude_slip` | 4 | 4 | 1 | 9 |
| `mcu_pin_swap` | 0 | 7 | 4 | 11 |
| `narrow_power_trace` | 13 | 2 | 3 | 18 |
| `pin_to_wrong_net` | 6 | 3 | 0 | 9 |
| `protection_bypassed` | 0 | 1 | 1 | 2 |
| `pullup_wrong_rail` | 0 | 3 | 1 | 4 |
| `resistor_underrated` | 0 | 4 | 0 | 4 |
| `reversed_polarity` | 5 | 2 | 1 | 8 |
| `short_between_nets` | 7 | 2 | 0 | 9 |
| `swapped_ic_pins` | 3 | 7 | 1 | 11 |
| `switch_loop_spread` | 0 | 0 | 6 | 6 |
| `transistor_pinout` | 4 | 3 | 2 | 9 |
| `weak_base_drive` | 0 | 4 | 0 | 4 |
| `wrong_feedback_resistor` | 7 | 1 | 4 | 12 |
| `wrong_filter_cap` | 10 | 3 | 0 | 13 |
| `wrong_led_resistor` | 6 | 3 | 4 | 13 |
| `wrong_pull_resistor` | 4 | 3 | 2 | 9 |

Latent fault types are the ones also listed in the packets' `latent` column; every latent and layout-latent type of the train splits is covered.

## Packets

| # | tier | task | family | faults (latent in bold) | hint | tools | why sampled | packet |
|---|---|---|---|---|---|---|---|---|
| 001 | normal | `pcbr2-normal-45a258bd` | divider_adc | wrong_feedback_resistor, narrow_power_trace, short_between_nets | vague | full | 3 faults; vague hint; disputable type narrow_power_trace; value near bounds: R2=60.4k inside [34000, 220000] | [README](packets/001-pcbr2-normal-45a258bd/README.md) |
| 002 | normal | `pcbr2-normal-671027f8` | divider_adc | bom_mismatch | vague | full | vague hint; disputable type bom_mismatch; value near bounds: R1=80.6k inside [33000, 390000] | [README](packets/002-pcbr2-normal-671027f8/README.md) |
| 003 | normal | `pcbr2-normal-9900dea2` | divider_adc | pin_to_wrong_net, wrong_feedback_resistor, footprint_swap | symptom | full | 3 faults; connectivity fault; disputable type footprint_swap; value near bounds: R2=34k inside [15000, 130000] | [README](packets/003-pcbr2-normal-9900dea2/README.md) |
| 004 | normal | `pcbr2-normal-c7b76f69` | divider_adc | wrong_feedback_resistor, bom_mismatch, footprint_swap | explicit | full | 3 faults; disputable type bom_mismatch; disputable type footprint_swap; value near bounds: R1=294k inside [55000, 660000] | [README](packets/004-pcbr2-normal-c7b76f69/README.md) |
| 005 | normal | `pcbr2-normal-cdac4f80` | divider_adc | wrong_filter_cap, bom_mismatch, board_pad_swap | explicit | full | 3 faults; disputable type bom_mismatch; value near bounds: C1=15n inside [7.4e-09, 6.9e-08] | [README](packets/005-pcbr2-normal-cdac4f80/README.md) |
| 006 | normal | `pcbr2-normal-ce7988c4` | divider_adc | bom_mismatch, footprint_swap | symptom | full | disputable type bom_mismatch; disputable type footprint_swap; value near bounds: C1=82n inside [1.4e-08, 1.2e-07] | [README](packets/006-pcbr2-normal-ce7988c4/README.md) |
| 007 | normal | `pcbr2-normal-495ac124` | ldo_reg | bom_mismatch, narrow_power_trace, clearance_violation | symptom | full | 3 faults; disputable type bom_mismatch; disputable type narrow_power_trace; value near bounds: C1=4.7u inside [1e-06, 2.2e-05] | [README](packets/007-pcbr2-normal-495ac124/README.md) |
| 008 | normal | `pcbr2-normal-49bb6d29` | ldo_reg | decap_misconnected, magnitude_slip, narrow_power_trace | explicit | full | 3 faults; connectivity fault; disputable type narrow_power_trace | [README](packets/008-pcbr2-normal-49bb6d29/README.md) |
| 009 | normal | `pcbr2-normal-59cf0417` | ldo_reg | reversed_polarity | vague | full | vague hint; connectivity fault | [README](packets/009-pcbr2-normal-59cf0417/README.md) |
| 010 | normal | `pcbr2-normal-845aa676` | ldo_reg | floating_pin, bom_mismatch | explicit | full | connectivity fault; disputable type bom_mismatch; value near bounds: C2=10u inside [1e-06, 2.2e-05] | [README](packets/010-pcbr2-normal-845aa676/README.md) |
| 011 | normal | `pcbr2-normal-a5e8691c` | ldo_reg | wrong_led_resistor, bom_mismatch, decap_moved_far | vague | full | 3 faults; vague hint; disputable type bom_mismatch; disputable type decap_moved_far; value near bounds: R4=3.9k inside [40, 4400] | [README](packets/011-pcbr2-normal-a5e8691c/README.md) |
| 012 | normal | `pcbr2-normal-b48aada4` | ldo_reg | wrong_feedback_resistor, decap_moved_far, board_pad_swap | symptom | full | 3 faults; disputable type decap_moved_far; value near bounds: R1=121k inside [9100, 410000] | [README](packets/012-pcbr2-normal-b48aada4/README.md) |
| 013 | normal | `pcbr2-normal-3281afd1` | led_driver | bom_mismatch | vague | full | vague hint; disputable type bom_mismatch; value near bounds: R1=620 inside [86, 4500] | [README](packets/013-pcbr2-normal-3281afd1/README.md) |
| 014 | normal | `pcbr2-normal-64adf6f3` | led_driver | wrong_led_resistor, narrow_power_trace, footprint_swap | explicit | full | 3 faults; disputable type footprint_swap; disputable type narrow_power_trace; value near bounds: R2=91 near [100, 700] | [README](packets/014-pcbr2-normal-64adf6f3/README.md) |
| 015 | normal | `pcbr2-normal-759d594b` | led_driver | wrong_led_resistor, bom_mismatch, short_between_nets | vague | full | 3 faults; vague hint; disputable type bom_mismatch; value near bounds: R1=300 inside [35, 410]; R2=330 inside [53, 410] | [README](packets/015-pcbr2-normal-759d594b/README.md) |
| 016 | normal | `pcbr2-normal-8f4b181b` | led_driver | reversed_polarity, wrong_led_resistor, bom_mismatch | explicit | full | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: R2=100 inside [40, 700]; R1=150 inside [26, 270] | [README](packets/016-pcbr2-normal-8f4b181b/README.md) |
| 017 | normal | `pcbr2-normal-cea21e0e` | led_driver | reversed_polarity, bom_mismatch | symptom | full | connectivity fault; disputable type bom_mismatch; value near bounds: R2=470 inside [98, 1400] | [README](packets/017-pcbr2-normal-cea21e0e/README.md) |
| 018 | normal | `pcbr2-normal-0d1f2443` | mcu_i2c | bom_mismatch, decap_moved_far, short_between_nets | explicit | full | 3 faults; disputable type bom_mismatch; disputable type decap_moved_far; value near bounds: R1=2k near [2200, 100000] | [README](packets/018-pcbr2-normal-0d1f2443/README.md) |
| 019 | normal | `pcbr2-normal-2706c683` | mcu_i2c | footprint_swap | vague | full | vague hint; disputable type footprint_swap | [README](packets/019-pcbr2-normal-2706c683/README.md) |
| 020 | normal | `pcbr2-normal-7748131b` | mcu_i2c | floating_pin, narrow_power_trace, broken_trace | vague | full | 3 faults; vague hint; connectivity fault; disputable type narrow_power_trace | [README](packets/020-pcbr2-normal-7748131b/README.md) |
| 021 | normal | `pcbr2-normal-84b323d0` | mcu_i2c | pin_to_wrong_net, bom_mismatch | vague | full | vague hint; connectivity fault; disputable type bom_mismatch; value near bounds: R2=30k inside [960, 94000] | [README](packets/021-pcbr2-normal-84b323d0/README.md) |
| 022 | normal | `pcbr2-normal-ed68599e` | mcu_i2c | bom_mismatch, decap_moved_far, clearance_violation | explicit | full | 3 faults; disputable type bom_mismatch; disputable type decap_moved_far; value near bounds: R1=5.6k inside [2200, 100000] | [README](packets/022-pcbr2-normal-ed68599e/README.md) |
| 023 | normal | `pcbr2-normal-42aa55e6` | nmos_switch | transistor_pinout, wrong_pull_resistor, board_pad_swap | explicit | full | 3 faults; connectivity fault; value near bounds: R2=330k near [4700, 220000] | [README](packets/023-pcbr2-normal-42aa55e6/README.md) |
| 024 | normal | `pcbr2-normal-952223f8` | nmos_switch | transistor_pinout, bom_mismatch, footprint_swap | explicit | full | 3 faults; connectivity fault; disputable type bom_mismatch; disputable type footprint_swap; value near bounds: R2=10k inside [4700, 220000] | [README](packets/024-pcbr2-normal-952223f8/README.md) |
| 025 | normal | `pcbr2-normal-d0764fbc` | nmos_switch | transistor_pinout, bom_mismatch, clearance_violation | symptom | full | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: C1=2.2u inside [1e-06, 2.2e-05] | [README](packets/025-pcbr2-normal-d0764fbc/README.md) |
| 026 | normal | `pcbr2-normal-d1ad54d4` | nmos_switch | narrow_power_trace | vague | full | vague hint; disputable type narrow_power_trace | [README](packets/026-pcbr2-normal-d1ad54d4/README.md) |
| 027 | normal | `pcbr2-normal-edeb2551` | nmos_switch | wrong_pull_resistor, short_between_nets, footprint_swap | vague | full | 3 faults; vague hint; disputable type footprint_swap; value near bounds: R2=3.9k near [4700, 220000] | [README](packets/027-pcbr2-normal-edeb2551/README.md) |
| 028 | normal | `pcbr2-normal-43f3fc2b` | npn_switch | decap_moved_far | vague | full | vague hint; disputable type decap_moved_far | [README](packets/028-pcbr2-normal-43f3fc2b/README.md) |
| 029 | normal | `pcbr2-normal-8572b831` | npn_switch | decap_misconnected, footprint_swap | explicit | full | connectivity fault; disputable type footprint_swap | [README](packets/029-pcbr2-normal-8572b831/README.md) |
| 030 | normal | `pcbr2-normal-99e128ea` | npn_switch | transistor_pinout, wrong_led_resistor, short_between_nets | symptom | full | 3 faults; connectivity fault; value near bounds: R3=62 inside [37, 470] | [README](packets/030-pcbr2-normal-99e128ea/README.md) |
| 031 | normal | `pcbr2-normal-cdcc9123` | npn_switch | reversed_polarity, narrow_power_trace | explicit | full | connectivity fault; disputable type narrow_power_trace | [README](packets/031-pcbr2-normal-cdcc9123/README.md) |
| 032 | normal | `pcbr2-normal-d4bc8603` | npn_switch | wrong_led_resistor | vague | full | vague hint; value near bounds: R3=470 inside [40, 560] | [README](packets/032-pcbr2-normal-d4bc8603/README.md) |
| 033 | normal | `pcbr2-normal-fc647be2` | npn_switch | floating_pin, bom_mismatch | explicit | full | connectivity fault; disputable type bom_mismatch; value near bounds: C1=220n inside [4.7e-08, 1e-05] | [README](packets/033-pcbr2-normal-fc647be2/README.md) |
| 034 | normal | `pcbr2-normal-07a6031b` | opamp_inv | pin_to_wrong_net, wrong_feedback_resistor, footprint_swap | vague | full | 3 faults; vague hint; connectivity fault; disputable type footprint_swap; value near bounds: R2=5.62k inside [2000, 24000] | [README](packets/034-pcbr2-normal-07a6031b/README.md) |
| 035 | normal | `pcbr2-normal-3b0d4e58` | opamp_inv | decap_misconnected | vague | full | vague hint; connectivity fault | [README](packets/035-pcbr2-normal-3b0d4e58/README.md) |
| 036 | normal | `pcbr2-normal-470b4a5a` | opamp_inv | wrong_filter_cap, bom_mismatch, decap_moved_far | symptom | full | 3 faults; disputable type bom_mismatch; disputable type decap_moved_far; value near bounds: R3=6.49k inside [4700, 470000] | [README](packets/036-pcbr2-normal-470b4a5a/README.md) |
| 037 | normal | `pcbr2-normal-ae8ddab1` | opamp_inv | wrong_pull_resistor, footprint_swap, clearance_violation | symptom | full | 3 faults; disputable type footprint_swap; value near bounds: R3=180k inside [4700, 470000] | [README](packets/037-pcbr2-normal-ae8ddab1/README.md) |
| 038 | normal | `pcbr2-normal-b7e2e161` | opamp_inv | swapped_ic_pins, wrong_feedback_resistor, decap_moved_far | explicit | full | 3 faults; connectivity fault; disputable type decap_moved_far; value near bounds: R2=162k inside [92000, 740000] | [README](packets/038-pcbr2-normal-b7e2e161/README.md) |
| 039 | normal | `pcbr2-normal-c2a8b888` | opamp_inv | wrong_pull_resistor, bom_mismatch, narrow_power_trace | explicit | full | 3 faults; disputable type bom_mismatch; disputable type narrow_power_trace; value near bounds: C3=1.5u inside [4.7e-07, 4.7e-05] | [README](packets/039-pcbr2-normal-c2a8b888/README.md) |
| 040 | normal | `pcbr2-normal-fba1e5cd` | opamp_inv | floating_pin, wrong_filter_cap, clearance_violation | vague | full | 3 faults; vague hint; connectivity fault; value near bounds: C2=220n near [2.7e-07, 3.1e-06] | [README](packets/040-pcbr2-normal-fba1e5cd/README.md) |
| 041 | normal | `pcbr2-normal-06e7d6b4` | opamp_noninv | floating_pin, magnitude_slip, decap_moved_far | vague | full | 3 faults; vague hint; connectivity fault; disputable type decap_moved_far | [README](packets/041-pcbr2-normal-06e7d6b4/README.md) |
| 042 | normal | `pcbr2-normal-1aed52ef` | opamp_noninv | swapped_ic_pins, wrong_filter_cap, footprint_swap | explicit | full | 3 faults; connectivity fault; disputable type footprint_swap; value near bounds: C2=390p inside [2.4e-10, 2.1e-09] | [README](packets/042-pcbr2-normal-1aed52ef/README.md) |
| 043 | normal | `pcbr2-normal-33197450` | opamp_noninv | wrong_feedback_resistor, board_pad_swap | vague | full | vague hint; value near bounds: R1=49.9k inside [6600, 79000] | [README](packets/043-pcbr2-normal-33197450/README.md) |
| 044 | normal | `pcbr2-normal-642e1742` | opamp_noninv | pin_to_wrong_net, bom_mismatch, short_between_nets | symptom | full | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: C1=1u inside [4.7e-08, 1e-05] | [README](packets/044-pcbr2-normal-642e1742/README.md) |
| 045 | normal | `pcbr2-normal-664a1054` | opamp_noninv | swapped_ic_pins, narrow_power_trace, short_between_nets | explicit | full | 3 faults; connectivity fault; disputable type narrow_power_trace | [README](packets/045-pcbr2-normal-664a1054/README.md) |
| 046 | normal | `pcbr2-normal-a3a8ba8e` | opamp_noninv | decap_moved_far, footprint_swap | vague | full | vague hint; disputable type decap_moved_far; disputable type footprint_swap | [README](packets/046-pcbr2-normal-a3a8ba8e/README.md) |
| 047 | normal | `pcbr2-normal-a4393966` | opamp_noninv | decap_misconnected, bom_mismatch | symptom | full | connectivity fault; disputable type bom_mismatch; value near bounds: R1=2.26k near [2700, 19000] | [README](packets/047-pcbr2-normal-a4393966/README.md) |
| 048 | normal | `pcbr2-normal-135e18bb` | rc_lowpass | bom_mismatch, narrow_power_trace | vague | full | vague hint; disputable type bom_mismatch; disputable type narrow_power_trace; value near bounds: C1=680n inside [9.4e-08, 9.8e-07] | [README](packets/048-pcbr2-normal-135e18bb/README.md) |
| 049 | normal | `pcbr2-normal-2f07e9d6` | rc_lowpass | wrong_filter_cap, narrow_power_trace | symptom | full | disputable type narrow_power_trace; value near bounds: C1=680n inside [1e-07, 1.2e-06] | [README](packets/049-pcbr2-normal-2f07e9d6/README.md) |
| 050 | normal | `pcbr2-normal-6f3f0b3a` | rc_lowpass | bom_mismatch, footprint_swap | explicit | full | disputable type bom_mismatch; disputable type footprint_swap; value near bounds: C1=39n inside [2.1e-08, 2.3e-07] | [README](packets/050-pcbr2-normal-6f3f0b3a/README.md) |
| 051 | normal | `pcbr2-normal-bbd982ed` | rc_lowpass | pin_to_wrong_net, wrong_filter_cap, broken_trace | explicit | full | 3 faults; connectivity fault; value near bounds: C1=33n inside [1.8e-08, 1.9e-07] | [README](packets/051-pcbr2-normal-bbd982ed/README.md) |
| 052 | normal | `pcbr2-normal-cd131412` | rc_lowpass | narrow_power_trace, footprint_swap, broken_trace | symptom | full | 3 faults; disputable type footprint_swap; disputable type narrow_power_trace | [README](packets/052-pcbr2-normal-cd131412/README.md) |
| 053 | normal | `pcbr2-normal-e17c488d` | rc_lowpass | magnitude_slip, wrong_filter_cap, clearance_violation | vague | full | 3 faults; vague hint; value near bounds: C1=390n near [2.3e-08, 3.2e-07] | [README](packets/053-pcbr2-normal-e17c488d/README.md) |
| 054 | normal | `pcbr2-normal-09cfd293` | xtal_osc | bom_mismatch, wrong_filter_cap, decap_moved_far | vague | full | 3 faults; vague hint; disputable type bom_mismatch; disputable type decap_moved_far; value near bounds: C1=15p inside [1e-11, 8.4e-11] | [README](packets/054-pcbr2-normal-09cfd293/README.md) |
| 055 | normal | `pcbr2-normal-1e52a308` | xtal_osc | pin_to_wrong_net, wrong_filter_cap, board_pad_swap | symptom | full | 3 faults; connectivity fault; value near bounds: C1=15p inside [6.6e-12, 6.7e-11] | [README](packets/055-pcbr2-normal-1e52a308/README.md) |
| 056 | normal | `pcbr2-normal-344a6f54` | xtal_osc | reversed_polarity | vague | full | vague hint; connectivity fault | [README](packets/056-pcbr2-normal-344a6f54/README.md) |
| 057 | normal | `pcbr2-normal-a221242b` | xtal_osc | narrow_power_trace | vague | full | vague hint; disputable type narrow_power_trace | [README](packets/057-pcbr2-normal-a221242b/README.md) |
| 058 | normal | `pcbr2-normal-ba117e3d` | xtal_osc | decap_misconnected, footprint_swap, broken_trace | symptom | full | 3 faults; connectivity fault; disputable type footprint_swap | [README](packets/058-pcbr2-normal-ba117e3d/README.md) |
| 059 | normal | `pcbr2-normal-c2cbda0c` | xtal_osc | decap_misconnected, bom_mismatch, wrong_filter_cap | explicit | full | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: C1=47p inside [6e-12, 7.5e-11] | [README](packets/059-pcbr2-normal-c2cbda0c/README.md) |
| 060 | normal | `pcbr2-normal-eaf5410f` | xtal_osc | floating_pin, bom_mismatch, magnitude_slip | explicit | full | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: C3=47n inside [4.7e-08, 1e-05] | [README](packets/060-pcbr2-normal-eaf5410f/README.md) |
| 061 | hard | `pcbr2-hard-7ab48cda` | ldo_reg | **capacitor_underrated**, **decap_wrong_rail**, swapped_ic_pins, bom_mismatch, board_pad_swap | vague | no_autoroute | 5 faults; vague hint; connectivity fault; disputable type bom_mismatch; 2 latent (capacitor_underrated, decap_wrong_rail); no_autoroute | [README](packets/061-pcbr2-hard-7ab48cda/README.md) |
| 062 | hard | `pcbr2-hard-016ec3b8` | led_driver | **resistor_underrated**, **led_underrated**, interacting_value, pin_to_wrong_net | vague | full | vague hint; connectivity fault; value near bounds: R4=970 inside [110, 1400]; 2 latent (led_underrated, resistor_underrated); interacting value fault | [README](packets/062-pcbr2-hard-016ec3b8/README.md) |
| 063 | hard | `pcbr2-hard-4e6a5282` | led_driver | **resistor_underrated**, **led_underrated**, interacting_value, reversed_polarity, footprint_swap | symptom | full | 5 faults; connectivity fault; disputable type footprint_swap; value near bounds: R3=230 inside [37, 420]; 2 latent (led_underrated, resistor_underrated); interacting value fault | [README](packets/063-pcbr2-hard-4e6a5282/README.md) |
| 064 | hard | `pcbr2-hard-9f5f47eb` | mcu_i2c | **connector_pin_swap**, **bias_wrong_rail**, swapped_ic_pins, magnitude_slip, bom_mismatch | symptom | full | 5 faults; connectivity fault; disputable type bias_wrong_rail; disputable type bom_mismatch; disputable type connector_pin_swap; value near bounds: R1=13k inside [2200, 100000]; 2 latent (bias_wrong_rail, connector_pin_swap) | [README](packets/064-pcbr2-hard-9f5f47eb/README.md) |
| 065 | hard | `pcbr2-hard-d2e822b9` | mcu_i2c | **mcu_pin_swap**, **bias_wrong_rail**, wrong_pull_resistor, bom_mismatch, magnitude_slip, broken_trace | symptom | full | 6 faults; disputable type bias_wrong_rail; disputable type bom_mismatch; disputable type mcu_pin_swap; value near bounds: R3=3.3k inside [600, 5700]; 2 latent (bias_wrong_rail, mcu_pin_swap) | [README](packets/065-pcbr2-hard-d2e822b9/README.md) |
| 066 | hard | `pcbr2-hard-86850653` | nmos_switch | **connector_pin_swap**, **capacitor_underrated**, pin_to_wrong_net, bom_mismatch | vague | no_autoroute | vague hint; connectivity fault; disputable type bom_mismatch; disputable type connector_pin_swap; value near bounds: R1=15 inside [4.7, 220]; 2 latent (capacitor_underrated, connector_pin_swap); no_autoroute | [README](packets/066-pcbr2-hard-86850653/README.md) |
| 067 | hard | `pcbr2-hard-a4ecf5ac` | nmos_switch | **capacitor_underrated**, **flyback_misplaced**, transistor_pinout, bom_mismatch | vague | no_autoroute | vague hint; connectivity fault; disputable type bom_mismatch; value near bounds: R1=82 inside [4.7, 220]; 2 latent (capacitor_underrated, flyback_misplaced); no_autoroute | [README](packets/067-pcbr2-hard-a4ecf5ac/README.md) |
| 068 | hard | `pcbr2-hard-c07e23bc` | nmos_switch | **capacitor_underrated**, **flyback_misplaced**, floating_pin, bom_mismatch, magnitude_slip, short_between_nets | symptom | no_autoroute | 6 faults; connectivity fault; disputable type bom_mismatch; value near bounds: R1=6.8 inside [4.7, 220]; 2 latent (capacitor_underrated, flyback_misplaced); no_autoroute | [README](packets/068-pcbr2-hard-c07e23bc/README.md) |
| 069 | hard | `pcbr2-hard-54a772f5` | npn_switch | **connector_pin_swap**, **weak_base_drive**, bom_mismatch | symptom | no_autoroute | disputable type bom_mismatch; disputable type connector_pin_swap; value near bounds: R1=1.6k near [2200, 100000]; 2 latent (connector_pin_swap, weak_base_drive); no_autoroute | [README](packets/069-pcbr2-hard-54a772f5/README.md) |
| 070 | hard | `pcbr2-hard-604ce286` | npn_switch | **weak_base_drive**, **connector_pin_swap**, pin_to_wrong_net, swapped_ic_pins, bom_mismatch, broken_trace | vague | no_autoroute | 6 faults; vague hint; connectivity fault; disputable type bom_mismatch; disputable type connector_pin_swap; value near bounds: C1=1u inside [4.7e-08, 1e-05]; 2 latent (connector_pin_swap, weak_base_drive); no_autoroute | [README](packets/070-pcbr2-hard-604ce286/README.md) |
| 071 | hard | `pcbr2-hard-bca22c92` | npn_switch | **connector_pin_swap**, **weak_base_drive**, wrong_pull_resistor | vague | full | vague hint; disputable type connector_pin_swap; value near bounds: R4=3.3k near [4700, 220000]; 2 latent (connector_pin_swap, weak_base_drive) | [README](packets/071-pcbr2-hard-bca22c92/README.md) |
| 072 | hard | `pcbr2-hard-3bd14dd1` | sys_analog_frontend | **decap_swapped**, **bias_wrong_rail**, floating_pin, wrong_led_resistor, footprint_swap | vague | full | 5 faults; vague hint; connectivity fault; disputable type bias_wrong_rail; disputable type decap_swapped; disputable type footprint_swap; value near bounds: R11=6.8k inside [110, 9700]; 2 latent (bias_wrong_rail, decap_swapped) | [README](packets/072-pcbr2-hard-3bd14dd1/README.md) |
| 073 | hard | `pcbr2-hard-46ad68b2` | sys_analog_frontend | **capacitor_underrated**, **bias_wrong_rail**, **decap_swapped**, wrong_filter_cap, short_between_nets | symptom | no_autoroute | 5 faults; disputable type bias_wrong_rail; disputable type decap_swapped; value near bounds: C5=10n near [1.3e-08, 1.3e-07]; 3 latent (bias_wrong_rail, capacitor_underrated, decap_swapped); no_autoroute | [README](packets/073-pcbr2-hard-46ad68b2/README.md) |
| 074 | hard | `pcbr2-hard-7de298fe` | sys_analog_frontend | **decap_swapped**, **bias_wrong_rail**, swapped_ic_pins, wrong_led_resistor, bom_mismatch, board_pad_swap | symptom | no_autoroute | 6 faults; connectivity fault; disputable type bias_wrong_rail; disputable type bom_mismatch; disputable type decap_swapped; value near bounds: R11=3.3k inside [100, 5600]; R9=2.49k inside [1000, 11000]; 2 latent (bias_wrong_rail, decap_swapped); no_autoroute | [README](packets/074-pcbr2-hard-7de298fe/README.md) |
| 075 | hard | `pcbr2-hard-b4a48a20` | sys_analog_frontend | **bias_wrong_rail**, **decap_wrong_rail**, swapped_ic_pins, bom_mismatch | vague | full | vague hint; connectivity fault; disputable type bias_wrong_rail; disputable type bom_mismatch; value near bounds: C5=220n inside [4.7e-08, 1e-05]; 2 latent (bias_wrong_rail, decap_wrong_rail) | [README](packets/075-pcbr2-hard-b4a48a20/README.md) |
| 076 | hard | `pcbr2-hard-0cf4a297` | sys_clocked_mcu | **decap_swapped**, **bias_wrong_rail**, **mcu_pin_swap**, wrong_pull_resistor, wrong_filter_cap, footprint_swap | vague | no_autoroute | 6 faults; vague hint; disputable type bias_wrong_rail; disputable type decap_swapped; disputable type footprint_swap; disputable type mcu_pin_swap; value near bounds: C6=3.9p near [4.6e-12, 5.2e-11]; 3 latent (bias_wrong_rail, decap_swapped, mcu_pin_swap); no_autoroute | [README](packets/076-pcbr2-hard-0cf4a297/README.md) |
| 077 | hard | `pcbr2-hard-38a325f7` | sys_clocked_mcu | **mcu_pin_swap**, **pullup_wrong_rail**, bom_mismatch | vague | no_autoroute | vague hint; disputable type bom_mismatch; disputable type mcu_pin_swap; disputable type pullup_wrong_rail; value near bounds: R6=330 inside [160, 2400]; 2 latent (mcu_pin_swap, pullup_wrong_rail); no_autoroute | [README](packets/077-pcbr2-hard-38a325f7/README.md) |
| 078 | hard | `pcbr2-hard-43548095` | sys_motor_ctrl | **connector_pin_swap**, **resistor_underrated**, **flyback_misplaced**, interacting_value, swapped_ic_pins | vague | full | 5 faults; vague hint; connectivity fault; disputable type connector_pin_swap; value near bounds: R6=73m inside [0.057, 0.68]; 3 latent (connector_pin_swap, flyback_misplaced, resistor_underrated); interacting value fault | [README](packets/078-pcbr2-hard-43548095/README.md) |
| 079 | hard | `pcbr2-hard-984daae2` | sys_motor_ctrl | **capacitor_underrated**, **pullup_wrong_rail**, **mcu_pin_swap**, floating_pin, narrow_power_trace, footprint_swap | symptom | no_autoroute | 6 faults; connectivity fault; disputable type footprint_swap; disputable type mcu_pin_swap; disputable type narrow_power_trace; disputable type pullup_wrong_rail; 3 latent (capacitor_underrated, mcu_pin_swap, pullup_wrong_rail); no_autoroute | [README](packets/079-pcbr2-hard-984daae2/README.md) |
| 080 | hard | `pcbr2-hard-b2c9bbd3` | sys_motor_ctrl | **mcu_pin_swap**, **decap_swapped**, reversed_polarity | vague | no_autoroute | vague hint; connectivity fault; disputable type decap_swapped; disputable type mcu_pin_swap; 2 latent (decap_swapped, mcu_pin_swap); no_autoroute | [README](packets/080-pcbr2-hard-b2c9bbd3/README.md) |
| 081 | hard | `pcbr2-hard-0d1beb96` | sys_sensor_node | **resistor_underrated**, **mcu_pin_swap**, **decap_swapped**, interacting_value, transistor_pinout | vague | no_autoroute | 5 faults; vague hint; connectivity fault; disputable type decap_swapped; disputable type mcu_pin_swap; value near bounds: R6=3.9k near [240, 2900]; 3 latent (decap_swapped, mcu_pin_swap, resistor_underrated); interacting value fault; no_autoroute | [README](packets/081-pcbr2-hard-0d1beb96/README.md) |
| 082 | hard | `pcbr2-hard-1faf490c` | sys_sensor_node | **pullup_wrong_rail**, **bias_wrong_rail**, **connector_pin_swap**, swapped_ic_pins, wrong_filter_cap, wrong_feedback_resistor | vague | no_autoroute | 6 faults; vague hint; connectivity fault; disputable type bias_wrong_rail; disputable type connector_pin_swap; disputable type pullup_wrong_rail; value near bounds: C6=68n inside [4.8e-08, 4.8e-07]; R1=69.8k inside [10000, 470000]; 3 latent (bias_wrong_rail, connector_pin_swap, pullup_wrong_rail); no_autoroute | [README](packets/082-pcbr2-hard-1faf490c/README.md) |
| 083 | hard | `pcbr2-hard-7a5e8342` | sys_sensor_node | **decap_wrong_rail**, **weak_base_drive**, **bias_wrong_rail**, interacting_value, transistor_pinout | symptom | full | 5 faults; connectivity fault; disputable type bias_wrong_rail; value near bounds: R6=6.6k near [390, 5200]; 3 latent (bias_wrong_rail, decap_wrong_rail, weak_base_drive); interacting value fault | [README](packets/083-pcbr2-hard-7a5e8342/README.md) |
| 084 | hard | `pcbr2-hard-ab03f02b` | sys_sensor_node | **decap_swapped**, **mcu_pin_swap**, **connector_pin_swap**, floating_pin, magnitude_slip, narrow_power_trace | symptom | full | 6 faults; connectivity fault; disputable type connector_pin_swap; disputable type decap_swapped; disputable type mcu_pin_swap; disputable type narrow_power_trace; 3 latent (connector_pin_swap, decap_swapped, mcu_pin_swap) | [README](packets/084-pcbr2-hard-ab03f02b/README.md) |
| 085 | hard | `pcbr2-hard-b6ab1dd6` | sys_sensor_node | **protection_bypassed**, **connector_pin_swap**, **bias_wrong_rail**, floating_pin, bom_mismatch, wrong_led_resistor | vague | no_autoroute | 6 faults; vague hint; connectivity fault; disputable type bias_wrong_rail; disputable type bom_mismatch; disputable type connector_pin_swap; value near bounds: R10=2.2k near [48, 1600]; 3 latent (bias_wrong_rail, connector_pin_swap, protection_bypassed); no_autoroute | [README](packets/085-pcbr2-hard-b6ab1dd6/README.md) |
| 086 | hard_layout | `pcbr2-hard_layout-01b22c23` | sys_clocked_mcu | **crystal_via**, **decap_long_path**, **bias_wrong_rail**, bom_mismatch, broken_trace | symptom | no_autoroute | 5 faults; disputable type bias_wrong_rail; disputable type bom_mismatch; disputable type decap_long_path; value near bounds: R3=43k inside [2200, 100000]; 3 latent (bias_wrong_rail, crystal_via, decap_long_path); no_autoroute | [README](packets/086-pcbr2-hard_layout-01b22c23/README.md) |
| 087 | hard_layout | `pcbr2-hard_layout-2108cf90` | sys_clocked_mcu | **crystal_far**, **decap_long_path**, **bias_wrong_rail**, decap_misconnected, wrong_led_resistor | vague | no_autoroute | 5 faults; vague hint; connectivity fault; disputable type bias_wrong_rail; disputable type crystal_far; disputable type decap_long_path; value near bounds: R6=12 inside [11, 120]; 3 latent (bias_wrong_rail, crystal_far, decap_long_path); no_autoroute | [README](packets/087-pcbr2-hard_layout-2108cf90/README.md) |
| 088 | hard_layout | `pcbr2-hard_layout-25b31985` | sys_clocked_mcu | **crystal_far**, **decap_long_path**, **protection_bypassed**, floating_pin, wrong_feedback_resistor, bom_mismatch | symptom | no_autoroute | 6 faults; connectivity fault; disputable type bom_mismatch; disputable type crystal_far; disputable type decap_long_path; value near bounds: R1=43.2k inside [10000, 470000]; R4=470 inside [310, 3300]; 3 latent (crystal_far, decap_long_path, protection_bypassed); no_autoroute | [README](packets/088-pcbr2-hard_layout-25b31985/README.md) |
| 089 | hard_layout | `pcbr2-hard_layout-36a2853a` | sys_clocked_mcu | **crystal_via**, **decap_long_path**, **connector_pin_swap**, wrong_feedback_resistor, magnitude_slip, narrow_power_trace | symptom | no_autoroute | 6 faults; disputable type connector_pin_swap; disputable type decap_long_path; disputable type narrow_power_trace; value near bounds: R2=33.2k inside [3300, 150000]; 3 latent (connector_pin_swap, crystal_via, decap_long_path); no_autoroute | [README](packets/089-pcbr2-hard_layout-36a2853a/README.md) |
| 090 | hard_layout | `pcbr2-hard_layout-9fd97b37` | sys_clocked_mcu | **decap_long_path**, **connector_pin_swap**, wrong_pull_resistor, footprint_swap | vague | no_autoroute | vague hint; disputable type connector_pin_swap; disputable type decap_long_path; disputable type footprint_swap; value near bounds: R5=390 near [470, 6400]; 2 latent (connector_pin_swap, decap_long_path); no_autoroute | [README](packets/090-pcbr2-hard_layout-9fd97b37/README.md) |
| 091 | hard_layout | `pcbr2-hard_layout-b42579b0` | sys_clocked_mcu | **crystal_far**, **connector_pin_swap**, bom_mismatch | vague | full | vague hint; disputable type bom_mismatch; disputable type connector_pin_swap; disputable type crystal_far; value near bounds: R3=15k inside [2200, 100000]; 2 latent (connector_pin_swap, crystal_far) | [README](packets/091-pcbr2-hard_layout-b42579b0/README.md) |
| 092 | hard_layout | `pcbr2-hard_layout-11f2f9c8` | sys_motor_ctrl | **analog_near_switch**, **pullup_wrong_rail**, reversed_polarity, wrong_led_resistor | vague | no_autoroute | vague hint; connectivity fault; disputable type analog_near_switch; disputable type pullup_wrong_rail; value near bounds: R11=470 inside [110, 3800]; 2 latent (analog_near_switch, pullup_wrong_rail); no_autoroute | [README](packets/092-pcbr2-hard_layout-11f2f9c8/README.md) |
| 093 | hard_layout | `pcbr2-hard_layout-144e527f` | sys_motor_ctrl | **switch_loop_spread**, **decap_long_path**, **mcu_pin_swap**, floating_pin, transistor_pinout, footprint_swap | vague | no_autoroute | 6 faults; vague hint; connectivity fault; disputable type decap_long_path; disputable type footprint_swap; disputable type mcu_pin_swap; disputable type switch_loop_spread; 3 latent (decap_long_path, mcu_pin_swap, switch_loop_spread); no_autoroute | [README](packets/093-pcbr2-hard_layout-144e527f/README.md) |
| 094 | hard_layout | `pcbr2-hard_layout-25a5d904` | sys_motor_ctrl | **switch_loop_spread**, **analog_near_switch**, **mcu_pin_swap**, transistor_pinout, wrong_led_resistor | symptom | no_autoroute | 5 faults; connectivity fault; disputable type analog_near_switch; disputable type mcu_pin_swap; disputable type switch_loop_spread; value near bounds: R11=1.3k inside [130, 1500]; 3 latent (analog_near_switch, mcu_pin_swap, switch_loop_spread); no_autoroute | [README](packets/094-pcbr2-hard_layout-25a5d904/README.md) |
| 095 | hard_layout | `pcbr2-hard_layout-5dd2d0dd` | sys_motor_ctrl | **kelvin_sense_tap**, **switch_loop_spread**, **mcu_pin_swap**, narrow_power_trace, board_pad_swap, footprint_swap | symptom | no_autoroute | 6 faults; disputable type footprint_swap; disputable type mcu_pin_swap; disputable type narrow_power_trace; disputable type switch_loop_spread; 3 latent (kelvin_sense_tap, mcu_pin_swap, switch_loop_spread); no_autoroute | [README](packets/095-pcbr2-hard_layout-5dd2d0dd/README.md) |
| 096 | hard_layout | `pcbr2-hard_layout-6e574dd4` | sys_motor_ctrl | **switch_loop_spread**, **mcu_pin_swap**, board_pad_swap | vague | full | vague hint; disputable type mcu_pin_swap; disputable type switch_loop_spread; 2 latent (mcu_pin_swap, switch_loop_spread) | [README](packets/096-pcbr2-hard_layout-6e574dd4/README.md) |
| 097 | hard_layout | `pcbr2-hard_layout-7a6f0d18` | sys_motor_ctrl | **decap_long_path**, **switch_loop_spread**, **connector_pin_swap**, wrong_pull_resistor, bom_mismatch | vague | no_autoroute | 5 faults; vague hint; disputable type bom_mismatch; disputable type connector_pin_swap; disputable type decap_long_path; disputable type switch_loop_spread; value near bounds: R9=1.5k inside [1500, 55000]; 3 latent (connector_pin_swap, decap_long_path, switch_loop_spread); no_autoroute | [README](packets/097-pcbr2-hard_layout-7a6f0d18/README.md) |
| 098 | hard_layout | `pcbr2-hard_layout-7beaa6f4` | sys_motor_ctrl | **kelvin_sense_tap**, **switch_loop_spread**, **bias_wrong_rail**, swapped_ic_pins, wrong_led_resistor, clearance_violation | vague | no_autoroute | 6 faults; vague hint; connectivity fault; disputable type bias_wrong_rail; disputable type switch_loop_spread; value near bounds: R11=510 inside [110, 5000]; 3 latent (bias_wrong_rail, kelvin_sense_tap, switch_loop_spread); no_autoroute | [README](packets/098-pcbr2-hard_layout-7beaa6f4/README.md) |
| 099 | hard_layout | `pcbr2-hard_layout-91edaf0c` | sys_motor_ctrl | **decap_long_path**, **connector_pin_swap**, wrong_feedback_resistor, decap_moved_far | vague | no_autoroute | vague hint; disputable type connector_pin_swap; disputable type decap_long_path; disputable type decap_moved_far; value near bounds: R1=22.6k inside [10000, 470000]; 2 latent (connector_pin_swap, decap_long_path); no_autoroute | [README](packets/099-pcbr2-hard_layout-91edaf0c/README.md) |
| 100 | hard_layout | `pcbr2-hard_layout-9dc50c55` | sys_motor_ctrl | **analog_near_switch**, **decap_long_path**, **bias_wrong_rail**, wrong_feedback_resistor, narrow_power_trace | vague | no_autoroute | 5 faults; vague hint; disputable type analog_near_switch; disputable type bias_wrong_rail; disputable type decap_long_path; disputable type narrow_power_trace; value near bounds: R1=232k inside [10000, 470000]; 3 latent (analog_near_switch, bias_wrong_rail, decap_long_path); no_autoroute | [README](packets/100-pcbr2-hard_layout-9dc50c55/README.md) |
