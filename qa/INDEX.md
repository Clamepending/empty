# Expert QA packets (G9)

100 review packets for TRAIN tasks only (holdout is never sampled), built by `python3 -m pcbenv.qa build --n 100 --out qa/packets --seed 7`. Tally with `python3 -m pcbenv.qa tally qa/packets`.

## Instructions for reviewers

You are a qualified electrical engineer checking that this benchmark is fair and graded correctly. You do **not** need KiCad: each packet's `README.md` has everything (TASK.md verbatim, datasheets, renders, the hidden faults, the reference fix as a diff, and the verifier's verdicts).

- **Time budget:** about 5 minutes per packet. If a packet needs more than 10, mark `unsure` and say why in `notes`; that is itself a finding.
- **Order:** read section 1 (agent's view) first and form your own opinion of what is wrong. Then read section 2 and compare.
- **What to look for:**
  - The task demands something the public material does not state (hidden requirement, ambiguous connection, a value with no assertion and no published range).
  - The injected fault is not actually a fault (e.g. a value change that is still within a sensible engineering tolerance; a footprint that is equally valid; a decap distance that is fine in practice).
  - The golden/reference design is itself wrong or poor practice.
  - The verifier fails the faulted files for the wrong reason, or would reject a valid alternative repair (different E-series value, re-routing instead of restoring, keeping an allowed footprint).
  - The verdict on the golden is anything but reward 1.
- **Form:** fill `review.yaml` (first reviewer). The second reviewer copies `qa/review_template.yaml` to `review-<initials>.yaml` in the same packet dir, **without reading the first form**.
- Unfilled fields count as pending; you can stop and resume at any time.

## Acceptance rule

- Two independent EEs review every packet.
- Per reviewer, at least 95% of completed packets have `verifier_verdict_agrees: yes`, `reference_fix_correct: yes` and `task_fair: yes` (computed by `tally`).
- Every disputed packet (any `no`/`unsure`, any rejected alternative fix, or the two reviewers disagreeing) must be resolved before sign-off: the orchestrator decides whether the **task** (regenerate / drop it, fix the TASK.md writer or fault injector) or the **verifier** (assertion window, value bound, alt_partitions, check logic) is wrong, fixes it in the owning module, regenerates the affected tasks and packets, and the disputing reviewer re-reviews them. No task ships with an open dispute.
- The 95% threshold is not yet in `thresholds.yaml` (orchestrator-owned); proposed key `qa.ee_verifier_agreement_min: 0.95`.
- Human sign-off is founder-owned. `qa/self_review.md` is an automated pre-screen by the packaging agent, not a substitute.

## Sample composition

| family | packets |
|---|---|
| divider_adc | 9 |
| ldo_reg | 11 |
| led_driver | 9 |
| mcu_i2c | 11 |
| nmos_switch | 10 |
| npn_switch | 10 |
| opamp_inv | 11 |
| opamp_noninv | 9 |
| rc_lowpass | 9 |
| xtal_osc | 11 |

| hint level | packets |
|---|---|
| explicit | 27 |
| symptom | 28 |
| vague | 45 |

| faults per task | packets |
|---|---|
| 1 | 20 |
| 2 | 22 |
| 3 | 58 |

| fault type | packets containing it |
|---|---|
| `board_pad_swap` | 10 |
| `bom_mismatch` | 31 |
| `broken_trace` | 12 |
| `clearance_violation` | 9 |
| `decap_misconnected` | 8 |
| `decap_moved_far` | 13 |
| `floating_pin` | 14 |
| `footprint_swap` | 19 |
| `magnitude_slip` | 9 |
| `narrow_power_trace` | 22 |
| `pin_to_wrong_net` | 12 |
| `reversed_polarity` | 10 |
| `short_between_nets` | 8 |
| `swapped_ic_pins` | 8 |
| `transistor_pinout` | 8 |
| `wrong_feedback_resistor` | 11 |
| `wrong_filter_cap` | 13 |
| `wrong_led_resistor` | 10 |
| `wrong_pull_resistor` | 11 |

## Packets

| # | task | family | faults | hint | why sampled | packet |
|---|---|---|---|---|---|---|
| 01 | `pcbr-divider_adc-180-ce681306` | divider_adc | wrong_filter_cap, bom_mismatch, board_pad_swap | symptom | 3 faults; disputable type bom_mismatch; value near bounds: C1=680n inside [5.5e-07, 4.7e-06]; R2=64.9k near [4900, 54000] | [README](packets/01-pcbr-divider_adc-180-ce681306/README.md) |
| 02 | `pcbr-divider_adc-270-7afd5451` | divider_adc | bom_mismatch, broken_trace | vague | vague hint; disputable type bom_mismatch; value near bounds: R1=24.9k inside [22000, 190000] | [README](packets/02-pcbr-divider_adc-270-7afd5451/README.md) |
| 03 | `pcbr-divider_adc-350-a532df0e` | divider_adc | wrong_feedback_resistor, short_between_nets | explicit | value near bounds: R1=26.1k near [33000, 360000] | [README](packets/03-pcbr-divider_adc-350-a532df0e/README.md) |
| 04 | `pcbr-divider_adc-390-db37bfe9` | divider_adc | wrong_filter_cap, clearance_violation | explicit | value near bounds: C1=6.8n inside [1e-09, 1.2e-08] | [README](packets/04-pcbr-divider_adc-390-db37bfe9/README.md) |
| 05 | `pcbr-divider_adc-530-bd8f0543` | divider_adc | wrong_filter_cap | vague | vague hint; value near bounds: C1=3.9n inside [7.8e-10, 7.4e-09] | [README](packets/05-pcbr-divider_adc-530-bd8f0543/README.md) |
| 06 | `pcbr-divider_adc-580-4ebbb1fe` | divider_adc | pin_to_wrong_net, bom_mismatch, magnitude_slip | vague | 3 faults; vague hint; connectivity fault; disputable type bom_mismatch; value near bounds: C1=120n inside [9.7e-08, 1e-06] | [README](packets/06-pcbr-divider_adc-580-4ebbb1fe/README.md) |
| 07 | `pcbr-divider_adc-630-19fbb293` | divider_adc | narrow_power_trace, footprint_swap | vague | vague hint; disputable type footprint_swap; disputable type narrow_power_trace | [README](packets/07-pcbr-divider_adc-630-19fbb293/README.md) |
| 08 | `pcbr-divider_adc-650-38bc0849` | divider_adc | pin_to_wrong_net, wrong_feedback_resistor | explicit | connectivity fault; value near bounds: R2=59k inside [22000, 270000] | [README](packets/08-pcbr-divider_adc-650-38bc0849/README.md) |
| 09 | `pcbr-divider_adc-700-45820320` | divider_adc | wrong_filter_cap, wrong_feedback_resistor, narrow_power_trace | symptom | 3 faults; disputable type narrow_power_trace; value near bounds: C1=5.6n inside [2.5e-09, 2.5e-08]; R1=49.9k inside [47000, 460000] | [README](packets/09-pcbr-divider_adc-700-45820320/README.md) |
| 10 | `pcbr-ldo_reg-141-bdb95561` | ldo_reg | decap_misconnected, magnitude_slip, footprint_swap | symptom | 3 faults; connectivity fault; disputable type footprint_swap | [README](packets/10-pcbr-ldo_reg-141-bdb95561/README.md) |
| 11 | `pcbr-ldo_reg-161-03db8610` | ldo_reg | swapped_ic_pins, wrong_feedback_resistor, short_between_nets | vague | 3 faults; vague hint; connectivity fault; value near bounds: R2=15.4k inside [3300, 150000] | [README](packets/11-pcbr-ldo_reg-161-03db8610/README.md) |
| 12 | `pcbr-ldo_reg-171-f80c5a9d` | ldo_reg | floating_pin, wrong_pull_resistor, decap_moved_far | vague | 3 faults; vague hint; connectivity fault; disputable type decap_moved_far | [README](packets/12-pcbr-ldo_reg-171-f80c5a9d/README.md) |
| 13 | `pcbr-ldo_reg-221-7d136a08` | ldo_reg | swapped_ic_pins, bom_mismatch, board_pad_swap | vague | 3 faults; vague hint; connectivity fault; disputable type bom_mismatch; value near bounds: C2=2.2u inside [1e-06, 2.2e-05] | [README](packets/13-pcbr-ldo_reg-221-7d136a08/README.md) |
| 14 | `pcbr-ldo_reg-361-4a4db820` | ldo_reg | clearance_violation | vague | vague hint | [README](packets/14-pcbr-ldo_reg-361-4a4db820/README.md) |
| 15 | `pcbr-ldo_reg-41-78e3b802` | ldo_reg | pin_to_wrong_net, bom_mismatch | symptom | connectivity fault; disputable type bom_mismatch; value near bounds: C2=10u inside [1e-06, 2.2e-05] | [README](packets/15-pcbr-ldo_reg-41-78e3b802/README.md) |
| 16 | `pcbr-ldo_reg-411-ca00c60a` | ldo_reg | wrong_feedback_resistor, decap_moved_far | explicit | disputable type decap_moved_far; value near bounds: R1=32.4k inside [7000, 320000] | [README](packets/16-pcbr-ldo_reg-411-ca00c60a/README.md) |
| 17 | `pcbr-ldo_reg-441-38703631` | ldo_reg | narrow_power_trace | vague | vague hint; disputable type narrow_power_trace | [README](packets/17-pcbr-ldo_reg-441-38703631/README.md) |
| 18 | `pcbr-ldo_reg-451-bec8f048` | ldo_reg | decap_moved_far | vague | vague hint; disputable type decap_moved_far | [README](packets/18-pcbr-ldo_reg-451-bec8f048/README.md) |
| 19 | `pcbr-ldo_reg-541-26180fe5` | ldo_reg | reversed_polarity | symptom | connectivity fault | [README](packets/19-pcbr-ldo_reg-541-26180fe5/README.md) |
| 20 | `pcbr-ldo_reg-761-f3c84e28` | ldo_reg | wrong_feedback_resistor, broken_trace, footprint_swap | explicit | 3 faults; disputable type footprint_swap; value near bounds: R1=10k inside [7000, 320000] | [README](packets/20-pcbr-ldo_reg-761-f3c84e28/README.md) |
| 21 | `pcbr-led_driver-22-96bbd902` | led_driver | pin_to_wrong_net, bom_mismatch, footprint_swap | explicit | 3 faults; connectivity fault; disputable type bom_mismatch; disputable type footprint_swap | [README](packets/21-pcbr-led_driver-22-96bbd902/README.md) |
| 22 | `pcbr-led_driver-232-8e7d18d6` | led_driver | reversed_polarity, wrong_led_resistor | explicit | connectivity fault; value near bounds: R1=12k inside [1200, 12000] | [README](packets/22-pcbr-led_driver-232-8e7d18d6/README.md) |
| 23 | `pcbr-led_driver-282-2bdcb793` | led_driver | bom_mismatch, broken_trace | vague | vague hint; disputable type bom_mismatch; value near bounds: R3=100 inside [58, 770] | [README](packets/23-pcbr-led_driver-282-2bdcb793/README.md) |
| 24 | `pcbr-led_driver-312-8e5d8552` | led_driver | reversed_polarity, wrong_led_resistor, footprint_swap | vague | 3 faults; vague hint; connectivity fault; disputable type footprint_swap; value near bounds: R1=75 inside [73, 710] | [README](packets/24-pcbr-led_driver-312-8e5d8552/README.md) |
| 25 | `pcbr-led_driver-562-0fb5b05e` | led_driver | magnitude_slip, board_pad_swap, narrow_power_trace | explicit | 3 faults; disputable type narrow_power_trace | [README](packets/25-pcbr-led_driver-562-0fb5b05e/README.md) |
| 26 | `pcbr-led_driver-692-e674ddce` | led_driver | wrong_led_resistor, narrow_power_trace, clearance_violation | symptom | 3 faults; disputable type narrow_power_trace; value near bounds: R1=110 inside [13, 190] | [README](packets/26-pcbr-led_driver-692-e674ddce/README.md) |
| 27 | `pcbr-led_driver-722-4b1b70cd` | led_driver | reversed_polarity, wrong_led_resistor, bom_mismatch | vague | 3 faults; vague hint; connectivity fault; disputable type bom_mismatch; value near bounds: R2=1.8k near [150, 1400]; R1=62 inside [39, 500] | [README](packets/27-pcbr-led_driver-722-4b1b70cd/README.md) |
| 28 | `pcbr-led_driver-732-5362982e` | led_driver | board_pad_swap | vague | vague hint | [README](packets/28-pcbr-led_driver-732-5362982e/README.md) |
| 29 | `pcbr-led_driver-772-b7ff9a78` | led_driver | bom_mismatch, narrow_power_trace, short_between_nets | symptom | 3 faults; disputable type bom_mismatch; disputable type narrow_power_trace; value near bounds: R2=220 inside [200, 2300] | [README](packets/29-pcbr-led_driver-772-b7ff9a78/README.md) |
| 30 | `pcbr-mcu_i2c-113-f904c866` | mcu_i2c | swapped_ic_pins, bom_mismatch, clearance_violation | symptom | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: R2=13k near [880, 8800] | [README](packets/30-pcbr-mcu_i2c-113-f904c866/README.md) |
| 31 | `pcbr-mcu_i2c-123-1565fd20` | mcu_i2c | floating_pin, decap_moved_far, broken_trace | explicit | 3 faults; connectivity fault; disputable type decap_moved_far | [README](packets/31-pcbr-mcu_i2c-123-1565fd20/README.md) |
| 32 | `pcbr-mcu_i2c-143-c981f98f` | mcu_i2c | swapped_ic_pins, narrow_power_trace, footprint_swap | vague | 3 faults; vague hint; connectivity fault; disputable type footprint_swap; disputable type narrow_power_trace | [README](packets/32-pcbr-mcu_i2c-143-c981f98f/README.md) |
| 33 | `pcbr-mcu_i2c-153-bfc3eb79` | mcu_i2c | wrong_pull_resistor, bom_mismatch, decap_moved_far | symptom | 3 faults; disputable type bom_mismatch; disputable type decap_moved_far; value near bounds: R3=2.2k near [2800, 25000]; R1=1.6k near [2200, 100000] | [README](packets/33-pcbr-mcu_i2c-153-bfc3eb79/README.md) |
| 34 | `pcbr-mcu_i2c-163-39beb37a` | mcu_i2c | pin_to_wrong_net | vague | vague hint; connectivity fault | [README](packets/34-pcbr-mcu_i2c-163-39beb37a/README.md) |
| 35 | `pcbr-mcu_i2c-303-3d8e4366` | mcu_i2c | floating_pin, magnitude_slip, bom_mismatch | vague | 3 faults; vague hint; connectivity fault; disputable type bom_mismatch; value near bounds: R1=62k inside [2200, 100000] | [README](packets/35-pcbr-mcu_i2c-303-3d8e4366/README.md) |
| 36 | `pcbr-mcu_i2c-333-89daf64f` | mcu_i2c | wrong_pull_resistor, narrow_power_trace, broken_trace | vague | 3 faults; vague hint; disputable type narrow_power_trace; value near bounds: R3=470 near [680, 5400] | [README](packets/36-pcbr-mcu_i2c-333-89daf64f/README.md) |
| 37 | `pcbr-mcu_i2c-483-7ce31b63` | mcu_i2c | decap_misconnected, floating_pin, bom_mismatch | symptom | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: C3=10n inside [1e-08, 1e-06] | [README](packets/37-pcbr-mcu_i2c-483-7ce31b63/README.md) |
| 38 | `pcbr-mcu_i2c-493-92bd686e` | mcu_i2c | decap_misconnected, narrow_power_trace, clearance_violation | explicit | 3 faults; connectivity fault; disputable type narrow_power_trace | [README](packets/38-pcbr-mcu_i2c-493-92bd686e/README.md) |
| 39 | `pcbr-mcu_i2c-563-9cf35825` | mcu_i2c | board_pad_swap | vague | vague hint | [README](packets/39-pcbr-mcu_i2c-563-9cf35825/README.md) |
| 40 | `pcbr-mcu_i2c-713-96e12866` | mcu_i2c | short_between_nets | vague | vague hint | [README](packets/40-pcbr-mcu_i2c-713-96e12866/README.md) |
| 41 | `pcbr-nmos_switch-124-8e35b38d` | nmos_switch | transistor_pinout, wrong_pull_resistor, board_pad_swap | explicit | 3 faults; connectivity fault; value near bounds: R2=330k near [4700, 220000] | [README](packets/41-pcbr-nmos_switch-124-8e35b38d/README.md) |
| 42 | `pcbr-nmos_switch-164-a3e65927` | nmos_switch | transistor_pinout, wrong_pull_resistor, narrow_power_trace | explicit | 3 faults; connectivity fault; disputable type narrow_power_trace; value near bounds: R2=270k near [4700, 220000] | [README](packets/42-pcbr-nmos_switch-164-a3e65927/README.md) |
| 43 | `pcbr-nmos_switch-224-c5ce2cba` | nmos_switch | transistor_pinout, bom_mismatch, clearance_violation | symptom | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: R1=30 inside [4.7, 220] | [README](packets/43-pcbr-nmos_switch-224-c5ce2cba/README.md) |
| 44 | `pcbr-nmos_switch-254-97ea7341` | nmos_switch | bom_mismatch, magnitude_slip, broken_trace | vague | 3 faults; vague hint; disputable type bom_mismatch; value near bounds: C1=15u inside [1e-06, 2.2e-05] | [README](packets/44-pcbr-nmos_switch-254-97ea7341/README.md) |
| 45 | `pcbr-nmos_switch-324-a2053b05` | nmos_switch | floating_pin, bom_mismatch, narrow_power_trace | symptom | 3 faults; connectivity fault; disputable type bom_mismatch; disputable type narrow_power_trace; value near bounds: C1=10u inside [1e-06, 2.2e-05] | [README](packets/45-pcbr-nmos_switch-324-a2053b05/README.md) |
| 46 | `pcbr-nmos_switch-334-f9c88267` | nmos_switch | transistor_pinout, wrong_pull_resistor, footprint_swap | explicit | 3 faults; connectivity fault; disputable type footprint_swap; value near bounds: R2=3.3k near [4700, 220000] | [README](packets/46-pcbr-nmos_switch-334-f9c88267/README.md) |
| 47 | `pcbr-nmos_switch-54-44ed9217` | nmos_switch | pin_to_wrong_net | vague | vague hint; connectivity fault | [README](packets/47-pcbr-nmos_switch-54-44ed9217/README.md) |
| 48 | `pcbr-nmos_switch-564-c0fc1c98` | nmos_switch | transistor_pinout | vague | vague hint; connectivity fault | [README](packets/48-pcbr-nmos_switch-564-c0fc1c98/README.md) |
| 49 | `pcbr-nmos_switch-574-b6ffc501` | nmos_switch | reversed_polarity | symptom | connectivity fault | [README](packets/49-pcbr-nmos_switch-574-b6ffc501/README.md) |
| 50 | `pcbr-nmos_switch-94-fcedf34a` | nmos_switch | narrow_power_trace, footprint_swap | vague | vague hint; disputable type footprint_swap; disputable type narrow_power_trace | [README](packets/50-pcbr-nmos_switch-94-fcedf34a/README.md) |
| 51 | `pcbr-npn_switch-105-d4bd3906` | npn_switch | floating_pin, swapped_ic_pins, narrow_power_trace | explicit | 3 faults; connectivity fault; disputable type narrow_power_trace | [README](packets/51-pcbr-npn_switch-105-d4bd3906/README.md) |
| 52 | `pcbr-npn_switch-185-e13e0b22` | npn_switch | transistor_pinout, wrong_pull_resistor, clearance_violation | symptom | 3 faults; connectivity fault; value near bounds: R4=3.9k near [4700, 220000] | [README](packets/52-pcbr-npn_switch-185-e13e0b22/README.md) |
| 53 | `pcbr-npn_switch-25-ffd8e224` | npn_switch | magnitude_slip, bom_mismatch, footprint_swap | explicit | 3 faults; disputable type bom_mismatch; disputable type footprint_swap | [README](packets/53-pcbr-npn_switch-25-ffd8e224/README.md) |
| 54 | `pcbr-npn_switch-45-ae23fa40` | npn_switch | decap_misconnected | vague | vague hint; connectivity fault | [README](packets/54-pcbr-npn_switch-45-ae23fa40/README.md) |
| 55 | `pcbr-npn_switch-545-22269cf9` | npn_switch | transistor_pinout, bom_mismatch, broken_trace | explicit | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: C1=2.2u inside [4.7e-08, 1e-05] | [README](packets/55-pcbr-npn_switch-545-22269cf9/README.md) |
| 56 | `pcbr-npn_switch-595-a42c16b2` | npn_switch | reversed_polarity, wrong_led_resistor | vague | vague hint; connectivity fault; value near bounds: R3=62 inside [42, 480] | [README](packets/56-pcbr-npn_switch-595-a42c16b2/README.md) |
| 57 | `pcbr-npn_switch-655-91d454d7` | npn_switch | transistor_pinout, wrong_led_resistor, decap_moved_far | symptom | 3 faults; connectivity fault; disputable type decap_moved_far; value near bounds: R3=240 inside [38, 310] | [README](packets/57-pcbr-npn_switch-655-91d454d7/README.md) |
| 58 | `pcbr-npn_switch-795-ef26a147` | npn_switch | wrong_led_resistor, narrow_power_trace | symptom | disputable type narrow_power_trace; value near bounds: R3=150 inside [110, 1000] | [README](packets/58-pcbr-npn_switch-795-ef26a147/README.md) |
| 59 | `pcbr-npn_switch-85-9f4dd3c1` | npn_switch | pin_to_wrong_net | vague | vague hint; connectivity fault | [README](packets/59-pcbr-npn_switch-85-9f4dd3c1/README.md) |
| 60 | `pcbr-npn_switch-95-01a07d7b` | npn_switch | reversed_polarity, wrong_pull_resistor | vague | vague hint; connectivity fault; value near bounds: R4=270k near [4700, 220000] | [README](packets/60-pcbr-npn_switch-95-01a07d7b/README.md) |
| 61 | `pcbr-opamp_inv-256-72a73548` | opamp_inv | swapped_ic_pins | explicit | connectivity fault | [README](packets/61-pcbr-opamp_inv-256-72a73548/README.md) |
| 62 | `pcbr-opamp_inv-306-6375845d` | opamp_inv | wrong_feedback_resistor, decap_moved_far, footprint_swap | symptom | 3 faults; disputable type decap_moved_far; disputable type footprint_swap; value near bounds: R1=17.4k near [950, 14000] | [README](packets/62-pcbr-opamp_inv-306-6375845d/README.md) |
| 63 | `pcbr-opamp_inv-326-89619a3d` | opamp_inv | floating_pin, wrong_pull_resistor, decap_moved_far | symptom | 3 faults; connectivity fault; disputable type decap_moved_far; value near bounds: R3=680k near [4700, 470000] | [README](packets/63-pcbr-opamp_inv-326-89619a3d/README.md) |
| 64 | `pcbr-opamp_inv-336-88531412` | opamp_inv | pin_to_wrong_net | vague | vague hint; connectivity fault | [README](packets/64-pcbr-opamp_inv-336-88531412/README.md) |
| 65 | `pcbr-opamp_inv-36-1f0a9d5a` | opamp_inv | decap_misconnected, wrong_filter_cap, footprint_swap | symptom | 3 faults; connectivity fault; disputable type footprint_swap; value near bounds: C2=1.5u near [2.1e-06, 1.7e-05] | [README](packets/65-pcbr-opamp_inv-36-1f0a9d5a/README.md) |
| 66 | `pcbr-opamp_inv-406-839e8a71` | opamp_inv | wrong_pull_resistor, decap_moved_far | vague | vague hint; disputable type decap_moved_far; value near bounds: R3=3.3k near [4700, 470000] | [README](packets/66-pcbr-opamp_inv-406-839e8a71/README.md) |
| 67 | `pcbr-opamp_inv-426-b34cbb63` | opamp_inv | wrong_pull_resistor, broken_trace | vague | vague hint; value near bounds: R3=3.9k near [4700, 470000] | [README](packets/67-pcbr-opamp_inv-426-b34cbb63/README.md) |
| 68 | `pcbr-opamp_inv-6-810fcada` | opamp_inv | bom_mismatch, narrow_power_trace, short_between_nets | explicit | 3 faults; disputable type bom_mismatch; disputable type narrow_power_trace | [README](packets/68-pcbr-opamp_inv-6-810fcada/README.md) |
| 69 | `pcbr-opamp_inv-66-e5086d78` | opamp_inv | wrong_feedback_resistor | vague | vague hint; value near bounds: R1=39.2k near [2700, 28000] | [README](packets/69-pcbr-opamp_inv-66-e5086d78/README.md) |
| 70 | `pcbr-opamp_inv-796-8bc93e64` | opamp_inv | bom_mismatch, board_pad_swap, short_between_nets | symptom | 3 faults; disputable type bom_mismatch; value near bounds: R3=20k inside [4700, 470000] | [README](packets/70-pcbr-opamp_inv-796-8bc93e64/README.md) |
| 71 | `pcbr-opamp_inv-96-c85f8a7f` | opamp_inv | floating_pin, bom_mismatch, narrow_power_trace | explicit | 3 faults; connectivity fault; disputable type bom_mismatch; disputable type narrow_power_trace; value near bounds: R3=26.7k inside [4700, 470000] | [README](packets/71-pcbr-opamp_inv-96-c85f8a7f/README.md) |
| 72 | `pcbr-opamp_noninv-107-0b2eda4b` | opamp_noninv | floating_pin, bom_mismatch, decap_moved_far | explicit | 3 faults; connectivity fault; disputable type bom_mismatch; disputable type decap_moved_far; value near bounds: R3=2.2M inside [47000, 2.2e+06] | [README](packets/72-pcbr-opamp_noninv-107-0b2eda4b/README.md) |
| 73 | `pcbr-opamp_noninv-137-0a8f970e` | opamp_noninv | pin_to_wrong_net, wrong_feedback_resistor | vague | vague hint; connectivity fault; value near bounds: R1=2.67k inside [1000, 14000] | [README](packets/73-pcbr-opamp_noninv-137-0a8f970e/README.md) |
| 74 | `pcbr-opamp_noninv-157-c5c97789` | opamp_noninv | decap_misconnected, footprint_swap, broken_trace | symptom | 3 faults; connectivity fault; disputable type footprint_swap | [README](packets/74-pcbr-opamp_noninv-157-c5c97789/README.md) |
| 75 | `pcbr-opamp_noninv-237-f1a93032` | opamp_noninv | floating_pin, bom_mismatch | vague | vague hint; connectivity fault; disputable type bom_mismatch; value near bounds: R1=3.57k inside [1500, 20000] | [README](packets/75-pcbr-opamp_noninv-237-f1a93032/README.md) |
| 76 | `pcbr-opamp_noninv-287-7fb1e091` | opamp_noninv | floating_pin, wrong_filter_cap, narrow_power_trace | explicit | 3 faults; connectivity fault; disputable type narrow_power_trace; value near bounds: C2=470p inside [1.8e-10, 1.9e-09] | [README](packets/76-pcbr-opamp_noninv-287-7fb1e091/README.md) |
| 77 | `pcbr-opamp_noninv-327-5a065faa` | opamp_noninv | swapped_ic_pins, wrong_feedback_resistor, short_between_nets | symptom | 3 faults; connectivity fault; value near bounds: R2=1.82k inside [680, 8100] | [README](packets/77-pcbr-opamp_noninv-327-5a065faa/README.md) |
| 78 | `pcbr-opamp_noninv-617-90f9e31e` | opamp_noninv | decap_misconnected, wrong_filter_cap | vague | vague hint; connectivity fault; value near bounds: C2=330p inside [2e-10, 2e-09] | [README](packets/78-pcbr-opamp_noninv-617-90f9e31e/README.md) |
| 79 | `pcbr-opamp_noninv-757-b4064ecb` | opamp_noninv | floating_pin, wrong_feedback_resistor, decap_moved_far | vague | 3 faults; vague hint; connectivity fault; disputable type decap_moved_far; value near bounds: R1=54.9k inside [10000, 100000] | [README](packets/79-pcbr-opamp_noninv-757-b4064ecb/README.md) |
| 80 | `pcbr-opamp_noninv-817-b7f45449` | opamp_noninv | magnitude_slip, narrow_power_trace, footprint_swap | symptom | 3 faults; disputable type footprint_swap; disputable type narrow_power_trace | [README](packets/80-pcbr-opamp_noninv-817-b7f45449/README.md) |
| 81 | `pcbr-rc_lowpass-108-b616cfab` | rc_lowpass | wrong_filter_cap, footprint_swap, broken_trace | explicit | 3 faults; disputable type footprint_swap; value near bounds: C1=4.7n inside [3.4e-09, 3.2e-08] | [README](packets/81-pcbr-rc_lowpass-108-b616cfab/README.md) |
| 82 | `pcbr-rc_lowpass-148-d080b6e3` | rc_lowpass | pin_to_wrong_net, footprint_swap | vague | vague hint; connectivity fault; disputable type footprint_swap | [README](packets/82-pcbr-rc_lowpass-148-d080b6e3/README.md) |
| 83 | `pcbr-rc_lowpass-348-5649934a` | rc_lowpass | pin_to_wrong_net, wrong_filter_cap | symptom | connectivity fault; value near bounds: C1=10n near [5.8e-10, 7.8e-09] | [README](packets/83-pcbr-rc_lowpass-348-5649934a/README.md) |
| 84 | `pcbr-rc_lowpass-388-5ad7e734` | rc_lowpass | bom_mismatch, magnitude_slip | explicit | disputable type bom_mismatch; value near bounds: R1=1.5k inside [960, 8400] | [README](packets/84-pcbr-rc_lowpass-388-5ad7e734/README.md) |
| 85 | `pcbr-rc_lowpass-628-dd01cbe4` | rc_lowpass | wrong_filter_cap, bom_mismatch, narrow_power_trace | vague | 3 faults; vague hint; disputable type bom_mismatch; disputable type narrow_power_trace; value near bounds: C2=39n inside [2.5e-08, 3.2e-07] | [README](packets/85-pcbr-rc_lowpass-628-dd01cbe4/README.md) |
| 86 | `pcbr-rc_lowpass-648-f070d3e7` | rc_lowpass | clearance_violation | vague | vague hint | [README](packets/86-pcbr-rc_lowpass-648-f070d3e7/README.md) |
| 87 | `pcbr-rc_lowpass-698-bec0d9e4` | rc_lowpass | wrong_filter_cap, narrow_power_trace, broken_trace | symptom | 3 faults; disputable type narrow_power_trace; value near bounds: C2=6.8p inside [3.2e-12, 3.9e-11] | [README](packets/87-pcbr-rc_lowpass-698-bec0d9e4/README.md) |
| 88 | `pcbr-rc_lowpass-728-24209a83` | rc_lowpass | bom_mismatch, wrong_filter_cap, board_pad_swap | vague | 3 faults; vague hint; disputable type bom_mismatch; value near bounds: C1=4.7n inside [8.7e-10, 1.2e-08] | [README](packets/88-pcbr-rc_lowpass-728-24209a83/README.md) |
| 89 | `pcbr-rc_lowpass-98-7c881f93` | rc_lowpass | bom_mismatch, short_between_nets | vague | vague hint; disputable type bom_mismatch; value near bounds: R1=560 inside [450, 3500] | [README](packets/89-pcbr-rc_lowpass-98-7c881f93/README.md) |
| 90 | `pcbr-xtal_osc-109-c298a4ec` | xtal_osc | reversed_polarity | vague | vague hint; connectivity fault | [README](packets/90-pcbr-xtal_osc-109-c298a4ec/README.md) |
| 91 | `pcbr-xtal_osc-139-9af6f1c3` | xtal_osc | pin_to_wrong_net | vague | vague hint; connectivity fault | [README](packets/91-pcbr-xtal_osc-139-9af6f1c3/README.md) |
| 92 | `pcbr-xtal_osc-259-1d707b0e` | xtal_osc | magnitude_slip, bom_mismatch, narrow_power_trace | symptom | 3 faults; disputable type bom_mismatch; disputable type narrow_power_trace; value near bounds: C2=33p inside [6e-12, 3.8e-11] | [README](packets/92-pcbr-xtal_osc-259-1d707b0e/README.md) |
| 93 | `pcbr-xtal_osc-279-2f36bb66` | xtal_osc | decap_misconnected, board_pad_swap, footprint_swap | symptom | 3 faults; connectivity fault; disputable type footprint_swap | [README](packets/93-pcbr-xtal_osc-279-2f36bb66/README.md) |
| 94 | `pcbr-xtal_osc-369-22ead68b` | xtal_osc | swapped_ic_pins, bom_mismatch, footprint_swap | vague | 3 faults; vague hint; connectivity fault; disputable type bom_mismatch; disputable type footprint_swap; value near bounds: C3=47n inside [4.7e-08, 1e-05] | [README](packets/94-pcbr-xtal_osc-369-22ead68b/README.md) |
| 95 | `pcbr-xtal_osc-589-c961f0f1` | xtal_osc | reversed_polarity, floating_pin, bom_mismatch | symptom | 3 faults; connectivity fault; disputable type bom_mismatch; value near bounds: R2=680 inside [110, 890] | [README](packets/95-pcbr-xtal_osc-589-c961f0f1/README.md) |
| 96 | `pcbr-xtal_osc-599-a599fcf2` | xtal_osc | bom_mismatch, wrong_filter_cap, decap_moved_far | explicit | 3 faults; disputable type bom_mismatch; disputable type decap_moved_far; value near bounds: C2=12p inside [6.1e-12, 6.7e-11] | [README](packets/96-pcbr-xtal_osc-599-a599fcf2/README.md) |
| 97 | `pcbr-xtal_osc-639-c91ead39` | xtal_osc | reversed_polarity, wrong_led_resistor, board_pad_swap | explicit | 3 faults; connectivity fault; value near bounds: R2=100 inside [77, 1200] | [README](packets/97-pcbr-xtal_osc-639-c91ead39/README.md) |
| 98 | `pcbr-xtal_osc-649-8fced652` | xtal_osc | wrong_led_resistor, narrow_power_trace, clearance_violation | vague | 3 faults; vague hint; disputable type narrow_power_trace; value near bounds: R2=2.4k near [280, 2200] | [README](packets/98-pcbr-xtal_osc-649-8fced652/README.md) |
| 99 | `pcbr-xtal_osc-79-322f057a` | xtal_osc | floating_pin, wrong_led_resistor, footprint_swap | explicit | 3 faults; connectivity fault; disputable type footprint_swap; value near bounds: R2=100 inside [83, 1100] | [README](packets/99-pcbr-xtal_osc-79-322f057a/README.md) |
| 10 | `pcbr-xtal_osc-819-7e6399e0` | xtal_osc | decap_moved_far, footprint_swap, broken_trace | explicit | 3 faults; disputable type decap_moved_far; disputable type footprint_swap | [README](packets/100-pcbr-xtal_osc-819-7e6399e0/README.md) |
