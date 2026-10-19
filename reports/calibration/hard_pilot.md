# Hard-tier pilot calibration (G12, round 1)

Sample: 40 tasks from `tasks/hard/` (pilot, 117 tasks; 7 v1 families with 1–2 latent faults
each, 2–4 faults total, symptom/vague hints, 30 % no_autoroute). One attempt per task per model,
opaque workdirs, graded by `verify_isolated`; oracle (golden restore) re-verified 1.0 on all 40
under current code. Grading script: `scratchpad/grade_hard.py` logic (copied below for record).

| model | pass | notes |
|---|---|---|
| sonnet | 30/40 (75 %) | all 10 failures = topology on latent faults (bias returned to wrong rail, connector/MCU pin swaps, swapped LDO caps); orchestrator checked 3: all fair (requirement stated in TASK.md/spec.json) |
| opus | 40/40 (100 %) | still saturated |

Conclusion: latent datasheet/intent faults bite mid-tier models but not the strongest. G12 not met.
Next levers (v2 hard tier): composite multi-rail boards (25–40 parts, builder-hard-B), 4–6 faults
with ≥2 latent, interacting faults, higher no_autoroute share on dense boards.
