# PCB-Repair pilot proposal (2–4 weeks)

> **Founder-owned (G11).** The structure below was drafted by agents. Price, data rights,
> exclusivity, licence and every contractual term are **[FOUNDER]** decisions, and legal review
> is needed before anything is signed. Numbers come from `reports/baseline.md` (§ = its
> sections).

## Goal

Let [LAB] decide, using its own models and harness, whether PCB-Repair gives (a) a trustworthy
reward and (b) a useful learning signal for agentic engineering work.

## Scope options (pick one)

| option | duration | what [LAB] gets |
|---|---|---|
| **Eval pilot** | 2 weeks | the hard + hard_layout tiers (train splits) and a fresh refresh batch of [FOUNDER: N] hard tasks generated for the pilot and never used elsewhere; we run or support [LAB]'s models at [LAB]'s chosen settings; a calibration report in the baseline.md format |
| **Training pilot** | 4 weeks | the above, plus normal + hard train splits for RL / fine-tuning; [LAB] trains and we grade on held-out tasks (our holdout, plus the fresh batch) before and after |

## Deliverables (from us)

1. Task bundles (`dist/`) with sha256s, the verifier and `pcbtool` pinned at one version
   (`docs/VERSIONING.md`), and the adapters (Inspect / JSONL / gym-like).
2. A fresh, deduplicated refresh batch generated from a new secret for the pilot (holdout
   policy below).
3. Onboarding support. The README quickstart takes minutes; a fresh agent completed it twice
   (`scorecard/STATUS.md` G8).
4. A graded report for [LAB]'s rollouts: pass rates with Wilson intervals, breakdowns by
   family, fault count, tool mode and latent fault type, a failure taxonomy, and a contamination
   audit, all produced by the same generator as `reports/baseline.md`.
5. A red-team summary for the pinned verifier version (`redteam/exploits.md`) and a promise to
   disclose any reward hack found during the pilot within [FOUNDER: N] business days.

## Acceptance criteria (proposed; both sides agree before kickoff)

| # | criterion | how it is checked |
|---|---|---|
| A1 | Reward integrity: oracle repair = 1.0 and faulted = 0.0 on every pilot task | re-verification log over the full pilot set (as in §5) |
| A2 | Determinism: the same files give the same reward on rerun | rerun of a random sample at [LAB]; any mismatch is a P0 for us |
| A3 | No known reward hacks against the pinned verifier | [LAB]'s own adversarial attempts and our red-team suite; any hack is fixed and re-released, or the affected tasks are withdrawn |
| A4 | Integration: [LAB] runs N tasks end to end in its harness within [FOUNDER: days] | [LAB] confirms |
| A5 | Signal (training pilot only): the held-out pass rate moves after training, measured with Wilson intervals | before/after report; **no promise of a specific gain** |

We do **not** propose "best model scores X %" as an acceptance criterion. Our own data shows the
strongest Claude model at about 95 % on the hard tiers (§1). A pilot can tell whether this holds
for [LAB]'s models.

## Holdout and contamination policy

- The holdout splits (20 % per tier) and any pilot-fresh batch are graded by us. [LAB] receives
  the public files only, unless the founder decides otherwise.
- Hidden goldens and the generation secret are never shipped to [LAB] for held-out tasks.
- We audit the transcripts we grade for file-access contamination (§4 shows the audit rule).

## Data rights and exclusivity: options for the founder

| option | description | trade-off |
|---|---|---|
| R1 non-exclusive eval licence | [LAB] may use the tasks internally for evaluation only | simplest; lowest price |
| R2 non-exclusive training licence | internal training and evaluation; no redistribution | standard; [FOUNDER: price] |
| R3 time-limited exclusivity on a fresh batch | [LAB] gets a refresh batch no one else receives for [FOUNDER: months] | refresh is cheap for us, so this can be priced per batch |
| R4 full exclusivity on a tier | the tier is withdrawn from other buyers | limits future sales; price accordingly |

All options: **[FOUNDER: licence text]**. The KiCad footprint licence (CC-BY-SA 4.0 with the
KiCad library exception) must be confirmed by counsel (`docs/DATA_CARD.md`).

## Price and timeline

- Price: **[FOUNDER: price]** (eval pilot) / **[FOUNDER: price]** (training pilot).
- Start: [FOUNDER: date]. Weekly check-ins; final report at the end of week 2 or 4.

## Known limitations we will state in the contract

Synthetic generic parts; behavioural SPICE models; KiCad 7 formats; no SI/PI, EMI, thermal or
DFM checks; calibration of Claude models only; human EE sign-off of task fairness still pending
(G9). See `gtm/FAQ.md` and `reports/INTERPRETATION.md`.
