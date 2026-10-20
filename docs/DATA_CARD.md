# Data card: PCB-Repair task set

## Summary

PCB-Repair tasks are small circuit-board repair problems. Each task is a golden design (a
schematic in `design.json` plus a KiCad 7 layout in `board.kicad_pcb`) with 1–3 injected faults
(hard tier: 3–6, at least two latent),
a natural-language problem report (`TASK.md`), a machine-readable spec (`spec.json`) and
datasheets for the generic parts. A deterministic verifier grades the agent's repaired files
against the hidden golden. The reward is binary.

## Provenance

- **100 % synthetic and procedurally generated.** Each circuit is produced by a family generator
  (`pcbenv/families/`) from an integer seed (v2: seed = HMAC(secret, task index), `pcbenv/taskids.py`). The layout comes from our own placer and maze router
  (`pcbenv/board.py`, `pcbenv/router.py`). Faults come from the fault injector (`pcbenv/faults`),
  and the text from templates. No third-party designs, scraped schematics, customer data or
  personal data are included.
- **Parts are generic** (`LDO_ADJ`, `OPAMP`, `MCU8`, `NPN`, ...). Their datasheets were written
  for this project and do not reproduce any manufacturer's datasheet.
- **Footprints come from the KiCad 7.0.11 standard footprint library**
  (`/usr/share/kicad/footprints`, Debian/Ubuntu package `kicad-footprints` 7.0.11-1). Board files
  embed copies of these footprints (pads, graphics, courtyard).
- **No model generated any of the data**, so it does not inherit model outputs or biases. Its
  distribution is set entirely by the generators' parameter ranges.

## Licensing

- **This dataset: LICENSE-TBD (founder decision).**
- **KiCad library footprints are licensed CC-BY-SA 4.0 with a KiCad-specific exception.** As we
  understand the KiCad library licence page, the exception says that designs which merely *use*
  library footprints (and files generated from them) are not considered Adapted Material. Such
  designs therefore do not have to carry CC-BY-SA, and their authors may license them as they
  wish. Our boards are designs that use the footprints unmodified, so we believe the exception
  applies to them. *This is our reading, not legal advice.* Before releasing the dataset under a
  chosen licence, confirm it against the text shipped with KiCad (`/usr/share/doc/kicad-footprints/`
  and https://www.kicad.org/libraries/license/) and attribute the KiCad Libraries project.
- **KiCad itself (GPL-3.0+) and ngspice (BSD-3 and other licences) are tools.** They are not
  redistributed in the task set. Container images that contain them must follow their licences.

## Composition

Source: `reports/v2_generation.md` (generated from the generators' statistics and `tasks/manifest.jsonl`).

| Field | Normal tier (v2) | Hard tier (v2) |
|---|---|---|
| Tasks | 819 (train 655 / holdout 164 = 20.0 %) | 452 (train 362 / holdout 90 = 19.9 %) |
| Splits (dirs under `tasks/`) | `v2/normal`, `v2/normal_holdout` | `v2/hard`, `v2/hard_holdout` |
| Families | 10 v1 families (`ldo_reg`, `led_driver`, `npn_switch`, `nmos_switch`, `opamp_noninv`, `opamp_inv`, `rc_lowpass`, `divider_adc`, `mcu_i2c`, `xtal_osc`), 81–83 tasks each | 4 composite multi-rail families (`sys_analog_frontend` 89, `sys_clocked_mcu` 101, `sys_motor_ctrl` 96, `sys_sensor_node` 95 = 84.3 %) + 5 v1 families (71) |
| Faults per task | 1: 42.1 %, 2: 33.3 %, 3: 24.5 % | 3: 24.6 %, 4: 35.6 %, 5: 23.9 %, 6: 15.9 % |
| Fault types | 19 (6 value, 6 connectivity, 7 board) | the 19 visible types + 12 latent types (invisible to every `pcbtool` check) + interacting value faults; 52.3 % of faults latent, ≥ 2 per task |
| DRC/ERC-invisible | 82.3 % of tasks have ≥ 1 | 100 % (every task has ≥ 2 latent faults) |
| Hint levels | explicit 31.5 %, symptom 38.0 %, vague 30.5 % | symptom 49.8 %, vague 50.2 % |
| Tool mode | full | full 61.1 %, no_autoroute 38.9 % |
| Board size | 2 copper layers, about 6–16 components | 2 copper layers, 20–27 components (composites), 50–72 mm |
| Task ids | opaque `pcbr2-normal-<hmac8>` | opaque `pcbr2-hard-<hmac8>` |
| Files per task | public: TASK.md, design.json, board.kicad_pcb, spec.json, parts/*.md · hidden: golden_design.json, golden_board.kicad_pcb, meta.json | same + public tools.json |

Hard tier, layout-rules sub-tier (`v2/hard_layout`, `v2/hard_layout_holdout`; 193 tasks = 154 train / 39
holdout; ids `pcbr2-hard_layout-<hmac8>`): `sys_motor_ctrl` 109 / `sys_clocked_mcu` 84 boards whose golden layout
meets board-geometry rules stated with formulae in TASK.md "Layout rules" and `spec.json:layout_rules` (Kelvin
sense on the current shunt, switching-loop area ≤ 60 mm², crystal copper path ≤ 10 mm with no vias, analog /
switching-node separation, plus the decoupling copper path), graded by the `layout_rules` / `layout` checks and
not computed by `pcbtool`. 3–6 faults per task with ≥ 1 layout-latent fault (sense trace tapped off the power
path, loop part moved away, crystal moved / via pair, analog trace routed along the switching node, decoupling
cap routed the long way; each invisible to `pcbtool` and violating exactly one layout rule) and ≥ 1 other latent
fault; no_autoroute 87.6 % (always when `pcbtool route` would repair a layout fault). Bundles
`dist/pcb-repair-v2-{hard-layout,hard-layout-holdout}.tar.gz`; details in `reports/v2_generation.md`.

Every shipped task passed the gates: golden 1.0, faulted 0.0, each fault alone 0.0, oracle repair 1.0,
no fault cancelled by another; hard tier also: every latent fault invisible to `pcbtool` alone and its
evidence present in the public text. Bundles: `dist/pcb-repair-v2-{normal,normal-holdout,hard,hard-holdout}.tar.gz`
(sha256s in the report). v1 (818 tasks) remains in git history.

## Intended use

Intended uses:
- Training and evaluating agentic LLMs on tool-using engineering repair tasks with a verifiable
  reward.
- Measuring the ability to diagnose faults from specs, simulation and DRC/ERC output.

Out of scope:
- A benchmark of real-world PCB design quality.
- Signal or power integrity, EMI, thermal, DFM or cost.
- Any certification of the generic parts' models.

## Known biases and limitations

- **Small topology space.** Each family has a fixed topology with sampled values, footprints and
  placement, so models can learn family-specific shortcuts. Holdout tasks come from the same
  families; there are no unseen families in v1.
- **Behavioural SPICE models** (see README "Limitations" and REWARD.md).
- **Fault realism.** Fault types model common bring-up errors (wrong value, swapped pins, missing
  connection, narrow power trace, ...). Their frequency is set by the generator and does not
  reflect real-world incidence.
- **English-only prompts, templated text.**

## Maintenance

- **Versioning** follows VERSIONING.md. Released tasks are immutable.
- **New tasks** come from the refresh engine (`python3 -m pcbenv.generate`) with new seeds,
  deduplicated against shipped tasks.
- **Errors** should be reported as issues, with the task id and verifier output attached.
