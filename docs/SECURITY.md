# Security model

## Threat model

The agent under evaluation is treated as **adversarial with respect to the reward**. It may try
to get reward 1 without repairing the design. It may read anything it can reach, write arbitrary
bytes into its files, plant symlinks, FIFOs or huge files, craft KiCad files that crash or confuse
the parser, or try to influence the grader through its environment (Python path, current working
directory, project files, rule files). We do not try to defend the host against a model that is
actively trying to escape a container. That is the container runtime's job, and the agent image
is set up to make it easy: non-root user, no network, dropped capabilities.

## Assets

1. `hidden/` for every task: the golden design and board and `meta.json` (faults, seeds, params,
   assertions). Reading any of these makes a task trivial.
2. The family generators (`pcbenv/families/`) and the fault injector (`pcbenv/faults*`). Together
   with a task's family and seed, they regenerate the golden.
3. The verifier's integrity: its code, its rules, and the data it trusts.
4. The holdout split. If its contents leak into training data, it is contaminated.

## Sandbox boundary

```
 host / orchestrator                         agent container (image target `agent`)
 ─────────────────────                       ──────────────────────────────────────
 tasks/<id>/public  ── copy ──────────────▶  /work  (TASK.md, design.json, board, spec.json, parts/)
 tasks/<id>/hidden  (never mounted)          pcbtool + the pcbenv modules it needs (read-only)
                                             user `agent`, --network none, --cap-drop ALL
 /submission  ◀── copy design.json, board.kicad_pcb only (regular files) ──
      │
      ▼
 grader container (image target `grader`)  or a host process: pcbenv.verify
   /task (ro, incl. hidden/), /submission (ro), --network none
```

- **The agent image** (`Dockerfile`, target `agent`) copies an explicit whitelist of modules:
  `board, boardnet, checks, design, drc, erc, golden, layout, parts, parts_lib, router, sim, tool`.
  It has no `families/`, no `faults*`, no `generate`, no tests, no tasks and no `.git`.
  `.dockerignore` also excludes `tasks/`, `dist/` and every `hidden/` directory from the build
  context. `docker/agent-entrypoint.sh` refuses to start (exit 3) if a `hidden/` directory is
  visible in `/work` or `/task_public`.
- **Grading happens outside the agent container**, either in the `grader` image
  (`docker/grade.sh`) or on the host. `docker/run_episode.sh` is the reference flow. The Inspect
  adapter does the same: the sandbox gets `Sample.files` (public files only), and the scorer reads
  the two deliverables back out and verifies them on the host.
- **`PcbRepairEnv` / `run_agent` / `examples/*` without Docker are NOT sandboxed.** Their `bash`
  tool runs on the host as the calling user and can read `hidden/`. Use them for scripted
  policies, debugging and trusted models only.

## What the verifier trusts

| Trusted | Not trusted |
|---|---|
| `task_dir/hidden/*` (golden design and board, meta.json) | everything in the workdir except the two deliverables |
| the `pcbenv` package and the KiCad library footprints installed on the grading host | the deliverables' content (validated, size-capped, parsed in a temp copy) |
| canonical DRC rules in `pcbenv/drc.py` | any `.kicad_pro`, `.kicad_dru`, fp-lib-table, or `*.py` next to the files |
| assertion stimuli and loads from `meta.json` | net names (graders compare partitions; SPICE node names are sanitised) |

Specific hardening in `verify.py` and its helpers:
- The deliverables are opened with `O_NOFOLLOW`, re-checked with `fstat` (same inode, still a
  regular file), read up to 5 MB, and copied to a fresh temp dir. Symlinks, FIFOs, devices and
  oversized files fail the `parse` gate.
- DRC runs on the temp copy next to the canonical `.kicad_pro` and `.kicad_dru` files, so no
  project or rules file in the workdir or the CWD applies. Numeric minimums are
  `max(canonical, golden)`.
- Footprint library lookups use only ids from the part's allowed list, never a path the agent
  chose.
- `verify_isolated` runs `python3 -I` (which ignores `PYTHON*` env vars and does not put the
  script dir or CWD on `sys.path`) in a fresh temp CWD with a timeout. A crashing or hanging
  KiCad parse becomes reward 0.
- `bin/pcbtool` runs `python3 -P`, so files in the agent's workdir cannot shadow `pcbenv`
  modules.
- Values are parsed by a strict regex before they reach the SPICE netlist, and net names are
  sanitised to `[A-Za-z0-9_]`. ngspice runs in a temp dir with a timeout.
- Task bundles are extracted with `pcbenv.api.extract_tasks`. It rejects absolute paths, `..`,
  symlinks, hardlinks, special files and members over 64 MB before writing anything, and then
  extracts with tarfile's `data` filter.

## Residual risks and operator responsibilities

- **Known gaps in coverage and isolation:**
  - Reward hacking is assessed by the red team (G5, `redteam/`). This document describes the
    design, not a proof.
  - KiCad's file parser is a large C++ attack surface. We isolate it in a subprocess, but we do
    not sandbox the grader process itself beyond `--network none` in the grader image.
- **What you must do as the operator:**
  - Keep `hidden/` and the holdout split out of any storage the agent or a training pipeline can
    read.
  - Do not give the agent container network access. With network access it could fetch this
    repository, including the generators.
  - Keep the generation secret `tasks/.secret` and the private manifests `tasks/private/` private
    (both git-ignored). v2 task ids are opaque (`pcbr2-<tier>-<hmac8>`) and generator seeds are
    HMAC(secret, index), so an id or a public manifest row that reaches a policy does not let it
    regenerate the golden with the open-source generators (RT37). Whoever holds the secret can.
  - Record the image digest, `pcbenv` version and task-set version with every result (see
    VERSIONING.md).
