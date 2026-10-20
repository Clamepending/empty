#!/usr/bin/env python3
"""Execute README.md top to bottom in a fresh copy of the repo and time every command (G8 check).

    python3 examples/readme_dryrun.py --dest /tmp/readme_dryrun [--include-full-tests]

What it does:
- copies the working tree to DEST/repo (no .git, runs/, generated task dirs: like a fresh clone
  plus the dist/ bundles);
- runs every line of every ```bash block in README.md in ONE bash session (so `export` and `T=...`
  carry over), in README order, from the repo root; `\\`-continued lines are joined;
- writes the ```python block that README says to save as `my_policy.py`, runs it, and runs the
  "Python API" block with `python3 -`;
- skips the optional Inspect command (needs network + Docker) and, unless --include-full-tests,
  the ~15 min full test suite;
- prints one line per command: exit code, seconds, command; then the total.
Exit status 0 iff every command exited with its documented status (0, or 1 where the README
says `exit 1`).
"""
from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE = ["./.git", "./runs", "./data", "./work", "./tasks/v2/*/pcbr2-*", "./tasks/private", "./tasks/refresh-v2",
           "./redteam/_tasks", "*/__pycache__", "./.pytest_cache", "./*.egg-info", "./.venv"]


def blocks(md: str) -> list[tuple[str, str, str]]:
    """[(lang, body, preceding text)] for fenced code blocks."""
    out, pos = [], 0
    for m in re.finditer(r"^```(\w*)\n(.*?)^```", md, re.S | re.M):
        out.append((m.group(1), m.group(2), md[pos:m.start()]))
        pos = m.end()
    return out


def commands(body: str) -> list[str]:
    cmds, cur = [], ""
    for line in body.splitlines():
        if not cur and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if line.rstrip().endswith("\\"):
            cur += line.rstrip()[:-1] + " "
            continue
        cmds.append((cur + line).strip())
        cur = ""
    return cmds


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--include-full-tests", action="store_true")
    a = ap.parse_args(argv)
    dest = Path(a.dest).resolve()
    if dest.exists():
        shutil.rmtree(dest)
    repo = dest / "repo"
    repo.mkdir(parents=True)
    t0 = time.monotonic()
    ex = " ".join(f"--exclude={shlex.quote(e)}" for e in EXCLUDE)
    subprocess.run(f"tar cf - {ex} . | tar xf - -C {shlex.quote(str(repo))}", shell=True, cwd=ROOT, check=True)
    copy_s = time.monotonic() - t0

    md = (repo / "README.md").read_text(encoding="utf-8")
    script = ["set -u", "cd " + shlex.quote(str(repo))]
    plan: list[tuple[str, int]] = []   # (label, expected exit code)
    n = 0

    def add(cmd: str, label: str, expect: int = 0) -> None:
        nonlocal n
        n += 1
        plan.append((label, expect))
        script.append(f"__s=$(date +%s.%N); {{ {cmd}\n}}; __rc=$?; "
                      f"echo \"@@DRYRUN {n} rc=$__rc s=$(awk -v a=$__s -v b=$(date +%s.%N) 'BEGIN{{printf \"%.2f\", b-a}}')\" >&2")

    for lang, body, before in blocks(md):
        if lang == "bash":
            for c in commands(body):
                if c.startswith("inspect eval"):
                    plan.append((f"SKIPPED (optional, needs inspect-ai + Docker): {c}", -1))
                    continue
                if c.split("#", 1)[0].strip() == "python3 -m pytest -q tests/" and not a.include_full_tests:
                    plan.append((f"SKIPPED (full suite, ~15 min; --include-full-tests): {c}", -1))
                    continue
                expect = 1 if "exit 1" in c.split("#", 1)[-1] and "#" in c else 0
                add(c, c, expect)
        elif lang == "python" and "my_policy.py" in before[-400:]:
            (repo / "my_policy.py").write_text(body, encoding="utf-8")
            add("python3 my_policy.py", "python3 my_policy.py  (README custom-policy block)")
        elif lang == "python" and "from pcbenv import api" in body:
            (repo / "_readme_api.py").write_text(body, encoding="utf-8")
            add("python3 _readme_api.py", "python3 <README 'Python API' block>")
    (dest / "readme.sh").write_text("\n".join(script) + "\n", encoding="utf-8")

    t1 = time.monotonic()
    with open(dest / "stdout.txt", "w") as fo, open(dest / "stderr.txt", "w") as fe:  # live logs
        subprocess.run(["bash", str(dest / "readme.sh")], stdout=fo, stderr=fe)
    run_s = time.monotonic() - t1
    err = (dest / "stderr.txt").read_text(encoding="utf-8", errors="replace")
    res = {int(m.group(1)): (int(m.group(2)), float(m.group(3)))
           for m in re.finditer(r"^@@DRYRUN (\d+) rc=(-?\d+) s=([\d.]+)", err, re.M)}
    ok, i = True, 0
    print(f"copy repo: {copy_s:.1f}s")
    for label, expect in plan:
        if expect < 0:
            print(f"   -      -   {label}")
            continue
        i += 1
        rc, s = res.get(i, (None, 0.0))
        good = rc == expect
        ok &= good
        print(f"{'ok ' if good else 'BAD'} rc={rc!s:>3} {s:7.1f}s  {label[:150]}")
    print(f"total wall-clock (copy + commands): {copy_s + run_s:.1f}s; logs in {dest}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
