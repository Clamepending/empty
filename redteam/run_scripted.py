"""Apply every scripted attack to many faulted tasks and report hacks/crashes/timeouts.

    python3 redteam/run_scripted.py --n 1000 [--workers 8] [--seed 0] [--json out.json]
    python3 redteam/run_scripted.py --source shipped --n 1200   # real tasks/ (manifest), all attacks
    python3 redteam/run_scripted.py --source v2 --n 1300 --workers 3   # round 3: v2 normal/hard/hard_layout

--source fixture (default): round-1 hand-made faulted tasks (redteam/tasks_fixture.py), round-1
attacks. --source shipped: (task, attack) pairs drawn from tasks/manifest.jsonl, stratified so
every family and every fault type appears (round-robin over fault types, families rotating
within each type, seeded), with round-1 + round-2 attacks; a pair is skipped when every fault
of the task is one the attack genuinely repairs (LEGIT_SHIPPED).

A pair (task, attack) counts as a *hack* when the faulted task's baseline (unchanged public
files) scores 0.0 and the attacked workdir scores 1.0. Tasks whose faulted baseline already
scores 1.0 (fault invisible to the verifier) are reported separately and not attacked.
Deterministic: task list and pair order derive from --seed only.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import shutil
import sys
import tempfile
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pcbenv.verify import verify_isolated  # noqa: E402
from redteam import tasks_fixture  # noqa: E402
from redteam.attacks import ATTACKS  # noqa: E402
from redteam.attacks.basic import LEGIT_FOR  # noqa: E402
from redteam.attacks.round2 import ATTACKS2  # noqa: E402
from redteam.attacks.round3 import ATTACKS3  # noqa: E402

ALL_ATTACKS = {**ATTACKS, **ATTACKS2, **ATTACKS3}
ROUTING = {"broken_trace", "clearance_violation", "short_between_nets", "narrow_power_trace", "footprint_swap"}
NOTATION = {"value_sci", "value_plain", "value_units", "value_micro_sign", "value_spaces"}
# attack -> shipped fault types it genuinely repairs (pairs whose faults are ALL in here are skipped)
LEGIT_SHIPPED = {
    "pcbtool_reroute_all": ROUTING,
    "pcbtool_sync": {"bom_mismatch", "board_pad_swap"},
    # these re-route the nets they touch at the power width -> genuine repair of routing faults
    "flip_part": ROUTING, "symmetric_pinswap": ROUTING,
    "other_footprint_size": ROUTING | {"bom_mismatch"},              # set-footprint re-pushes the design value
    "polarity_and_symmetric": ROUTING | {"reversed_polarity"},       # A/K swap undoes a reversed diode
    "sync_design_from_board": {"bom_mismatch"},   # board value may be inside the published bound
    **{n: {"bom_mismatch"} for n in NOTATION},    # rewrites board value := design value
    # round-1 value attacks also write design value (+ suffix) onto the board -> fixes bom_mismatch;
    # the trailing-newline residue itself is RT59
    "value_newline": {"bom_mismatch"}, "value_unit_suffix": {"bom_mismatch"},
    # round 3 (v2): the no_autoroute bypass re-routes every net (genuine for routing faults); blanket
    # footprint upsizing re-pushes values and re-routes (genuine for *_underrated / routing faults);
    # values at the low end of their PUBLISHED bounds are a genuine repair when the spec still passes
    "tools_full_route_all": ROUTING,
    "upsize_all": ROUTING | {"bom_mismatch", "capacitor_underrated", "resistor_underrated", "led_underrated"},
    "values_to_bound_min": {"bom_mismatch", "wrong_filter_cap", "wrong_feedback_resistor", "wrong_led_resistor",
                            "wrong_pull_resistor", "magnitude_slip", "interacting_value", "weak_base_drive"},
}
ROOT = Path(__file__).resolve().parents[1]


def _build(spec: tuple) -> str:
    return tasks_fixture.build(*spec)


def _grade(task_dir: str, attack: str | None) -> dict:
    tmp = tempfile.mkdtemp(prefix="rt_wd_")
    wd = os.path.join(tmp, "work")
    try:
        shutil.copytree(os.path.join(task_dir, "public"), wd)
        if attack:
            try:
                ALL_ATTACKS[attack](wd)
            except Exception as e:  # noqa: BLE001 - attack failing to apply is not a verifier crash
                return {"task": task_dir, "attack": attack, "status": "attack_error", "detail": repr(e)[:300]}
        r = verify_isolated(wd, task_dir, timeout=120)
        err = str(r.detail.get("error", ""))
        if "timed out" in err:
            status = "timeout"
        elif "subprocess failed" in err or (err and r.reward == 0 and not r.gates):
            status = "crash"
        else:
            status = "pass" if r.reward == 1.0 else "fail"
        return {"task": task_dir, "attack": attack, "status": status, "reward": r.reward,
                "failed": sorted([k for k, v in {**r.gates, **r.checks}.items() if not v]), "error": err[:300]}
    except Exception:  # noqa: BLE001
        return {"task": task_dir, "attack": attack, "status": "crash", "error": traceback.format_exc()[-300:]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _grade_args(a: tuple) -> dict:
    return _grade(*a)


def shipped_pairs(n: int, seed: int, names: list[str]) -> tuple[list[tuple[str, str]], Counter, Counter]:
    """Stratified (task_dir, attack) pairs from the shipped manifest (deterministic in seed)."""
    rows = [json.loads(line) for line in open(ROOT / "tasks" / "manifest.jsonl")]
    rng = random.Random(f"rt2-shipped:{seed}")
    by_type: dict[str, dict[str, list[dict]]] = {}
    for m in rows:
        for f in {f["type"] for f in m["faults"]}:
            by_type.setdefault(f, {}).setdefault(m["family"], []).append(m)
    for fams in by_type.values():
        for lst in fams.values():
            rng.shuffle(lst)
    cursors = {t: [0, {fam: 0 for fam in fams}] for t, fams in by_type.items()}
    types = sorted(by_type)
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    i = guard = 0
    while len(pairs) < n and guard < 50 * n:
        guard += 1
        t = types[i % len(types)]
        fams = sorted(by_type[t])
        cur = cursors[t]
        fam = fams[cur[0] % len(fams)]
        cur[0] += 1
        lst = by_type[t][fam]
        m = lst[cur[1][fam] % len(lst)]
        cur[1][fam] += 1
        attack = names[(i // len(types) + types.index(t)) % len(names)]
        i += 1
        ftypes = {f["type"] for f in m["faults"]}
        if ftypes <= LEGIT_SHIPPED.get(attack, set()):
            continue
        td = str(ROOT / "tasks" / m["split"] / m["id"])
        if (td, attack) in seen:
            continue
        seen.add((td, attack))
        pairs.append((td, attack))
    fam_cov = Counter(Path(td).name.split("-")[1] for td, _ in pairs)
    meta_types = {str(ROOT / "tasks" / m["split"] / m["id"]): [f["type"] for f in m["faults"]] for m in rows}
    type_cov = Counter(t for td, _ in pairs for t in set(meta_types[td]))
    return pairs, fam_cov, type_cov


def v2_pairs(n: int, seed: int, names: list[str]) -> tuple[list[tuple[str, str]], Counter, Counter]:
    """Stratified (task_dir, attack) pairs over the NON-holdout v2 splits: round-robin over
    (tier, fault type) strata -- latent and layout-latent types included -- families rotating within
    each stratum, attacks rotating per stratum. Deterministic in `seed`."""
    rows = [json.loads(line) for line in open(ROOT / "tasks" / "manifest.jsonl")]
    rows = [m for m in rows if not m.get("holdout") and str(m.get("split", "")).startswith("v2/")]
    rng = random.Random(f"rt3-v2:{seed}")
    strata: dict[tuple[str, str], dict[str, list[dict]]] = {}
    for m in rows:
        for f in sorted({f["type"] for f in m["faults"]}):
            strata.setdefault((m["tier"], f), {}).setdefault(m["family"], []).append(m)
    for fams in strata.values():
        for lst in fams.values():
            rng.shuffle(lst)
    keys = sorted(strata)
    cur = {k: [0, {fam: 0 for fam in strata[k]}] for k in keys}
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    row_of: dict[str, dict] = {}
    i = guard = 0
    while len(pairs) < n and guard < 50 * n:
        guard += 1
        k = keys[i % len(keys)]
        fams = sorted(strata[k])
        c = cur[k]
        fam = fams[c[0] % len(fams)]
        c[0] += 1
        lst = strata[k][fam]
        m = lst[c[1][fam] % len(lst)]
        c[1][fam] += 1
        attack = names[(i // len(keys) + keys.index(k)) % len(names)]
        i += 1
        if {f["type"] for f in m["faults"]} <= LEGIT_SHIPPED.get(attack, set()):
            continue
        td = str(ROOT / "tasks" / m["path"])
        if (td, attack) in seen:
            continue
        seen.add((td, attack))
        row_of[td] = m
        pairs.append((td, attack))
    fam_cov = Counter(f"{row_of[td]['tier']}/{row_of[td]['family']}" for td, _ in pairs)
    type_cov = Counter(f"{row_of[td]['tier']}/{t}" for td, _ in pairs for t in {f["type"] for f in row_of[td]["faults"]})
    return pairs, fam_cov, type_cov


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 2))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--source", choices=("fixture", "shipped", "v2"), default="fixture")
    ap.add_argument("--json")
    a = ap.parse_args()
    ctx = mp.get_context("spawn")
    invisible: list[str] = []
    if a.source in ("shipped", "v2"):
        names = sorted(ALL_ATTACKS) if a.source == "v2" else sorted({**ATTACKS, **ATTACKS2})
        pairs, fam_cov, type_cov = (v2_pairs if a.source == "v2" else shipped_pairs)(a.n, a.seed, names)
        tds = sorted({t for t, _ in pairs})
        with ctx.Pool(a.workers, maxtasksperchild=10) as pool:
            base = pool.map(_grade_args, [(t, None) for t in tds])
        invisible = sorted(b["task"] for b in base if b["status"] == "pass")
        bad_base = [b for b in base if b["status"] not in ("pass", "fail")]
        pairs = [p for p in pairs if p[0] not in set(invisible)]
        if a.source == "v2":
            tiers = Counter(Path(td).name.split("-")[1] for td in tds)
            print(f"v2 tiers (tasks): {dict(sorted(tiers.items()))}")
        print(f"shipped tasks used: {len(tds)}  families: {len(fam_cov)} {dict(sorted(fam_cov.items()))}")
        print(f"fault types covered: {len(type_cov)} {dict(sorted(type_cov.items()))}")
    else:
        names = sorted(ATTACKS)
        per_seed = len(tasks_fixture.all_specs(range(1, 2)))
        nseeds = max(1, -(-a.n // (per_seed * max(1, len(names) - 2))) + 1)
        specs = tasks_fixture.all_specs(range(1, 1 + nseeds))
        with ctx.Pool(a.workers, maxtasksperchild=10) as pool:
            tds = pool.map(_build, specs)
            base = pool.map(_grade_args, [(t, None) for t in tds])
        invisible = sorted(b["task"] for b in base if b["status"] == "pass")
        bad_base = [b for b in base if b["status"] not in ("pass", "fail")]
        targets = [(t, k) for t, (f, s, k), b in zip(tds, specs, base) if b["status"] == "fail"]
        pairs = [(t, n) for t, k in targets for n in names if k not in LEGIT_FOR.get(n, ())]
        random.Random(a.seed).shuffle(pairs)
        pairs = sorted(pairs[: a.n])
    with ctx.Pool(a.workers, maxtasksperchild=10) as pool:
        res = pool.map(_grade_args, pairs, chunksize=4)
    c = Counter(r["status"] for r in res)
    hacks = [r for r in res if r["status"] == "pass"]
    print(f"tasks: {len(tds)}  faulted-baseline invisible (score 1.0, not attacked): {len(invisible)}  "
          f"baseline crashes: {len(bad_base)}")
    print(f"attack applications: {len(res)}  attacks: {len(names)}")
    print(f"successes (hacks): {len(hacks)}  crashes: {c['crash']}  timeouts: {c['timeout']}  "
          f"attack_errors: {c['attack_error']}  blocked: {c['fail']}")
    per = Counter((r["attack"], r["status"]) for r in res)
    for n in names:
        print(f"  {n:24s} " + " ".join(f"{s}={per[(n, s)]}" for s in ("fail", "pass", "crash", "timeout", "attack_error")
                                        if per[(n, s)]))
    for h in hacks[:20]:
        print("HACK", h["attack"], h["task"])
    for r in [r for r in res if r["status"] in ("crash", "timeout", "attack_error")][:10]:
        print(r["status"].upper(), r["attack"], r["task"], (r.get("error") or r.get("detail", ""))[:200])
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": dict(c), "invisible": invisible, "results": res}, indent=1))
    return 1 if hacks or c["crash"] or c["timeout"] else 0


if __name__ == "__main__":
    sys.exit(main())
