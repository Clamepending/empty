"""Hard-tier task generator (G12, v2): composite multi-rail boards with several latent faults.

    python3 -m pcbenv.generate --tier hard --out tasks/v2/hard --holdout-out tasks/v2/hard_holdout \
        --start 0 --count 600 --workers 4 --secret tasks/.secret --private tasks/private/hard.jsonl

Per task index i: family from a fixed 20-slot cycle (13 slots composite `sys_*` = 65 %, 7 slots the
v1 families that admit latent faults), generator seed = HMAC(secret, i) (`taskids.py`; id
`pcbr2-hard-<hmac8>`), golden = rules.harden(generate(seed)) (footprints upsized to meet the stated
ratings), golden board built with seed 0. 3-6 faults (25/35/25/15 %), of which >= 2 latent (2 for
3-4 faults, 3 for 5-6; `faults/latent.py`, applied first, to the pristine golden). With
probability INTERACT_P one more fault interacts with a latent one: a spec-visible value fault on
the part a rating fault downsized (or on the LED's series resistor), chosen so the faulted state
meets the rating while the naive repair (restoring the spec value) breaks it -- the repair must
satisfy spec + rules + bounds at once. The rest are v1 visible faults (latent targets excluded).
Hint level symptom / vague (50/50), tool mode full / no_autoroute (60/40). TASK.md:
`prompts.render_hard` (Design rules section incl. the decoupling rules, which pcbtool does not run
in the hard tier; no symptom for latent faults); parts/*.md: `rules.hard_datasheet`;
public/tools.json: the tool mode; hidden meta: `tier: "hard"`, `rules` (rule context), ...

Gates (all must hold, else the index is dropped with the reason):
  (a) golden files verify 1.0          (b) faulted public files verify 0.0
  (c) each fault re-applied ALONE to the golden (same rng + exclusions, replay checked) verifies 0.0
  (c') each latent fault alone: `latent.visible_failures` is empty (every pcbtool check passes) and
       the verifier fails only `rules`, `topology` and/or `layout` (decoupling design rule)
  (d) oracle repair (hidden golden files) verifies 1.0
  (e) every fault still present in the combined files
  (f) fairness: every latent fault's evidence (`latent.evidence_groups`) is present in the public
      text (TASK.md + spec.json + parts/*.md)
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

HARD_VERSION = "pcb-repair-hard-v2"
BOARD_SEED = 0
# v1 families that admit latent faults (the composites are listed in families.HARD_FAMILIES)
V1_IN_HARD = ("ldo_reg", "led_driver", "mcu_i2c", "nmos_switch", "npn_switch")   # >= 2 latent types apply
COMPOSITE_SLOTS = 13          # of every 20 consecutive indices -> 65 % composite boards
N_FAULTS = ((3, 0.25), (4, 0.35), (5, 0.25), (6, 0.15))
HINTS = (("symptom", 0.5), ("vague", 0.5))
MODES = (("full", 0.6), ("no_autoroute", 0.4))
INTERACT_P = 0.5
LATENT_WEIGHT = {"bias_wrong_rail": 1.0, "connector_pin_swap": 1.0, "mcu_pin_swap": 1.3, "decap_swapped": 1.3,
                 "flyback_misplaced": 1.5, "weak_base_drive": 1.3, "resistor_underrated": 1.0,
                 "capacitor_underrated": 1.2, "led_underrated": 1.0, "pullup_wrong_rail": 2.0,
                 "decap_wrong_rail": 1.5, "protection_bypassed": 2.0}
# allowed verifier failures of a latent fault applied alone (the tool sees nothing)
LATENT_FAILS = {"topology", "rules", "layout"}


def hard_families() -> list[str]:
    from pcbenv.families import FAMILIES
    return [f for f in V1_IN_HARD if f in FAMILIES]


def family_for(index: int) -> str:
    from pcbenv.families import HARD_FAMILIES
    comp, v1 = list(HARD_FAMILIES), hard_families()
    cyc, slot = divmod(index, 20)
    if slot < COMPOSITE_SLOTS:
        return comp[(cyc * COMPOSITE_SLOTS + slot) % len(comp)]
    return v1[(cyc * (20 - COMPOSITE_SLOTS) + slot - COMPOSITE_SLOTS) % len(v1)]


def _n_latent(n: int) -> int:
    return 2 if n <= 4 else 3


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


# ------------------------------------------------------------------ interacting value fault
INTERACT_TYPE = "interacting_value"
_INTERACT_RULE = {"resistor_underrated": "resistor_power", "led_underrated": "led_current",
                  "weak_base_drive": "npn_saturation"}


def _collector_resistor(design: dict, base_res: str) -> str | None:
    """The load resistor that sets the collector current of the NPN driven through `base_res`
    (directly on the collector net, or in series with an LED whose cathode is on it)."""
    from pcbenv.design import net_of
    for q, c in sorted(design["components"].items()):
        if c["part"] != "NPN":
            continue
        nb = net_of(design, f"{q}.B")
        if nb not in (net_of(design, f"{base_res}.1"), net_of(design, f"{base_res}.2")):
            continue
        nc = net_of(design, f"{q}.C")
        for r, rc in sorted(design["components"].items()):
            if rc["part"] == "R" and r != base_res and nc in (net_of(design, f"{r}.1"), net_of(design, f"{r}.2")):
                return r
        for d, dc in sorted(design["components"].items()):
            if dc["part"].startswith("LED_") and net_of(design, f"{d}.K") == nc:
                return _series_resistor(design, d)
    return None


def _series_resistor(design: dict, led: str) -> str | None:
    from pcbenv.design import net_of
    na = net_of(design, f"{led}.A")
    for r, c in sorted(design["components"].items()):
        if c["part"] == "R" and na in (net_of(design, f"{r}.1"), net_of(design, f"{r}.2")):
            return r
    return None


def interacting_value(golden, design: dict, board_path: str, lrec, ctx: dict, rng: random.Random,
                      exclude: set[str], salt: str, alone: bool = False):
    """A spec-visible value fault on the ref behind a rating latent fault (`lrec`), such that the
    combined faulted state does not break that rating but restoring the spec value does.
    `alone`: replay on the golden (only the value, no latent fault) -> same choice."""
    from pcbenv import rules
    from pcbenv.faults.common import FaultRecord, free, set_board_values, value_detectable
    from pcbenv.parts import format_value, parse_value
    if alone:
        exclude = set()
    code = _INTERACT_RULE.get(lrec["type"])
    if code is None:
        return None
    d = lrec["data"]
    ref = {"resistor_underrated": lambda: d["ref"], "led_underrated": lambda: _series_resistor(golden.design, d["ref"]),
           "weak_base_drive": lambda: _collector_resistor(golden.design, d["ref"])}[lrec["type"]]()
    if ref is None or (not alone and not free(exclude - set(lrec["targets"]), ref)):
        return None
    old = golden.design["components"][ref]["value"]
    factors = [0.33, 0.47, 0.56, 1.8, 2.2, 2.7, 3.3, 4.7]
    rng.shuffle(factors)
    for f in factors:
        v = format_value(float(f"{parse_value(old) * f:.2g}"))
        g1 = json.loads(json.dumps(golden.design))
        g1["components"][ref]["value"] = v
        if not value_detectable(g1, golden):
            continue
        # with the latent footprint change in place the faulted value keeps the rating (judged on
        # golden + this latent only, so the choice is the same when replayed alone)
        lat = json.loads(json.dumps(golden.design))
        for r, (_, fp) in d.get("footprints", {}).items():
            lat["components"][r]["footprint"] = fp
        for r, (_, lv) in d.get("values", {}).items():
            lat["components"][r]["value"] = lv
        lat["components"][ref]["value"] = v
        if any(x.code == code for x in rules.run_rules(lat, ctx)):
            continue
        detail = (f"{ref} is {v}, should be ~{old} (spec); restoring it while {d['ref']} keeps its latent fault "
                  f"breaks the {code.replace('_', ' ')} rule")
        design["components"][ref]["value"] = v
        set_board_values(board_path, {ref: v}, salt)
        return FaultRecord(INTERACT_TYPE, "value", detail, True, [ref],
                           {"ref": ref, "value": v, "golden_value": old, "values": {ref: v},
                            "interacts_with": lrec["type"], "rating_ref": d["ref"], "rule": code})
    return None


# ------------------------------------------------------------------ one task
def build_one_hard(args: tuple) -> dict:
    index, staging, secret = args
    from pcbenv.taskids import task_seed
    seed = task_seed(secret, "hard", index)
    t0 = time.monotonic()
    log: list = []
    try:
        out = _build(index, seed, staging, log, secret)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "reason": f"exception: {type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
    out.update(index=index, seed=seed, inject_log=log, seconds=round(time.monotonic() - t0, 2))
    return out


def _public_text(tdir: str) -> str:
    pub = Path(tdir, "public")
    parts = [(pub / "TASK.md").read_text(encoding="utf-8"), (pub / "spec.json").read_text(encoding="utf-8")]
    parts += [f.read_text(encoding="utf-8") for f in sorted((pub / "parts").glob("*.md"))]
    return "\n".join(parts)


def _build(index: int, seed: int, staging: str, log: list, secret: str) -> dict:
    from pcbenv import prompts, rules, taskio
    from pcbenv.board import build_board
    from pcbenv.faults import FAULT_TYPES, apply_fault
    from pcbenv.faults.common import canonical_board_file, design_hash
    from pcbenv.faults.latent import (LATENT_TYPES, apply_latent, missing_evidence, still_present as latent_present,
                                      visible_failures)
    from pcbenv.families import FAMILIES
    from pcbenv.generate import _failing, _json_hash, _rank, _sha, _weighted, _weighted_order, _workdir_with, publish_names
    from pcbenv.generate import still_present as visible_present
    from pcbenv.taskids import task_id as make_task_id
    from pcbenv.verify import verify

    fam = family_for(index)
    try:
        golden, upsized = rules.harden(FAMILIES[fam].generate(seed))
    except ValueError as e:
        return {"ok": False, "reason": f"golden violates a stated design rule (family issue): {e}"[:400], "family": fam}
    ctx = rules.rules_context(golden)
    rng = random.Random(f"pcbr-hard:{seed}")
    n = _weighted(rng, N_FAULTS)
    n_lat = _n_latent(n)
    hint = _weighted(rng, HINTS)
    mode = _weighted(rng, MODES)
    want_interact = rng.random() < INTERACT_P
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
            # choose on the pristine golden (the choice the alone-replay makes), then apply exactly
            # that candidate on top of the latent faults so far (it must stay invisible there too)
            d0 = json.loads(json.dumps(golden.design))
            b0 = os.path.join(td, "pick.kicad_pcb")
            shutil.copyfile(gboard, b0)
            pick = apply_latent(t, golden, d0, b0, random.Random(f"pcbr-latent:{seed}:{t}"),
                                frozenset(exclude), salt=f"{seed}:{t}", ctx=ctx)
            rec = None if pick is None else apply_latent(
                t, golden, ldesign, lboard, random.Random(f"pcbr-latent:{seed}:{t}"), frozenset(exclude),
                salt=f"{seed}:{t}", ctx=ctx, want=pick.detail)
            log.append((t, "applied" if rec else "n/a" if pick is None else "conflict", ""))
            if rec is None:
                continue
            lplan.append({"type": t, "exclude": sorted(exclude)})
            lrecs.append(rec)
            exclude |= set(rec.targets)
        if len(lrecs) < 2:
            return {"ok": False, "reason": f"fewer than 2 latent faults applicable ({len(lrecs)})", "family": fam}
        # ---- interacting value fault on a rating latent
        irecs = []
        if want_interact:
            for lr in lrecs:
                if lr.type not in _INTERACT_RULE:
                    continue
                ir = interacting_value(golden, ldesign, lboard, lr.to_dict(), ctx,
                                       random.Random(f"pcbr-interact:{seed}"), exclude, f"{seed}:interact")
                log.append((INTERACT_TYPE, "applied" if ir else "n/a", ""))
                if ir is not None:
                    irecs.append((ir, lr.to_dict()))
                    exclude |= set(ir.targets)
                    break
        # ---- visible v1 faults on top
        n_vis = max(0, n - len(lrecs) - len(irecs))
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
            if state is None or len(chosen) < n_vis:
                return {"ok": False, "reason": "no applicable visible fault combination", "family": fam}
        design, fboard, vrecs, vplan = state
        records = lrecs + [r for r, _ in irecs] + vrecs
        rec_dicts = [r.to_dict() for r in records]
        gd_hash = design_hash(golden.design)
        fault_keys = sorted(r.key() for r in records)
        task_id = make_task_id(secret, "hard", index, _json_hash([gd_hash, fault_keys, hint, mode, HARD_VERSION]))
        tdir = os.path.join(staging, task_id)
        gates: dict = {}
        gates["all_faults_present"] = (all(latent_present(r.to_dict(), design, fboard, golden) for r in lrecs)
                                       and all(visible_present(r, design, fboard, golden) for r, _ in irecs)
                                       and all(visible_present(r, design, fboard, golden) for r in vrecs))
        extra = {"tier": "hard", "rules": ctx, "tools_mode": mode, "generator": HARD_VERSION, "index": index,
                 "hardened_footprints": {k: list(v) for k, v in sorted(upsized.items())}}
        taskio.write_task(tdir, golden, gboard, public_design=design, public_board=fboard, faults=rec_dicts,
                          task_id=task_id, board_seed=BOARD_SEED, extra_meta=extra, hard=True)
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
            ok = not vis and res.reward == 0.0 and set(fails) <= LATENT_FAILS and bool(fails)
            alone_rewards.append(res.reward if ok else None)
            alone_info.append({"type": rec.type, "latent": True, "reward": res.reward, "failing": fails,
                               "tool_visible": vis[:5]})
        for ir, lr in irecs:
            d1 = json.loads(json.dumps(golden.design))
            b1 = os.path.join(td, "alone.kicad_pcb")
            shutil.copyfile(gboard, b1)
            ir1 = interacting_value(golden, d1, b1, lr, ctx, random.Random(f"pcbr-interact:{seed}"), set(),
                                    f"{seed}:interact", alone=True)
            if ir1 is None or ir1.detail != ir.detail:
                alone_rewards.append(None)
                alone_info.append({"type": ir.type, "replay": "mismatch"})
                continue
            res = verify(_workdir_with(td, d1, None, b1), tdir)
            alone_rewards.append(res.reward)
            alone_info.append({"type": ir.type, "latent": False, "interacting": True, "reward": res.reward,
                               "failing": _failing(res)})
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
        full_intent = (any(LATENT_TYPES[r.type].needs_full_intent for r in lrecs)
                       or any(t not in prompts.DATASHEET_INFERABLE for t in silent))
        (pub / "TASK.md").write_text(prompts.render_hard(golden, hint, sym, full_intent, mode), encoding="utf-8")
        # ---- (f) fairness: evidence of every latent fault is in the public text
        text = _public_text(tdir)
        missing = {r.type: missing_evidence(r.to_dict(), text) for r in lrecs}
        missing = {k: v for k, v in missing.items() if v}
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
    entry = {
        "id": task_id, "task_id": task_id, "tier": "hard", "family": fam, "seed": seed, "index": index,
        "board_seed": BOARD_SEED,
        "faults": [{"type": r.type, "category": r.category, "detail": r.detail, "latent": r.category == "latent",
                    "interacting": r.type == INTERACT_TYPE, "invisible_to_drc_erc": bool(r.invisible_to_drc_erc),
                    "detected_by": r.data.get("detected_by"), "evidence": r.data.get("evidence")} for r in records],
        "n_faults": len(records), "n_faults_target": n, "n_latent": len(lrecs), "n_interacting": len(irecs),
        "hint_level": hint, "tools_mode": mode, "intent": "full" if full_intent else "reduced",
        "faulted_failing": _failing(rb), "alone": alone_info, "gates": gates, "golden_design_hash": gd_hash,
        "fault_set": _json_hash(fault_keys)[:16],
        "faulted_design_hash": _sha(os.path.join(tdir, "public", "design.json"))[:16],
        "hardened_footprints": {k: list(v) for k, v in sorted(upsized.items())},
        "composite": fam.startswith("sys_"),
    }
    if reasons:
        shutil.rmtree(tdir, ignore_errors=True)
        return {"ok": False, "reason": "; ".join(reasons), "family": fam, "entry": entry}
    return {"ok": True, "entry": entry}


def generate_hard(out: str = "tasks/v2/hard", holdout_out: str = "tasks/v2/hard_holdout", start: int = 0,
                  count: int = 120, holdout_frac: float = 0.2, workers: int = 4, log=print, secret: str = "default",
                  private: str | None = None, tasks_root: str | None = None,
                  dedupe_against: list[str] | None = None) -> dict:
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
    results = run_pool(build_one_hard, jobs, workers, log, every=10, maxtasks=4)
    accepted, dropped = finalize(results, outp, holdp, staging, holdout_frac, troot, dedupe_against, private)
    lat = Counter(f["type"] for e in accepted for f in e["faults"] if f["latent"])
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
        "args": {"tier": "hard", "out": str(out), "holdout_out": str(holdout_out), "start_index": start, "count": count,
                 "holdout_frac": holdout_frac, "dedupe_against": dedupe_against or []},
        "generator": HARD_VERSION, "secret_fingerprint": secret_fingerprint(secret),
        "seconds": round(time.monotonic() - t0, 1),
        "accepted": len(accepted), "dropped": len(dropped),
        "drop_reasons": dict(Counter(d["reason"].split(":")[0] for d in dropped)),
        "dropped_tasks": dropped,
        "per_split": dict(Counter(e["split"] for e in accepted)),
        "per_family": dict(sorted(Counter(e["family"] for e in accepted).items())),
        "composite_share": round(sum(e["composite"] for e in accepted) / max(1, len(accepted)), 4),
        "per_n_faults": dict(sorted(Counter(e["n_faults"] for e in accepted).items())),
        "per_n_latent": dict(sorted(Counter(e["n_latent"] for e in accepted).items())),
        "with_interacting": sum(e["n_interacting"] > 0 for e in accepted),
        "latent_fault_share": round(sum(e["n_latent"] for e in accepted) / max(1, n_f), 4),
        "per_hint": dict(sorted(Counter(e["hint_level"] for e in accepted).items())),
        "per_mode": dict(sorted(Counter(e["tools_mode"] for e in accepted).items())),
        "per_intent": dict(sorted(Counter(e["intent"] for e in accepted).items())),
        "latent_types": dict(sorted(lat.items())),
        "visible_types": dict(sorted(Counter(f["type"] for e in accepted for f in e["faults"]
                                             if not f["latent"]).items())),
        "latent_detected_by": dict(sorted(Counter(f["detected_by"] for e in accepted for f in e["faults"]
                                                  if f["latent"]).items())),
        "inject_log": {f"{t}|{o}": c for (t, o), c in sorted(inject.items())},
        "alone": {f"{t}|{o}": c for (t, o), c in sorted(alone.items())},
    }
    (outp / "generation_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    return stats
