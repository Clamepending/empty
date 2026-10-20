"""Hard-tier `hard_layout` sub-tier generator (G12): composite boards graded also on board-geometry
layout rules (`pcbenv/layout_rules.py`) that pcbtool does not compute.

    python3 -m pcbenv.generate --tier hard_layout --out tasks/v2/hard_layout \
        --holdout-out tasks/v2/hard_layout_holdout --start 0 --count 260 --workers 4 \
        --secret tasks/.secret --private tasks/private/hard_layout.jsonl

Per task index i: composite family from a fixed 20-slot cycle (sys_motor_ctrl 11, sys_clocked_mcu 9:
the composites with layout rules beyond decoupling), seed = HMAC(secret, "seed:hard_layout:i"), golden =
rules.harden(generate(seed)), golden board built with the layout rules (`build_board(layout_rules=)`:
tight switching loop, Kelvin sense branch, short via-free crystal nets; an attempt is accepted only if
every rule holds with margin). 3-6 faults (25/35/25/15 %): 1 layout-latent (2 for 5-6 faults,
`latent.LAYOUT_LATENT_TYPES`, applied first on the pristine golden), 1 other latent
(`latent.LATENT_TYPES`; must not disturb the layout rules), the rest v1 visible faults. Hint level
symptom / vague (50/50). Tool mode: no_autoroute if `pcbtool route` on a layout fault's net(s) would
repair it (`latent.autoroute_fixes`), else no_autoroute with p = 0.6 -> >= 60 % no_autoroute.
TASK.md = `prompts.render_hard` + `layout_rules.rules_md`; spec.json gains `layout_rules`; hidden
meta: `tier: "hard_layout"`, `rules`, `layout_rules`, `tools_mode`.

Gates (as the hard tier, plus): latent layout faults alone fail only `layout_rules` / `layout`;
other latent faults alone leave `layout_rules` passing; in full mode no layout fault is fixed by
`pcbtool route`; every layout fault's rule text is in TASK.md (fairness).
"""
from __future__ import annotations

import json
import math
import os
import random
import shutil
import tempfile
import time
import traceback
from collections import Counter
from pathlib import Path

LAYOUT_VERSION = "pcb-repair-hard-layout-v2.1"
TIER = "hard_layout"
BOARD_SEED = 0
# the composites with board-geometry rules beyond decoupling (Kelvin / loop / separation; crystal)
CYCLE = ["sys_motor_ctrl"] * 11 + ["sys_clocked_mcu"] * 9
N_FAULTS = ((3, 0.25), (4, 0.35), (5, 0.25), (6, 0.15))
HINTS = (("symptom", 0.5), ("vague", 0.5))
NO_AUTOROUTE_P = 0.6
LAYOUT_WEIGHT = {"kelvin_sense_tap": 1.5, "switch_loop_spread": 1.5, "crystal_far": 1.3, "crystal_via": 1.0,
                 "analog_near_switch": 1.2, "decap_long_path": 0.5}
LAYOUT_FAILS = {"layout_rules", "layout"}
LATENT_FAILS = {"topology", "rules", "layout"}


def family_for(index: int) -> str:
    return CYCLE[(index * 7) % len(CYCLE)]


def _n_layout(n: int) -> int:
    return 1 if n <= 4 else 2


def build_one_layout(args: tuple) -> dict:
    index, staging, secret = args
    from pcbenv.taskids import task_seed
    seed = task_seed(secret, TIER, index)
    t0 = time.monotonic()
    log: list = []
    try:
        out = _build(index, seed, staging, log, secret)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "reason": f"exception: {type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
    out.update(index=index, seed=seed, inject_log=log, seconds=round(time.monotonic() - t0, 2))
    return out


def _pick_and_apply(t, golden, ldesign, lboard, gboard, td, seed, exclude, ctx):
    """Choose latent `t` on the pristine golden, then apply exactly that candidate on the current
    state (the alone-replay makes the same choice). Returns (pick, rec)."""
    from pcbenv.faults.latent import apply_latent
    d0 = json.loads(json.dumps(golden.design))
    b0 = os.path.join(td, "pick.kicad_pcb")
    shutil.copyfile(gboard, b0)
    pick = apply_latent(t, golden, d0, b0, random.Random(f"pcbr-latent:{seed}:{t}"), frozenset(exclude),
                        salt=f"{seed}:{t}", ctx=ctx)
    if pick is None:
        return None, None
    rec = apply_latent(t, golden, ldesign, lboard, random.Random(f"pcbr-latent:{seed}:{t}"), frozenset(exclude),
                       salt=f"{seed}:{t}", ctx=ctx, want=pick.detail)
    return pick, rec


def _build(index: int, seed: int, staging: str, log: list, secret: str) -> dict:
    from pcbenv import prompts, rules, taskio
    from pcbenv.board import build_board
    from pcbenv.faults import FAULT_TYPES, apply_fault
    from pcbenv.faults.common import canonical_board_file, design_hash
    from pcbenv.faults.latent import (LATENT_TYPES, LAYOUT_LATENT_TYPES, apply_latent, autoroute_fixes, layout_issues,
                                      still_present as latent_present, visible_failures)
    from pcbenv.families import FAMILIES
    from pcbenv.generate import _failing, _json_hash, _sha, _weighted, _weighted_order, _workdir_with, publish_names
    from pcbenv.generate import still_present as visible_present
    from pcbenv.generate_hard import LATENT_WEIGHT, _apply_visible
    from pcbenv.layout_rules import layout_rules_context, rules_md
    from pcbenv.taskids import task_id as make_task_id
    from pcbenv.verify import verify

    fam = family_for(index)
    try:
        golden, upsized = rules.harden(FAMILIES[fam].generate(seed))
    except ValueError as e:
        return {"ok": False, "reason": f"golden violates a stated design rule (family issue): {e}"[:400], "family": fam}
    ctx = rules.rules_context(golden)
    lctx = layout_rules_context(golden)
    rng = random.Random(f"pcbr-hard-layout:{seed}")
    n = _weighted(rng, N_FAULTS)
    n_lay = _n_layout(n)
    hint = _weighted(rng, HINTS)
    want_no_auto = rng.random() < NO_AUTOROUTE_P
    with tempfile.TemporaryDirectory(prefix="pcbhl_") as td:
        gboard = os.path.join(td, "golden.kicad_pcb")
        build_board(golden, gboard, BOARD_SEED, layout_rules=lctx)
        canonical_board_file(gboard, f"{golden.family}:{golden.seed}:{BOARD_SEED}:hard_layout")
        work = os.path.join(td, "work")
        os.mkdir(work)
        ldesign = json.loads(json.dumps(golden.design))
        lboard = os.path.join(td, "latent.kicad_pcb")
        shutil.copyfile(gboard, lboard)
        lrecs, lplan, exclude = [], [], set()
        # ---- layout-latent faults first (pristine golden geometry)
        order = [(-math.log(1.0 - rng.random()) / LAYOUT_WEIGHT.get(t, 1.0), t) for t in sorted(LAYOUT_LATENT_TYPES)]
        used_codes: set[str] = set()
        for _, t in sorted(order):
            if len(lrecs) == n_lay:
                break
            codes = set(LAYOUT_LATENT_TYPES[t].rule_codes)
            if codes & used_codes:
                continue  # one fault per layout rule
            pick, rec = _pick_and_apply(t, golden, ldesign, lboard, gboard, td, seed, exclude, ctx)
            log.append((t, "applied" if rec else "n/a" if pick is None else "conflict", ""))
            if rec is None:
                continue
            lplan.append({"type": t, "exclude": sorted(exclude)})
            lrecs.append(rec)
            used_codes |= codes
            exclude |= set(rec.targets)
        if not lrecs:
            return {"ok": False, "reason": "no layout-latent fault applicable", "family": fam}
        n_layout_applied = len(lrecs)
        # ---- one other latent fault (datasheet / intent), must not disturb the layout rules
        base_issues = layout_issues(golden, lboard)
        order = [(-math.log(1.0 - rng.random()) / LATENT_WEIGHT.get(t, 1.0), t) for t in sorted(LATENT_TYPES)]
        for _, t in sorted(order):
            if len(lrecs) > n_layout_applied:
                break
            d_try = json.loads(json.dumps(ldesign))
            b_try = os.path.join(td, "try.kicad_pcb")
            shutil.copyfile(lboard, b_try)
            pick, rec = _pick_and_apply(t, golden, d_try, b_try, gboard, td, seed, exclude, ctx)
            if rec is not None and layout_issues(golden, b_try) != base_issues:
                log.append((t, "conflict", "disturbs layout rules"))
                continue
            log.append((t, "applied" if rec else "n/a" if pick is None else "conflict", ""))
            if rec is None:
                continue
            ldesign = d_try
            shutil.copyfile(b_try, lboard)
            lplan.append({"type": t, "exclude": sorted(exclude)})
            lrecs.append(rec)
            exclude |= set(rec.targets)
        if len(lrecs) == n_layout_applied:
            return {"ok": False, "reason": "no other latent fault applicable", "family": fam}
        # ---- visible v1 faults on top
        n_vis = max(0, n - len(lrecs))
        vorder = _weighted_order(rng, sorted(FAULT_TYPES))
        chosen: list[str] = []
        state = (json.loads(json.dumps(ldesign)), lboard, [], [])
        if n_vis:
            from pcbenv.generate import _rank as rank
            state = None
            for t in vorder:
                if len(chosen) == n_vis:
                    break
                trial = sorted(chosen + [t], key=lambda x: (rank(x), (chosen + [t]).index(x)))
                res = _apply_visible(golden, ldesign, lboard, trial, seed, exclude, work, log)
                if res is None:
                    continue
                chosen, state = trial, res
            if state is None or len(chosen) < n_vis:
                return {"ok": False, "reason": "no applicable visible fault combination", "family": fam}
        design, fboard, vrecs, vplan = state
        records = lrecs + vrecs
        rec_dicts = [r.to_dict() for r in records]
        lay_recs = [r for r in lrecs if r.type in LAYOUT_LATENT_TYPES]
        # ---- tool mode: a layout fault `pcbtool route` would repair forces no_autoroute
        auto = {r.type: autoroute_fixes(golden, golden.design, _alone_board(td, golden, gboard, r, lplan, seed, ctx),
                                        r.to_dict()) for r in lay_recs}
        mode = "no_autoroute" if (want_no_auto or any(auto.values())) else "full"
        gd_hash = design_hash(golden.design)
        fault_keys = sorted(r.key() for r in records)
        task_id = make_task_id(secret, TIER, index, _json_hash([gd_hash, fault_keys, hint, mode, LAYOUT_VERSION]))
        tdir = os.path.join(staging, task_id)
        gates: dict = {"autoroute_fixes": auto}
        gates["all_faults_present"] = (all(latent_present(r.to_dict(), design, fboard, golden) for r in lrecs)
                                       and all(visible_present(r, design, fboard, golden) for r in vrecs))
        extra = {"tier": TIER, "rules": ctx, "layout_rules": lctx, "tools_mode": mode, "generator": LAYOUT_VERSION,
                 "index": index, "hardened_footprints": {k: list(v) for k, v in sorted(upsized.items())}}
        taskio.write_task(tdir, golden, gboard, public_design=design, public_board=fboard, faults=rec_dicts,
                          task_id=task_id, board_seed=BOARD_SEED, extra_meta=extra, hard=True)
        pub = Path(tdir, "public")
        for f in sorted((pub / "parts").glob("*.md")):
            f.write_text(rules.hard_datasheet(f.stem), encoding="utf-8")
        (pub / "tools.json").write_text(json.dumps({"mode": mode}, indent=2) + "\n", encoding="utf-8")
        spec = json.loads((pub / "spec.json").read_text(encoding="utf-8"))
        spec["layout_rules"] = lctx
        taskio._write_json(pub / "spec.json", spec)
        # ---- (c) each fault alone
        alone_rewards, alone_info = [], []
        for rec, p in zip(lrecs, lplan):
            d1 = json.loads(json.dumps(golden.design))
            b1 = os.path.join(td, "alone.kicad_pcb")
            shutil.copyfile(gboard, b1)
            rec1 = apply_latent(p["type"], golden, d1, b1, random.Random(f"pcbr-latent:{seed}:{p['type']}"),
                                frozenset(p["exclude"]), salt=f"{seed}:{p['type']}", ctx=ctx)
            if rec1 is None or rec1.detail != rec.detail:
                alone_rewards.append(None)
                alone_info.append({"type": rec.type, "replay": "mismatch"})
                continue
            vis = visible_failures(golden, d1, b1)
            res = verify(_workdir_with(td, d1, None, b1), tdir)
            fails = _failing(res)
            allowed = LAYOUT_FAILS if rec.type in LAYOUT_LATENT_TYPES else LATENT_FAILS
            ok = not vis and res.reward == 0.0 and set(fails) <= allowed and bool(fails)
            alone_rewards.append(res.reward if ok else None)
            alone_info.append({"type": rec.type, "latent": True, "layout": rec.type in LAYOUT_LATENT_TYPES,
                               "reward": res.reward, "failing": fails, "tool_visible": vis[:5]})
        silent = []
        for rec, p in zip(vrecs, vplan):
            d1 = json.loads(json.dumps(golden.design))
            b1 = os.path.join(td, "alone.kicad_pcb")
            shutil.copyfile(gboard, b1)
            rec1 = apply_fault(p["type"], golden, d1, b1, random.Random(f"pcbr-fault:{seed}:{p['type']}"),
                               frozenset(p["exclude"]), salt=f"{seed}:{p['type']}")
            if rec1 is None or rec1.detail != rec.detail:
                alone_rewards.append(None)
                alone_info.append({"type": rec.type, "replay": "mismatch"})
                continue
            res = verify(_workdir_with(td, d1, None, b1), tdir)
            fails = _failing(res)
            alone_rewards.append(res.reward)
            alone_info.append({"type": rec.type, "latent": False, "reward": res.reward, "failing": fails})
            if set(fails) == {"topology"}:
                silent.append(rec.type)
        gates["each_fault_detected"] = alone_rewards
        # ---- TASK.md + final meta
        sym = (prompts.symptoms(golden, design, fboard, silent,
                                decoupling=any(r.type == "decap_moved_far" for r in vrecs))
               if hint == "symptom" else [])
        full_intent = (any(LATENT_TYPES[r.type].needs_full_intent for r in lrecs if r.type in LATENT_TYPES)
                       or any(t not in prompts.DATASHEET_INFERABLE for t in silent))
        text = prompts.render_hard(golden, hint, sym, full_intent, mode)
        (pub / "TASK.md").write_text(prompts.add_layout_rules(text, rules_md(lctx, bool(golden.decoupling))),
                                     encoding="utf-8")
        # ---- (f) fairness
        from pcbenv.generate_hard import evidence_gate
        missing = evidence_gate(lrecs, rec_dicts, tdir)
        gates["evidence_public"] = not missing
        renames = publish_names(tdir, golden, f"{task_id}:names")
        meta = taskio.load_meta(tdir)
        meta.update(faults=rec_dicts, hint_level=hint, intent="full" if full_intent else "reduced",
                    public_net_renames=renames, difficulty={"measured": None, "predicted": "hard"})
        taskio._write_json(Path(tdir, "hidden", "meta.json"), meta)
        # ---- (a) golden, (b) faulted, (d) oracle
        gates["golden"] = verify(_workdir_with(td, golden.design, None, gboard), tdir).reward
        rb = verify(str(pub), tdir)
        gates["faulted"] = rb.reward
        wd = tempfile.mkdtemp(prefix="oracle_", dir=td)
        taskio.copy_public(tdir, wd)
        shutil.copyfile(os.path.join(tdir, "hidden", "golden_design.json"), os.path.join(wd, "design.json"))
        shutil.copyfile(os.path.join(tdir, "hidden", "golden_board.kicad_pcb"), os.path.join(wd, "board.kicad_pcb"))
        gates["oracle_repair"] = verify(wd, tdir).reward
        # ---- the faulted public board: every layout fault's rule really fails there too
        fissues = layout_issues(golden, fboard)
        gates["layout_faults_graded"] = [bool(set(LAYOUT_LATENT_TYPES[r.type].rule_codes) & set(fissues))
                                         for r in lay_recs]

    reasons = []
    if gates["golden"] != 1.0:
        reasons.append("golden does not verify 1.0")
    if gates["faulted"] != 0.0:
        reasons.append("faulted task does not verify 0.0")
    if any(r != 0.0 for r in alone_rewards):
        bad = [a["type"] for a, r in zip(alone_info, alone_rewards) if r != 0.0]
        reasons.append("fault not individually detected / latent visible / replay mismatch: " + ",".join(bad))
    if gates["oracle_repair"] != 1.0:
        reasons.append("oracle repair does not verify 1.0")
    if not gates["all_faults_present"]:
        reasons.append("a fault was cancelled by another")
    if not gates["evidence_public"]:
        reasons.append(f"latent evidence missing from public text: {missing}"[:300])
    if mode == "full" and any(auto.values()):
        reasons.append("autoroute repairs a layout fault in full mode")
    if not all(gates["layout_faults_graded"]):
        reasons.append("a layout fault is not violated in the combined board")
    entry = {
        "id": task_id, "task_id": task_id, "tier": TIER, "family": fam, "seed": seed, "index": index,
        "board_seed": BOARD_SEED,
        "faults": [{"type": r.type, "category": r.category, "detail": r.detail, "latent": r.category == "latent",
                    "layout": r.type in LAYOUT_LATENT_TYPES, "interacting": False,
                    "invisible_to_drc_erc": bool(r.invisible_to_drc_erc), "detected_by": r.data.get("detected_by"),
                    "evidence": r.data.get("evidence")} for r in records],
        "n_faults": len(records), "n_faults_target": n, "n_latent": len(lrecs), "n_layout": len(lay_recs),
        "n_interacting": 0, "hint_level": hint, "tools_mode": mode, "intent": "full" if full_intent else "reduced",
        "autoroute_fixable": sorted(t for t, v in auto.items() if v),
        "faulted_failing": _failing(rb), "alone": alone_info, "gates": gates, "golden_design_hash": gd_hash,
        "fault_set": _json_hash(fault_keys)[:16],
        "faulted_design_hash": _sha(os.path.join(tdir, "public", "design.json"))[:16],
        "faulted_board_hash": _sha(os.path.join(tdir, "public", "board.kicad_pcb"))[:16],
        "hardened_footprints": {k: list(v) for k, v in sorted(upsized.items())},
        "composite": True, "layout_rules": sorted(k for k in lctx if k != "version"),
    }
    if reasons:
        shutil.rmtree(tdir, ignore_errors=True)
        return {"ok": False, "reason": "; ".join(reasons), "family": fam, "entry": entry}
    return {"ok": True, "entry": entry}


def _alone_board(td: str, golden, gboard: str, rec, lplan: list[dict], seed: int, ctx: dict) -> str:
    """The golden board with only layout fault `rec` applied (for the autoroute check)."""
    from pcbenv.faults.latent import apply_latent
    p = next(x for x in lplan if x["type"] == rec.type)
    b1 = os.path.join(td, f"auto_{rec.type}.kicad_pcb")
    shutil.copyfile(gboard, b1)
    d1 = json.loads(json.dumps(golden.design))
    apply_latent(rec.type, golden, d1, b1, random.Random(f"pcbr-latent:{seed}:{rec.type}"), frozenset(p["exclude"]),
                 salt=f"{seed}:{rec.type}", ctx=ctx)
    return b1


def generate_hard_layout(out: str = "tasks/v2/hard_layout", holdout_out: str = "tasks/v2/hard_layout_holdout",
                         start: int = 0, count: int = 60, holdout_frac: float = 0.2, workers: int = 4, log=print,
                         secret: str = "default", private: str | None = None, tasks_root: str | None = None,
                         dedupe_against: list[str] | None = None, holdout_pin: str | None = None) -> dict:
    from pcbenv.generate import _clear, finalize, run_pool
    from pcbenv.taskids import secret_fingerprint
    t0 = time.monotonic()
    outp, holdp = Path(out), Path(holdout_out)
    troot = Path(tasks_root) if tasks_root else outp.parent
    for d in (outp, holdp):
        _clear(d)
    staging = outp / "_staging"
    staging.mkdir(parents=True)
    jobs = [(i, str(staging), secret) for i in range(start, start + count)]
    results = run_pool(build_one_layout, jobs, workers, log, every=10, maxtasks=4)
    accepted, dropped = finalize(results, outp, holdp, staging, holdout_frac, troot, dedupe_against, private,
                                 holdout_pin)
    inject = Counter()
    for r in results:
        for t, outcome, _ in r.get("inject_log", []):
            inject[(t, outcome)] += 1
    alone = Counter()
    for r in results:
        for a in (r.get("entry") or {}).get("alone", []):
            alone[(a["type"], "mismatch" if a.get("replay") else "detected" if a.get("reward") == 0.0 else "missed")] += 1
    n_f = sum(e["n_faults"] for e in accepted)
    stats = {
        "args": {"tier": TIER, "out": str(out), "holdout_out": str(holdout_out), "start_index": start, "count": count,
                 "holdout_frac": holdout_frac, "dedupe_against": dedupe_against or []},
        "generator": LAYOUT_VERSION, "secret_fingerprint": secret_fingerprint(secret),
        "seconds": round(time.monotonic() - t0, 1),
        "accepted": len(accepted), "dropped": len(dropped),
        "drop_reasons": dict(Counter(d["reason"].split(":")[0] for d in dropped)),
        "dropped_tasks": dropped,
        "per_split": dict(Counter(e["split"] for e in accepted)),
        "per_family": dict(sorted(Counter(e["family"] for e in accepted).items())),
        "per_n_faults": dict(sorted(Counter(e["n_faults"] for e in accepted).items())),
        "per_n_latent": dict(sorted(Counter(e["n_latent"] for e in accepted).items())),
        "per_n_layout": dict(sorted(Counter(e["n_layout"] for e in accepted).items())),
        "latent_fault_share": round(sum(e["n_latent"] for e in accepted) / max(1, n_f), 4),
        "per_hint": dict(sorted(Counter(e["hint_level"] for e in accepted).items())),
        "per_mode": dict(sorted(Counter(e["tools_mode"] for e in accepted).items())),
        "per_intent": dict(sorted(Counter(e["intent"] for e in accepted).items())),
        "layout_types": dict(sorted(Counter(f["type"] for e in accepted for f in e["faults"] if f["layout"]).items())),
        "autoroute_fixable": dict(sorted(Counter(t for e in accepted for t in e["autoroute_fixable"]).items())),
        "latent_types": dict(sorted(Counter(f["type"] for e in accepted for f in e["faults"]
                                            if f["latent"] and not f["layout"]).items())),
        "visible_types": dict(sorted(Counter(f["type"] for e in accepted for f in e["faults"]
                                             if not f["latent"]).items())),
        "inject_log": {f"{t}|{o}": c for (t, o), c in sorted(inject.items())},
        "alone": {f"{t}|{o}": c for (t, o), c in sorted(alone.items())},
    }
    (outp / "generation_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    return stats
