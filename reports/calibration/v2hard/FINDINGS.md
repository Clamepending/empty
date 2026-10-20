# v2 hard-tier calibration — findings (G12, round 2)

Sample: 44 tasks from tasks/v2/hard (stratified over 9 families, 3–6 faults, ≥2 latent each),
one attempt per model, opaque workdirs, effort=medium, graded by `verify_isolated`; oracle
re-verified 1.0 on all; transcript audit (actions only) found 0 contaminated rollouts.
Served models confirmed from transcripts: claude-haiku-5-5, claude-sonnet-5-5, claude-opus-5-5.

| model | pass | tool calls (approx, all agents) |
|---|---|---|
| haiku | 44/44 (100 %) | ~275 on the second half alone; hand-computed decoupling paths, rule checks |
| sonnet | 25/44 (57 %) | far fewer; trusted `pcbtool check` and stopped |
| opus | 42/44 (95 %) | 2 failures, both `layout` (decoupling copper path, not computed by pcbtool) |

Reproduce: `python3 reports/calibration/grade_v2hard.py summary` (graded rollouts and deliverables
committed in this directory).

## Interpretation
- Every graded requirement is stated in public material, so the hard tier measures **diligence**
  (does the agent verify the rules pcbtool doesn't check?) more than capability. A careful small
  model beats a hasty mid-size one.
- That is a legitimate RL target (it teaches verification behaviour), and mid-tier pass rate 57 %
  is inside the learnable band — but G12 requires the *best* model in 10–70 %, and the best observed
  model is at 100 %. **G12 not met.**
- Round 3 (layout-rule faults, hand-routing) is in progress; expectation is that geometry rules
  are also solvable by a diligent agent that computes them. If so, frontier-level difficulty needs
  a different task paradigm (open-ended placement/routing/synthesis with optimisation targets,
  not repair against fully-stated rules).
