"""Hard-tier task generator (G12): latent datasheet-rule / interface faults with no tool feedback.

    python3 -m pcbenv.generate --tier hard --start-seed 200000 --count 140 --workers 4
        (writes tasks/hard/<id>, tasks/hard_holdout/<id>, tasks/hard/manifest.jsonl)

Per seed s: family = HARD_FAMILIES[s % n] (families that admit at least one latent fault type),
golden = rules.harden(generate(s)) (footprints upsized to meet the stated ratings), golden board
built with seed 0. 2-4 faults (40/40/20 %), of which 1 (or 2 for 4-fault tasks and half of the
3-fault tasks) are latent (`faults/latent.py`, applied first, to the pristine golden) and the
rest v1 visible faults (applied after, with the latent targets excluded). Hint level symptom /
vague (50/50), tool mode full / no_autoroute (70/30). TASK.md: `prompts.render_hard` (Design
rules section; no symptom for latent faults); parts/*.md: `rules.hard_datasheet`;
public/tools.json: the tool mode; hidden meta: `tier: "hard"`, `rules` (rule context), ...

Gates (all must hold, else the seed is dropped with the reason):
  (a) golden files verify 1.0          (b) faulted public files verify 0.0
  (c) each fault re-applied ALONE to the golden (same rng + exclusions, replay checked) verifies 0.0
  (c') each latent fault alone: `latent.visible_failures` is empty (every pcbtool check passes) and
       the verifier fails only `rules` and/or `topology`
  (d) oracle repair (hidden golden files) verifies 1.0
  (e) every fault still present in the combined files
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import shutil
import tempfile
import time
import traceback
from collections import Counter
from multiprocessing import get_context
from pathlib import Path

HARD_VERSION = "pcb-repair-hard-v0"
BOARD_SEED = 0
HARD_FAMILIES = ("ldo_reg", "led_driver", "mcu_i2c", "nmos_switch", "npn_switch", "opamp_inv", "opamp_noninv")
N_FAULTS = ((2, 0.40), (3, 0.40), (4, 0.20))
HINTS = (("symptom", 0.5), ("vague", 0.5))
MODES = (("full", 0.7), ("no_autoroute", 0.3))
LATENT_WEIGHT = {"bias_wrong_rail": 1.0, "connector_pin_swap": 1.0, "mcu_pin_swap": 1.5, "decap_swapped": 1.5,
                 "flyback_misplaced": 1.5, "weak_base_drive": 1.5, "resistor_underrated": 1.2,
                 "capacitor_underrated": 1.5, "led_underrated": 1.0}


def hard_families() -> list[str]:
    from pcbenv.families import FAMILIES
    return [f for f in HARD_FAMILIES if f in FAMILIES]


def _n_latent(n: int, rng: random.Random) -> int:
    if n >= 4:
        return 2
    if n == 3:
        return 1 + (rng.random() < 0.5)
    return 1


def _apply_visible(golden, start_design: dict, start_board: str, seq: list[str], seed: int, exclude0: set[str],
                   work: str, log: list):
    from pcbenv.faults import InvalidInjection, apply_fault
    design = json.loads(json.dumps(start_design))
    board = os.path.join(work, "faulted.kicad_pcb")
    shutil.copyfile(start_board, board)
    records, plan, exclude = [], [], set(exclude0)
    for t in seq:
        rng = random.Random(f"pcbr-fault:{seed}:{t}")
        try:
            rec = apply_fault(t, golden, design, board, rng, frozenset(exclude), salt=f"{seed}:{t}")
        except InvalidInjection as e:
            log.append((t, "invalid", str(e)[:200]))
            return None
        if rec is None:
            log.append((t, "n/a", ""))
            return None
        log.append((t, "applied", ""))
        plan.append({"type": t, "exclude": sorted(exclude)})
        records.append(rec)
        exclude |= set(rec.targets)
    return design, board, records, plan


def build_one_hard(args: tuple) -> dict:
    seed, staging = args
    t0 = time.monotonic()
    log: list = []
    try:
        out = _build(seed, staging, log)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "reason": f"exception: {type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
    out.update(seed=seed, inject_log=log, seconds=round(time.monotonic() - t0, 2))
    return out


def _build(seed: int, staging: str, log: list) -> dict:
    from pcbenv import prompts, rules, taskio
    from pcbenv.board import build_board
    from pcbenv.faults.common import canonical_board_file, design_hash
    from pcbenv.faults.latent import LATENT_TYPES, apply_latent, still_present as latent_present, visible_failures
    from pcbenv.families import FAMILIES
    from pcbenv.generate import _failing, _json_hash, _rank, _sha, _weighted, _weighted_order, _workdir_with
    from pcbenv.generate import still_present as visible_present
    from pcbenv.faults import FAULT_TYPES
    from pcbenv.verify import verify

    fams = hard_families()
    fam = fams[seed % len(fams)]
    try:
        golden, upsized = rules.harden(FAMILIES[fam].generate(seed))
    except ValueError as e:
        return {"ok": False, "reason": f"golden violates a stated design rule (family issue): {e}"[:400], "family": fam}
    ctx = rules.rules_context(golden)
    rng = random.Random(f"pcbr-hard:{seed}")
    n = _weighted(rng, N_FAULTS)
    n_lat = _n_latent(n, rng)
    hint = _weighted(rng, HINTS)
    mode = _weighted(rng, MODES)
    with tempfile.TemporaryDirectory(prefix="pcbhard_") as td:
        gboard = os.path.join(td, "golden.kicad_pcb")
        build_board(golden, gboard, BOARD_SEED)
        canonical_board_file(gboard, f"{golden.family}:{golden.seed}:{BOARD_SEED}:hard")
        work = os.path.join(td, "work")
        os.mkdir(work)
        # ---- latent faults first, on the pristine golden
        ldesign = json.loads(json.dumps(golden.design))
        lboard = os.path.join(td, "latent.kicad_pcb")
        shutil.copyfile(gboard, lboard)
        lrecs, lplan, exclude = [], [], set()
        order = [(-math.log(1.0 - rng.random()) / LATENT_WEIGHT.get(t, 1.0), t) for t in sorted(LATENT_TYPES)]
        for _, t in sorted(order):
            if len(lrecs) == n_lat:
                break
            rec = apply_latent(t, golden, ldesign, lboard, random.Random(f"pcbr-latent:{seed}:{t}"),
                               frozenset(exclude), salt=f"{seed}:{t}", ctx=ctx)
            log.append((t, "applied" if rec else "n/a", ""))
            if rec is None:
                continue
            lplan.append({"type": t, "exclude": sorted(exclude)})
            lrecs.append(rec)
            exclude |= set(rec.targets)
        if not lrecs:
            return {"ok": False, "reason": "no latent fault applicable", "family": fam}
        # ---- visible v1 faults on top
        n_vis = n - len(lrecs)
        vorder = _weighted_order(rng, sorted(FAULT_TYPES))
        chosen: list[str] = []
        state = (json.loads(json.dumps(ldesign)), lboard, [], [])
        if n_vis:
            state = None
            for t in vorder:
                if len(chosen) == n_vis:
                    break
                trial = sorted(chosen + [t], key=lambda x: (_rank(x), (chosen + [t]).index(x)))
                res = _apply_visible(golden, ldesign, lboard, trial, seed, exclude, work, log)
                if res is None:
                    continue
                chosen, state = trial, res
            if state is None:
                return {"ok": False, "reason": "no applicable visible fault combination", "family": fam}
        design, fboard, vrecs, vplan = state
        records = lrecs + vrecs
        rec_dicts = [r.to_dict() for r in records]
        gd_hash = design_hash(golden.design)
        fault_keys = sorted(r.key() for r in records)
        task_id = f"pcbh-{fam}-{seed}-{_json_hash([gd_hash, fault_keys, hint, mode, HARD_VERSION])[:8]}"
        tdir = os.path.join(staging, task_id)
        gates: dict = {}
        gates["all_faults_present"] = (all(latent_present(r.to_dict(), design, fboard, golden) for r in lrecs)
                                       and all(visible_present(r, design, fboard, golden) for r in vrecs))
        extra = {"tier": "hard", "rules": ctx, "tools_mode": mode, "generator": HARD_VERSION,
                 "hardened_footprints": {k: list(v) for k, v in sorted(upsized.items())}}
        taskio.write_task(tdir, golden, gboard, public_design=design, public_board=fboard, faults=rec_dicts,
                          task_id=task_id, board_seed=BOARD_SEED, extra_meta=extra)
        pub = Path(tdir, "public")
        for f in sorted((pub / "parts").glob("*.md")):
            f.write_text(rules.hard_datasheet(f.stem), encoding="utf-8")
        (pub / "tools.json").write_text(json.dumps({"mode": mode}, indent=2) + "\n", encoding="utf-8")
        # ---- (c) each fault alone (latent: also invisible to every pcbtool check)
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
            ok = not vis and res.reward == 0.0 and set(fails) <= {"topology", "rules"} and bool(fails)
            alone_rewards.append(res.reward if ok else None)
            alone_info.append({"type": rec.type, "latent": True, "reward": res.reward, "failing": fails,
                               "tool_visible": vis[:5]})
        silent = []
        for rec, p in zip(vrecs, vplan):
            d1 = json.loads(json.dumps(golden.design))
            b1 = os.path.join(td, "alone.kicad_pcb")
            shutil.copyfile(gboard, b1)
            from pcbenv.faults import apply_fault
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
        sym = prompts.symptoms(golden, design, fboard, silent) if hint == "symptom" else []
        full_intent = (any(LATENT_TYPES[r.type].needs_full_intent for r in lrecs)
                       or any(t not in prompts.DATASHEET_INFERABLE for t in silent))
        (pub / "TASK.md").write_text(prompts.render_hard(golden, hint, sym, full_intent, mode), encoding="utf-8")
        meta = taskio.load_meta(tdir)
        meta.update(faults=rec_dicts, hint_level=hint, intent="full" if full_intent else "reduced",
                    difficulty={"measured": None, "predicted": "hard"})
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
    entry = {
        "id": task_id, "task_id": task_id, "tier": "hard", "family": fam, "seed": seed, "board_seed": BOARD_SEED,
        "faults": [{"type": r.type, "category": r.category, "detail": r.detail, "latent": r.category == "latent",
                    "detected_by": r.data.get("detected_by"), "evidence": r.data.get("evidence")} for r in records],
        "n_faults": len(records), "n_faults_target": n, "n_latent": len(lrecs),
        "hint_level": hint, "tools_mode": mode, "intent": "full" if full_intent else "reduced",
        "faulted_failing": _failing(rb), "alone": alone_info, "gates": gates, "golden_design_hash": gd_hash,
        "fault_set": _json_hash(fault_keys)[:16],
        "faulted_design_hash": _sha(os.path.join(tdir, "public", "design.json"))[:16],
        "hardened_footprints": {k: list(v) for k, v in sorted(upsized.items())},
    }
    if reasons:
        shutil.rmtree(tdir, ignore_errors=True)
        return {"ok": False, "reason": "; ".join(reasons), "family": fam, "entry": entry}
    return {"ok": True, "entry": entry}


def generate_hard(out: str = "tasks/hard", holdout_out: str = "tasks/hard_holdout", start: int = 200000,
                  count: int = 120, holdout_frac: float = 0.2, workers: int = 4, log=print) -> dict:
    t0 = time.monotonic()
    outp, holdp = Path(out), Path(holdout_out)
    for d in (outp, holdp):
        if d.exists():
            shutil.rmtree(d)
    staging = outp / "_staging"
    staging.mkdir(parents=True)
    holdp.mkdir(parents=True)
    jobs = [(s, str(staging)) for s in range(start, start + count)]
    results = []
    if workers <= 1:
        results = [build_one_hard(j) for j in jobs]
    else:
        with get_context("spawn").Pool(workers, maxtasksperchild=4) as pool:
            for i, r in enumerate(pool.imap(build_one_hard, jobs, chunksize=1)):
                results.append(r)
                if (i + 1) % 10 == 0:
                    log(f"  {i + 1}/{len(jobs)} seeds done, {sum(x['ok'] for x in results)} ok "
                        f"({time.monotonic() - t0:.0f} s)")
    accepted, dropped, seen = [], [], set()
    for r in results:
        if not r["ok"]:
            dropped.append({"seed": r["seed"], "family": r.get("family"), "reason": r["reason"]})
            continue
        e = r["entry"]
        key = (e["golden_design_hash"], e["fault_set"])
        if key in seen or e["faulted_design_hash"] in seen:
            dropped.append({"seed": r["seed"], "family": e["family"], "reason": "duplicate"})
            shutil.rmtree(staging / e["id"], ignore_errors=True)
            continue
        seen |= {key, e["faulted_design_hash"]}
        accepted.append(e)
    n_hold = round(holdout_frac * len(accepted))
    hold = {e["id"] for e in sorted(accepted, key=lambda e: hashlib.sha256(e["id"].encode()).hexdigest())[:n_hold]}
    for e in accepted:
        e["split"] = "hard_holdout" if e["id"] in hold else "hard"
        dst = (holdp if e["id"] in hold else outp) / e["id"]
        e["path"] = f"{dst.parent.name}/{e['id']}"
        shutil.move(str(staging / e["id"]), str(dst))
    shutil.rmtree(staging, ignore_errors=True)
    with open(outp / "manifest.jsonl", "w", encoding="utf-8") as f:
        for e in accepted:
            f.write(json.dumps(e, sort_keys=True) + "\n")
    lat = Counter(f["type"] for e in accepted for f in e["faults"] if f["latent"])
    stats = {
        "args": {"out": str(out), "holdout_out": str(holdout_out), "start_seed": start, "count": count,
                 "holdout_frac": holdout_frac},
        "generator": HARD_VERSION, "seconds": round(time.monotonic() - t0, 1),
        "accepted": len(accepted), "dropped": len(dropped),
        "drop_reasons": dict(Counter(d["reason"].split(":")[0] for d in dropped)),
        "dropped_tasks": dropped,
        "per_split": dict(Counter(e["split"] for e in accepted)),
        "per_family": dict(sorted(Counter(e["family"] for e in accepted).items())),
        "per_n_faults": dict(sorted(Counter(e["n_faults"] for e in accepted).items())),
        "per_n_latent": dict(sorted(Counter(e["n_latent"] for e in accepted).items())),
        "per_hint": dict(sorted(Counter(e["hint_level"] for e in accepted).items())),
        "per_mode": dict(sorted(Counter(e["tools_mode"] for e in accepted).items())),
        "per_intent": dict(sorted(Counter(e["intent"] for e in accepted).items())),
        "latent_types": dict(sorted(lat.items())),
        "visible_types": dict(sorted(Counter(f["type"] for e in accepted for f in e["faults"]
                                             if not f["latent"]).items())),
        "latent_detected_by": dict(sorted(Counter(f["detected_by"] for e in accepted for f in e["faults"]
                                                  if f["latent"]).items())),
    }
    (outp / "generation_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    return stats
