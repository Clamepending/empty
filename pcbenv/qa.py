"""Expert-QA review packets (G9): build reviewer packets for a stratified task sample, tally reviews.

    python3 -m pcbenv.qa build --n 100 --out qa/packets --seed 7 [--mix normal=60,hard=25,hard_layout=15] [--workers 4]
    python3 -m pcbenv.qa tally qa/packets

Only TRAIN tasks are ever used (manifest row not holdout AND no path part of the task dir contains
"holdout", e.g. `tasks/v2/normal/` or `tasks/v2/hard/`); holdout tasks are refused. A packet is `<out>/<nn>-<task_id>/`:

- `README.md`   TASK.md verbatim (what the agent sees) + reviewer-only section (faults, reference
                fix as a diff, verifier verdicts on faulted and golden files, spec assertions
                before/after, value bounds; hard tiers: latent faults with the exact public sentence
                that reveals them, design-rule quantities before/after; hard_layout: layout-rule
                metrics before/after with the loop polygon / rule copper paths drawn on the board).
- `*.svg`       schematic-style netlist graph and board plot, faulted and golden (pure-python SVG).
- `review.yaml` the form the EE fills (`review-<initials>.yaml` for further reviewers).

Everything written is a deterministic function of (manifest, task dirs, n, seed): no timestamps,
no timings, no temp paths.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DISPUTED_TYPES = ("bom_mismatch", "footprint_swap", "decap_moved_far", "narrow_power_trace",
                  # v2 hard tiers: requirement inferred from intent text / a stated limit, not a function
                  "bias_wrong_rail", "decap_swapped", "pullup_wrong_rail", "mcu_pin_swap", "connector_pin_swap",
                  "switch_loop_spread", "analog_near_switch", "decap_long_path", "crystal_far")
LAYOUT_LATENT = ("kelvin_sense_tap", "switch_loop_spread", "crystal_far", "crystal_via", "analog_near_switch",
                 "decap_long_path")
TIERS = ("normal", "hard", "hard_layout")
DEFAULT_MIX = "normal=60,hard=25,hard_layout=15"
NEAR_BOUND_FACTOR = 1.5
AGREEMENT_MIN = 0.95  # acceptance rule (not yet in thresholds.yaml; orchestrator-owned)

REVIEW_FIELDS = {
    "task_fair": ("yes", "no", "unsure"),
    "solvable_from_public_material": ("yes", "no"),
    "reference_fix_correct": ("yes", "no"),
    "verifier_verdict_agrees": ("yes", "no"),
    "alternative_valid_fixes_rejected": None,   # "none" or free text
    "severity_if_wrong": ("low", "med", "high"),
    "rule_stated_clearly": ("yes", "no"),
    "layout_rule_reasonable": ("yes", "no", "n/a"),
}

REVIEW_TEMPLATE = """\
# Expert review form for packet {packet}  (task {task_id})
# Fill every field; leave a field empty ("") if you have not decided yet (counts as pending).
# Answer from the packet README (sections 1-2) and renders. ~5 min per packet.
reviewer: ""                          # your initials
task_fair: ""                         # yes | no | unsure  -- is this a fair task for an engineer?
solvable_from_public_material: ""     # yes | no  -- section 1 (TASK.md, datasheets, files) is enough
reference_fix_correct: ""             # yes | no  -- section 2.2 (golden) is a correct repair
verifier_verdict_agrees: ""           # yes | no  -- section 2.3 verdicts match your judgement
alternative_valid_fixes_rejected: ""  # none | <describe a valid repair the grader would reject>
severity_if_wrong: ""                 # low | med | high  -- impact if task/verifier is wrong
rule_stated_clearly: ""               # yes | no  -- every graded design/layout rule and latent requirement (2.7-2.9) is stated clearly in public text
layout_rule_reasonable: ""            # yes | no | n/a  -- hard_layout: limits/definitions in 2.9 are defensible practice (else n/a)
notes: ""
"""


# ====================================================================== task selection
def is_holdout_row(r: dict) -> bool:
    return bool(r.get("holdout")) or "holdout" in str(r.get("split", ""))


def task_dir_of(tasks_root: Path, r: dict) -> Path:
    """`tasks_root/<split>/<id>` (v2 splits are paths such as `v2/normal`)."""
    return tasks_root / str(r.get("split", "")) / r["id"]


def load_train_rows(manifest: Path, tasks_root: Path) -> list[dict]:
    """Manifest rows of TRAIN (non-holdout) tasks whose directory exists under `tasks_root/<split>`
    (v1: split `train`; v2: `v2/normal`, `v2/hard`)."""
    rows = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if is_holdout_row(r):
            continue
        d = task_dir_of(tasks_root, r)
        if not d.is_dir() or any("holdout" in part for part in d.resolve().parts):
            continue
        rows.append(r)
    return sorted(rows, key=lambda r: r["id"])


def _pv(s: str) -> float | None:
    from pcbenv.parts import parse_value
    try:
        return parse_value(str(s))
    except Exception:  # noqa: BLE001
        return None


def near_bound_faults(faults: list[dict], bounds: dict) -> list[str]:
    """Value faults whose wrong value is inside its acceptable range or within x1.5 of a bound
    (the cases where 'is this really wrong?' is a judgement call)."""
    out = []
    for f in faults:
        if f.get("category") != "value":
            continue
        d = f.get("data") or {}
        ref = d.get("ref")
        v = _pv(d.get("board_value") or d.get("value") or "")
        if ref not in bounds or v is None:
            continue
        lo, hi = bounds[ref]
        if lo <= v <= hi:
            out.append(f"{ref}={d.get('board_value') or d.get('value')} inside [{lo:g}, {hi:g}]")
        elif lo / NEAR_BOUND_FACTOR <= v <= hi * NEAR_BOUND_FACTOR:
            out.append(f"{ref}={d.get('board_value') or d.get('value')} near [{lo:g}, {hi:g}]")
    return out


def tier_of(row: dict) -> str:
    return str(row.get("tier") or str(row.get("split", "")).split("/")[-1] or "v1")


def parse_mix(text: str) -> dict[str, float]:
    """`normal=60,hard=25,hard_layout=15` -> {tier: weight}."""
    out: dict[str, float] = {}
    for part in str(text).split(","):
        if not part.strip():
            continue
        k, _, v = part.partition("=")
        k = k.strip()
        if k not in TIERS or not v.strip():
            raise ValueError(f"bad --mix entry {part!r} (tiers: {', '.join(TIERS)})")
        if "holdout" in k:
            raise ValueError("holdout splits are never sampled")
        out[k] = float(v)
        if out[k] < 0:
            raise ValueError(f"negative weight in --mix: {part!r}")
    if not out or sum(out.values()) <= 0:
        raise ValueError(f"empty --mix {text!r}")
    return out


def tier_quotas(n: int, mix: dict[str, float], available: dict[str, int] | None = None) -> dict[str, int]:
    """Largest-remainder split of n over the mix weights (ties by TIERS order), capped by
    `available` per tier (overflow goes to the other tiers by weight)."""
    tot = sum(mix.values())
    exact = {t: n * w / tot for t, w in mix.items()}
    q = {t: int(math.floor(x)) for t, x in exact.items()}
    order = sorted(mix, key=lambda t: (-(exact[t] - q[t]), TIERS.index(t)))
    for t in order[: n - sum(q.values())]:
        q[t] += 1
    if available is not None:
        spare = 0
        for t in list(q):
            if q[t] > available.get(t, 0):
                spare += q[t] - available.get(t, 0)
                q[t] = available.get(t, 0)
        for t in sorted(mix, key=lambda t: (-mix[t], TIERS.index(t))):
            add = min(spare, available.get(t, 0) - q[t])
            q[t] += add
            spare -= add
    return q


def task_features(row: dict, meta: dict, public_text: str | list | None = None) -> dict:
    """Strata keys and ambiguity score of one task. `public_text` (TASK.md + spec.json + parts/*.md)
    enables the latent-evidence check: a latent fault whose evidence text is missing from the
    public material is the strongest 'unfair task' signal."""
    tier = tier_of(row)
    types = [f["type"] for f in row["faults"]]
    cats = [f["category"] for f in row["faults"]]
    near = near_bound_faults(meta.get("faults", []), meta.get("value_bounds") or {})
    latent = [t for t, c in zip(types, cats) if c == "latent"]
    lay_lat = [t for t in latent if t in LAYOUT_LATENT]
    mode = row.get("tools_mode") or meta.get("tools_mode") or "full"
    many = row["n_faults"] >= (5 if tier.startswith("hard") else 3)
    reasons = []
    if many:
        reasons.append(f"{row['n_faults']} faults")
    if row["hint_level"] == "vague":
        reasons.append("vague hint")
    if "connectivity" in cats:
        reasons.append("connectivity fault")
    for t in sorted(set(types) & set(DISPUTED_TYPES)):
        reasons.append(f"disputable type {t}")
    if near:
        reasons.append("value near bounds: " + "; ".join(near))
    if latent:
        reasons.append(f"{len(latent)} latent ({', '.join(sorted(set(latent)))})")
    if row.get("n_interacting"):
        reasons.append("interacting value fault")
    if mode == "no_autoroute":
        reasons.append("no_autoroute")
    missing = []
    if public_text is not None and latent:
        from pcbenv.faults.latent import missing_evidence
        for f in meta.get("faults", []):
            if f.get("category") == "latent" and missing_evidence(f, public_text):
                missing.append(f["type"])
        if missing:
            reasons.append("latent evidence NOT found in public text: " + ", ".join(missing))
    score = (many + (row["hint_level"] == "vague") + 0.5 * ("connectivity" in cats)
             + len(set(types) & set(DISPUTED_TYPES)) + bool(near) + min(1.5, 0.5 * len(latent))
             + 1.0 * bool(lay_lat) + 0.5 * bool(row.get("n_interacting")) + 0.5 * (mode == "no_autoroute")
             + 3.0 * bool(missing))
    keys = [("tier", tier), ("family", row["family"]), ("fam_tier", tier, row["family"]),
            ("hint", tier, row["hint_level"]), ("nf", tier, row["n_faults"]),
            ("fam_hint", row["family"], row["hint_level"]), ("tools", tier, mode),
            ("intent", tier, row.get("intent", "")), ("nlat", tier, len(latent))]
    for t in sorted(set(types)):
        keys += [("ftype", t), ("ftype_hint", t, row["hint_level"]), ("fam_ftype", row["family"], t)]
    for r in sorted(meta.get("layout_rules") or {}):
        if r != "version":
            keys.append(("lrule", r))
    return {"keys": keys, "score": score, "reasons": reasons, "missing_evidence": missing}


KEY_WEIGHTS = {"tier": 0.0, "family": 1.0, "fam_tier": 3.0, "hint": 3.0, "nf": 12.0, "fam_hint": 2.0, "tools": 3.0, "intent": 1.0,
               "nlat": 2.0, "ftype": 5.0, "ftype_hint": 1.0, "fam_ftype": 1.0, "lrule": 3.0}
FAULT_KEYS = ("ftype", "ftype_hint", "fam_ftype")  # divided by #faults so many-fault tasks don't win by count
AMBIG_WEIGHT = 0.25


def _gain(r: dict, f: dict, counts: Counter, jitter: float) -> float:
    nf = max(1, r["n_faults"])
    cov = sum(KEY_WEIGHTS[k[0]] / (1 + counts[k]) / (nf if k[0] in FAULT_KEYS else 1) for k in f["keys"])
    return cov * (1 + AMBIG_WEIGHT * f["score"]) + jitter


def select_tasks(rows: list[dict], metas: dict[str, dict], n: int, seed: int,
                 mix: dict[str, float] | None = None, public: dict[str, str] | None = None) -> list[dict]:
    """Greedy stratified sample: each pick maximises coverage gain over strata (tier, family, hint,
    #faults, tool mode, intent, #latent, family x hint, fault type, fault type x hint, family x fault
    type, layout rule), each stratum giving weight/(1+already picked), times an ambiguity
    multiplier; seeded jitter breaks ties. With `mix`, picks are drawn per tier up to its quota
    (strata counts are shared across tiers). A final repair pass swaps in a task for every fault
    type of the eligible tiers that the greedy pass left uncovered."""
    rng = random.Random(seed)
    public = public or {}
    feats = {r["id"]: task_features(r, metas[r["id"]], public.get(r["id"])) for r in rows}
    jitter = {r["id"]: rng.random() * 1e-3 for r in rows}
    if mix:
        avail = Counter(tier_of(r) for r in rows)
        quota = tier_quotas(min(n, len(rows)), mix, dict(avail))
    else:
        quota = None
    counts: Counter = Counter()
    chosen: list[dict] = []
    taken: Counter = Counter()
    left = [r for r in rows if quota is None or quota.get(tier_of(r), 0) > 0]
    while left and len(chosen) < n:
        best = max(left, key=lambda r: _gain(r, feats[r["id"]], counts, jitter[r["id"]]))
        left.remove(best)
        chosen.append(best)
        counts.update(feats[best["id"]]["keys"])
        taken[tier_of(best)] += 1
        if quota is not None and taken[tier_of(best)] >= quota.get(tier_of(best), 0):
            left = [r for r in left if tier_of(r) != tier_of(best)]
    # coverage repair: every fault type of the eligible tiers appears at least once
    eligible = [r for r in rows if quota is None or quota.get(tier_of(r), 0) > 0]
    universe = sorted({f["type"] for r in eligible for f in r["faults"]})
    for t in universe:
        have = Counter(f2 for r in chosen for f2 in {f["type"] for f in r["faults"]})
        if have[t]:
            continue
        ids = {r["id"] for r in chosen}
        cands = [r for r in eligible if r["id"] not in ids and t in {f["type"] for f in r["faults"]}]
        if not cands:
            continue
        add = max(cands, key=lambda r: (feats[r["id"]]["score"], jitter[r["id"]]))
        same = [r for r in chosen if tier_of(r) == tier_of(add)] if quota is not None else list(chosen)
        removable = [r for r in same if all(have[x] > 1 for x in {f["type"] for f in r["faults"]})]
        if not removable:
            continue
        out = min(removable, key=lambda r: (feats[r["id"]]["score"], jitter[r["id"]]))
        chosen[chosen.index(out)] = add
    return chosen


# ====================================================================== formatting helpers
def _fmt(x, unit: str = "") -> str:
    from pcbenv.taskio import _fmt as f
    if x is None:
        return "—"
    try:
        return f(float(x), unit)
    except (TypeError, ValueError):
        return str(x)


def _md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _fence(text: str) -> str:
    longest = max([len(m) for m in re.findall(r"`+", text)] + [2])
    return "`" * max(4, longest + 1)


# ====================================================================== diffs
def pin_nets(design: dict) -> dict[str, str]:
    return {p: n for n, pins in design["nets"].items() for p in pins}


def match_nets(design: dict, golden: dict) -> dict[str, str]:
    """Greedy max-overlap matching of design nets onto golden nets (deterministic)."""
    pairs = sorted(((-len(set(design["nets"][a]) & set(golden["nets"][b])), a, b)
                    for a in design["nets"] for b in golden["nets"]))
    out: dict[str, str] = {}
    used: set[str] = set()
    for ov, a, b in pairs:
        if ov == 0 or a in out or b in used:
            continue
        out[a] = b
        used.add(b)
    return out


def moved_pins(design: dict, golden: dict) -> set[str]:
    """Pins whose connection differs from the golden once nets are matched: unconnected on one
    side, or sitting on a net whose best golden match is not the pin's golden net."""
    m = match_nets(design, golden)
    dn, gn = pin_nets(design), pin_nets(golden)
    out = set()
    for p in set(dn) | set(gn):
        if p not in dn or p not in gn or m.get(dn[p]) != gn[p]:
            out.add(p)
    return out


def connection_diff(faulted: dict, golden: dict, ref_parts: dict[str, str]) -> list[str]:
    """Human-readable lines for each pin the reference fix re-connects (faulted -> golden)."""
    fp, gp = pin_nets(faulted), pin_nets(golden)
    lines = []
    for p in sorted(moved_pins(faulted, golden)):
        def desc(d, nets, pin):
            if pin not in nets:
                return "unconnected"
            others = sorted(set(d["nets"][nets[pin]]) - {pin})
            return f"net `{nets[pin]}` ({', '.join(others) or 'no other pins'})"
        lines.append(f"`{p}`: faulted {desc(faulted, fp, p)} → golden {desc(golden, gp, p)}")
    return lines


def design_diff(faulted: dict, golden: dict) -> list[str]:
    out = []
    fc, gc = faulted["components"], golden["components"]
    for ref in sorted(set(fc) | set(gc)):
        a, b = fc.get(ref, {}), gc.get(ref, {})
        for k in ("part", "value", "footprint"):
            if a.get(k, "") != b.get(k, ""):
                out.append(f"`{ref}` {k}: `{a.get(k, '')}` → `{b.get(k, '')}`")
    return out


def _track_key(t) -> tuple:
    s, e = t.GetStart(), t.GetEnd()
    a, b = (round(s.x / 1e6, 3), round(s.y / 1e6, 3)), (round(e.x / 1e6, 3), round(e.y / 1e6, 3))
    if t.GetClass() == "PCB_VIA":
        return ("via", a, round(t.GetWidth() / 1e6, 3))
    if t.GetClass() == "PCB_ARC":
        m = t.GetMid()
        return (t.GetLayerName(), min(a, b), max(a, b), round(t.GetWidth() / 1e6, 3),
                (round(m.x / 1e6, 3), round(m.y / 1e6, 3)))
    return (t.GetLayerName(), min(a, b), max(a, b), round(t.GetWidth() / 1e6, 3))


def board_geometry(path: str) -> dict:
    """Plain-python snapshot of a board for diffing and rendering."""
    import pcbnew

    from pcbenv import boardnet
    b = boardnet.load_board(path)
    bb = b.GetBoardEdgesBoundingBox()
    geo = {"bbox": (bb.GetX() / 1e6, bb.GetY() / 1e6, bb.GetWidth() / 1e6, bb.GetHeight() / 1e6),
           "edges": [], "footprints": {}, "tracks": [], "vias": []}
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts and d.GetClass() == "PCB_SHAPE":
            geo["edges"].append(_shape_pts(d))
    for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
        ref = fp.GetReference()
        pos = fp.GetPosition()
        crt = [_shape_pts(g) for g in fp.GraphicalItems()
               if g.GetLayer() in (pcbnew.F_CrtYd, pcbnew.B_CrtYd) and g.GetClass() in ("MGRAPHIC", "FP_SHAPE", "PCB_SHAPE")]
        pads = []
        for p in sorted(fp.Pads(), key=lambda p: p.GetNumber()):
            pp, sz = p.GetPosition(), p.GetSize()
            pads.append({"num": p.GetNumber(), "x": pp.x / 1e6, "y": pp.y / 1e6, "w": sz.x / 1e6, "h": sz.y / 1e6,
                         "rot": round(p.GetOrientationDegrees(), 3), "shape": int(p.GetShape()),
                         "net": p.GetNetname(), "th": p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH})
        geo["footprints"][ref] = {"x": pos.x / 1e6, "y": pos.y / 1e6, "rot": round(fp.GetOrientationDegrees(), 3),
                                  "side": "B" if fp.IsFlipped() else "F", "fpid": str(fp.GetFPIDAsString()),
                                  "value": fp.GetValue(), "crt": crt, "pads": pads}
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            p = t.GetPosition()
            geo["vias"].append({"x": p.x / 1e6, "y": p.y / 1e6, "d": t.GetWidth() / 1e6, "net": t.GetNetname(),
                                "key": _track_key(t)})
        else:
            pts = [(t.GetStart().x / 1e6, t.GetStart().y / 1e6)]
            if t.GetClass() == "PCB_ARC":
                pts.append((t.GetMid().x / 1e6, t.GetMid().y / 1e6))
            pts.append((t.GetEnd().x / 1e6, t.GetEnd().y / 1e6))
            geo["tracks"].append({"pts": pts, "w": t.GetWidth() / 1e6, "layer": t.GetLayerName(),
                                  "net": t.GetNetname(), "key": _track_key(t)})
    geo["tracks"].sort(key=lambda t: repr(t["key"]))
    geo["vias"].sort(key=lambda t: repr(t["key"]))
    return geo


def _shape_pts(s) -> list[tuple[float, float]]:
    import pcbnew
    t = s.GetShape()
    if t == pcbnew.SHAPE_T_RECT:
        try:
            return [(c.x / 1e6, c.y / 1e6) for c in s.GetRectCorners()] + [(s.GetRectCorners()[0].x / 1e6,
                                                                            s.GetRectCorners()[0].y / 1e6)]
        except Exception:  # noqa: BLE001
            a, b = s.GetStart(), s.GetEnd()
            return [(a.x / 1e6, a.y / 1e6), (b.x / 1e6, a.y / 1e6), (b.x / 1e6, b.y / 1e6), (a.x / 1e6, b.y / 1e6),
                    (a.x / 1e6, a.y / 1e6)]
    if t == pcbnew.SHAPE_T_POLY:
        o = s.GetPolyShape().Outline(0)
        pts = [(o.CPoint(i).x / 1e6, o.CPoint(i).y / 1e6) for i in range(o.PointCount())]
        return pts + pts[:1]
    if t == pcbnew.SHAPE_T_CIRCLE:
        c, r = s.GetCenter(), s.GetRadius()
        return [((c.x + r * math.cos(a)) / 1e6, (c.y + r * math.sin(a)) / 1e6)
                for a in [i * math.pi / 12 for i in range(25)]]
    if t == pcbnew.SHAPE_T_ARC:
        return [(p.x / 1e6, p.y / 1e6) for p in (s.GetStart(), s.GetArcMid(), s.GetEnd())]
    return [(s.GetStart().x / 1e6, s.GetStart().y / 1e6), (s.GetEnd().x / 1e6, s.GetEnd().y / 1e6)]


def board_diff(fgeo: dict, ggeo: dict) -> dict:
    """Summary of what the reference fix changes on the board (faulted -> golden)."""
    out = {"footprints": [], "pad_nets": [], "nets_rerouted": [], "values": []}
    for ref in sorted(set(fgeo["footprints"]) | set(ggeo["footprints"])):
        a, b = fgeo["footprints"].get(ref), ggeo["footprints"].get(ref)
        if a is None or b is None:
            out["footprints"].append(f"`{ref}` present only in {'golden' if a is None else 'faulted'}")
            continue
        if a["fpid"] != b["fpid"]:
            out["footprints"].append(f"`{ref}` footprint `{a['fpid']}` → `{b['fpid']}`")
        if (round(a["x"], 3), round(a["y"], 3), a["rot"] % 360, a["side"]) != \
                (round(b["x"], 3), round(b["y"], 3), b["rot"] % 360, b["side"]):
            d = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
            out["footprints"].append(f"`{ref}` moved ({a['x']:.2f}, {a['y']:.2f}, {a['rot']:g}°, {a['side']}) → "
                                     f"({b['x']:.2f}, {b['y']:.2f}, {b['rot']:g}°, {b['side']}), {d:.2f} mm")
        if a["value"] != b["value"]:
            out["values"].append(f"`{ref}` board value `{a['value']}` → `{b['value']}`")
        if a["fpid"] == b["fpid"]:
            bn = {p["num"]: p["net"] for p in b["pads"]}
            for p in a["pads"]:
                if p["num"] in bn and p["net"] != bn[p["num"]]:
                    out["pad_nets"].append(f"`{ref}` pad {p['num']}: net `{p['net'] or '(none)'}` → "
                                           f"`{bn[p['num']] or '(none)'}`")
    fk, gk = defaultdict(set), defaultdict(set)
    fw, gw = defaultdict(list), defaultdict(list)
    for geo, keys, widths in ((fgeo, fk, fw), (ggeo, gk, gw)):
        for t in geo["tracks"]:
            keys[t["net"]].add(t["key"])
            widths[t["net"]].append(t["w"])
        for v in geo["vias"]:
            keys[v["net"]].add(v["key"])
    for net in sorted(set(fk) | set(gk)):
        rem, add = fk[net] - gk[net], gk[net] - fk[net]
        if not rem and not add:
            continue
        line = f"net `{net or '(no net)'}`: {len(rem)} track/via item(s) removed, {len(add)} added"
        if fw[net] and gw[net] and abs(min(fw[net]) - min(gw[net])) > 1e-6:
            line += f"; narrowest track {min(fw[net]):.3g} mm → {min(gw[net]):.3g} mm"
        out["nets_rerouted"].append(line)
    return out


# ====================================================================== SVG: board
LAYER_COLORS = {"F.Cu": "#c83434", "B.Cu": "#3b6fd1"}


def _palette(name: str) -> str:
    h = int(hashlib.sha256(name.encode()).hexdigest()[:6], 16)
    return f"hsl({h % 360},60%,38%)"


def render_board_svg(geo: dict, other: dict | None, title: str, overlay: dict | None = None) -> str:
    """Board plot: outline, courtyards, pads (net-labelled), tracks by layer, vias. Items that
    differ from `other` (the counterpart board) are drawn with a yellow halo / magenta box.
    `overlay` (hard_layout, `layout_overlay`): switching-loop polygon, rule copper paths, Kelvin
    sense island, separation stretches."""
    x0, y0, w, h = geo["bbox"]
    pad_mm = 2.0
    scale = 20.0  # px per mm
    W, H = (w + 2 * pad_mm) * scale, (h + 2 * pad_mm) * scale + 40
    okeys = set()
    ofp = {}
    if other is not None:
        okeys = {t["key"] for t in other["tracks"]} | {v["key"] for v in other["vias"]}
        ofp = other["footprints"]

    def X(x):
        return f"{(x - x0 + pad_mm) * scale:.1f}"

    def Y(y):
        return f"{(y - y0 + pad_mm) * scale + 40:.1f}"

    def poly(pts):
        return " ".join(f"{X(px)},{Y(py)}" for px, py in pts)

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
         f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="Helvetica,Arial,sans-serif">',
         f'<rect width="100%" height="100%" fill="#f7f5ee"/>',
         f'<text x="8" y="18" font-size="15" font-weight="bold">{html.escape(title)}</text>',
         '<text x="8" y="34" font-size="11">red = F.Cu track, blue = B.Cu track, grey = courtyard, '
         'yellow halo = differs from the other board, magenta box = footprint moved/changed</text>']
    if overlay is not None:
        H += 16
        o[0] = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
                f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="Helvetica,Arial,sans-serif">')
        o.append('<text x="8" y="{:.0f}" font-size="11">layout rules: purple fill = switching-loop polygon, '
                 'cyan dashed = rule copper paths (crystal / decoupling), green glow = Kelvin sense island '
                 '(shunt pad deleted), black dash = analog track within the separation gap</text>'.format(H - 6))
    for e in geo["edges"]:
        o.append(f'<polyline points="{poly(e)}" fill="none" stroke="#c9b000" stroke-width="2"/>')
    if overlay is not None:
        for lp in overlay.get("loop", []):
            o.append(f'<polygon points="{poly(lp)}" fill="#8a2be2" fill-opacity="0.22" stroke="#6a0dad" '
                     f'stroke-width="2"><title>switching-loop polygon</title></polygon>')
        for pts in overlay.get("kelvin", []):
            if len(pts) == 1:
                o.append(f'<circle cx="{X(pts[0][0])}" cy="{Y(pts[0][1])}" r="12" fill="#00c000" fill-opacity="0.45"/>')
            else:
                o.append(f'<polyline points="{poly(pts)}" fill="none" stroke="#00c000" stroke-opacity="0.55" '
                         f'stroke-width="16" stroke-linecap="round"/>')
    # halos for differing tracks first
    for t in geo["tracks"]:
        if other is not None and t["key"] not in okeys:
            o.append(f'<polyline points="{poly(t["pts"])}" fill="none" stroke="#ffe100" stroke-opacity="0.85" '
                     f'stroke-width="{max(t["w"] * scale + 10, 10):.1f}" stroke-linecap="round"/>')
    for v in geo["vias"]:
        if other is not None and v["key"] not in okeys:
            o.append(f'<circle cx="{X(v["x"])}" cy="{Y(v["y"])}" r="{v["d"] * scale / 2 + 6:.1f}" fill="#ffe100"/>')
    for ref, fp in sorted(geo["footprints"].items()):
        for c in fp["crt"]:
            o.append(f'<polyline points="{poly(c)}" fill="none" stroke="#888" stroke-width="1"/>')
        for p in fp["pads"]:
            cx, cy = (p["x"] - x0 + pad_mm) * scale, (p["y"] - y0 + pad_mm) * scale + 40
            pw, ph = p["w"] * scale, p["h"] * scale
            rx = min(pw, ph) / 2 if p["shape"] in (0, 2) else (min(pw, ph) * 0.25 if p["shape"] == 4 else 0)
            fill = "#d4a017" if p["th"] else "#e0a96d"
            o.append(f'<g transform="translate({cx:.1f},{cy:.1f}) rotate({-p["rot"]:g})">'
                     f'<rect x="{-pw / 2:.1f}" y="{-ph / 2:.1f}" width="{pw:.1f}" height="{ph:.1f}" rx="{rx:.1f}" '
                     f'fill="{fill}" stroke="#7a5a00" stroke-width="0.5"><title>{html.escape(ref)} pad {p["num"]}: '
                     f'{html.escape(p["net"] or "(no net)")}</title></rect></g>')
    for t in geo["tracks"]:
        col = LAYER_COLORS.get(t["layer"], "#555")
        o.append(f'<polyline points="{poly(t["pts"])}" fill="none" stroke="{col}" stroke-opacity="0.8" '
                 f'stroke-width="{t["w"] * scale:.1f}" stroke-linecap="round"><title>{html.escape(t["net"])} '
                 f'{t["layer"]} {t["w"]:.3g} mm</title></polyline>')
    for v in geo["vias"]:
        o.append(f'<circle cx="{X(v["x"])}" cy="{Y(v["y"])}" r="{v["d"] * scale / 2:.1f}" fill="#666">'
                 f'<title>via {html.escape(v["net"])}</title></circle>')
    for ref, fp in sorted(geo["footprints"].items()):
        for p in fp["pads"]:
            if p["net"]:
                o.append(f'<text x="{X(p["x"])}" y="{float(Y(p["y"])) + 3:.1f}" font-size="8" text-anchor="middle" '
                         f'fill="#000">{html.escape(p["net"][:10])}</text>')
        moved = ref in ofp and (abs(ofp[ref]["x"] - fp["x"]) > 1e-3 or abs(ofp[ref]["y"] - fp["y"]) > 1e-3
                                or ofp[ref]["rot"] % 360 != fp["rot"] % 360 or ofp[ref]["fpid"] != fp["fpid"])
        xs = [px for c in fp["crt"] for px, _ in c] or [fp["x"]]
        ys = [py for c in fp["crt"] for _, py in c] or [fp["y"]]
        if moved:
            o.append(f'<rect x="{float(X(min(xs))) - 4:.1f}" y="{float(Y(min(ys))) - 4:.1f}" '
                     f'width="{(max(xs) - min(xs)) * scale + 8:.1f}" height="{(max(ys) - min(ys)) * scale + 8:.1f}" '
                     f'fill="none" stroke="#d0009a" stroke-width="2.5" stroke-dasharray="6,3"/>')
        val = f" {fp['value']}" if fp["value"] and fp["value"] != ref else ""
        o.append(f'<text x="{X(fp["x"])}" y="{float(Y(min(ys))) - 3:.1f}" font-size="12" font-weight="bold" '
                 f'text-anchor="middle" fill="#202020">{html.escape(ref + val)}</text>')
    if overlay is not None:
        for label, pts in overlay.get("paths", []):
            o.append(f'<polyline points="{poly(pts)}" fill="none" stroke="#00b5d8" stroke-width="3" '
                     f'stroke-dasharray="7,4"><title>{html.escape(label)}</title></polyline>')
            o.append(f'<text x="{X(pts[-1][0])}" y="{float(Y(pts[-1][1])) + 14:.1f}" font-size="10" fill="#007a92" '
                     f'stroke="#fff" stroke-width="3" paint-order="stroke">{html.escape(label)}</text>')
        for pts in overlay.get("near", []):
            o.append(f'<polyline points="{poly(pts)}" fill="none" stroke="#000" stroke-width="4" '
                     f'stroke-dasharray="3,3"><title>analog track within separation gap</title></polyline>')
    o.append("</svg>")
    return "\n".join(o) + "\n"


# ====================================================================== SVG: schematic-ish netlist graph
def schematic_layout(golden: dict) -> dict:
    """Deterministic placement computed from the golden design (reused for the faulted one)."""
    from pcbenv.parts import PARTS
    comps = golden["components"]
    order = sorted(comps, key=lambda r: ({"J": 0, "U": 1, "Q": 2, "Y": 3}.get(r[0], 4), r))
    ncol = max(2, math.ceil(math.sqrt(len(order))))
    cw, ch = 300, 230
    centers = {r: (90 + cw * (i % ncol) + cw / 2, 80 + ch * (i // ncol) + ch / 2) for i, r in enumerate(order)}
    pins = {r: sorted(PARTS[comps[r]["part"]].pins) for r in order}
    gnets = pin_nets(golden)
    # pin side: toward the mean of the other members' component centres
    side = {}
    for r in order:
        for p in pins[r]:
            pin = f"{r}.{p}"
            n = gnets.get(pin)
            others = [centers[q.split(".")[0]] for q in golden["nets"].get(n, []) if q.split(".")[0] != r] if n else []
            mx = sum(c[0] for c in others) / len(others) if others else centers[r][0] + 1
            side[pin] = "L" if mx < centers[r][0] else "R"
    anchors, boxes = {}, {}
    for r in order:
        cx, cy = centers[r]
        left = [p for p in pins[r] if side[f"{r}.{p}"] == "L"]
        right = [p for p in pins[r] if side[f"{r}.{p}"] == "R"]
        if not left and len(right) > 1:
            left, right = right[: len(right) // 2], right[len(right) // 2:]
        rows = max(len(left), len(right), 1)
        bw, bh = 104, 34 + 18 * rows
        boxes[r] = (cx - bw / 2, cy - bh / 2, bw, bh)
        for i, p in enumerate(left):
            anchors[f"{r}.{p}"] = (cx - bw / 2, cy - bh / 2 + 30 + 18 * i, "L")
        for i, p in enumerate(right):
            anchors[f"{r}.{p}"] = (cx + bw / 2, cy - bh / 2 + 30 + 18 * i, "R")
    ncols_used = min(ncol, len(order))
    width = 180 + cw * ncols_used
    height = 120 + ch * math.ceil(len(order) / ncol)
    return {"anchors": anchors, "boxes": boxes, "width": width, "height": height}


def _hub_positions(design: dict, lay: dict) -> dict[str, tuple[float, float]]:
    hubs: dict[str, tuple[float, float]] = {}
    for n in sorted(design["nets"]):
        pts = [lay["anchors"][p] for p in design["nets"][n] if p in lay["anchors"]]
        if not pts:
            continue
        x = sum(p[0] + (-38 if p[2] == "L" else 38) for p in pts) / len(pts)
        y = sum(p[1] for p in pts) / len(pts)
        if len(pts) == 1:
            y += 0
        hubs[n] = [x, y]
    # push hubs out of boxes and apart from each other (deterministic relaxation)
    for _ in range(60):
        moved = False
        for n, (x, y) in sorted(hubs.items()):
            for bx, by, bw, bh in lay["boxes"].values():
                if bx - 16 < x < bx + bw + 16 and by - 16 < y < by + bh + 16:
                    y = by + bh + 22 if y > by + bh / 2 else by - 22
                    moved = True
            for m, (x2, y2) in sorted(hubs.items()):
                if m != n and abs(x - x2) < 60 and abs(y - y2) < 22:
                    y += 13 if (n > m) else -13
                    moved = True
            hubs[n] = [min(max(x, 40), lay["width"] - 40), min(max(y, 50), lay["height"] - 20)]
        if not moved:
            break
    return {n: (round(x, 1), round(y, 1)) for n, (x, y) in hubs.items()}


def render_schematic_svg(design: dict, golden: dict, title: str) -> str:
    """Netlist graph: components as boxes with pin labels, nets as labelled hubs. Pins whose
    connections differ from the golden and values that differ are drawn in red."""
    lay = schematic_layout(golden)
    hubs = _hub_positions(design, lay)
    fn = pin_nets(design)
    bad = moved_pins(design, golden) if design is not golden else set()
    W, H = lay["width"], lay["height"]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="Helvetica,Arial,sans-serif">',
         '<rect width="100%" height="100%" fill="#ffffff"/>',
         f'<text x="10" y="20" font-size="15" font-weight="bold">{html.escape(title)}</text>',
         '<text x="10" y="38" font-size="11">boxes = components (ref, part, value, footprint), dots = nets; '
         'red = connection or value differs from the golden design</text>']
    for n, (hx, hy) in sorted(hubs.items()):
        col = _palette(n)
        for p in sorted(design["nets"][n]):
            if p not in lay["anchors"]:
                continue
            ax, ay, s = lay["anchors"][p]
            stub = ax - 14 if s == "L" else ax + 14
            red = p in bad
            o.append(f'<polyline points="{ax:.1f},{ay:.1f} {stub:.1f},{ay:.1f} {hx},{hy}" fill="none" '
                     f'stroke="{"#e00000" if red else col}" stroke-width="{2.4 if red else 1.4}"'
                     f'{" stroke-dasharray=\"5,3\"" if red else ""}/>')
    comps = design["components"]
    gcomps = golden["components"]
    for r, (bx, by, bw, bh) in sorted(lay["boxes"].items()):
        c = comps.get(r, {})
        o.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw}" height="{bh}" fill="#f2f4fa" stroke="#334" '
                 f'stroke-width="1.5" rx="4"/>')
        o.append(f'<text x="{bx + bw / 2:.1f}" y="{by + 14:.1f}" font-size="13" font-weight="bold" '
                 f'text-anchor="middle">{html.escape(r)} <tspan font-weight="normal" font-size="10">'
                 f'{html.escape(c.get("part", ""))}</tspan></text>')
        vd = c.get("value", "") != gcomps.get(r, {}).get("value", "")
        if c.get("value"):
            o.append(f'<text x="{bx + bw / 2:.1f}" y="{by + 25:.1f}" font-size="10" text-anchor="middle" '
                     f'fill="{"#e00000" if vd else "#333"}" font-weight="{"bold" if vd else "normal"}">'
                     f'{html.escape(c["value"])}</text>')
        fd = c.get("footprint", "") != gcomps.get(r, {}).get("footprint", "")
        fpname = c.get("footprint", "").split(":")[-1]
        o.append(f'<text x="{bx + bw / 2:.1f}" y="{by + bh + 11:.1f}" font-size="8" text-anchor="middle" '
                 f'fill="{"#e00000" if fd else "#777"}">{html.escape(fpname[:26])}</text>')
    for p, (ax, ay, s) in sorted(lay["anchors"].items()):
        pin = p.split(".", 1)[1]
        red = p in bad
        unconnected = p not in fn
        o.append(f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="2.5" fill="{"#e00000" if red else "#334"}"/>')
        tx = ax + 4 if s == "L" else ax - 4
        anchor = "start" if s == "L" else "end"
        o.append(f'<text x="{tx:.1f}" y="{ay + 3.5:.1f}" font-size="10" text-anchor="{anchor}" '
                 f'fill="{"#e00000" if red else "#223"}">{html.escape(pin)}{" ✕" if unconnected else ""}</text>')
    for n, (hx, hy) in sorted(hubs.items()):
        col = _palette(n)
        o.append(f'<circle cx="{hx}" cy="{hy}" r="5" fill="{col}"/>')
        o.append(f'<text x="{hx}" y="{hy - 8:.1f}" font-size="11" font-weight="bold" text-anchor="middle" '
                 f'fill="{col}" stroke="#fff" stroke-width="3" paint-order="stroke">{html.escape(n)}</text>')
    o.append("</svg>")
    return "\n".join(o) + "\n"


# ====================================================================== v2: public evidence of latent faults
def public_sources(task_dir: Path) -> list[tuple[str, str]]:
    """[(public file name, text)]: TASK.md, spec.json, parts/*.md (what the agent can read)."""
    pub = Path(task_dir) / "public"
    out = [("TASK.md", (pub / "TASK.md").read_text(encoding="utf-8")),
           ("spec.json", (pub / "spec.json").read_text(encoding="utf-8"))]
    out += [(f"parts/{f.name}", f.read_text(encoding="utf-8")) for f in sorted((pub / "parts").glob("*.md"))]
    return out


def public_text(task_dir: Path) -> str:
    """Same concatenation the hard generators use for their evidence gate."""
    return "\n".join(t for _, t in public_sources(task_dir))


def _sentence(line: str, needle: str) -> str:
    """The sentence of `line` holding `needle` (whole line if short)."""
    line = line.strip()
    if len(line) <= 320:
        return line
    k = max(0, line.find(needle))
    a = max(line.rfind(". ", 0, k), line.rfind("; ", 0, k))
    b = min([x for x in (line.find(". ", k), line.find("; ", k)) if x >= 0] or [len(line)])
    return ("… " if a > 0 else "") + line[a + 2 if a > 0 else 0: b + 1].strip() + (" …" if b < len(line) - 1 else "")


def evidence_quotes(fault: dict, sources: list[tuple[str, str]]) -> list[dict]:
    """For each evidence group of a latent fault (`latent.evidence_groups`, matched by
    `latent.match_evidence`: requirement lines only, v2.1): the first alternative found, the file and
    the exact line/sentence it is in, and every file holding a match. `found` False = no alternative
    of the group is public (the fault would be unfair)."""
    from pcbenv.faults.latent import _alt_hit, match_evidence, requirement_lines
    lines = requirement_lines(sources)
    out = []
    for m in match_evidence(fault, sources):
        files = []
        if m["found"]:
            for fname in dict.fromkeys(f for f, _ in lines):
                if _alt_hit(m["alt"], [x for x in lines if x[0] == fname]):
                    files.append(fname)
        needle = m["alt"].split(":", 1)[1] if m["found"] and m["alt"].startswith("@") else (m["alt"] or "")
        out.append({"group": m["group"], "found": m["found"], "alt": m["alt"], "file": m["file"],
                    "quote": _sentence(m["line"], needle) if m["found"] else None, "files": files})
    return out


# ====================================================================== v2: design-rule metrics
def _rule_scenarios(ctx: dict) -> list[dict]:
    return list(ctx.get("scenarios", []))


def rule_metrics(design: dict, ctx: dict) -> dict[tuple, dict]:
    """Every quantity the `rules` check limits (pcbenv.rules), worst case over the rule context's
    operating conditions: {(code, subject, quantity): {value, limit, unit, ratio, ok, cond}}.
    `ratio` = value / limit (>1 violates). Simulation failures appear as code 'simulation'."""
    from pcbenv import rules as RL
    out: dict[tuple, dict] = {}
    only = set(ctx.get("only") or RL.RULE_CODES)

    def put(code, subj, qty, value, limit, unit, ratio, cond, pkg=""):
        if code not in only:
            return
        k = (code, subj, qty)
        cur = out.get(k)
        if cur is None or ratio > cur["ratio"] + 1e-12:
            out[k] = {"value": value, "limit": limit, "unit": unit, "ratio": ratio, "ok": ratio <= 1 + 1e-6,
                      "cond": cond, "pkg": pkg}

    if "flyback" in only:
        net_of = {p: n for n, pins in design["nets"].items() for p in pins}
        for ld in ctx.get("inductive_loads", []):
            ok = not RL.check_flyback(design, {"inductive_loads": [ld]})
            ds = [r for r, c in sorted(design["components"].items()) if c["part"] == "D_SCHOTTKY"]
            where = "; ".join(f"{d}: K on `{net_of.get(d + '.K')}`, A on `{net_of.get(d + '.A')}`" for d in ds)
            out[("flyback", f"{ld['supply_pin']}-{ld['switched_pin']}", "diode across load")] = {
                "value": "present" if ok else "missing", "limit": "K on supply side, A on switched side",
                "unit": "", "ratio": 0.0 if ok else 2.0, "ok": ok, "cond": where or "no Schottky"}
    for k, sc in enumerate(_rule_scenarios(ctx)):
        try:
            op = RL.operating_point(design, sc)
        except Exception as e:  # noqa: BLE001
            out[("simulation", f"condition {k}", "op")] = {"value": "fails", "limit": "", "unit": "", "ratio": 9.0,
                                                           "ok": False, "cond": str(e)[:120]}
            continue
        v, i = op.v, op.i
        c = f"cond {k}"
        for ref, comp in RL._comps(design, "MCU8"):
            g = v[f"{ref}.GND"]
            vdd = v[f"{ref}.VDD"] - g
            put("mcu_abs_max", ref, "VDD-GND", vdd, RL.MCU_VDD_MAX, "V", vdd / RL.MCU_VDD_MAX, c)
            for pin in ("NRST", "PA0", "PA1", "PA2", "SDA", "SCL"):
                pp = f"{ref}.{pin}"
                if not RL._connected(design, pp):
                    continue
                vp = v[pp] - g
                hi = vdd + RL.MCU_PIN_MARGIN
                # ratio = overshoot beyond [0, VDD] in units of the 0.3 V margin (1 = at the limit)
                r = max(0.0, (vp - vdd) / RL.MCU_PIN_MARGIN, -vp / RL.MCU_PIN_MARGIN)
                put("mcu_abs_max", pp, "pin voltage (ratio: overshoot / 0.3 V)", vp, f"-0.3 … {hi:.3g} V", "V", r, c)
                lim = RL.MCU_I2C_MAX_A if pin in ("SDA", "SCL") else RL.MCU_GPIO_MAX_A
                ip = abs(i.get(pp, 0.0))
                put("mcu_pin_current", pp, "|I|", ip, lim, "A", ip / lim, c)
        for ref, comp in RL._comps(design, "OPAMP"):
            vn, vpp = v[f"{ref}.V-"], v[f"{ref}.V+"]
            put("opamp_abs_max", ref, "V+ - V-", vpp - vn, RL.OPAMP_SUPPLY_MAX, "V", (vpp - vn) / RL.OPAMP_SUPPLY_MAX, c)
            for pin in ("IN+", "IN-"):
                pp = f"{ref}.{pin}"
                if RL._connected(design, pp):
                    r = max(0.0, (v[pp] - vpp) / RL.OPAMP_IN_MARGIN, (vn - v[pp]) / RL.OPAMP_IN_MARGIN)
                    put("opamp_abs_max", pp, "input vs rails (ratio: overshoot / 0.3 V)", v[pp] - vn,
                        f"-0.3 … {vpp - vn + RL.OPAMP_IN_MARGIN:.3g} V", "V", r, c)
        for ref, comp in RL._comps(design, "LDO_ADJ"):
            g = v[f"{ref}.GND"]
            vin, ven, vout = v[f"{ref}.VIN"] - g, v[f"{ref}.EN"] - g, v[f"{ref}.VOUT"] - g
            iout = -i.get(f"{ref}.VOUT", 0.0)
            put("ldo_abs_max", ref, "VIN", vin, RL.LDO_VIN_MAX, "V", vin / RL.LDO_VIN_MAX, c)
            if RL._connected(design, f"{ref}.EN") and vin > 0:
                put("ldo_abs_max", f"{ref}.EN", "EN (ratio: (EN-VIN) / 0.3 V)", ven, f"VIN+0.3 = {vin + 0.3:.3g} V", "V",
                    max(0.0, (ven - vin) / 0.3), c)
            put("ldo_abs_max", ref, "IOUT", iout, RL.LDO_IOUT_MAX, "A", iout / RL.LDO_IOUT_MAX, c)
            pd = max(0.0, vin - vout) * max(0.0, iout)
            put("ldo_abs_max", ref, "(VIN-VOUT)·IOUT", pd, RL.LDO_PD_MAX, "W", pd / RL.LDO_PD_MAX, c)
        for ref, comp in RL._comps(design, "NMOS"):
            vgs, vds = v[f"{ref}.G"] - v[f"{ref}.S"], v[f"{ref}.D"] - v[f"{ref}.S"]
            idr = abs(i.get(f"{ref}.D", 0.0))
            put("nmos_abs_max", ref, "|VGS|", abs(vgs), RL.NMOS_VGS_MAX, "V", abs(vgs) / RL.NMOS_VGS_MAX, c)
            put("nmos_abs_max", ref, "VDS", vds, RL.NMOS_VDS_MAX, "V", vds / RL.NMOS_VDS_MAX, c)
            put("nmos_abs_max", ref, "ID", idr, RL.NMOS_ID_MAX, "A", idr / RL.NMOS_ID_MAX, c)
        for ref, comp in RL._comps(design, "NPN"):
            vce = v[f"{ref}.C"] - v[f"{ref}.E"]
            ic, ib = i.get(f"{ref}.C", 0.0), i.get(f"{ref}.B", 0.0)
            put("npn_abs_max", ref, "VCE", vce, RL.NPN_VCE_MAX, "V", vce / RL.NPN_VCE_MAX, c)
            put("npn_abs_max", ref, "IC", abs(ic), RL.NPN_IC_MAX, "A", abs(ic) / RL.NPN_IC_MAX, c)
            put("npn_abs_max", ref, "IB", abs(ib), RL.NPN_IB_MAX, "A", abs(ib) / RL.NPN_IB_MAX, c)
            if 0 <= vce <= RL.NPN_SAT_VCE and ic >= RL.NPN_SAT_IC_MIN:
                beta = ic / ib if ib > 1e-12 else math.inf
                put("npn_saturation", ref, "forced beta IC/IB (saturated)", beta, RL.NPN_FORCED_BETA_MAX, "",
                    beta / RL.NPN_FORCED_BETA_MAX if math.isfinite(beta) else 9.0, c)
        for ref, comp in RL._comps(design, "LED_"):
            ia = i.get(f"{ref}.A", 0.0)
            lim = RL.LED_IF_MAX_A.get(comp["footprint"], min(RL.LED_IF_MAX_A.values())) * RL.LED_DERATING
            put("led_current", ref, "IF", ia, lim, "A", ia / lim, c, comp["footprint"].split(":")[-1].split("_")[1])
            vr = v[f"{ref}.K"] - v[f"{ref}.A"]
            put("led_reverse", ref, "VR", vr, RL.LED_VR_MAX, "V", vr / RL.LED_VR_MAX, c)
        for ref, comp in RL._comps(design, "D_SCHOTTKY"):
            ia = i.get(f"{ref}.A", 0.0)
            vr = v[f"{ref}.K"] - v[f"{ref}.A"]
            put("diode_ratings", ref, "VR", vr, RL.SCHOTTKY_VR_MAX, "V", vr / RL.SCHOTTKY_VR_MAX, c)
            put("diode_ratings", ref, "IF", ia, RL.SCHOTTKY_IF_MAX, "A", ia / RL.SCHOTTKY_IF_MAX, c)
        for ref, comp in RL._comps(design, "R"):
            if comp["part"] != "R" or comp["footprint"] not in RL.R_POWER_W:
                continue
            try:
                rv = parse_value_safe(comp["value"])
            except ValueError:
                continue
            ir = i.get(f"{ref}.1", 0.0)
            pw = ir * ir * rv
            lim = RL.R_POWER_W[comp["footprint"]] * RL.R_DERATING
            put("resistor_power", ref, "I²R", pw, lim, "W", pw / lim, c, comp["footprint"].split(":")[-1].split("_")[1])
        for ref, comp in RL._comps(design, "C"):
            if comp["part"] != "C" or comp["footprint"] not in RL.C_VOLTAGE_V:
                continue
            vc = abs(v[f"{ref}.1"] - v[f"{ref}.2"])
            lim = RL.C_VOLTAGE_V[comp["footprint"]] * RL.C_DERATING
            put("capacitor_voltage", ref, "|V|", vc, lim, "V", vc / lim, c, comp["footprint"].split(":")[-1].split("_")[1])
    return out


def parse_value_safe(v: str) -> float:
    from pcbenv.parts import parse_value
    return parse_value(str(v))


def _q(x, unit: str) -> str:
    if isinstance(x, str):
        return x
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "∞" if x is not None else "—"
    if abs(x) < 1e-12:
        x = 0.0
    if unit == "":
        return f"{x:.3g}"
    return _fmt(x, unit)


RULE_NEAR = 0.8   # rows at >= 80 % of a limit are shown even if untouched by a fault


def rules_table(meta: dict, fdesign: dict, gdesign: dict) -> tuple[list[str], int]:
    """Markdown table of the design rules involved (violated on either side, touching a fault's
    refs, or within 80 % of the limit), faulted vs golden. Returns (lines, #rules evaluated)."""
    ctx = meta.get("rules") or meta.get("rules_power")
    if not ctx:
        return [], 0
    fm, gm = rule_metrics(fdesign, ctx), rule_metrics(gdesign, ctx)
    touched = set()
    for f in meta.get("faults", []):
        for t in f.get("targets", []):
            if not t.startswith("net:"):
                touched.add(t)
        d = f.get("data") or {}
        for k in ("ref", "cap", "diode", "pin"):
            if isinstance(d.get(k), str):
                touched.add(d[k].split(".")[0])
        for pin in d.get("pins") or []:
            touched.add(str(pin).split(".")[0])
    keys = sorted(set(fm) | set(gm), key=lambda k: (k[0], k[1], k[2]))
    rows = []
    for k in keys:
        a, b = fm.get(k), gm.get(k)
        subj_ref = k[1].split(".")[0].split("-")[0]
        bad = (a and not a["ok"]) or (b and not b["ok"])
        near = any(x and x["ratio"] >= RULE_NEAR for x in (a, b))
        ra, rb = (a["ratio"] if a else 0.0), (b["ratio"] if b else 0.0)
        relevant = subj_ref in touched and (max(ra, rb) >= 0.05 or abs(ra - rb) >= 0.05
                                            or (a and b and a.get("pkg") != b.get("pkg")))
        if not (bad or near or relevant or k[0] in ("flyback", "simulation")):
            continue
        def cell(x):
            if x is None:
                return "—"
            x = dict(x, ratio=0.0 if abs(x["ratio"]) < 5e-3 else x["ratio"])
            lim_x = x["limit"] if isinstance(x["limit"], str) else _q(x["limit"], x["unit"])
            pkg = f"{x['pkg']}: " if x.get("pkg") else ""
            return (f"{pkg}{_q(x['value'], x['unit'])} of {lim_x} ({x['ratio']:.0%}){'' if x['ok'] else ' ❌'}"
                    if x.get("pkg") or k[0] in ("mcu_abs_max", "ldo_abs_max", "opamp_abs_max") and isinstance(x["limit"], str)
                    else f"{_q(x['value'], x['unit'])} ({x['ratio']:.0%}){'' if x['ok'] else ' ❌'}")
        lim = (a or b)
        lim_s = ("per package / condition, see cells" if (a and b and a["limit"] != b["limit"]) else
                 (_q(lim["limit"], lim["unit"]) if not isinstance(lim["limit"], str) else lim["limit"]))
        why = "violated" if bad else ("fault target" if subj_ref in touched else ("near limit" if near else ""))
        rows.append(f"| `{k[0]}` | `{k[1]}` | {_md_escape(k[2])} | {_md_escape(lim_s)} | {cell(a)} | {cell(b)} | "
                    f"{why} | {_md_escape((a or b)['cond'])} |")
    head = ["| rule | subject | quantity | limit | faulted (of limit) | golden (of limit) | shown because | "
            "worst condition (faulted) |", "|---|---|---|---|---|---|---|---|"]
    return (head + rows if rows else ["- no rule quantity is violated, touched by a fault, or within 80 % of a limit"]), \
        len(set(fm) | set(gm))


# ====================================================================== v2: layout-rule metrics and overlay
def _board_pad(b, pin: str, ref_parts: dict[str, str]):
    from pcbenv.layout_rules import _pad
    return _pad(b, pin, ref_parts)


def layout_metrics(board_path: str, meta: dict) -> dict[str, tuple]:
    """{label: (value, limit, unit, ok)} for every layout rule (layout_rules) and decoupling rule."""
    from pcbenv import boardnet
    from pcbenv import layout as LY
    from pcbenv import layout_rules as LR
    b = boardnet.load_board(board_path)
    rp = meta.get("ref_parts") or {}
    lctx = meta.get("layout_rules") or {}
    out: dict[str, tuple] = {}
    for r in lctx.get("kelvin", []):
        ok, why = LR.kelvin_ok(b, r, rp)
        out[f"Kelvin: {r['sense_pin']} leaves from {r['shunt_pin']} (not sharing copper with "
            f"{', '.join(r['load_pins'])})"] = ("ok" if ok else "VIOLATED: " + why, "own trace from shunt pad", "", ok)
    for r in lctx.get("switch_loop", []):
        a = LR.loop_area(b, r, rp)
        ok = not isinstance(a, str) and a <= r["max_area_mm2"] + LR.EPS
        out[f"switching-loop area ({r['name']})"] = (a, r["max_area_mm2"], "mm²", ok)
    for r in lctx.get("crystal", []):
        for label, d, nv in LR.crystal_metrics(b, r, rp):
            out[f"crystal copper path {label}"] = (d if d is not None else "not connected", r["max_path_mm"], "mm",
                                                   d is not None and d <= r["max_path_mm"] + LR.EPS)
            out[f"crystal vias on net of {label.split('->')[0]}"] = (nv, 0, "", nv == 0 or not r.get("no_vias"))
    for r in lctx.get("separation", []):
        s = LR.separation_length(b, r, rp)
        ok = not isinstance(s, str) and s <= r["max_parallel_mm"] + LR.EPS
        out[f"separation: {'/'.join(r['victim_pins'])} net length within {r['min_gap_mm']:g} mm of "
            f"{'/'.join(r['aggressor_pins'])} net"] = (s, r["max_parallel_mm"], "mm", ok)
    for dc in meta.get("decoupling") or []:
        d = LY.decoupling_path_mm(b, dc["cap"], dc["ic_pin"], rp)
        lim = LY.max_path_mm(dc)
        out[f"decoupling copper path {dc['cap']} -> {dc['ic_pin']}"] = (
            d if d is not None else "not connected", lim, "mm", d is not None and d <= lim + 1e-6)
        ip = LY._ic_pad(b, dc["ic_pin"], rp)
        fp = b.FindFootprintByReference(dc["cap"])
        if ip is not None and fp is not None:
            ix, iy = ip.GetPosition().x / 1e6, ip.GetPosition().y / 1e6
            dist = max(math.hypot(p.GetPosition().x / 1e6 - ix, p.GetPosition().y / 1e6 - iy) for p in fp.Pads())
            out[f"decoupling straight line {dc['cap']} pads -> {dc['ic_pin']}"] = (dist, dc["max_mm"], "mm",
                                                                                 dist <= dc["max_mm"] + 1e-6)
    return out


def layout_overlay(board_path: str, meta: dict) -> dict:
    """Geometry the reviewer needs drawn on the board render (mm): switching-loop polygon, copper
    paths of the crystal / decoupling / loop legs, the Kelvin sense island, and the victim-track
    stretches that run within the separation gap of the switching node."""
    from pcbenv import boardnet
    from pcbenv import layout as LY
    from pcbenv import layout_rules as LR
    b = boardnet.load_board(board_path)
    rp = meta.get("ref_parts") or {}
    lctx = meta.get("layout_rules") or {}
    ov: dict = {"loop": [], "paths": [], "kelvin": [], "near": []}
    for r in lctx.get("switch_loop", []):
        poly = LR.loop_polygon(b, r, rp)
        if not isinstance(poly, str):
            ov["loop"].append([(round(x, 4), round(y, 4)) for x, y in poly])
    for r in lctx.get("crystal", []):
        for a, c in r["pairs"]:
            pa, pc = _board_pad(b, a, rp), _board_pad(b, c, rp)
            res = LY.copper_path(b, pa, pc) if pa is not None and pc is not None else None
            if res:
                ov["paths"].append((f"{a}->{c} {res[0]:.1f} mm", [(round(x, 4), round(y, 4)) for x, y in res[1]]))
    for dc in meta.get("decoupling") or []:
        ip = LY._ic_pad(b, dc["ic_pin"], rp)
        fp = b.FindFootprintByReference(dc["cap"])
        best = None
        if ip is not None and fp is not None and ip.GetNetCode() > 0:
            for cp in sorted(fp.Pads(), key=lambda p: p.GetNumber()):
                if cp.GetNetCode() == ip.GetNetCode():
                    res = LY.copper_path(b, cp, ip)
                    if res and (best is None or res[0] < best[0]):
                        best = res
        if best:
            ov["paths"].append((f"{dc['cap']}->{dc['ic_pin']} {best[0]:.1f} mm",
                                [(round(x, 4), round(y, 4)) for x, y in best[1]]))
    for r in lctx.get("kelvin", []):
        sh, se = _board_pad(b, r["shunt_pin"], rp), _board_pad(b, r["sense_pin"], rp)
        if sh is None or se is None or se.GetNetCode() <= 0:
            continue
        for t in LR.island_items(b, se.GetNetCode(), se, drop_pad=sh):
            if t.GetClass() == "PCB_VIA":
                q = t.GetPosition()
                ov["kelvin"].append([(round(q.x / 1e6, 4), round(q.y / 1e6, 4))])
            else:
                ov["kelvin"].append([(round(t.GetStart().x / 1e6, 4), round(t.GetStart().y / 1e6, 4)),
                                     (round(t.GetEnd().x / 1e6, 4), round(t.GetEnd().y / 1e6, 4))])
    for r in lctx.get("separation", []):
        vp = [_board_pad(b, p, rp) for p in r["victim_pins"]]
        ap = [_board_pad(b, p, rp) for p in r["aggressor_pins"]]
        if any(p is None or p.GetNetCode() <= 0 for p in vp + ap):
            continue
        for vc in sorted({p.GetNetCode() for p in vp}):
            vs, _ = LR.net_tracks(b, vc)
            for ac in sorted({p.GetNetCode() for p in ap}):
                ags, _ = LR.net_tracks(b, ac)
                for lay, x1, y1, x2, y2, _w in vs:
                    for la, a1, b1, a2, b2, _wa in ags:
                        if la != lay:
                            continue
                        iv = LR._near_interval((x1, y1, x2, y2), (a1, b1, a2, b2), r["min_gap_mm"])
                        if iv and iv[1] - iv[0] > 1e-9:
                            ov["near"].append([(round(x1 + (x2 - x1) * t, 4), round(y1 + (y2 - y1) * t, 4))
                                               for t in iv])
    ov["kelvin"].sort()
    ov["near"].sort()
    return ov


# ====================================================================== packet
def _verify_both(task_dir: Path) -> tuple[dict, dict]:
    from pcbenv.verify import verify
    out = []
    with tempfile.TemporaryDirectory(prefix="pcbqa_") as td:
        for name, d, b in (("faulted", task_dir / "public" / "design.json", task_dir / "public" / "board.kicad_pcb"),
                           ("golden", task_dir / "hidden" / "golden_design.json",
                            task_dir / "hidden" / "golden_board.kicad_pcb")):
            wd = Path(td) / name
            wd.mkdir()
            shutil.copyfile(d, wd / "design.json")
            shutil.copyfile(b, wd / "board.kicad_pcb")
            r = verify(str(wd), str(task_dir))
            det = {k: v for k, v in r.detail.items() if k not in ("seconds", "wall_seconds")}
            out.append({"reward": r.reward, "gates": r.gates, "checks": r.checks, "detail": det})
    return out[0], out[1]


def _assertion_table(meta: dict, fdesign: dict, gdesign: dict) -> list[str]:
    from pcbenv import sim
    from pcbenv.taskio import _UNITS, describe_assertion
    fa = {r.name: r for r in sim.run_assertions(fdesign, meta.get("assertions", []))}
    ga = {r.name: r for r in sim.run_assertions(gdesign, meta.get("assertions", []))}
    lines = ["| assertion | what | allowed | faulted: measured | | golden: measured | |",
             "|---|---|---|---|---|---|---|"]
    for a in meta.get("assertions", []):
        n = sim.assertion_name(a)
        u = _UNITS.get(a.get("type"), "")
        rng = f"{_fmt(a['min'], u)} … {_fmt(a['max'], u)}" if "min" in a and "max" in a else "see def."
        what = describe_assertion(a).split(":", 1)[-1].strip()
        what = re.sub(r" between .* and [^()]*", " ", what).replace("  ", " ")
        f, g = fa.get(n), ga.get(n)
        fm = _fmt(f.measured, u) if f else "—"
        gm = _fmt(g.measured, u) if g else "—"
        lines.append(f"| `{n}` | {_md_escape(what)} | {rng} | {fm} | {'✅' if f and f.passed else '❌'} | {gm} | "
                     f"{'✅' if g and g.passed else '❌'} |")
    return lines


def _value_table(meta: dict, fdesign: dict, gdesign: dict, fgeo: dict) -> list[str]:
    from pcbenv.taskio import _VALUE_UNITS
    touched = {t for f in meta.get("faults", []) for t in f.get("targets", []) if not t.startswith("net:")}
    lines = ["| ref | part | acceptable range | faulted design.json | faulted board | golden | touched by a fault |",
             "|---|---|---|---|---|---|---|"]
    for ref, (lo, hi) in sorted((meta.get("value_bounds") or {}).items()):
        part = gdesign["components"].get(ref, {}).get("part", "")
        unit = _VALUE_UNITS.get(part, "Hz" if part.startswith("XTAL") else "")
        fv = fdesign["components"].get(ref, {}).get("value", "")
        bv = fgeo["footprints"].get(ref, {}).get("value", "")
        gv = gdesign["components"].get(ref, {}).get("value", "")

        def mark(v):
            x = _pv(v)
            ok = x is not None and lo * (1 - 1e-9) <= x <= hi * (1 + 1e-9)
            return f"`{v}`{'' if ok else ' ⚠ out of range'}"
        lines.append(f"| `{ref}` | {part} | {_fmt(lo, unit)} … {_fmt(hi, unit)} | {mark(fv)} | {mark(bv)} | "
                     f"{mark(gv)} | {'**yes**' if ref in touched else ''} |")
    return lines


def _verdict_table(fres: dict, gres: dict) -> list[str]:
    from pcbenv.verify import CHECKS, GATES
    lines = ["| stage | kind | faulted files | golden files |", "|---|---|---|---|"]
    extra = tuple(sorted((set(fres["checks"]) | set(gres["checks"])) - set(CHECKS)))
    for k in GATES + CHECKS + extra:
        kind = "gate" if k in GATES else "check"
        fv = (fres["gates"] if k in GATES else fres["checks"]).get(k)
        gv = (gres["gates"] if k in GATES else gres["checks"]).get(k)
        lines.append(f"| {k} | {kind} | {'pass' if fv else '**FAIL**'} | {'pass' if gv else '**FAIL**'} |")
    lines.append(f"| **reward** | | **{fres['reward']:g}** | **{gres['reward']:g}** |")
    return lines


def build_packet(row: dict, task_dir: Path, out_dir: Path, nn: int, reasons: list[str], width: int = 2) -> dict:
    """Write one packet dir. Returns a summary row for the index."""
    task_dir = Path(task_dir)
    if any("holdout" in part for part in task_dir.resolve().parts):
        raise ValueError(f"refusing holdout task {task_dir}")
    meta = json.loads((task_dir / "hidden" / "meta.json").read_text(encoding="utf-8"))
    fdesign = json.loads((task_dir / "public" / "design.json").read_text(encoding="utf-8"))
    gdesign = json.loads((task_dir / "hidden" / "golden_design.json").read_text(encoding="utf-8"))
    task_md = (task_dir / "public" / "TASK.md").read_text(encoding="utf-8")
    num = f"{nn:0{width}d}"
    name = f"{num}-{row['id']}"
    pdir = out_dir / name
    if pdir.exists():
        shutil.rmtree(pdir)
    pdir.mkdir(parents=True)

    fboard = str(task_dir / "public" / "board.kicad_pcb")
    gboard = str(task_dir / "hidden" / "golden_board.kicad_pcb")
    fgeo = board_geometry(fboard)
    ggeo = board_geometry(gboard)
    has_lr = bool(meta.get("layout_rules"))
    fov = layout_overlay(fboard, meta) if has_lr else None
    gov = layout_overlay(gboard, meta) if has_lr else None
    renders = {
        "schematic_faulted.svg": render_schematic_svg(fdesign, gdesign, f"{row['id']} — design.json as given (faulted)"),
        "schematic_golden.svg": render_schematic_svg(gdesign, gdesign, f"{row['id']} — golden design (reference fix)"),
        "board_faulted.svg": render_board_svg(fgeo, ggeo, f"{row['id']} — board.kicad_pcb as given (faulted)", fov),
        "board_golden.svg": render_board_svg(ggeo, fgeo, f"{row['id']} — golden board (reference fix)", gov),
    }
    for fname, svg in renders.items():
        (pdir / fname).write_text(svg, encoding="utf-8")
    fres, gres = _verify_both(task_dir)
    ddiff = design_diff(fdesign, gdesign)
    cdiff = connection_diff(fdesign, gdesign, meta.get("ref_parts", {}))
    bdiff = board_diff(fgeo, ggeo)
    rel = os.path.relpath(task_dir, pdir)

    tier = tier_of(row)
    mode = row.get("tools_mode") or meta.get("tools_mode") or "full"
    n_lat = sum(1 for f in meta.get("faults", []) if f.get("category") == "latent")
    L: list[str] = [f"# QA packet {num}: `{row['id']}`", "",
                    "| family | tier | tool mode | hint level | intent in TASK.md | faults | latent | predicted difficulty |",
                    "|---|---|---|---|---|---|---|---|",
                    f"| {row['family']} | {tier} | {mode} | {row['hint_level']} | {row.get('intent', '')} | "
                    f"{row['n_faults']} | {n_lat} | {row.get('difficulty_predicted', '')} |", "",
                    f"Task files: [`{rel}/public/`]({rel}/public/) (what the agent gets) and "
                    f"[`{rel}/hidden/`]({rel}/hidden/) (grader only). "
                    f"Why sampled: {', '.join(reasons) or 'stratum coverage'}.", "",
                    "**How to review (≈5 min):** read section 1 as if you were the agent, decide whether you could "
                    "find and fix the problems from it; then check section 2 (faults, reference fix, verifier "
                    "verdicts) and fill `review.yaml`. Do not let section 2 influence your fairness judgement of "
                    "section 1.", "",
                    "## 1. What the agent sees", "",
                    "### 1.1 TASK.md (verbatim)", ""]
    fence = _fence(task_md)
    L += [f"{fence}markdown", task_md.rstrip("\n"), fence, ""]
    L += ["### 1.2 Public files", "",
          "The agent also gets `design.json`, `board.kicad_pcb`, `spec.json` and the part datasheets below, "
          "plus the `pcbtool` commands listed in TASK.md (DRC, ERC, simulation of the public assertions, value-range "
          "check). Renders of the faulted files:", "",
          "![faulted schematic](schematic_faulted.svg)", "", "![faulted board](board_faulted.svg)", ""]
    for ds in sorted((task_dir / "public" / "parts").glob("*.md")):
        txt = ds.read_text(encoding="utf-8")
        fd = _fence(txt)
        L += [f"<details><summary>Datasheet <code>parts/{ds.name}</code></summary>", "", f"{fd}markdown",
              txt.rstrip("\n"), fd, "", "</details>", ""]

    L += ["## 2. Reviewer-only (hidden from the agent)", "", "### 2.1 Injected faults", "",
          "| # | type | category | DRC/ERC-invisible | latent (pcbtool-clean) | detail | verifier, this fault alone |",
          "|---|---|---|---|---|---|---|"]
    alone = {i: a for i, a in enumerate(row.get("alone", []))}
    for i, f in enumerate(meta.get("faults", [])):
        a = alone.get(i, {})
        al = f"reward {a.get('reward', '?')}; fails {', '.join(a.get('failing', [])) or '—'}" if a else "—"
        lat = "**yes**" + (" (layout)" if f["type"] in LAYOUT_LATENT else "") if f.get("category") == "latent" else ""
        L.append(f"| {i + 1} | `{f['type']}` | {f.get('category', '')} | "
                 f"{'yes' if f.get('invisible_to_drc_erc') else 'no'} | {lat} | {_md_escape(f.get('detail', ''))} | {al} |")
    L += ["", "### 2.2 Reference fix (faulted → golden)", "",
          "The reference repair is the hidden golden pair (`golden_design.json`, `golden_board.kicad_pcb`). "
          "Any repair that passes every gate and check scores 1.0; it need not be byte-identical.", "",
          "**design.json: component changes**", ""]
    L += [f"- {x}" for x in ddiff] or ["- none"]
    L += ["", "**design.json: connection changes** (per pin: what it connects to)", ""]
    L += [f"- {x}" for x in cdiff] or ["- none"]
    L += ["", "**board.kicad_pcb: footprints moved / changed**", ""]
    L += [f"- {x}" for x in bdiff["footprints"]] or ["- none"]
    L += ["", "**board.kicad_pcb: footprint values (BOM)**", ""]
    L += [f"- {x}" for x in bdiff["values"]] or ["- none"]
    L += ["", "**board.kicad_pcb: pad-net changes**", ""]
    L += [f"- {x}" for x in bdiff["pad_nets"]] or ["- none"]
    L += ["", "**board.kicad_pcb: nets re-routed** (track/via geometry differs)", ""]
    L += [f"- {x}" for x in bdiff["nets_rerouted"]] or ["- none"]
    L += ["", "Golden renders (compare with 1.2; highlighted items differ):", "",
          "![golden schematic](schematic_golden.svg)", "", "![golden board](board_golden.svg)", "",
          "### 2.3 Verifier verdicts", "",
          "Reward is 1 only if every gate and check passes.", ""]
    L += _verdict_table(fres, gres)
    L += ["", "Verifier messages on the faulted files:", ""]
    msgs = [f"- **{k}**: {_md_escape(m)}" for k, v in sorted(fres["detail"].items()) for m in
            (v if isinstance(v, list) else [v])]
    L += msgs or ["- none"]
    gmsgs = [f"- **{k}**: {_md_escape(m)}" for k, v in sorted(gres["detail"].items()) for m in
             (v if isinstance(v, list) else [v])]
    if gmsgs:
        L += ["", "Verifier messages on the golden files (should be none):", ""] + gmsgs
    L += ["", "### 2.4 Spec assertions before / after", ""]
    L += _assertion_table(meta, fdesign, gdesign)
    L += ["", "### 2.5 Value bounds", "",
          "Bounds are public (TASK.md / spec.json); `values` check = every value inside its range.", ""]
    L += _value_table(meta, fdesign, gdesign, fgeo)
    pn = meta.get("power_nets") or {}
    dc = meta.get("decoupling") or []
    if pn or dc:
        L += ["", "### 2.6 Layout rules", ""]
        L += [f"- power net `{n}` (golden pins {', '.join(meta.get('power_net_pins', {}).get(n, []))}): "
              f"every track ≥ {w} mm" for n, w in sorted(pn.items())]
        L += [f"- decoupling: `{d['cap']}` within {d.get('max_path_mm', d['max_mm'])} mm of copper path (and {d['max_mm']} mm straight-line) of `{d['ic_pin']}`" for d in dc]
    if meta.get("alt_partitions"):
        L += ["", f"Alternative accepted topologies: {len(meta['alt_partitions'])} (see meta.json)."]
    latent = [(i, f) for i, f in enumerate(meta.get("faults", [])) if f.get("category") == "latent"]
    if latent:
        srcs = public_sources(task_dir)
        L += ["", "### 2.7 Latent faults and their public evidence", "",
              "A latent fault leaves `pcbtool check` clean; the agent can only find it by reading the public text. "
              "For each one: the generator's evidence claim, then every evidence group the generator's fairness gate "
              "requires (`pcbenv/faults/latent.py:evidence_groups`) with the exact public line it matched. Judge "
              "whether that text really lets an engineer infer the requirement (`task_fair`, `rule_stated_clearly`).", ""]
        for i, f in latent:
            d = f.get("data") or {}
            L += [f"**Fault {i + 1}: `{f['type']}`** — {_md_escape(f.get('detail', ''))}", "",
                  f"- detected by: `{d.get('detected_by') or f.get('detected_by') or '?'}`"
                  + (f"; rule violations it causes: {_md_escape('; '.join(d.get('rule_violations') or []))}"
                     if d.get("rule_violations") else ""),
                  f"- generator's evidence claim: {_md_escape(d.get('evidence') or f.get('evidence') or '—')}"]
            for e in evidence_quotes(f, srcs):
                alts = " / ".join(f"`{a}`" for a in e["group"])
                if e["found"]:
                    more = [x for x in e["files"] if x != e["file"]]
                    L.append(f"- evidence group {alts}: matched `{e['alt']}` in `{e['file']}`"
                             + (f" (also in {', '.join(f'`{x}`' for x in more)})" if more else "") + ":")
                    L.append(f"  > {_md_escape(e['quote'])}")
                else:
                    L.append(f"- evidence group {alts}: **⚠ NOT FOUND in the public material**")
            L.append("")
    rtab, nrules = rules_table(meta, fdesign, gdesign)
    if rtab:
        ctx = meta.get("rules") or meta.get("rules_power") or {}
        scope = ("all datasheet rules (hard tier)" if meta.get("rules") else
                 "resistor power only (`rules_power`, all v2 tiers)")
        L += ["", "### 2.8 Design rules (`rules` check, not run by pcbtool)", "",
              f"Scope: {scope}; {len(ctx.get('scenarios', []))} operating condition(s) from the spec's stimuli; "
              f"{nrules} rule quantities evaluated per design. Rows shown: violated on either side, on a part a fault "
              f"touches (if ≥ 5 % of its limit or changed by ≥ 5 points or by a footprint change), or at ≥ {RULE_NEAR:.0%} of the limit. Values are the worst case over the conditions "
              "(computed with `pcbenv.rules.operating_point`; limits from `pcbenv/rules.py`, stated in "
              "`parts/<PART>.md` and TASK.md \"Design rules\").", ""]
        L += rtab
        L += ["", "Rule violations reported by the verifier: faulted: "
              + (_md_escape("; ".join(fres["detail"].get("rules", []))) or "none")
              + "; golden: " + (_md_escape("; ".join(gres["detail"].get("rules", []))) or "none") + "."]
    if has_lr or (tier == "hard_layout"):
        fm, gm = layout_metrics(fboard, meta), layout_metrics(gboard, meta)
        L += ["", "### 2.9 Layout rules (`layout_rules` check + decoupling, not run by pcbtool)", "",
              "Measured with `pcbenv/layout_rules.py` / `pcbenv/layout.py` on each board (definitions in TASK.md "
              "\"Layout rules\"). The board renders draw the loop polygon (purple), the rule copper paths (cyan "
              "dashed), the Kelvin sense island with the shunt pad deleted (green) and analog-track stretches inside "
              "the separation gap (black dashes).", "",
              "| metric | limit | faulted | golden |", "|---|---|---|---|"]
        for k in sorted(set(fm) | set(gm)):
            a, b = fm.get(k), gm.get(k)
            lim = a or b

            def c(x):
                if x is None:
                    return "—"
                val = _q(x[0], "") if x[2] in ("",) else (f"{x[0]:.2f} {x[2]}" if isinstance(x[0], (int, float))
                                                         else str(x[0]))
                return f"{_md_escape(val)}{'' if x[3] else ' ❌'}"
            lim_s = lim[1] if isinstance(lim[1], str) else f"{lim[1]:g} {lim[2]}".strip()
            L.append(f"| {_md_escape(k)} | {_md_escape(lim_s)} | {c(a)} | {c(b)} |")
        lr = meta.get("layout_rules") or {}
        L += ["", f"Golden builder target: every layout rule at 0.8 × its limit. Rules in this task: "
              f"{', '.join(sorted(k for k in lr if k != 'version')) or 'none'}."]
    L += ["", "## 3. Review", "",
          "Fill `review.yaml` in this directory (second reviewer: copy `../../review_template.yaml` to "
          "`review-<initials>.yaml` here, without looking at the first form). Questions to answer:", "",
          "1. **task_fair / solvable_from_public_material**: from section 1 only, can a competent engineer locate "
          "and fix every injected fault? Is anything required that is not stated (a value with no assertion and no "
          "published range, a connection only the golden reveals)?",
          "2. **reference_fix_correct**: is the golden (2.2) a correct design that meets the stated intent?",
          "3. **verifier_verdict_agrees**: do you agree the faulted files fail and the golden passes, for the reasons "
          "given in 2.3?",
          "4. **alternative_valid_fixes_rejected**: is there an engineering-valid repair the grader would reject "
          "(e.g. a different E-series value that meets intent but fails an assertion window or value bound; "
          "keeping a swapped footprint and re-routing; a different valid placement)?",
          "5. **rule_stated_clearly**: is every design rule / layout rule / latent requirement this task grades "
          "(2.7–2.9) stated in the public material clearly enough that an engineer would apply it the way the "
          "grader does (limit, which part, which condition)? Normal-tier tasks: answer for the resistor-power rule "
          "(`yes` if no rule is involved).",
          "6. **layout_rule_reasonable**: hard_layout tasks only (else `n/a`): are the layout-rule limits and their "
          "geometric definitions (2.9) defensible engineering practice for this board, i.e. would you reject the "
          "faulted layout in a design review, and accept the golden one?", ""]
    (pdir / "README.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (pdir / "review.yaml").write_text(REVIEW_TEMPLATE.format(packet=name, task_id=row["id"]), encoding="utf-8")
    return {"packet": name, "id": row["id"], "family": row["family"], "hint": row["hint_level"], "tier": tier,
            "tools_mode": mode, "faults": [f["type"] for f in row["faults"]],
            "latent": [f["type"] for f in row["faults"] if f.get("category") == "latent"], "reasons": reasons,
            "faulted_reward": fres["reward"], "golden_reward": gres["reward"]}


def _build_job(args: tuple) -> dict:
    row, task_dir, out_dir, nn, reasons, width = args
    return build_packet(row, Path(task_dir), Path(out_dir), nn, reasons, width)


def _xtab(summaries: list[dict], key: str, label: str) -> list[str]:
    tiers = [t for t in TIERS if any(s["tier"] == t for s in summaries)]
    vals = sorted({v for s in summaries for v in (s[key] if isinstance(s[key], list) else [s[key]])}, key=str)
    out = [f"| {label} | " + " | ".join(tiers) + " | total |", "|---" * (len(tiers) + 2) + "|"]
    for v in vals:
        cs = [sum(1 for s in summaries if s["tier"] == t and (v in s[key] if isinstance(s[key], list) else s[key] == v))
              for t in tiers]
        out.append(f"| `{v}` | " + " | ".join(str(c) for c in cs) + f" | {sum(cs)} |")
    return out


def render_index(summaries: list[dict], n: int, seed: int, mix: str = DEFAULT_MIX,
                 pool: dict[str, int] | None = None) -> str:
    for s in summaries:
        s["ftypes"] = sorted(set(s["faults"]))
        s["nf"] = str(len(s["faults"]))
    tiers = Counter(s["tier"] for s in summaries)
    L = ["# Expert QA packets (G9, v2 tasks)", "",
         f"{len(summaries)} review packets for TRAIN tasks only (the `*_holdout` splits are never read or sampled), "
         f"built by `python3 -m pcbenv.qa build --n {n} --out qa/packets --seed {seed} --mix {mix}`. "
         "Tally with `python3 -m pcbenv.qa tally qa/packets`.", "",
         "Tiers: " + ", ".join(f"{t} {tiers.get(t, 0)}" + (f" (of {pool[t]} train tasks)" if pool and t in pool else "")
                               for t in TIERS) + ".", "",
         "## Instructions for reviewers", "",
         "You are a qualified electrical engineer checking that this benchmark is fair and graded correctly. "
         "You do **not** need KiCad: each packet's `README.md` has everything (TASK.md verbatim, datasheets, "
         "renders, the hidden faults, the reference fix as a diff, the verifier's verdicts and, for the hard tiers, "
         "the design-rule and layout-rule numbers before and after).", "",
         "- **Time budget:** about 5 minutes per normal packet, 10 per hard / hard_layout packet. If a packet needs "
         "more than twice that, mark `unsure` and say why in `notes`; that is itself a finding.",
         "- **Order:** read section 1 (agent's view) first and form your own opinion of what is wrong. Then read "
         "section 2 and compare.",
         "- **Tiers:** `normal` = visible faults (pcbtool finds most of them). `hard` adds the `rules` check "
         "(datasheet design rules stated in TASK.md \"Design rules\" and `parts/*.md`, NOT run by pcbtool) and "
         "**latent** faults that leave `pcbtool check` clean and can only be found by reading the public text "
         "(section 2.7 quotes the exact sentence the generator relies on). `hard_layout` adds the `layout_rules` "
         "check (Kelvin sense, switching-loop area, crystal path / vias, analog-switching separation; decoupling "
         "copper path under `layout`), with metrics in 2.9 and the loop / paths drawn on the board renders. "
         "`no_autoroute` tasks disable `pcbtool route` / `sync` (hand-edited tracks).",
         "- **What to look for:**",
         "  - The task demands something the public material does not state (hidden requirement, ambiguous "
         "connection, a value with no assertion and no published range, a latent fault whose quoted evidence "
         "does not really imply the requirement).",
         "  - The injected fault is not actually a fault (e.g. a value change that is still within a sensible "
         "engineering tolerance; a footprint that is equally valid; a decap distance or loop area that is fine "
         "in practice).",
         "  - A design / layout rule an expert would dispute (limit too tight or too loose, wrong definition, "
         "a rule that real datasheets do not impose).",
         "  - The golden/reference design is itself wrong or poor practice.",
         "  - The verifier fails the faulted files for the wrong reason, or would reject a valid alternative "
         "repair (different E-series value, re-routing instead of restoring, keeping an allowed footprint, a "
         "different but compliant layout).",
         "  - The verdict on the golden is anything but reward 1.",
         "- **Form:** fill `review.yaml` (first reviewer). The second reviewer copies `qa/review_template.yaml` to "
         "`review-<initials>.yaml` in the same packet dir, **without reading the first form**. v2 adds "
         "`rule_stated_clearly: yes|no` and `layout_rule_reasonable: yes|no|n/a` (`n/a` outside hard_layout).",
         "- Unfilled fields count as pending; you can stop and resume at any time.", "",
         "## Acceptance rule", "",
         "- Two independent EEs review every packet.",
         f"- Per reviewer, at least {AGREEMENT_MIN:.0%} of completed packets have `verifier_verdict_agrees: yes`, "
         f"`reference_fix_correct: yes` and `task_fair: yes` (computed by `tally`).",
         "- Every disputed packet (any `no`/`unsure` incl. `rule_stated_clearly: no` / `layout_rule_reasonable: no`, "
         "any rejected alternative fix, or the two reviewers disagreeing) must be resolved before sign-off: the "
         "orchestrator decides whether the **task** (regenerate / drop it, fix the TASK.md writer or fault injector) "
         "or the **verifier** (assertion window, value bound, rule limit, alt_partitions, check logic) is wrong, "
         "fixes it in the owning module, regenerates the affected tasks and packets, and the disputing reviewer "
         "re-reviews them. No task ships with an open dispute.",
         f"- The {AGREEMENT_MIN:.0%} threshold is not yet in `thresholds.yaml` (orchestrator-owned); "
         "proposed key `qa.ee_verifier_agreement_min: 0.95`.",
         "- Human sign-off is founder-owned. [`self_review_v2.md`](self_review_v2.md) is a pre-screen of 15 v2 "
         "packets by the QA agent (not a substitute); read its findings before starting, they list the cases most "
         "likely to be disputed. ([`self_review.md`](self_review.md) is the v1 pre-screen, kept for history; its "
         "packet numbers refer to the deleted v1 packets.)", "",
         "## Sample composition", ""]
    L += _xtab(summaries, "family", "family") + [""]
    L += _xtab(summaries, "hint", "hint level") + [""]
    L += _xtab(summaries, "tools_mode", "tool mode") + [""]
    L += _xtab(summaries, "nf", "faults per task") + [""]
    L += _xtab(summaries, "ftypes", "fault type (packets containing it)") + [""]
    L += ["Latent fault types are the ones also listed in the packets' `latent` column; every latent and "
          "layout-latent type of the train splits is covered.", "",
          "## Packets", "",
          "| # | tier | task | family | faults (latent in bold) | hint | tools | why sampled | packet |",
          "|---|---|---|---|---|---|---|---|---|"]
    for s in summaries:
        fl = ", ".join(f"**{t}**" if t in s.get("latent", []) else t for t in s["faults"])
        L.append(f"| {s['packet'].split('-', 1)[0]} | {s['tier']} | `{s['id']}` | {s['family']} | {fl} | {s['hint']} | "
                 f"{s['tools_mode']} | {_md_escape('; '.join(s['reasons'])) or 'coverage'} | "
                 f"[README](packets/{s['packet']}/README.md) |")
    return "\n".join(L) + "\n"


def build(n: int, out: Path, seed: int, manifest: Path, tasks_root: Path, workers: int = 4,
          index: Path | None = None, mix: str | None = DEFAULT_MIX) -> list[dict]:
    rows = load_train_rows(manifest, tasks_root)
    mixd = parse_mix(mix) if mix else None
    if mixd is not None:
        rows = [r for r in rows if tier_of(r) in mixd]
    metas = {r["id"]: json.loads((task_dir_of(tasks_root, r) / "hidden" / "meta.json").read_text())
             for r in rows}
    pub = {r["id"]: public_sources(task_dir_of(tasks_root, r)) for r in rows}
    chosen = select_tasks(rows, metas, n, seed, mixd, pub)
    chosen.sort(key=lambda r: (TIERS.index(tier_of(r)) if tier_of(r) in TIERS else 9, r["family"], r["id"]))
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():
        if old.is_dir() and re.match(r"\d\d+-pcbr2?-", old.name):
            shutil.rmtree(old)
    width = max(2, len(str(len(chosen))))
    jobs = [(r, str(task_dir_of(tasks_root, r)), str(out), i + 1,
             task_features(r, metas[r["id"]], pub[r["id"]])["reasons"], width) for i, r in enumerate(chosen)]
    if workers > 1 and len(jobs) > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(workers) as pool:
            summaries = pool.map(_build_job, jobs, chunksize=1)
    else:
        summaries = [_build_job(j) for j in jobs]
    idx = index if index is not None else out.parent / "INDEX.md"
    idx.write_text(render_index(summaries, n, seed, mix or "", dict(Counter(tier_of(r) for r in rows))),
                   encoding="utf-8")
    (idx.parent / "review_template.yaml").write_text(
        REVIEW_TEMPLATE.format(packet="<packet>", task_id="<task id>"), encoding="utf-8")
    return summaries


# ====================================================================== tally
def _norm(v) -> str:
    if v is None:
        return ""
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return str(v).strip().lower()


def read_reviews(packet_dir: Path) -> list[dict]:
    out = []
    for f in sorted(packet_dir.glob("review*.yaml")):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            d = {"_error": str(e)}
        if not isinstance(d, dict):
            d = {"_error": "not a mapping"}
        d["_file"] = f.name
        out.append(d)
    return out


def review_status(d: dict) -> str:
    """'pending' (nothing filled), 'partial', 'complete' or 'invalid'."""
    if "_error" in d:
        return "invalid"
    filled = [k for k in REVIEW_FIELDS if _norm(d.get(k))]
    if not filled:
        return "pending"
    for k in filled:
        allowed = REVIEW_FIELDS[k]
        if allowed and _norm(d.get(k)) not in allowed:
            return "invalid"
    return "complete" if len(filled) == len(REVIEW_FIELDS) else "partial"


DISPUTE_KEYS = ("task_fair", "solvable_from_public_material", "reference_fix_correct", "verifier_verdict_agrees",
                "rule_stated_clearly", "layout_rule_reasonable")


def _agrees(d: dict) -> bool:
    return (_norm(d.get("verifier_verdict_agrees")) == "yes" and _norm(d.get("reference_fix_correct")) == "yes"
            and _norm(d.get("task_fair")) == "yes")


def _disputes(d: dict) -> list[str]:
    out = []
    for k in DISPUTE_KEYS:
        v = _norm(d.get(k))
        if v in ("no", "unsure"):
            out.append(f"{k}={v}")
    alt = _norm(d.get("alternative_valid_fixes_rejected"))
    if alt and alt not in ("none", "no", "n/a"):
        out.append(f"alternative fix rejected: {str(d.get('alternative_valid_fixes_rejected'))[:120]}")
    return out


def tally(packets_dir: Path) -> dict:
    packets = sorted(p for p in Path(packets_dir).iterdir() if p.is_dir() and (p / "README.md").exists())
    status = Counter()
    by_reviewer: dict[str, list[dict]] = defaultdict(list)
    field_counts: dict[str, Counter] = {k: Counter() for k in REVIEW_FIELDS}
    disputed: list[tuple[str, str]] = []
    pending: list[str] = []
    for p in packets:
        revs = read_reviews(p)
        complete = []
        any_filled = False
        for d in revs:
            st = review_status(d)
            status[st] += 1
            if st == "invalid":
                disputed.append((p.name, f"{d['_file']}: invalid form ({d.get('_error', 'bad field value')})"))
                continue
            if st == "pending":
                continue
            any_filled = True
            for k in REVIEW_FIELDS:
                v = _norm(d.get(k))
                if v:
                    field_counts[k]["none" if k == "alternative_valid_fixes_rejected" and v == "none" else
                                    ("described" if k == "alternative_valid_fixes_rejected" else v)] += 1
            for reason in _disputes(d):
                disputed.append((p.name, f"{d['_file']} ({d.get('reviewer') or '?'}): {reason}"))
            if st == "complete":
                complete.append(d)
                by_reviewer[str(d.get("reviewer") or d["_file"])].append({"packet": p.name, "agrees": _agrees(d)})
        if not any_filled:
            pending.append(p.name)
        if len(complete) >= 2:
            if len({tuple(_norm(d.get(k)) for k in DISPUTE_KEYS) for d in complete}) > 1:
                disputed.append((p.name, "reviewers disagree"))
    reviewers = {r: {"complete": len(v), "agree": sum(x["agrees"] for x in v),
                     "rate": (sum(x["agrees"] for x in v) / len(v)) if v else None} for r, v in sorted(by_reviewer.items())}
    two = sum(1 for p in packets if sum(review_status(d) == "complete" for d in read_reviews(p)) >= 2)
    accepted = (len(reviewers) >= 2 and two == len(packets) and not disputed
                and all(v["rate"] is not None and v["rate"] >= AGREEMENT_MIN for v in reviewers.values()))
    return {"packets": len(packets), "forms": dict(status), "pending_packets": pending, "reviewers": reviewers,
            "packets_with_two_complete_reviews": two, "fields": {k: dict(v) for k, v in field_counts.items()},
            "disputed": disputed, "accepted": accepted}


def print_tally(t: dict) -> None:
    print(f"packets: {t['packets']}   forms: {t['forms']}")
    print(f"packets with no filled review (pending): {len(t['pending_packets'])}")
    print(f"packets with >=2 complete reviews: {t['packets_with_two_complete_reviews']}/{t['packets']}")
    for r, v in t["reviewers"].items():
        rate = "n/a" if v["rate"] is None else f"{v['rate']:.1%}"
        print(f"reviewer {r}: {v['complete']} complete, agree with verifier+fix+fairness {v['agree']} ({rate})")
    for k, c in t["fields"].items():
        if c:
            print(f"  {k}: {dict(sorted(c.items()))}")
    print(f"disputed: {len({p for p, _ in t['disputed']})} packet(s)")
    for p, why in t["disputed"]:
        print(f"  {p}: {why}")
    print(f"ACCEPTED (2 EEs, every packet reviewed twice, agreement >= {AGREEMENT_MIN:.0%}, no open disputes): "
          f"{'yes' if t['accepted'] else 'no'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m pcbenv.qa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--n", type=int, default=100)
    b.add_argument("--out", default="qa/packets")
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--manifest", default=str(ROOT / "tasks" / "manifest.jsonl"))
    b.add_argument("--tasks", default=str(ROOT / "tasks"))
    b.add_argument("--workers", type=int, default=4)
    b.add_argument("--mix", default=DEFAULT_MIX,
                   help=f"tier quotas as percentages (default {DEFAULT_MIX}); holdout splits are never sampled")
    t = sub.add_parser("tally")
    t.add_argument("packets")
    t.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        t0 = time.monotonic()
        s = build(a.n, Path(a.out), a.seed, Path(a.manifest), Path(a.tasks), a.workers, mix=a.mix)
        dt = time.monotonic() - t0
        bad = [x["packet"] for x in s if x["faulted_reward"] != 0.0 or x["golden_reward"] != 1.0]
        print(f"built {len(s)} packets in {dt:.1f} s ({dt / max(len(s), 1):.2f} s/packet, {a.workers} workers)",
              file=sys.stderr)
        if bad:
            print(f"WARNING: verdict anomalies (faulted != 0 or golden != 1): {bad}", file=sys.stderr)
        return 0
    res = tally(Path(a.packets))
    if a.json:
        print(json.dumps(res, indent=2, sort_keys=True))
    else:
        print_tally(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
