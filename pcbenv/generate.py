"""Task generator + refresh engine (G4 / G10), v2 layout.

    # normal tier (v1 families), 20 % holdout, generation secret in tasks/.secret (git-ignored)
    python3 -m pcbenv.generate --tier normal --out tasks/v2/normal --holdout-out tasks/v2/normal_holdout \
        --start 0 --count 1030 --workers 4 --secret tasks/.secret --private tasks/private/normal.jsonl
    # hard tier (pcbenv/generate_hard.py)
    python3 -m pcbenv.generate --tier hard --out tasks/v2/hard --holdout-out tasks/v2/hard_holdout ...
    # refresh run (G10): new indices, deduped against the shipped manifest
    python3 -m pcbenv.generate --tier normal --out tasks/refresh-v2/normal --start 100000 --count 120 \
        --holdout-frac 0 --dedupe-against tasks/manifest.jsonl --secret tasks/.secret
    python3 -m pcbenv.generate --combine tasks/v2/normal tasks/v2/hard --manifest tasks/manifest.jsonl
    python3 -m pcbenv.generate --pack tasks/v2 --dist dist          # deterministic tarballs only

Task index i in [start, start+count): family = V1_FAMILIES[i % 10], generator seed =
HMAC(secret, i) (`pcbenv/taskids.py`; ids are opaque `pcbr2-normal-<hmac8>`, public manifests carry
no seeds, the private manifest does), golden = generate(seed), golden board = build_board(golden,
seed 0); 1-3 faults (40/35/25 %) are injected with disjoint targets in a fixed category order
(connectivity, value, DRC-clean board faults, DRC-breaking board faults) so later faults can neither
undo nor block earlier ones. Hint level 30/40/30 % (explicit / symptom / vague). Public net names
not referenced in the public text are neutralised (`pcbenv/netnames.py`, RT34). Every task is gated:
  (a) the golden files verify 1.0;
  (b) the faulted public files verify 0.0;
  (c) each fault re-applied ALONE to the golden (same rng, same exclusions -> same choice,
      checked) verifies 0.0;
  (d) oracle repair (hidden golden design + board copied into the workdir) verifies 1.0;
  (e) every fault is still present in the combined faulted files (no cancellation).
Failing tasks are dropped with the reason. Accepted tasks are deduplicated (golden design hash
+ fault set, and faulted design.json hash) against each other and `--dedupe-against`
manifests, then split: the `round(holdout_frac * N)` tasks with the smallest sha256(task id)
go to --holdout-out, the rest to --out. Same arguments (and secret) -> same task ids and bytes.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import random
import shutil
import sys
import tarfile
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict
from multiprocessing import get_context
from pathlib import Path

GENERATOR_VERSION = "pcb-repair-v2"
BOARD_SEED = 0
N_FAULTS = ((1, 0.40), (2, 0.35), (3, 0.25))
HINTS = (("explicit", 0.30), ("symptom", 0.40), ("vague", 0.30))
# selection weight (fault types applicable to few families get more weight so counts balance)
TYPE_WEIGHT = {"wrong_led_resistor": 2.5, "transistor_pinout": 4.5, "reversed_polarity": 2.0,
               "wrong_pull_resistor": 1.5, "wrong_feedback_resistor": 1.8, "wrong_filter_cap": 1.5,
               "swapped_ic_pins": 1.8, "decap_moved_far": 2.2, "decap_misconnected": 1.3, "floating_pin": 2.2}
DRC_BREAKING = {"clearance_violation", "broken_trace", "short_between_nets", "footprint_swap"}


def family_order() -> list[str]:
    """Normal tier: the v1 families only (the composite sys_* families are hard-tier)."""
    from pcbenv.families import V1_FAMILIES
    return list(V1_FAMILIES)


def _rank(ftype: str) -> int:
    from pcbenv.faults import CATEGORY_ORDER, FAULT_TYPES
    if ftype in DRC_BREAKING:
        return 3
    return CATEGORY_ORDER[FAULT_TYPES[ftype].category]


def _weighted(rng: random.Random, table) -> object:
    x = rng.random()
    acc = 0.0
    for v, p in table:
        acc += p
        if x < acc:
            return v
    return table[-1][0]


def _weighted_order(rng: random.Random, names: list[str]) -> list[str]:
    keys = [(-math.log(1.0 - rng.random()) / TYPE_WEIGHT.get(n, 1.0), n) for n in names]
    return [n for _, n in sorted(keys)]


def _sha(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


# ------------------------------------------------------------------ fault sequence
def _apply_sequence(golden, gboard: str, seq: list[str], seed: int, work: str, log: list):
    """Apply fault types `seq` (in order) to fresh copies of the golden. Returns
    (design, board_path, records, plan) or None if one is not applicable."""
    from pcbenv.faults import InvalidInjection, apply_fault
    design = json.loads(json.dumps(golden.design))
    board = os.path.join(work, "faulted.kicad_pcb")
    shutil.copyfile(gboard, board)
    records, plan, exclude = [], [], set()
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


def choose_faults(golden, gboard: str, seed: int, n: int, rng: random.Random, work: str, log: list):
    from pcbenv.faults import FAULT_TYPES
    order = _weighted_order(rng, sorted(FAULT_TYPES))
    chosen: list[str] = []
    state = None
    for t in order:
        if len(chosen) == n:
            break
        trial = sorted(chosen + [t], key=lambda x: (_rank(x), (chosen + [t]).index(x)))
        res = _apply_sequence(golden, gboard, trial, seed, work, log)
        if res is None:
            continue
        chosen, state = trial, res
    if len(chosen) < n:
        if state is None:
            return None
    return state


# ------------------------------------------------------------------ persistence check
def still_present(rec, design: dict, board_path: str, golden) -> bool:
    from pcbenv import boardnet
    from pcbenv.faults.common import drc_result, net_of
    d, t = rec.data, rec.type
    rp = {r: c["part"] for r, c in golden.design["components"].items()}
    info = boardnet.board_info(board_path, parts=rp)
    if t == "bom_mismatch":
        return info.values.get(d["ref"]) == d["board_value"] and design["components"][d["ref"]]["value"] == d["golden_value"]
    if rec.category == "value":
        vals = d.get("values") or {d["ref"]: d["value"]}
        return all(design["components"][r]["value"] == v and info.values.get(r) == v for r, v in vals.items())
    if rec.category == "connectivity":
        return all(net_of(design, p) == new for p, (_, new) in d["moves"].items())
    if t == "board_pad_swap":
        fp = boardnet.load_board(board_path).FindFootprintByReference(d["ref"])
        nets = {p.GetNumber(): p.GetNetname() for p in fp.Pads()}
        return nets.get(d["pads"][0]) == d["nets"][1] and nets.get(d["pads"][1]) == d["nets"][0]
    if t == "footprint_swap":
        return design["components"][d["ref"]]["footprint"] == d["footprint"] == info.footprints.get(d["ref"])
    if t == "narrow_power_trace":
        return info.track_widths.get(d["net"], 99) < d["required"] - 1e-6
    if t == "decap_moved_far":
        x, y, _ = info.positions[d["cap"]]
        return abs(x - d["pos"][0]) < 1e-3 and abs(y - d["pos"][1]) < 1e-3
    r = drc_result(board_path)
    if t == "broken_trace":
        return r.unconnected > 0
    return bool(r.errors)


# ------------------------------------------------------------------ one task
def _workdir_with(td: str, design: dict | None, design_src: str | None, board_src: str) -> str:
    wd = tempfile.mkdtemp(prefix="wd_", dir=td)
    if design is not None:
        Path(wd, "design.json").write_text(json.dumps(design, indent=2, sort_keys=True) + "\n")
    else:
        shutil.copyfile(design_src, os.path.join(wd, "design.json"))
    shutil.copyfile(board_src, os.path.join(wd, "board.kicad_pcb"))
    return wd


def _failing(res) -> list[str]:
    return sorted([k for k, v in res.gates.items() if not v] + [k for k, v in res.checks.items() if not v])


def predicted_difficulty(n: int, hint: str, n_invisible: int) -> str:
    score = n + {"explicit": 0, "symptom": 1, "vague": 2}[hint] + 0.5 * n_invisible
    return "easy" if score < 2.5 else "medium" if score < 4.0 else "hard"


def build_one(args: tuple) -> dict:
    index, staging, secret = args
    from pcbenv.taskids import task_seed
    seed = task_seed(secret, "normal", index)
    t0 = time.monotonic()
    log: list = []
    try:
        out = _build_one(index, seed, staging, log, secret)
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "reason": f"exception: {type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
    out.update(index=index, seed=seed, inject_log=log, seconds=round(time.monotonic() - t0, 2))
    return out


def publish_names(tdir: str, golden, salt: str) -> dict[str, str]:
    """RT34: neutral names for the public nets that TASK.md / spec.json do not mention."""
    from pcbenv import netnames
    rp = {r: c["part"] for r, c in golden.design["components"].items()}
    return netnames.neutralise_public(tdir, rp, salt)


def _build_one(index: int, seed: int, staging: str, log: list, secret: str) -> dict:
    from pcbenv import prompts, taskio
    from pcbenv.board import build_board
    from pcbenv.faults import apply_fault
    from pcbenv.faults.common import canonical_board_file, design_hash
    from pcbenv.families import FAMILIES
    from pcbenv.golden import Golden
    from pcbenv.verify import verify

    from pcbenv.taskids import task_id as make_task_id
    fam = family_order()[index % len(family_order())]
    golden: Golden = FAMILIES[fam].generate(seed)
    # all tiers (QA F5): the resistor power rule is stated (parts/R.md) and graded (meta rules_power);
    # resistor footprints of the golden are upsized where the family's choice breaks it
    from pcbenv import rules as RL
    try:
        golden, _ = RL.harden(golden, only=["resistor_power"])
    except ValueError as e:
        return {"ok": False, "reason": f"golden violates the resistor power rule: {e}"[:300], "family": fam}
    power_ctx = RL.rules_context(golden, ["resistor_power"])
    rng = random.Random(f"pcbr-task:{seed}")
    n = _weighted(rng, N_FAULTS)
    hint = _weighted(rng, HINTS)
    alone_info: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="pcbgen_") as td:
        gboard = os.path.join(td, "golden.kicad_pcb")
        build_board(golden, gboard, BOARD_SEED)
        canonical_board_file(gboard, f"{golden.family}:{golden.seed}:{BOARD_SEED}")
        work = os.path.join(td, "work")
        os.mkdir(work)
        state = choose_faults(golden, gboard, seed, n, rng, work, log)
        if state is None:
            return {"ok": False, "reason": "no applicable fault combination", "family": fam}
        design, fboard, records, plan = state
        gd_hash = design_hash(golden.design)
        fault_keys = sorted(r.key() for r in records)
        task_id = make_task_id(secret, "normal", index, _json_hash([gd_hash, fault_keys, hint, GENERATOR_VERSION]))
        tdir = os.path.join(staging, task_id)

        gates: dict = {}
        # (e) no cancellation
        gates["all_faults_present"] = all(still_present(r, design, fboard, golden) for r in records)
        # write the task (TASK.md is rewritten below once symptoms are known)
        taskio.write_task(tdir, golden, gboard, public_design=design, public_board=fboard,
                          faults=[r.to_dict() for r in records], task_id=task_id, board_seed=BOARD_SEED,
                          extra_meta={"rules_power": power_ctx})
        if (Path(tdir) / "public" / "parts" / "R.md").exists():
            (Path(tdir) / "public" / "parts" / "R.md").write_text(RL.hard_datasheet("R"), encoding="utf-8")
        # (c) each fault alone
        alone_rewards = []
        for rec, p in zip(records, plan):
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
            alone_rewards.append(res.reward)
            rec.invisible_to_drc_erc = rec1.invisible_to_drc_erc
            fails = _failing(res)
            # a layout failure that only says "this power net's pin set changed" is a by-product of
            # the topology change, not an independent observable symptom
            layout_side = "layout" in fails and all(
                str(m).startswith(("power_net_missing", "power_net_unrouted")) for m in res.detail.get("layout", []))
            alone_info.append({"type": rec.type, "reward": res.reward, "failing": fails,
                               "topology_only": set(fails) - ({"layout"} if layout_side else set()) == {"topology"}})
        gates["each_fault_detected"] = alone_rewards
        silent = [a["type"] for a in alone_info if a.get("topology_only")]
        # TASK.md + final meta
        sym = prompts.symptoms(golden, design, fboard, silent) if hint != "vague" else []
        rec_dicts = [r.to_dict() for r in records]
        full_intent = prompts.needs_full_intent(hint, silent)
        Path(tdir, "public", "TASK.md").write_text(
            prompts.add_power_rule_note(prompts.render(golden, hint, rec_dicts, sym, full_intent), golden),
            encoding="utf-8")
        n_inv = sum(r.invisible_to_drc_erc for r in records)
        renames = publish_names(tdir, golden, f"{task_id}:names")
        meta = taskio.load_meta(tdir)
        meta.update(faults=rec_dicts, hint_level=hint, intent="full" if full_intent else "reduced",
                    generator=GENERATOR_VERSION, tier="normal", index=index, public_net_renames=renames,
                    difficulty={"measured": None, "predicted": predicted_difficulty(len(records), hint, n_inv)})
        taskio._write_json(Path(tdir, "hidden", "meta.json"), meta)
        # (a) golden files, (b) faulted public, (d) oracle repair
        gates["golden"] = verify(_workdir_with(td, golden.design, None, gboard), tdir).reward
        rb = verify(os.path.join(tdir, "public"), tdir)
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
        bad = [rec.type for rec, r in zip(records, alone_rewards) if r != 0.0]
        reasons.append("fault not individually detected / replay mismatch: " + ",".join(bad))
    if gates["oracle_repair"] != 1.0:
        reasons.append("oracle repair does not verify 1.0")
    if not gates["all_faults_present"]:
        reasons.append("a fault was cancelled by another")
    entry = {
        "id": task_id, "task_id": task_id, "tier": "normal", "family": fam, "seed": seed, "index": index,
        "board_seed": BOARD_SEED,
        "faults": [{"type": r.type, "category": r.category, "detail": r.detail,
                    "invisible_to_drc_erc": r.invisible_to_drc_erc} for r in records],
        "n_faults": len(records), "n_faults_target": n,
        "invisible_share": round(n_inv / len(records), 4), "has_invisible": n_inv > 0,
        "hint_level": hint, "intent": "full" if full_intent else "reduced", "faulted_failing": _failing(rb), "alone": alone_info,
        "gates": gates, "golden_design_hash": gd_hash,
        "fault_set": _json_hash(fault_keys)[:16],
        "faulted_design_hash": _sha(os.path.join(tdir, "public", "design.json"))[:16],
        "difficulty_predicted": predicted_difficulty(len(records), hint, n_inv),
    }
    if reasons:
        shutil.rmtree(tdir, ignore_errors=True)
        return {"ok": False, "reason": "; ".join(reasons), "family": fam, "entry": entry}
    return {"ok": True, "entry": entry}


# ------------------------------------------------------------------ packing
def pack(src_dir: str | Path, tar_path: str | Path, arc_root: str) -> None:
    """Deterministic .tar.gz of src_dir: sorted entries, mtime 0, uid/gid 0, no gzip timestamp.
    `generation_stats.json` (generator bookkeeping) is left out."""
    src = Path(src_dir)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        paths = sorted(p for p in src.rglob("*") if p.name != "generation_stats.json")
        for p in [src] + paths:
            rel = arc_root if p == src else f"{arc_root}/{p.relative_to(src).as_posix()}"
            ti = tarfile.TarInfo(rel)
            ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = 0, 0, 0, "", ""
            if p.is_dir():
                ti.type, ti.mode = tarfile.DIRTYPE, 0o755
                tf.addfile(ti)
            else:
                data = p.read_bytes()
                ti.size, ti.mode = len(data), 0o644
                tf.addfile(ti, io.BytesIO(data))
    Path(tar_path).parent.mkdir(parents=True, exist_ok=True)
    with open(tar_path, "wb") as f:
        with gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0, compresslevel=9) as gz:
            gz.write(buf.getvalue())


V2_SPLITS = ("normal", "normal_holdout", "hard", "hard_holdout", "hard_layout", "hard_layout_holdout")


def pack_all(root: str | Path, dist: str | Path, name: str = GENERATOR_VERSION) -> list[str]:
    """dist/<name>-<split>.tar.gz for every v2 split dir under `root` (e.g. tasks/v2)."""
    made = []
    for split in V2_SPLITS:
        d = Path(root) / split
        if d.is_dir():
            tag = split.replace("_", "-")
            tp = Path(dist) / f"{name}-{tag}.tar.gz"
            pack(d, tp, f"{name}-{tag}")
            made.append(str(tp))
    return made


# ------------------------------------------------------------------ driver
def load_manifest(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


PRIVATE_KEYS = ("seed", "index")   # never in a public manifest (RT37); kept in the private manifest


def public_row(e: dict) -> dict:
    return {k: v for k, v in e.items() if k not in PRIVATE_KEYS}


def _clear(d: Path) -> None:
    """Remove a previous run's output: task dirs, _staging, manifest/stats. Refuses anything else."""
    if not d.exists():
        return
    for c in sorted(d.iterdir()):
        if c.is_dir() and (c.name == "_staging" or (c / "public").is_dir() or (c / "hidden").is_dir()):
            shutil.rmtree(c)
        elif c.is_file() and c.name in ("manifest.jsonl", "generation_stats.json"):
            c.unlink()
        else:
            raise RuntimeError(f"refusing to clear {d}: unexpected entry {c.name}")


def run_pool(fn, jobs: list, workers: int, log, every: int = 25, maxtasks: int = 6) -> list[dict]:
    t0 = time.monotonic()
    if workers <= 1:
        return [fn(j) for j in jobs]
    results = []
    with get_context("spawn").Pool(workers, maxtasksperchild=maxtasks) as pool:
        for i, r in enumerate(pool.imap(fn, jobs, chunksize=1)):
            results.append(r)
            if (i + 1) % every == 0:
                log(f"  {i + 1}/{len(jobs)} done, {sum(x['ok'] for x in results)} ok ({time.monotonic() - t0:.0f} s)")
    return results


def finalize(results: list[dict], outp: Path, holdp: Path, staging: Path, holdout_frac: float,
             tasks_root: Path, dedupe_against: list[str] | None, private: str | None) -> tuple[list, list]:
    """Dedupe, split (smallest sha256(id) -> holdout), move into place, write manifests.
    Returns (accepted, dropped). Public manifest rows carry no seed/index (RT37)."""
    seen_pairs, seen_fhash, seen_ids = set(), set(), set()
    for m in dedupe_against or []:
        for e in load_manifest(m):
            seen_pairs.add((e.get("golden_design_hash"), e.get("fault_set")))
            seen_fhash.add(e.get("faulted_design_hash"))
            seen_ids.add(e.get("id"))
    accepted, dropped = [], []
    for r in results:
        if not r["ok"]:
            dropped.append({"index": r["index"], "family": r.get("family"), "reason": r["reason"]})
            continue
        e = r["entry"]
        key = (e["golden_design_hash"], e["fault_set"])
        if key in seen_pairs or e["faulted_design_hash"] in seen_fhash or e["id"] in seen_ids:
            dropped.append({"index": r["index"], "family": e["family"], "reason": "duplicate"})
            shutil.rmtree(staging / e["id"], ignore_errors=True)
            continue
        seen_pairs.add(key)
        seen_fhash.add(e["faulted_design_hash"])
        seen_ids.add(e["id"])
        accepted.append(e)
    n_hold = round(holdout_frac * len(accepted))
    by_hash = sorted(accepted, key=lambda e: hashlib.sha256(e["id"].encode()).hexdigest())
    hold = {e["id"] for e in by_hash[:n_hold]}
    for e in accepted:
        dst_root = holdp if e["id"] in hold else outp
        e["holdout"] = e["id"] in hold
        e["split"] = Path(os.path.relpath(dst_root, tasks_root)).as_posix()
        e["path"] = f"{e['split']}/{e['id']}"
        dst_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging / e["id"]), str(dst_root / e["id"]))
    shutil.rmtree(staging, ignore_errors=True)
    for d, rows in ((outp, [e for e in accepted if not e["holdout"]]), (holdp, [e for e in accepted if e["holdout"]])):
        if rows or d == outp:
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "manifest.jsonl", "w", encoding="utf-8") as f:
                for e in rows:
                    f.write(json.dumps(public_row(e), sort_keys=True) + "\n")
    if private:
        pp = Path(private)
        pp.parent.mkdir(parents=True, exist_ok=True)
        with open(pp, "w", encoding="utf-8") as f:
            for e in accepted:
                f.write(json.dumps({"id": e["id"], "tier": e.get("tier"), "family": e["family"], "index": e["index"],
                                    "seed": e["seed"], "split": e["split"]}, sort_keys=True) + "\n")
            for d in dropped:
                f.write(json.dumps({"dropped": True, **d}, sort_keys=True) + "\n")
    return accepted, dropped


def generate(out: str, start: int, count: int, holdout_frac: float = 0.2, workers: int = 4,
             dedupe_against: list[str] | None = None, log=print, holdout_out: str | None = None,
             secret: str = "default", private: str | None = None, tasks_root: str | None = None) -> dict:
    """Normal tier: task indices [start, start+count). `secret` is the secret itself (see
    `taskids.load_secret`); `holdout_out` defaults to `<out>_holdout`; split names in the manifest
    are the split dirs relative to `tasks_root` (default: the parent of `out`)."""
    from pcbenv.faults import FAULT_TYPES
    from pcbenv.taskids import secret_fingerprint
    t0 = time.monotonic()
    outp = Path(out)
    holdp = Path(holdout_out) if holdout_out else Path(f"{out}_holdout")
    troot = Path(tasks_root) if tasks_root else outp.parent
    for d in (outp, holdp):
        _clear(d)
    staging = outp / "_staging"
    staging.mkdir(parents=True)
    jobs = [(i, str(staging), secret) for i in range(start, start + count)]
    results = run_pool(build_one, jobs, workers, log)
    accepted, dropped = finalize(results, outp, holdp, staging, holdout_frac, troot, dedupe_against, private)

    # statistics (per fault type: attempts / validity / detection)
    per_type = {t: {"attempts": 0, "applied": 0, "invalid": 0, "not_applicable": 0, "alone_checked": 0,
                    "alone_detected": 0, "replay_mismatch": 0, "in_shipped": 0, "invisible_in_shipped": 0, "families": set()}
                for t in FAULT_TYPES}
    for r in results:
        for t, outcome, _ in r.get("inject_log", []):
            s = per_type[t]
            s["attempts"] += 1
            s["applied" if outcome == "applied" else "invalid" if outcome == "invalid" else "not_applicable"] += 1
        e = r.get("entry")
        if e:
            for a in e["alone"]:
                s = per_type[a["type"]]
                if a.get("replay") == "mismatch":
                    s["replay_mismatch"] += 1   # task dropped; not a detection result
                    continue
                s["alone_checked"] += 1
                s["alone_detected"] += a.get("reward") == 0.0
    for e in accepted:
        for f in e["faults"]:
            s = per_type[f["type"]]
            s["in_shipped"] += 1
            s["invisible_in_shipped"] += f["invisible_to_drc_erc"]
            s["families"].add(e["family"])
    for s in per_type.values():
        s["families"] = sorted(s["families"])
    stats = {
        "args": {"tier": "normal", "out": str(out), "holdout_out": str(holdp), "start_index": start, "count": count,
                 "holdout_frac": holdout_frac, "dedupe_against": dedupe_against or []},
        "generator": GENERATOR_VERSION, "secret_fingerprint": secret_fingerprint(secret),
        "seconds": round(time.monotonic() - t0, 1),
        "accepted": len(accepted), "dropped": len(dropped),
        "drop_reasons": dict(Counter(d["reason"].split(":")[0] for d in dropped)),
        "dropped_tasks": dropped,
        "per_split": dict(Counter(e["split"] for e in accepted)),
        "per_family": dict(sorted(Counter(e["family"] for e in accepted).items())),
        "per_n_faults": dict(sorted(Counter(e["n_faults"] for e in accepted).items())),
        "per_hint": dict(sorted(Counter(e["hint_level"] for e in accepted).items())),
        "share_with_invisible": round(sum(e["has_invisible"] for e in accepted) / max(1, len(accepted)), 4),
        "per_type": per_type,
    }
    (outp / "generation_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    return stats


def combine(manifests: list[str], out: str) -> int:
    """Concatenate per-split public manifests into one (e.g. tasks/manifest.jsonl)."""
    rows = [r for m in manifests for r in load_manifest(m)]
    Path(out).write_text("".join(json.dumps(public_row(r), sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    return len(rows)


def _pct(a: int, b: int) -> str:
    return "n/a" if not b else f"{100.0 * a / b:.1f} %"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m pcbenv.generate", description=__doc__.split("\n")[0])
    ap.add_argument("--tier", choices=("normal", "hard", "hard_layout"), default="normal")
    ap.add_argument("--out", default=None, help="train split dir (default tasks/v2/<tier>)")
    ap.add_argument("--holdout-out", default=None, help="holdout split dir (default <out>_holdout)")
    ap.add_argument("--tasks-root", default="tasks", help="manifest split names are relative to this dir")
    ap.add_argument("--start", "--start-seed", "--seed", dest="start", type=int, default=0, help="first task index")
    ap.add_argument("--count", type=int, default=10, help="number of task indices to try")
    ap.add_argument("--holdout-frac", type=float, default=0.2)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dedupe-against", action="append", default=[], help="manifest.jsonl to dedupe against")
    ap.add_argument("--secret", default=None, help="generation-secret file (default tasks/.secret) or 'default' "
                    "for the documented public reproducibility secret")
    ap.add_argument("--create-secret", action="store_true", help="create the secret file if missing")
    ap.add_argument("--private", default=None, help="private manifest (ids -> index/seed), e.g. tasks/private/normal.jsonl")
    ap.add_argument("--combine", nargs="*", metavar="SPLIT_DIR", help="only write --manifest from these split dirs")
    ap.add_argument("--manifest", default="tasks/manifest.jsonl")
    ap.add_argument("--pack", metavar="V2_ROOT", help="only write deterministic tarballs of V2_ROOT/<split>")
    ap.add_argument("--dist", default="dist", help="tarball directory for --pack")
    a = ap.parse_args(argv)
    if a.combine is not None:
        ms = [str(Path(d) / "manifest.jsonl") for d in a.combine]
        print(f"wrote {a.manifest}: {combine(ms, a.manifest)} rows")
        return 0
    if a.pack:
        for p in pack_all(a.pack, a.dist):
            print(f"wrote {p} ({os.path.getsize(p) / 1e6:.1f} MB, sha256 {_sha(p)})")
        return 0
    from pcbenv.taskids import load_secret
    secret = load_secret(a.secret, create=a.create_secret)
    out = a.out or f"tasks/v2/{a.tier}"
    if a.tier == "hard_layout":
        from pcbenv.generate_hard_layout import generate_hard_layout
        st = generate_hard_layout(out, a.holdout_out or f"{out}_holdout", a.start, a.count, a.holdout_frac, a.workers,
                                  secret=secret, private=a.private, tasks_root=a.tasks_root,
                                  dedupe_against=a.dedupe_against)
    elif a.tier == "hard":
        from pcbenv.generate_hard import generate_hard
        st = generate_hard(out, a.holdout_out or f"{out}_holdout", a.start, a.count, a.holdout_frac, a.workers,
                           secret=secret, private=a.private, tasks_root=a.tasks_root, dedupe_against=a.dedupe_against)
    else:
        st = generate(out, a.start, a.count, a.holdout_frac, a.workers, a.dedupe_against,
                      holdout_out=a.holdout_out, secret=secret, private=a.private, tasks_root=a.tasks_root)
    print(json.dumps({k: v for k, v in st.items() if k not in ("per_type", "dropped_tasks")}, indent=2))
    return 0 if st["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
