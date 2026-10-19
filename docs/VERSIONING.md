# Versioning

Three things carry versions. Every result must record all three, plus the container image digest
when Docker is used.

| Artifact | Version string | Where |
|---|---|---|
| Python package / verifier | `pcb-repair X.Y.Z` (semver) | `pyproject.toml` |
| Task set | `tasks-vMAJOR.MINOR` | bundle name in `dist/` and the manifest header or rows |
| Design / meta schema | `pcbenv/design@1` | `design.json` `schema` field |

## Package and verifier (semver)

- **MAJOR:** any change that can change the reward of any released task for any input. That
  includes a new gate or check, a tightened rule, a changed tolerance, or a different
  DRC/SPICE engine version. Before release, rerun all goldens (every one must score 1.0) and the
  red-team regression suite, and publish a reward diff on the released task sets.
- **MINOR:** new adapters, new pcbtool commands, new families or fault types used only by *new*
  task sets, and new optional API. Rewards on released tasks must not change; CI checks this by
  re-verifying a fixed corpus of goldens and recorded submissions.
- **PATCH:** bug fixes that do not change rewards on that same corpus, plus docs and performance.
- **The stable API** is `pcbenv.api.__all__`, the adapters' documented functions, the
  `pcbtool` CLI, and the JSONL formats. Anything else may change in a MINOR release.

## Task sets

- **Released tasks never change.** A task's files are frozen at release, and its id is never
  reused. A buggy task is *withdrawn*: it is listed in the next release's manifest as
  `withdrawn` with a reason, and it is not edited.
- **Each release pins the verifier** major version it was validated with. A verifier MAJOR bump
  triggers a new task-set MINOR (same tasks, re-validated) or MAJOR (tasks changed or withdrawn).
- **We recommend that the manifest carry a sha256 for each public and hidden file**, so that
  consumers can detect modified copies.
- **Generation is deterministic.** `generate --seed N` with the same package version produces
  byte-identical tasks.

## Holdout policy

- **Size:** 20 % of each release is `holdout` (`thresholds.yaml: tasks.holdout_share`).
- **Hidden data is never redistributed.** Holdout tasks are graded only by the maintainers or
  inside a grader the evaluated party cannot read. Their `hidden/` dirs are never shipped in a
  public bundle, and their public files should not be used for training.
- **No training on holdout.** Holdout results are reported separately from train results.
  Repeated tuning against holdout scores counts as contamination; use a fresh refresh-engine
  batch instead.
- **Rotation:** when a holdout set may be contaminated (published, leaked, or used for model
  selection too many times), it is retired to `train` in the next release, and a fresh holdout is
  generated with new seeds and deduplicated against all shipped tasks.
