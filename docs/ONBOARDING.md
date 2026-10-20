# Onboarding check (G8): README dry run

The README is checked by executing it rather than by reading it. `examples/readme_dryrun.py` does the following:

1. Copies the working tree into a fresh directory. It leaves out `.git`, `runs/` and the generated
   task dirs, so the copy looks like a clone plus `dist/`.
2. Runs every line of every bash block in `README.md` in order, in one bash session, from the repo root.
3. Saves the "custom policy" Python block as `my_policy.py` and runs it.
4. Runs the "Python API" block.
5. Times each command and checks that each exit code is the one the README documents.

```bash
python3 examples/readme_dryrun.py --dest /tmp/readme_dryrun        # add --include-full-tests for the ~15 min suite
```

Two commands are skipped by design:

- The Inspect command needs `pip install inspect-ai` and a Docker daemon. The README marks it as optional.
- The full test suite (`python3 -m pytest -q tests/`, about 15 min) runs only with `--include-full-tests`.

## Last measured run

The host had 4 cores and a load average of about 0.5–2.5, with other agents running.

| Step | Command | Exit | Seconds |
|---|---|---|---|
| 0 | preflight (`import pcbnew, numpy, yaml`; ngspice) | 0 | 0.2 |
| 1 | `export PATH=...` | 0 | 0.0 |
| 1 | `api extract ...-normal.tar.gz data` (655 tasks) | 0 | 3.7 |
| 1 | `api extract ...-hard.tar.gz data` (362 tasks) | 0 | 4.0 |
| 1 | `api splits data` | 0 | 0.2 |
| 2 | `api list data --split v2/normal \| head -3` | 0 | 0.2 |
| 2 | `api list data --split v2/hard \| head -3` | 0 | 0.2 |
| 3 | `demo_policy.py --make-demo ...` (reward 1) | 0 | 2.0 |
| 3 | `demo_policy.py --tasks data --split v2/normal --split v2/hard --limit 10 --workers 4` (20 tasks, mean reward 0.05) | 0 | 12.4 |
| 4 | `T=$(... list --split v2/normal --json \| head -1 ...)` | 0 | 0.2 |
| 4 | `rm -rf runs/work && mkdir -p runs/work && cp -r "$T/public/." runs/work/` | 0 | 0.0 |
| 4 | `(cd runs/work && pcbtool check)` (faulty task) | 1 | 0.6 |
| 4 | `api verify runs/work "$T"` (reward 0) | 1 | 0.6 |
| 5 | `jsonl export --split v2/normal` (655 rows) | 0 | 0.9 |
| 5 | `jsonl predict-unchanged --limit 5` | 0 | 0.2 |
| 5 | `jsonl score --workers 4` | 0 | 1.4 |
| 6 | fast tests (4 files, 80 tests) | 0 | 27.1 |
| – | custom policy (`my_policy.py`) | 0 | 0.9 |
| – | Python API block | 0 | 2.0 |
| | **Total (copy + all commands)** | | **57.2** |

The demo policy's 20-task step finished in 12–17 s across three runs. Each episode is capped by
`--max-seconds` (default 20 s) and by at most 20 simulations. Before this change, the
exhaustive E24/E96 search took 160–190 s on some normal tasks and up to 26 min on a hard task.
