# Data card: PCB-Repair task set

## Summary

PCB-Repair tasks are small circuit-board repair problems. Each task is a golden design (a
schematic in `design.json` plus a KiCad 7 layout in `board.kicad_pcb`) with 1–3 injected faults,
a natural-language problem report (`TASK.md`), a machine-readable spec (`spec.json`) and
datasheets for the generic parts. A deterministic verifier grades the agent's repaired files
against the hidden golden. The reward is binary.

## Provenance

- **100 % synthetic and procedurally generated.** Each circuit is produced by a family generator
  (`pcbenv/families/`) from an integer seed. The layout comes from our own placer and maze router
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

<!-- ORCHESTRATOR: fill from tasks/manifest.jsonl and reports/g4_faults.md once G4 ships. -->

| Field | Value |
|---|---|
| Families | 10: `ldo_reg`, `led_driver`, `npn_switch`, `nmos_switch`, `opamp_noninv`, `opamp_inv`, `rc_lowpass`, `divider_adc`, `mcu_i2c`, `xtal_osc` |
| Fault types | _TBD (≥ 15, see reports/g4_faults.md)_ |
| Tasks | _TBD (≥ 500 shipped)_ |
| Splits | `train`, `holdout` (20 %) |
| Board size | 2 copper layers, about 6–16 components, a few cm across |
| Files per task | public: TASK.md, design.json, board.kicad_pcb, spec.json, parts/*.md · hidden: golden_design.json, golden_board.kicad_pcb, meta.json |

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
