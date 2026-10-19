# Scorecard status

Updated by the orchestrator after re-running each acceptance command itself.

| Goal | Status | Evidence |
|---|---|---|
| G0 orchestrator | in progress | — |
| G1 circuits | ✅ verified | `pytest tests/test_families.py tests/test_sim.py` → 84 passed (19 s) |
| G2 board | ✅ verified | `pytest tests/` → 209 passed (46 s); 400-board stress run DRC-clean |
| G3 verifier/harness | ✅ verified | `pytest tests/` → 472 passed; verify median 0.54 s, p99 0.65 s |
| G4 faults + tasks | ✅ verified | 818 tasks (654 train/164 holdout), 19 fault types, 100 % valid/detected; orchestrator spot-check 30/30 faulted=0, restored=1; invisible share 81 %; 577 tests pass |
| G5 red team | 🔄 round 2 on shipped tasks | round 1: 1000 scripted + 96 agent attempts, 0 hacks; RT01 (expert-disagrees) fixed via value bounds |
| G6 calibration | 🔄 250 attempts running (haiku×2, sonnet×2, opus×1 on 50-task stratified sample) | — |
| G7 baseline report | ⏳ blocked on G6 | — |
| G8 packaging | 🟡 part 1 verified (19 adapter tests); onboarding test pending | Docker build blocked by Docker Hub 429 |
| G9 QA packets | ⏳ blocked on G4 (human sign-off = founder) | — |
| G10 refresh engine | ✅ verified | refresh run seeds 100000+: 118 new gated, deduped tasks |
| G11 buyer signal | founder-owned | — |
