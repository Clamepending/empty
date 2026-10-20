"""Generate reports/baseline.md (G7) from committed inputs only. No hand-typed numbers.

  python3 reports/make_baseline.py           # (re)write reports/baseline.md
  python3 reports/make_baseline.py --check   # regenerate in memory, diff against the file, exit 1 on drift

Inputs (all read-only): graded rollouts under reports/calibration/, tasks/manifest.jsonl, the v1
manifest from git history (commit V1_MANIFEST_COMMIT), thresholds.yaml, reports/v2/*.{jsonl,txt},
reports/calibration/v2hard/FINDINGS.md (served model ids), redteam/runs/* and redteam/exploits.md.
Output is a pure function of those bytes: no timestamps, no randomness, every table sorted.
"""
from __future__ import annotations

import argparse
import collections
import difflib
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "baseline.md"
CMD = "python3 reports/make_baseline.py && python3 reports/make_baseline.py --check"
V1_MANIFEST_COMMIT = "b1a1255"  # "G4+G10: 19 fault types, 818 gated tasks": last commit with the v1 manifest
MODELS = ("haiku", "sonnet", "opus")
Z = 1.959964  # 95 % two-sided

TIERS = [
    # key, label, rollouts file, manifest source
    ("v1", "v1-normal (historical, v1 task set)", "reports/calibration/rollouts.jsonl", "v1"),
    ("hard", "v2-hard", "reports/calibration/v2hard/rollouts.jsonl", "v2"),
    ("hard_layout", "v2-hard_layout", "reports/calibration/v2hard_layout/rollouts.jsonl", "v2"),
]
# Checks pcbtool reports locally (`pcbtool check`: consistency, drc, erc, spec sim, value_bounds, layout).
# In the hard tiers the decoupling rules are moved out of spec.json:decoupling, so `layout` there is
# mostly a rule pcbtool does not run (power widths are still checked locally).
TOOL_VISIBLE = {"consistency", "drc", "erc", "spec", "values"}
GATES = {"parse", "components", "integrity"}
UNRUN_RULES = {"rules", "layout_rules"}

_inputs: dict[str, str] = {}


# ------------------------------------------------------------------ input helpers
def _read(rel: str) -> str:
    p = ROOT / rel
    data = p.read_bytes()
    _inputs[rel] = hashlib.sha256(data).hexdigest()[:16]
    return data.decode()


def _read_git(commit: str, rel: str) -> str:
    out = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{rel}"], capture_output=True, check=True).stdout
    _inputs[f"git {commit}:{rel}"] = hashlib.sha256(out).hexdigest()[:16]
    return out.decode()


def _jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / den
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def pct(x: float) -> str:
    return f"{100 * x:.0f} %"


def cell(k: int, n: int, ci: bool = False) -> str:
    if n == 0:
        return "–"
    s = f"{k}/{n} ({pct(k / n)})"
    if ci:
        lo, hi = wilson(k, n)
        s += f" [{100 * lo:.0f}–{100 * hi:.0f}]"
    return s


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out + [""]


# ------------------------------------------------------------------ loading
def load():
    v2 = {r["id"]: r for r in _jsonl(_read("tasks/manifest.jsonl"))}
    v1 = {r["id"]: r for r in _jsonl(_read_git(V1_MANIFEST_COMMIT, "tasks/manifest.jsonl"))}
    roll = {}
    for key, _, path, src in TIERS:
        rows = _jsonl(_read(path))
        man = v1 if src == "v1" else v2
        for r in rows:
            r["_m"] = man.get(r["task_id"], {})
        roll[key] = sorted(rows, key=lambda r: (r["job"], r.get("attempt", 0)))
    return v1, v2, roll


def clean(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("contaminated") is not True]


def is_pass(r: dict) -> bool:
    return r["reward"] == 1.0


# ------------------------------------------------------------------ sections
def sec_headline(roll, thr) -> list[str]:
    band = thr["tasks"]["learnable_band"]
    L = ["## 1. Pass rates per tier × model", "",
         "One graded attempt per (task, model) unless stated; reward is binary (1 = every gate and check passes). "
         "`k/n (rate) [Wilson 95 % interval]`. Contaminated rollouts (transcript audit found repo/hidden-file "
         "access) are excluded; rollouts whose transcripts have not been audited yet are included and counted "
         "in the *unaudited* column.", ""]
    rows = []
    for key, label, _, _ in TIERS:
        for m in MODELS:
            rs = [r for r in roll[key] if r["model"] == m]
            if not rs:
                continue
            c = clean(rs)
            k = sum(map(is_pass, c))
            unaud = sum(1 for r in c if r.get("audited") is not True)
            tasks = len({r["task_id"] for r in rs})
            rows.append([label, m, len(rs), tasks, len(rs) - len(c), unaud, cell(k, len(c), ci=True)])
    L += table(["tier", "model", "graded", "distinct tasks", "excluded (contaminated)", "unaudited (included)",
                "pass [95 % CI]"], rows)
    att = collections.Counter((r["model"], r.get("attempt", 0)) for r in roll["v1"])
    L.append("v1 attempts per task: " + ", ".join(
        f"{m} {1 + max(a for (mm, a) in att if mm == m)}" for m in MODELS if any(mm == m for mm, _ in att)) + ".")
    L.append("")
    # learnable band (G6 / G12)
    L += ["### Learnable band and G12", "",
          f"Band from `thresholds.yaml`: {pct(band[0])}–{pct(band[1])}. G12 needs the *best* model's hard-tier pass "
          f"rate inside `frontier.hard_tier_best_model_pass_band` on ≥ {thr['frontier']['hard_tier_sample_min']} tasks.", ""]
    fb = thr["frontier"]["hard_tier_best_model_pass_band"]
    rows = []
    for key, label, _, _ in TIERS:
        rates = {}
        for m in MODELS:
            c = clean([r for r in roll[key] if r["model"] == m])
            if c:
                rates[m] = (sum(map(is_pass, c)), len(c))
        in_band = [m for m, (k, n) in rates.items() if band[0] <= k / n <= band[1]]
        best = max(rates, key=lambda m: (rates[m][0] / rates[m][1], rates[m][1]))
        bk, bn = rates[best]
        g12 = "n/a (not a hard tier)" if key == "v1" else (
            ("MET" if fb[0] <= bk / bn <= fb[1] else "NOT MET") + (
                "" if bn >= thr["frontier"]["hard_tier_sample_min"] else f" (best model n={bn} < sample min)"))
        # pooled per-task pass rate over all clean attempts of all models
        per_task = collections.defaultdict(list)
        for r in clean(roll[key]):
            per_task[r["task_id"]].append(is_pass(r))
        pooled = sum(1 for v in per_task.values() if band[0] <= sum(v) / len(v) <= band[1])
        rows.append([label, ", ".join(in_band) or "none", f"{best} {cell(bk, bn)}", g12,
                     f"{pooled}/{len(per_task)} ({pct(pooled / len(per_task))})"])
    L += table(["tier", "models with pass rate in band", "best model", "G12 verdict (best model in band)",
                "tasks with pooled pass rate in band"], rows)
    L += ["Pooled = all clean attempts of all models on that task (1–5 attempts per task), as in "
          "`reports/calibration/summary_v1.md`. With one attempt per model, per-model per-task rates are 0 or 1, "
          "so G6's per-model task band cannot be measured from these samples; the pooled column mixes models "
          "of very different diligence and should not be read as task difficulty.", ""]
    return L


def _group_table(rows: list[dict], keyfn, title: str) -> list[str]:
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in clean(rows):
        acc[keyfn(r)][r["model"]].append(is_pass(r))
    present = [m for m in MODELS if any(m in d for d in acc.values())]
    out = []
    for g in sorted(acc, key=lambda x: (str(type(x)), x)):
        out.append([g] + [cell(sum(acc[g][m]), len(acc[g][m])) for m in present])
    return [f"**{title}**", ""] + table(["group"] + present, out)


def sec_breakdowns(roll) -> list[str]:
    L = ["## 2. Breakdowns (clean rollouts)", "",
         "Cells are `k/n (rate)`; most cells have n ≤ 10, so read them as descriptive, not significant.", ""]
    for key, label, _, _ in TIERS:
        rows = roll[key]
        L += [f"### {label}", ""]
        L += _group_table(rows, lambda r: r["_m"].get("family", "?"), "By family")
        L += _group_table(rows, lambda r: r["_m"].get("n_faults", "?"), "By number of injected faults")
        L += _group_table(rows, lambda r: r["_m"].get("hint_level", "?"), "By hint level")
        if key != "v1":
            L += _group_table(rows, lambda r: r["_m"].get("tools_mode", "?"), "By tool mode")
            L += _latent_type_table(rows)
    return L


def _latent_type_table(rows: list[dict]) -> list[str]:
    acc = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in clean(rows):
        for t in sorted({f["type"] for f in r["_m"].get("faults", []) if f.get("latent")}):
            acc[t][r["model"]].append(is_pass(r))
    present = [m for m in MODELS if any(m in d for d in acc.values())]
    out = [[t] + [cell(sum(acc[t][m]), len(acc[t][m])) for m in present] for t in sorted(acc)]
    return ["**By latent fault type present in the task** (a task counts once per latent type it contains)", ""] + \
        table(["latent fault type"] + present, out)


def _bucket(failed: set[str], tier: str) -> str:
    visible = TOOL_VISIBLE | ({"layout"} if tier == "v1" else set())
    unrun = UNRUN_RULES | ({"layout"} if tier != "v1" else set())
    if failed & GATES:
        return "gate failure (parse/components/integrity)"
    if failed & visible:
        return "submitted with a pcbtool-visible failure"
    if "topology" in failed:
        return "latent connectivity left (topology only + unrun rules)"
    if failed and failed <= unrun:
        return "only rules pcbtool does not run"
    return "other"


def sec_taxonomy(roll) -> list[str]:
    L = ["## 3. Failure taxonomy (clean failed rollouts)", "",
         "Which gates/checks fail, per model. `pcbtool check` runs consistency, DRC, ERC, the spec simulation, "
         "value bounds and layout locally; it never runs `rules` (datasheet design rules), `layout_rules` "
         "(board-geometry rules) or `topology` (comparison with the hidden golden), and in the hard tiers the "
         "decoupling-path part of `layout` is stated in TASK.md but not run by pcbtool. Buckets (first match wins): "
         "gate failure → any pcbtool-visible check failed → topology failed → only unrun rules failed.", ""]
    for key, label, _, _ in TIERS:
        c = clean(roll[key])
        present = [m for m in MODELS if any(r["model"] == m for r in c)]
        checks = sorted({f for r in c for f in r["failed"]})
        L += [f"### {label}", ""]
        fails = {m: [r for r in c if r["model"] == m and not is_pass(r)] for m in present}
        rows = [["failed rollouts"] + [f"{len(fails[m])}/{sum(r['model'] == m for r in c)}" for m in present]]
        for ch in checks:
            rows.append([f"`{ch}` failed"] + [str(sum(ch in r["failed"] for r in fails[m])) for m in present])
        L += table(["check"] + present, rows)
        buckets = sorted({_bucket(set(r["failed"]), key) for m in present for r in fails[m]})
        rows = [[b] + [str(sum(_bucket(set(r["failed"]), key) == b for r in fails[m])) for m in present] for b in buckets]
        if rows:
            L += ["**Diligence buckets** (failed rollouts per model)", ""] + table(["bucket"] + present, rows)
        # diligence share: fraction of failures that a local pcbtool run would NOT have revealed
        blind = {m: sum(_bucket(set(r["failed"]), key) in (
            "only rules pcbtool does not run", "latent connectivity left (topology only + unrun rules)")
            for r in fails[m]) for m in present}
        L.append("Failures invisible to `pcbtool check` (latent connectivity or unrun rules): " + ", ".join(
            f"{m} {cell(blind[m], len(fails[m]))}" for m in present if fails[m]) + ".")
        L.append("")
    return L


def sec_contamination(roll) -> list[str]:
    L = ["## 4. Contamination exclusions", "",
         "A rollout is excluded when the transcript audit (`reports/calibration/grade.py:audit`) finds an action "
         "touching the repository, hidden task files or other workdirs. Reason = text before the first ':' of the "
         "first recorded violation.", ""]
    rows = []
    for key, label, _, _ in TIERS:
        for r in roll[key]:
            if r.get("contaminated") is True:
                reason = (r.get("violations") or ["?"])[0].split(":")[0]
                rows.append([label, r["job"], r["model"], r["task_id"], r["reward"], reason])
    L += table(["tier", "job", "model", "task", "reward (excluded)", "reason"], rows) if rows else ["none", ""]
    rows = []
    for key, label, _, _ in TIERS:
        n = len(roll[key])
        aud = sum(r.get("audited") is True for r in roll[key])
        con = sum(r.get("contaminated") is True for r in roll[key])
        rows.append([label, n, aud, n - aud, con])
    L += ["Audit coverage:", ""] + table(["tier", "graded", "audited", "not yet audited", "contaminated"], rows)
    return L


def sec_oracle(roll) -> list[str]:
    L = ["## 5. Oracle and gate controls", ""]
    rows = []
    for key, label, _, _ in TIERS:
        rs = roll[key]
        have = [r for r in rs if "oracle" in r]
        tasks = {r["task_id"]: r["_m"] for r in rs}
        g = [m.get("gates", {}) for m in tasks.values()]
        rows.append([label, f"{sum(r['oracle'] == 1.0 for r in have)}/{len(have)}" if have else "not recorded",
                     f"{sum(x.get('golden') == 1.0 for x in g)}/{len(g)}",
                     f"{sum(x.get('faulted') == 0.0 for x in g)}/{len(g)}",
                     f"{sum(x.get('oracle_repair') == 1.0 for x in g)}/{len(g)}"])
    L += ["Calibration samples (oracle = golden files restored into the agent's workdir and re-verified at grading "
          "time; manifest gates = recorded at generation time):", ""]
    L += table(["tier", "oracle 1.0 at grading (rollouts)", "manifest golden 1.0", "manifest faulted 0.0",
                "manifest oracle repair 1.0"], rows)
    rc = _jsonl(_read("reports/v2/recheck_all_tasks_after_drc_fix.jsonl"))
    by = collections.defaultdict(lambda: [0, 0, 0])
    for r in rc:
        by[r["split"]][0] += 1
        by[r["split"]][1] += r["faulted"] == 0.0
        by[r["split"]][2] += r["oracle"] == 1.0
    rows = [[s, n, f, o] for s, (n, f, o) in sorted(by.items())]
    rows.append(["**all**", sum(v[0] for v in by.values()), sum(v[1] for v in by.values()), sum(v[2] for v in by.values())])
    L += ["Full shipped set re-verified after the DRC-rules fix (`reports/v2/recheck_all_tasks_after_drc_fix.jsonl`):", ""]
    L += table(["split", "tasks", "faulted = 0.0", "oracle = 1.0"], rows)
    txt = _read("reports/v2/orchestrator_test_run.txt")
    tests = [(m.group(1), int(m.group(2))) for m in re.finditer(r"^(\S+\.py) (\d+) passed", txt, re.M)]
    failed = len(re.findall(r"\d+ failed", txt))
    L += [f"Orchestrator test run (`reports/v2/orchestrator_test_run.txt`): {sum(n for _, n in tests)} tests passed "
          f"across {len(tests)} files, {failed} file(s) with failures.", ""]
    return L


def sec_models() -> list[str]:
    txt = _read("reports/calibration/v2hard/FINDINGS.md")
    m = re.search(r"Served models confirmed from transcripts:\s*([^\n.]+(?:\.[0-9][^\n.]*)*)", txt)
    ids = sorted(set(re.findall(r"claude-[a-z]+-[0-9]+-[0-9]+", m.group(1)))) if m else []
    return ["## 6. Served model ids", "",
            "- v2-hard: " + (", ".join(f"`{i}`" for i in ids) if ids else "not recorded") +
            " (confirmed from transcripts, `reports/calibration/v2hard/FINDINGS.md`).",
            "- v1-normal, v2-hard_layout: not recorded in committed files; rollouts carry only the alias "
            "(haiku / sonnet / opus).",
            "- All runs: one attempt per task per model (v1: see §1), reasoning effort = medium, same agent harness, "
            "opaque per-job workdirs.", ""]


def sec_tasks(v1, v2) -> list[str]:
    L = ["## 8. Task set (from `tasks/manifest.jsonl`)", ""]
    tiers = ["normal", "hard", "hard_layout"]
    by = {t: [r for r in v2.values() if r["tier"] == t] for t in tiers}
    rows = []
    for t in tiers:
        rs = by[t]
        h = sum(r["holdout"] for r in rs)
        nf = sum(len(r["faults"]) for r in rs)
        lat = sum(bool(f.get("latent")) for r in rs for f in r["faults"])
        inv_task = sum(any(f.get("invisible_to_drc_erc") for f in r["faults"]) for r in rs)
        lay = sum(bool(f.get("layout")) for r in rs for f in r["faults"])
        rows.append([t, len(rs), len(rs) - h, f"{h} ({pct(h / len(rs))})", len({r["family"] for r in rs}),
                     len({f["type"] for r in rs for f in r["faults"]}), nf,
                     f"{lat} ({pct(lat / nf)})", f"{lay}", f"{inv_task} ({pct(inv_task / len(rs))})"])
    tot = list(v2.values())
    rows.append(["**all v2**", len(tot), sum(not r["holdout"] for r in tot), sum(r["holdout"] for r in tot), "",
                 len({f["type"] for r in tot for f in r["faults"]}), sum(len(r["faults"]) for r in tot), "", "", ""])
    L += table(["tier", "tasks", "train", "holdout", "families", "fault types", "fault instances",
                "latent faults (share of instances)", "layout-latent faults", "tasks with ≥1 DRC/ERC-invisible fault"], rows)
    L += [f"v1 (historical, git `{V1_MANIFEST_COMMIT}`): {len(v1)} tasks, "
          f"{sum(r.get('split') == 'holdout' for r in v1.values())} holdout, "
          f"{len({r['family'] for r in v1.values()})} families, "
          f"{len({f['type'] for r in v1.values() for f in r['faults']})} fault types.", ""]
    for name, fn in (("family", lambda r: r["family"]), ("faults per task", lambda r: r["n_faults"]),
                     ("hint level", lambda r: r["hint_level"]), ("tool mode", lambda r: r.get("tools_mode") or "full (no tools.json)")):
        keys = sorted({fn(r) for r in tot}, key=lambda x: (str(type(x)), x))
        rows = [[k] + [sum(fn(r) == k for r in by[t]) or "–" for t in tiers] for k in keys]
        L += [f"**By {name}** (tasks)", ""] + table([name] + tiers, rows)
    types = sorted({(f["category"], f["type"]) for r in tot for f in r["faults"]})
    rows = [[f"`{ty}`", cat] + [sum(f["type"] == ty for r in by[t] for f in r["faults"]) or "–" for t in tiers]
            for cat, ty in types]
    L += ["**Fault instances by type**", ""] + table(["fault type", "category"] + tiers, rows)
    return L


def _rt_summary(text: str) -> dict:
    m = {k: int(v) for k, v in re.findall(r"(attack applications|successes \(hacks\)|timeouts|attack_errors|blocked|crashes): (\d+)", text)}
    t = re.search(r"^tasks: (\d+)", text, re.M)
    a = re.search(r"attacks: (\d+)", text)
    m["tasks"] = int(t.group(1)) if t else None
    m["attacks"] = int(a.group(1)) if a else None
    m["HACK lines"] = len(re.findall(r"^HACK ", text, re.M))
    return m


def sec_redteam() -> list[str]:
    L = ["## 9. Red team (G5)", "",
         "Scripted runs (`redteam/runs/*.txt`, output of `redteam/run_scripted.py`):", ""]
    runs = [("round 1, fixture (final)", "redteam/runs/fixture_n1000_seed0.txt"),
            ("round 2, shipped v1, run 1 (superseded)", "redteam/runs/shipped_run1_superseded.txt"),
            ("round 2, shipped v1, run 2 (superseded)", "redteam/runs/shipped_run2_superseded.txt"),
            ("round 2, shipped v1 (final)", "redteam/runs/shipped_n1200_seed0.txt"),
            ("round 3, v2 normal/hard/hard_layout", "redteam/runs/v2_n1300_seed0.txt"),
            ("round 3, v2 retry of errored/timed-out", "redteam/runs/v2_n1300_seed0_retry.txt")]
    rows, final_apps, final_hacks, final_blocked, final_unfinished = [], 0, 0, 0, 0
    for label, rel in runs:
        if not (ROOT / rel).exists():
            rows.append([label, "file absent", "", "", "", "", ""])
            continue
        s = _rt_summary(_read(rel))
        if "attack applications" not in s:
            rows.append([label, "no summary yet (run in progress or empty)", "", "", "", "", ""])
            continue
        rows.append([label, s["tasks"], s["attacks"], s["attack applications"], s.get("blocked", ""),
                     s.get("successes (hacks)", ""), f"{s.get('timeouts', 0)} / {s.get('attack_errors', 0)}"])
        if "superseded" not in label:
            final_apps += s["attack applications"]
            final_hacks += s.get("successes (hacks)", 0)
            final_blocked += s.get("blocked", 0)
            final_unfinished += s.get("timeouts", 0) + s.get("attack_errors", 0)
    L += table(["run", "tasks", "attacks", "applications", "blocked", "hacks", "timeouts / attack errors"], rows)
    L += [f"Non-superseded scripted applications: **{final_apps}** ({final_blocked} completed and blocked, "
          f"{final_unfinished} timed out or hit an attack-script error and so prove nothing either way), "
          f"hacks: **{final_hacks}**. Superseded runs found hacks that were fixed before the final run of the same round.", ""]
    ha = _read("redteam/runs/hand_attempts.txt")
    kinds = collections.Counter()
    fake_hits = 0
    for line in ha.splitlines():
        mm = re.match(r"^H\d+\s+\S+\s+\S+\s+(\S+)\s+reward=([\d.]+)", line)
        if mm:
            kinds[mm.group(1)] += 1
            fake_hits += mm.group(1) == "fake" and float(mm.group(2)) == 1.0
    ex = _read("redteam/exploits.md")
    r1 = re.search(r"(\d+) faulted tasks × (\d+) low-effort policies =\s+(\d+) attempts, (\d+) reward-1\.0 episodes, (\d+) hacks", ex)
    r3n = re.search(r"(\d+) recorded attempts \(H(\d+)–H(\d+)\)", ex)
    r3f = re.search(r"fake: (\d+) attempts, (\d+) reach 1\.0", ex)
    rows = []
    if r1:
        rows.append(["round 1: scripted low-effort policies via the harness (exploits.md)", r1.group(3), "–", r1.group(5)])
    rows.append(["round 2: hand attempts (`redteam/runs/hand_attempts.txt`)", sum(kinds.values()),
                 ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())), fake_hits])
    if r3n:
        rows.append(["round 3: hand attempts on v2 hard/hard_layout (exploits.md RT75)", r3n.group(1),
                     f"fake {r3f.group(1)}" if r3f else "?", r3f.group(2) if r3f else "?"])
    L += ["Agent / hand attempts:", ""] + table(["source", "attempts", "kinds", "fake attempts reaching 1.0 (hacks)"], rows)
    total_agent = (int(r1.group(3)) if r1 else 0) + sum(kinds.values()) + (int(r3n.group(1)) if r3n else 0)
    L += [f"Agent/hand attempts total: **{total_agent}**. Reward-1.0 episodes from `minimal-legit` attempts or "
          "round-1 policies are genuine (cheap but correct) repairs, not hacks.", ""]
    # exploit ledger: latest verdict per RT id in exploits.md summary tables
    latest: dict[str, str] = {}
    first: dict[str, str] = {}
    for idt, verdict in re.findall(r"^\| (RT\d+(?:[–-]RT\d+)?) \| ([A-Z][A-Z-]+(?: \([^)]*\))?)", ex, re.M):
        first.setdefault(idt, verdict)
        latest[idt] = verdict
    ever_bad = sorted(i for i in first if any(v.startswith(("EXPLOIT", "EXPERT-DISAGREES"))
                                              for v in (first[i], latest[i])))
    rows = [[i, first[i], latest[i]] for i in sorted(latest, key=lambda s: int(re.findall(r"\d+", s)[0]))
            if not latest[i].startswith("BLOCKED")]
    L += ["Exploit ledger (`redteam/exploits.md` summary tables; BLOCKED rows omitted):", ""]
    L += table(["id", "first verdict", "latest verdict"], rows)
    fixed = [i for i in ever_bad if latest[i].startswith("FIXED")]
    L += [f"Findings ever rated EXPLOIT or EXPERT-DISAGREES (verifier gave 1.0 to something an expert rejects, or "
          f"an exploitable gap): {len(ever_bad)}; latest verdict FIXED: {len(fixed)}; still open: "
          f"{', '.join(i for i in ever_bad if i not in fixed) or 'none'}. Open LEAK items are listed above.", ""]
    return L


def sec_sample(roll) -> list[str]:
    L = ["## 7. Calibration sample composition", ""]
    rows = []
    for key, label, _, _ in TIERS:
        tasks = {r["task_id"]: r["_m"] for r in roll[key]}
        hold = sum(bool(m.get("holdout")) or m.get("split") == "holdout" for m in tasks.values())
        lat = [m.get("n_latent") for m in tasks.values() if m.get("n_latent") is not None]
        rows.append([label, len(tasks), hold, len({m.get('family') for m in tasks.values()}),
                     f"{min(lat)}–{max(lat)}" if lat else "–",
                     sum(1 for m in tasks.values() if not m)])
    L += table(["tier", "distinct tasks", "from holdout", "families", "latent faults per task", "not in manifest"], rows)
    return L


def build() -> str:
    _inputs.clear()
    thr = yaml.safe_load(_read("thresholds.yaml"))
    v1, v2, roll = load()
    body: list[str] = []
    body += sec_headline(roll, thr)
    body += sec_breakdowns(roll)
    body += sec_taxonomy(roll)
    body += sec_contamination(roll)
    body += sec_oracle(roll)
    body += sec_models()
    body += sec_sample(roll)
    body += sec_tasks(v1, v2)
    body += sec_redteam()
    head = ["# PCB-Repair baseline report (G7)", "",
            "**Generated file: do not edit by hand.** Every number below is computed by `reports/make_baseline.py` "
            "from the inputs listed at the end. Reproduce and verify with:", "",
            "```", CMD, "```", "",
            "`--check` regenerates the report in memory and exits 1 if it differs from this file. "
            "Interpretation and caveats: `reports/INTERPRETATION.md` (hand-written).", ""]
    tail = ["## Inputs", "", "sha256 prefixes of the exact bytes read:", ""]
    tail += table(["input", "sha256[:16]"], [[f"`{k}`", v] for k, v in sorted(_inputs.items())])
    return "\n".join(head + body + tail).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="diff a fresh build against reports/baseline.md")
    a = ap.parse_args()
    text = build()
    if a.check:
        old = OUT.read_text() if OUT.exists() else ""
        if old == text and build() == text:
            print(f"OK: {OUT.relative_to(ROOT)} reproduces exactly ({len(text.splitlines())} lines)")
            return 0
        sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), text.splitlines(True),
                                                   "baseline.md (file)", "baseline.md (fresh)"))
        print("DRIFT: reports/baseline.md does not match a fresh build", file=sys.stderr)
        return 1
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
