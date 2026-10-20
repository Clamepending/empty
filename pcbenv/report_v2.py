"""reports/v2_generation.md from the generators' own statistics and manifests (nothing hand-edited).

    python3 -m pcbenv.report_v2 --out reports/v2_generation.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from pcbenv.generate import _pct, load_manifest

ROOT = Path("tasks")
DIST = Path("dist")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _rows(*dirs: Path) -> list[dict]:
    return [r for d in dirs for r in load_manifest(d / "manifest.jsonl")]


def _tier_common(L: list[str], st: dict, rows: list[dict], train: str, hold: str) -> None:
    n = len(rows)
    nh = sum(r["holdout"] for r in rows)
    L += [f"- tasks: **{n}** ({train} {n - nh}, {hold} {nh} = {_pct(nh, n)} holdout)",
          f"- indices tried: {st['args']['count']} (start {st['args']['start_index']}); accepted {st['accepted']}, "
          f"dropped {st['dropped']} ({', '.join(f'{k}: {v}' for k, v in st['drop_reasons'].items()) or 'none'})",
          f"- generation time: {st['seconds']:.0f} s (4 workers); generator `{st['generator']}`, secret fingerprint "
          f"`{st['secret_fingerprint']}`",
          "- every shipped task passed: golden 1.0, faulted 0.0, each fault alone 0.0, oracle repair 1.0, all faults "
          "still present in the combined files", ""]
    L += ["| family | tasks | holdout |", "|---|---|---|"]
    fam = Counter(r["family"] for r in rows)
    famh = Counter(r["family"] for r in rows if r["holdout"])
    L += [f"| {k} | {v} | {famh.get(k, 0)} |" for k, v in sorted(fam.items())]
    L += ["", "| faults per task | tasks | share |", "|---|---|---|"]
    L += [f"| {k} | {v} | {_pct(v, n)} |" for k, v in sorted(Counter(r["n_faults"] for r in rows).items())]
    L += ["", "| hint level | tasks | share | full intent |", "|---|---|---|---|"]
    for k, v in sorted(Counter(r["hint_level"] for r in rows).items()):
        full = sum(r["hint_level"] == k and r.get("intent") == "full" for r in rows)
        L.append(f"| {k} | {v} | {_pct(v, n)} | {full} |")


def _dropped(L: list[str], st: dict) -> None:
    if st["dropped_tasks"]:
        L += ["", "Dropped task indices (the private manifest maps indices to seeds):", ""]
        L += [f"- index {d['index']} ({d['family']}): {d['reason'][:240]}" for d in st["dropped_tasks"]]


def normal_section(L: list[str], tdir: Path, hdir: Path) -> None:
    from pcbenv.faults import FAULT_TYPES
    st = json.loads((tdir / "generation_stats.json").read_text())
    rows = _rows(tdir, hdir)
    L += ["## Normal tier (`tasks/v2/normal`, `tasks/v2/normal_holdout`)", ""]
    _tier_common(L, st, rows, "normal", "normal_holdout")
    inv = sum(r["has_invisible"] for r in rows)
    L += ["", f"Tasks with ≥ 1 DRC/ERC-invisible fault: **{inv}/{len(rows)} = {_pct(inv, len(rows))}** "
          "(threshold ≥ 40 %).", "",
          "validity = injection produced loadable, schema-valid files (applied / (applied + invalid)); detection = "
          "the fault applied ALONE to the golden scores 0.0 (gate c, every task); invisible = share of shipped "
          "instances whose fault alone leaves DRC and ERC clean (measured). Attempts include not-applicable tries.", "",
          "| type | category | attempts | injected | shipped | validity | detection | DRC/ERC-invisible |",
          "|---|---|---|---|---|---|---|---|"]
    for t, ft in FAULT_TYPES.items():
        v = st["per_type"][t]
        L.append(f"| `{t}` | {ft.category} | {v['attempts']} | {v['applied']} | {v['in_shipped']} | "
                 f"{_pct(v['applied'], v['applied'] + v['invalid'])} | "
                 f"{_pct(v['alone_detected'], v['alone_checked'])} ({v['alone_detected']}/{v['alone_checked']}) | "
                 f"{_pct(v['invisible_in_shipped'], v['in_shipped'])} |")
    _dropped(L, st)


def hard_section(L: list[str], tdir: Path, hdir: Path) -> None:
    st = json.loads((tdir / "generation_stats.json").read_text())
    rows = _rows(tdir, hdir)
    n = len(rows)
    L += ["", "## Hard tier (`tasks/v2/hard`, `tasks/v2/hard_holdout`)", ""]
    _tier_common(L, st, rows, "hard", "hard_holdout")
    comp = sum(r["composite"] for r in rows)
    nf = sum(r["n_faults"] for r in rows)
    nl = sum(r["n_latent"] for r in rows)
    L += ["", f"- composite `sys_*` boards: **{comp}/{n} = {_pct(comp, n)}** (target ≥ 60 %)",
          f"- latent faults: **{nl}/{nf} = {_pct(nl, nf)}** of all faults; every task has ≥ 2 "
          f"(distribution {dict(sorted(Counter(r['n_latent'] for r in rows).items()))})",
          f"- tasks with an interacting value fault (its naive repair breaks a design rule): "
          f"{sum(r['n_interacting'] > 0 for r in rows)}",
          f"- tool mode: " + ", ".join(f"{k} {v} ({_pct(v, n)})" for k, v in
                                       sorted(Counter(r["tools_mode"] for r in rows).items())),
          f"- intent: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r["intent"] for r in rows).items())),
          "- fairness gate: every latent fault's evidence (`latent.evidence_groups`) was found in the task's "
          "public text (TASK.md + spec.json + parts/*.md) for every shipped task", ""]
    inj = st["inject_log"]
    alone = st["alone"]
    types = sorted({k.split("|")[0] for k in list(inj) + list(alone)})
    shipped = Counter(f["type"] for r in rows for f in r["faults"])
    lat = {f["type"]: f["latent"] for r in rows for f in r["faults"]}
    inv = Counter(f["type"] for r in rows for f in r["faults"] if f.get("invisible_to_drc_erc"))
    L += ["Per fault type (latent = invisible to every pcbtool check by construction; for latent types "
          "`applied`/`n/a`/`conflict` = applicable alone on the golden / not applicable / applicable alone but not "
          "on top of the other latent faults; validity counts loadable, schema-valid injections; detection = the "
          "fault alone scores 0.0):", "",
          "| type | latent | applied | n/a | conflict | invalid | validity | detection (alone) | shipped | DRC/ERC-invisible |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for t in types:
        a, na, cf, bad = (inj.get(f"{t}|{o}", 0) for o in ("applied", "n/a", "conflict", "invalid"))
        det, miss = alone.get(f"{t}|detected", 0), alone.get(f"{t}|missed", 0)
        L.append(f"| `{t}` | {'yes' if lat.get(t) else 'no' if t in lat else '?'} | {a} | {na} | {cf} | {bad} | "
                 f"{_pct(a, a + bad)} | {_pct(det, det + miss)} ({det}/{det + miss}) | {shipped.get(t, 0)} | "
                 f"{_pct(inv.get(t, 0), shipped.get(t, 0))} |")
    L += ["", "Latent faults by grader check: " + ", ".join(f"{k} {v}" for k, v in st["latent_detected_by"].items())]
    _dropped(L, st)


def hard_layout_section(L: list[str], tdir: Path, hdir: Path) -> None:
    p = tdir / "generation_stats.json"
    if not p.exists():
        return
    st = json.loads(p.read_text())
    rows = _rows(tdir, hdir)
    n = len(rows)
    L += ["", "## Hard tier, layout-rules sub-tier (`tasks/v2/hard_layout`, `tasks/v2/hard_layout_holdout`)", "",
          "Composite boards graded also on board-geometry layout rules (`pcbenv/layout_rules.py`: Kelvin sense, "
          "switching-loop area, crystal trace length / no vias, analog-switching separation; plus the decoupling "
          "copper path), stated with formulae and limits in TASK.md \"Layout rules\" and `spec.json:layout_rules`, "
          "not computed by pcbtool. Golden margins: `reports/v2/layout_rules_sweep.txt` "
          "(`python3 -m pcbenv.layout_rules --sweep 50`).", ""]
    _tier_common(L, st, rows, "hard_layout", "hard_layout_holdout")
    nf = sum(r["n_faults"] for r in rows)
    nl = sum(r["n_latent"] for r in rows)
    nlay = sum(r["n_layout"] for r in rows)
    L += ["", f"- latent faults: **{nl}/{nf} = {_pct(nl, nf)}** of all faults, of which layout-latent {nlay}; every "
          f"task has ≥ 1 layout-latent and ≥ 1 other latent fault (layout-latent per task "
          f"{dict(sorted(Counter(r['n_layout'] for r in rows).items()))})",
          f"- tool mode: " + ", ".join(f"{k} {v} ({_pct(v, n)})" for k, v in
                                       sorted(Counter(r["tools_mode"] for r in rows).items()))
          + " (target no_autoroute ≥ 60 %; a task whose layout fault `pcbtool route` would repair is always "
            "no_autoroute)",
          f"- layout faults that `pcbtool route` on their nets would repair (forced no_autoroute): "
          + (", ".join(f"{k} {v}" for k, v in sorted(st.get("autoroute_fixable", {}).items())) or "none"),
          f"- intent: " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(r["intent"] for r in rows).items())),
          "- gates: golden 1.0, faulted 0.0, each fault alone 0.0 (layout faults alone: invisible to every pcbtool "
          "check and failing only `layout_rules` / `layout`; other latent faults alone leave the layout rules "
          "intact), oracle 1.0, every fault present in the combined files, the violated layout rule's text present "
          "in TASK.md", ""]
    inj, alone = st["inject_log"], st["alone"]
    shipped = Counter(f["type"] for r in rows for f in r["faults"])
    kind = {f["type"]: ("layout" if f.get("layout") else "latent" if f["latent"] else "visible")
            for r in rows for f in r["faults"]}
    types = sorted({k.split("|")[0] for k in list(inj) + list(alone)})
    L += ["| type | kind | applied | n/a | conflict | detection (alone) | shipped |", "|---|---|---|---|---|---|---|"]
    for t in types:
        a, na, cf = (inj.get(f"{t}|{o}", 0) for o in ("applied", "n/a", "conflict"))
        det, miss = alone.get(f"{t}|detected", 0), alone.get(f"{t}|missed", 0)
        L.append(f"| `{t}` | {kind.get(t, '?')} | {a} | {na} | {cf} | {_pct(det, det + miss)} ({det}/{det + miss}) | "
                 f"{shipped.get(t, 0)} |")
    _dropped(L, st)


def refresh_section(L: list[str], d: Path, tier: str) -> None:
    p = d / "generation_stats.json"
    if not p.exists():
        return
    st = json.loads(p.read_text())
    rows = _rows(d, Path(f"{d}_holdout"))
    a = st["args"]
    extra = ""
    if tier == "normal":
        inv = sum(r["has_invisible"] for r in rows)
        extra = f"; invisible-fault share {_pct(inv, len(rows))}"
    else:
        extra = f"; composite share {_pct(sum(r['composite'] for r in rows), len(rows))}"
    L += [f"- {tier}: indices {a['start_index']}..{a['start_index'] + a['count'] - 1} ({a['count']} tried), deduped "
          f"against {', '.join(a['dedupe_against'])}: **{st['accepted']} new gated, deduped tasks** (threshold ≥ 100); "
          f"dropped {st['dropped']} ({', '.join(f'{k}: {v}' for k, v in st['drop_reasons'].items()) or 'none'})"
          f"{extra}; {st['seconds']:.0f} s"]


def render(commands: list[str]) -> str:
    v2 = ROOT / "v2"
    L = ["# v2 task generation (normal + hard tier + hard_layout)", "",
         "Generated by `python3 -m pcbenv.report_v2` from the generators' own statistics "
         "(`generation_stats.json`) and public manifests. Nothing here is hand-edited.", "",
         "## Commands", "", "```"] + commands + ["```", "",
         "Task ids are opaque (`pcbr2-<tier>-<hmac8>`) and generator seeds are HMAC(secret, index) (RT37, "
         "`pcbenv/taskids.py`). The secret is `tasks/.secret` (git-ignored, never published); seeds live only in "
         "`hidden/meta.json` and the private manifests `tasks/private/*.jsonl` (git-ignored). Public manifests "
         "(`tasks/manifest.jsonl`, one per split dir, inside the tarballs) carry family / fault metadata but no "
         "seeds. Byte-identical regeneration needs the same secret; `--secret default` is the documented public "
         "secret for reproducibility runs (tests use it).", ""]
    normal_section(L, v2 / "normal", v2 / "normal_holdout")
    hard_section(L, v2 / "hard", v2 / "hard_holdout")
    hard_layout_section(L, v2 / "hard_layout", v2 / "hard_layout_holdout")
    L += ["", "## G10 refresh runs (new indices, deduped against `tasks/manifest.jsonl`)", ""]
    refresh_section(L, ROOT / "refresh-v2" / "normal", "normal")
    refresh_section(L, ROOT / "refresh-v2" / "hard", "hard")
    L += ["", "## Tarballs", "", "Deterministic (sorted entries, mtime 0, no gzip timestamp); each contains its split's "
          "task dirs and public `manifest.jsonl`.", "", "| file | MB | sha256 |", "|---|---|---|"]
    for p in sorted(DIST.glob("pcb-repair-v2.1-*.tar.gz")):
        L.append(f"| `{p}` | {p.stat().st_size / 1e6:.1f} | `{_sha(p)}` |")
    man = ROOT / "manifest.jsonl"
    if man.exists():
        splits = sorted({r["split"] for r in load_manifest(man)})
        L += ["", f"`tasks/manifest.jsonl` (all {len(splits)} v2 splits, {len(load_manifest(man))} rows): sha256 "
              f"`{_sha(man)}`"]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m pcbenv.report_v2")
    ap.add_argument("--out", default="reports/v2_generation.md")
    ap.add_argument("--commands", default=None, help="text file with the exact generation commands")
    a = ap.parse_args(argv)
    cmds = Path(a.commands).read_text().strip().splitlines() if a.commands else []
    Path(a.out).write_text(render(cmds), encoding="utf-8")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
