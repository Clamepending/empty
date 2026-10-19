# Scorecard status

Updated by the orchestrator after re-running each acceptance command itself.

| Goal | Status | Evidence |
|---|---|---|
| G0 orchestrator | in progress | — |
| G1 circuits | ✅ verified | `pytest tests/test_families.py tests/test_sim.py` → 84 passed (19 s) |
| G2 board | ✅ verified | `pytest tests/` → 209 passed (46 s); 400-board stress run DRC-clean |
| G3 verifier/harness | ✅ verified | `pytest tests/` → 472 passed; verify median 0.54 s, p99 0.65 s |
| G4 faults + tasks | ✅ verified | 818 tasks (654 train/164 holdout), 19 fault types, 100 % valid/detected; orchestrator spot-check 30/30 faulted=0, restored=1; invisible share 81 %; 577 tests pass |
| G5 red team | 🟡 round 2 done; round 3 on v2 pending | round 1+2: 3200 scripted + 124 agent attempts, 0 hacks; open expert-disagrees/leaks RT30–RT37, RT59 → being fixed in v2 integration |
| G6 calibration | ❌ measured, threshold FAILED on v1 | 250 attempts graded by verifier, 0 contaminated: haiku 99 %, sonnet 100 %, opus 100 %; 0/50 tasks in 10–70 % band (need ≥40 %). v1 saturated → G12 hard tier |
| G7 baseline report | ⏳ blocked on G6 | — |
| G8 packaging | 🟡 part 1 verified (19 adapter tests); onboarding test pending | Docker build blocked by Docker Hub 429 |
| G9 QA packets | 🟡 packets ✅, human sign-off pending (founder) | 100 packets in qa/; agent pre-screen found F1 (pull-up bounds tighter than datasheet), F3/F4 prompt text bugs, F5 unenforced 1206 rule → queued for v2 fix |
| G10 refresh engine | ✅ verified | refresh run seeds 100000+: 118 new gated, deduped tasks |
| G12 hard tier | 🔄 v2 integration + regeneration running | A ✅ (rules, 9 latent types, 91 tests); B ✅ (sim convergence P0 fix, bounds audit, 4 composite families; full suite 900 passed). Pilot: sonnet 75 %, opus 100 % → not yet in band |
| G11 buyer signal | founder-owned | — |
