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

## Follow-up: why Haiku (100 %) beat Sonnet (57 %) on v2 hard

Same 44 tasks, prompt, effort (medium) and grader for all three models; oracles all 1.0; served
model ids confirmed from transcripts. Paired: 19 tasks Sonnet failed and Haiku passed; **0** the
other way. Sonnet's failures were mostly `rules` (14) — datasheet design rules that TASK.md states
and says pcbtool does NOT check. Cleanest case: 17 tasks contained an under-rated capacitor
(voltage > 80 % of the footprint's rating, stated in parts/C.md): Opus fixed 17/17, Haiku 17/17,
Sonnet 9/17 — and passed exactly those 9. Sonnet claimed "believed fixed" on all 19 failures,
typically ending with "pcbtool check passes".

Effort check: Sonnet re-run on its 19 failed tasks at **effort=high** (fresh workdirs, 0
contaminated) → **12/19 pass**; `rules` failures 14 → 2; remaining failures mostly topology
(missed latent wiring faults). Rollouts: `reports/calibration/v2hard_sonnet_high_rerun/`.

Interpretation: the Haiku/Sonnet gap is mainly a *behavioural, effort-sensitive* difference
(trusting the tool's green checks vs. doing the requested manual review), not a grader artifact
and not evidence that Haiku is more capable. For buyers: hard-tier pass rates depend materially
on effort/scaffolding; report results with effort settings attached. Caveat: the high-effort run
is a second attempt on already-failed tasks (not a fresh 44-task run), so it overstates nothing
about Sonnet-high's overall rate but can't give it either.
