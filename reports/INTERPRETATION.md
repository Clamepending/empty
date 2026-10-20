# What the baseline numbers mean (hand-written)

Every number quoted here comes from `reports/baseline.md`, which `python3 reports/make_baseline.py`
generates from committed rollout logs (§ numbers refer to its sections). If this file and
baseline.md disagree, baseline.md wins and this file is stale.

## The short version for a buyer

1. **The reward is trustworthy.** The shipped set has 1464 v2 tasks. All 1464 score 0.0 when
   submitted faulted and 1.0 when the hidden golden is restored (§5). Every calibration rollout's
   oracle re-verified at 1.0. The red team ran 3500 scripted attack applications in its
   non-superseded runs and 148 agent/hand attempts, and found **0 hacks** (§9). Five earlier
   findings where the verifier passed something an EE would reject were all fixed in v2. What is
   still open: four low-severity information leaks (RT34–36, RT70), and 64 round-3 applications
   that timed out or errored, whose retry has not finished. "0 hacks" is bounded by what the red
   team tried. It is not a proof.
2. **v1 / normal tier is saturated. It is historical, not a selling point.** Haiku scored
   99/100, Sonnet 100/100 and Opus 50/50, and 0/50 tasks fell in the learnable band (§1). The
   normal tier is useful as a warm-up curriculum and a regression set. It does not tell current
   models apart.
3. **The hard tiers separate mid-tier agents from careful ones. They do not challenge the
   strongest one.**
   - On v2-hard, Sonnet scored 25/44 (57 %, CI 42–70) and on v2-hard_layout 7/36 (19 %,
     CI 10–35).
   - Opus scored 42/44 (95 %) and 38/40 (95 %).
   - Haiku scored 44/44 (100 %) on v2-hard. On hard_layout it stands at 19/26 (73 %), which is
     partial, not yet audited, and not final.
4. **What makes a task hard here is diligence, not raw capability.**
   - Every one of Sonnet's hard-tier failures (19/19 on hard, 29/29 on hard_layout) is invisible to
     `pcbtool check` (§3). They are rules the tool doesn't run (`rules`, `layout_rules`,
     hard-tier decoupling `layout`) or latent connectivity errors. All of them are stated in
     TASK.md or the datasheets.
   - Sonnet trusted the local checker and stopped. Haiku hand-verified the stated rules (many
     more tool calls, per `reports/calibration/v2hard/FINDINGS.md`; tool-call counts are not in
     the committed rollouts, so baseline.md does not report them) and beat Sonnet.
   - The one counter-signal is Haiku on hard_layout. 6 of its 7 failures so far were submitted
     with a pcbtool-*visible* failure, mostly DRC after hand-routing in `no_autoroute` mode (§3).
     That is the first sign of a capability limit (geometry and routing) rather than a diligence
     one, and it is worth watching as the Haiku data completes.
5. **G12 (best model's hard-tier pass rate within 10–70 %) is NOT met after three rounds** (§1):
   the pilot, v2-hard and v2-hard_layout. Each round added more latent faults, composite
   multi-rail boards, `no_autoroute`, and then geometric layout rules. Each round lowered
   Sonnet's pass rate, and Opus stayed at about 95 %.

## Diagnosis: why repair-against-stated-rules saturates

Every graded requirement in PCB-Repair is, by design, **fully stated and checkable from public
material**. That is what makes the reward equal correctness, and it is also what caps the
difficulty:

- The task is "find every violated, stated rule and fix it". For an agent that reads everything
  and computes every rule (decoupling copper paths, loop areas, Kelvin taps, abs-max at every DC
  operating point), the work is long but closed. Nothing has to be traded off, there is no
  ambiguity to resolve, and there is no search over a large design space.
- Adding more rules or more faults makes the task longer, not deeper. That lengthening punishes
  agents that stop early (Sonnet), not agents that are careful (Opus, and Haiku on v2-hard).
- Binary reward against a single golden also means the environment never asks for anything
  *better* than the reference. It only asks for "equal to the reference within the stated
  rules".

**This is still a legitimate RL target.** "Verify the requirements your tools don't check
before you submit" is a real and transferable behaviour. Mid-tier models fail it often: Sonnet
is at 57 % on v2-hard and 19 % on hard_layout. That is a learnable band with a clean,
unhackable reward. But it is a *diligence / verification-behaviour* environment. It is not a
frontier-capability benchmark, and it should not be sold as one.

## What would plausibly be frontier-hard (not built; each has risks)

| direction | why it could bite the best models | main risk |
|---|---|---|
| **Placement and routing quality, scored against a reference** (wirelength, via count, loop areas, layer usage, congestion, all relative to our router's or a stronger reference's result) | an optimisation target with no closed "done" state; spatial reasoning over 20–100+ parts | the reward becomes graded, not binary. The reference quality sets the ceiling, and a weak reference router (ours is a maze router, with no Freerouting here) makes the scale easy to beat. Metrics are gameable unless DRC, connectivity and rule gates stay hard gates |
| **Spec → circuit synthesis with many valid answers** (meet a stated spec with a parts library; graded by simulation and rules, not by matching a golden) | open design space; trade-offs among cost, part count, margin and tolerance | the verifier must accept every correct design. It needs adversarial hardening (the checker *is* the spec), and the red-team effort is much larger than for repair. Deferred to v2 in GOALS.md for exactly this reason |
| **Larger boards** (4-layer, 60–200 parts, multiple power domains) | long-horizon bookkeeping; context pressure; interacting faults | mostly lengthens tasks again (diligence, not depth). KiCad-7 DRC runtime and our router may not scale |
| **Real datasheet ambiguity** (real parts, real datasheets with conflicting or underspecified limits; engineer-judgement calls) | the agent must decide what the requirement *is*, not only check it | licensing and accuracy of real datasheets; the grading has to settle the ambiguity, so it needs EE adjudication per task (cost, and agreement under 100 %); "reward == correctness" gets weaker |
| **Tolerance / worst-case / Monte Carlo design** (pass across corners, not at nominal) | requires numerical reasoning and design margin, not lookup | simulation cost; behavioural SPICE models limit realism |

We have no measurement for any of these. They are hypotheses, and each needs its own
calibration round with the same discipline: oracle and gates, red team, and contamination
audit.

## Caveats (read before quoting any number)

- **One attempt per task per model in v2.** v1: two attempts for Haiku and Sonnet, one for
  Opus. There is no pass@k and no variance across seeds or runs.
- **Small samples:** about 40 tasks per tier. Wilson 95 % intervals are wide: Sonnet on v2-hard
  is 42–70 %. Family, fault-count and latent-type cells have n ≤ 17 and are descriptive only.
- **Haiku on hard_layout is partial** (26 of the planned 40). Its transcripts are not audited
  yet, so those rollouts are included in the rates but could still be excluded (§4).
- **Claude-family models only** (haiku / sonnet / opus aliases; served ids are recorded only for
  v2-hard: `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`, §6). No other vendors and
  no open-weights models.
- **effort = medium and one harness** (the same agent scaffold, prompt and tool set for all
  models). Results depend on the scaffold. A scaffold that auto-runs every rule would move
  Sonnet a lot.
- **Possible within-agent learning:** each calibration agent worked 2–3 tasks in sequence, so
  later tasks may benefit from earlier ones. This is not controlled.
- **Contamination:** 4 Sonnet hard_layout rollouts were excluded for touching repo paths (§4).
  The audit catches file access in actions. It does not catch knowledge that leaks through the
  prompt.
- **Generic parts, behavioural SPICE models, KiCad 7.0.11 file formats and DRC.** No signal or
  power integrity, EMI, thermal or DFM checks. The tasks are synthetic and procedurally generated.
- **Human EE sign-off (G9) is still pending.** The agent pre-screen (`qa/self_review.md`) found
  arguable value bounds (F1–F3) that were queued for fixing in v2. Until two EEs sign off, task
  fairness rests on agent review only.
