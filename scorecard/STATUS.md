# Scorecard status

Updated by the orchestrator after re-running each acceptance command itself.

| Goal | Status | Evidence |
|---|---|---|
| G0 orchestrator | in progress | — |
| G1 circuits | ✅ verified | `pytest tests/test_families.py tests/test_sim.py` → 84 passed (19 s) |
| G2 board | ✅ verified | `pytest tests/` → 209 passed (46 s); 400-board stress run DRC-clean |
| G3 verifier/harness | ✅ verified | `pytest tests/` → 472 passed; verify median 0.54 s, p99 0.65 s |
| G4 faults + tasks | ✅ verified (v2.1) | 1721 tasks (normal 655+164, hard 370+92, hard_layout 153+39, refresh 248); recheck 1721/1721 faulted=0 oracle=1; orchestrator spot check 40/40 |
| G5 red team | ✅ verified | 3 rounds: >5,700 scripted attack applications + >170 hand attempts, 0 hacks; all expert-disagrees/leak findings fixed (RT70/RT76 in v2.1); 132/132 redteam tests pass |
| G6 calibration | ❌ v1 saturated; superseded by G12 | v1: 0/50 in band. v2 hard: sonnet 57 % in band, best model 100 % |
| G7 baseline report | ✅ verified | `python3 reports/make_baseline.py --check` reproduces exactly from committed rollouts; reports/INTERPRETATION.md |
| G8 packaging | ✅ verified | onboarding passes C (1.7 min) and D (2.8 min) back-to-back from README only, no code reading, 20 tasks each incl. hard tier + custom policy; earlier A/B failures fixed (split aliasing, bounded demo, docs) |
| G9 QA packets | 🟡 v2 packets ✅ (100, 60/25/15 tiers); pre-screen F1–F5 fixed in v2.1; **human EE sign-off pending (founder)** | qa/INDEX.md, qa/self_review_v2.md |
| G10 refresh engine | ✅ verified | refresh run seeds 100000+: 118 new gated, deduped tasks |
| G12 hard tier | ❌ not met after 3 rounds (documented) | v2 hard: haiku 100 %, sonnet 57 % (63 % of its failures fixed at effort=high), opus 95 %; hard_layout: haiku 74 %, sonnet 19 %, opus 95 %. Repair against fully-stated rules saturates for careful agents; frontier-hard needs open-ended design tasks (reports/INTERPRETATION.md) |
| G11 buyer signal | 🟡 materials ready (gtm/), sending/pricing/licence = founder | — |

Latest full verification (v2.1): 1134 tests pass incl. red team — reports/v2/orchestrator_test_run_v21.txt. Calibration regraded under the v2.1 verifier: 0 verdict changes.
