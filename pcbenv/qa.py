"""Expert-QA review packets (G9): build reviewer packets for a stratified task sample, tally reviews.

    python3 -m pcbenv.qa build --n 100 --out qa/packets --seed 7 [--workers 4]
    python3 -m pcbenv.qa tally qa/packets

Only TRAIN tasks are ever used (manifest row not holdout AND no path part of the task dir contains
"holdout", e.g. `tasks/v2/normal/` or `tasks/v2/hard/`); holdout tasks are refused. A packet is `<out>/<nn>-<task_id>/`:

- `README.md`   TASK.md verbatim (what the agent sees) + reviewer-only section (faults, reference
                fix as a diff, verifier verdicts on faulted and golden files, spec assertions
                before/after, value bounds).
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
DISPUTED_TYPES = ("bom_mismatch", "footprint_swap", "decap_moved_far", "narrow_power_trace")
NEAR_BOUND_FACTOR = 1.5
AGREEMENT_MIN = 0.95  # acceptance rule (not yet in thresholds.yaml; orchestrator-owned)

REVIEW_FIELDS = {
    "task_fair": ("yes", "no", "unsure"),
    "solvable_from_public_material": ("yes", "no"),
    "reference_fix_correct": ("yes", "no"),
    "verifier_verdict_agrees": ("yes", "no"),
    "alternative_valid_fixes_rejected": None,   # "none" or free text
    "severity_if_wrong": ("low", "med", "high"),
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


def task_features(row: dict, meta: dict) -> dict:
    types = [f["type"] for f in row["faults"]]
    cats = [f["category"] for f in row["faults"]]
    near = near_bound_faults(meta.get("faults", []), meta.get("value_bounds") or {})
    reasons = []
    if row["n_faults"] >= 3:
        reasons.append("3 faults")
    if row["hint_level"] == "vague":
        reasons.append("vague hint")
    if "connectivity" in cats:
        reasons.append("connectivity fault")
    for t in sorted(set(types) & set(DISPUTED_TYPES)):
        reasons.append(f"disputable type {t}")
    if near:
        reasons.append("value near bounds: " + "; ".join(near))
    score = ((row["n_faults"] >= 3) + (row["hint_level"] == "vague") + 0.5 * ("connectivity" in cats)
             + len(set(types) & set(DISPUTED_TYPES)) + bool(near))
    keys = [("family", row["family"]), ("hint", row["hint_level"]), ("nf", row["n_faults"]),
            ("fam_hint", row["family"], row["hint_level"])]
    for t in sorted(set(types)):
        keys += [("ftype", t), ("ftype_hint", t, row["hint_level"]), ("fam_ftype", row["family"], t)]
    return {"keys": keys, "score": score, "reasons": reasons}


KEY_WEIGHTS = {"family": 3.0, "hint": 3.0, "nf": 12.0, "fam_hint": 2.0, "ftype": 5.0, "ftype_hint": 1.0,
               "fam_ftype": 1.0}
FAULT_KEYS = ("ftype", "ftype_hint", "fam_ftype")  # divided by #faults so 3-fault tasks don't win by count
AMBIG_WEIGHT = 0.25


def select_tasks(rows: list[dict], metas: dict[str, dict], n: int, seed: int) -> list[dict]:
    """Greedy stratified sample: each pick maximises coverage gain over strata (family, hint,
    #faults, family x hint, fault type, fault type x hint, family x fault type), each stratum
    giving weight/(1+already picked), times an ambiguity multiplier; seeded jitter breaks ties."""
    rng = random.Random(seed)
    feats = {r["id"]: task_features(r, metas[r["id"]]) for r in rows}
    jitter = {r["id"]: rng.random() * 1e-3 for r in rows}
    counts: Counter = Counter()
    chosen: list[dict] = []
    left = list(rows)
    while left and len(chosen) < n:
        def gain(r):
            f = feats[r["id"]]
            nf = max(1, r["n_faults"])
            cov = sum(KEY_WEIGHTS[k[0]] / (1 + counts[k]) / (nf if k[0] in FAULT_KEYS else 1) for k in f["keys"])
            return cov * (1 + AMBIG_WEIGHT * f["score"]) + jitter[r["id"]]
        best = max(left, key=gain)
        left.remove(best)
        chosen.append(best)
        counts.update(feats[best["id"]]["keys"])
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


def render_board_svg(geo: dict, other: dict | None, title: str) -> str:
    """Board plot: outline, courtyards, pads (net-labelled), tracks by layer, vias. Items that
    differ from `other` (the counterpart board) are drawn with a yellow halo / magenta box."""
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
    for e in geo["edges"]:
        o.append(f'<polyline points="{poly(e)}" fill="none" stroke="#c9b000" stroke-width="2"/>')
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
    for k in GATES + CHECKS:
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

    fgeo = board_geometry(str(task_dir / "public" / "board.kicad_pcb"))
    ggeo = board_geometry(str(task_dir / "hidden" / "golden_board.kicad_pcb"))
    renders = {
        "schematic_faulted.svg": render_schematic_svg(fdesign, gdesign, f"{row['id']} — design.json as given (faulted)"),
        "schematic_golden.svg": render_schematic_svg(gdesign, gdesign, f"{row['id']} — golden design (reference fix)"),
        "board_faulted.svg": render_board_svg(fgeo, ggeo, f"{row['id']} — board.kicad_pcb as given (faulted)"),
        "board_golden.svg": render_board_svg(ggeo, fgeo, f"{row['id']} — golden board (reference fix)"),
    }
    for fname, svg in renders.items():
        (pdir / fname).write_text(svg, encoding="utf-8")
    fres, gres = _verify_both(task_dir)
    ddiff = design_diff(fdesign, gdesign)
    cdiff = connection_diff(fdesign, gdesign, meta.get("ref_parts", {}))
    bdiff = board_diff(fgeo, ggeo)
    rel = os.path.relpath(task_dir, pdir)

    L: list[str] = [f"# QA packet {num}: `{row['id']}`", "",
                    "| family | tier | hint level | intent in TASK.md | faults | predicted difficulty |",
                    "|---|---|---|---|---|---|",
                    f"| {row['family']} | {row.get('tier', 'v1')} | {row['hint_level']} | {row.get('intent', '')} | "
                    f"{row['n_faults']} | {row.get('difficulty_predicted', '')} |", "",
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
          "| # | type | category | DRC/ERC-invisible | detail | verifier, this fault alone |", "|---|---|---|---|---|---|"]
    alone = {i: a for i, a in enumerate(row.get("alone", []))}
    for i, f in enumerate(meta.get("faults", [])):
        a = alone.get(i, {})
        al = f"reward {a.get('reward', '?')}; fails {', '.join(a.get('failing', [])) or '—'}" if a else "—"
        L.append(f"| {i + 1} | `{f['type']}` | {f.get('category', '')} | "
                 f"{'yes' if f.get('invisible_to_drc_erc') else 'no'} | {_md_escape(f.get('detail', ''))} | {al} |")
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
          "keeping a swapped footprint and re-routing; a different valid placement)?", ""]
    (pdir / "README.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (pdir / "review.yaml").write_text(REVIEW_TEMPLATE.format(packet=name, task_id=row["id"]), encoding="utf-8")
    return {"packet": name, "id": row["id"], "family": row["family"], "hint": row["hint_level"],
            "faults": [f["type"] for f in row["faults"]], "reasons": reasons,
            "faulted_reward": fres["reward"], "golden_reward": gres["reward"]}


def _build_job(args: tuple) -> dict:
    row, task_dir, out_dir, nn, reasons, width = args
    return build_packet(row, Path(task_dir), Path(out_dir), nn, reasons, width)


def render_index(summaries: list[dict], n: int, seed: int) -> str:
    fams = Counter(s["family"] for s in summaries)
    hints = Counter(s["hint"] for s in summaries)
    ftypes = Counter(t for s in summaries for t in set(s["faults"]))
    nf = Counter(len(s["faults"]) for s in summaries)
    L = ["# Expert QA packets (G9)", "",
         f"{len(summaries)} review packets for TRAIN tasks only (holdout is never sampled), built by "
         f"`python3 -m pcbenv.qa build --n {n} --out qa/packets --seed {seed}`. "
         "Tally with `python3 -m pcbenv.qa tally qa/packets`.", "",
         "## Instructions for reviewers", "",
         "You are a qualified electrical engineer checking that this benchmark is fair and graded correctly. "
         "You do **not** need KiCad: each packet's `README.md` has everything (TASK.md verbatim, datasheets, "
         "renders, the hidden faults, the reference fix as a diff, and the verifier's verdicts).", "",
         "- **Time budget:** about 5 minutes per packet. If a packet needs more than 10, mark `unsure` and say why "
         "in `notes`; that is itself a finding.",
         "- **Order:** read section 1 (agent's view) first and form your own opinion of what is wrong. Then read "
         "section 2 and compare.",
         "- **What to look for:**",
         "  - The task demands something the public material does not state (hidden requirement, ambiguous "
         "connection, a value with no assertion and no published range).",
         "  - The injected fault is not actually a fault (e.g. a value change that is still within a sensible "
         "engineering tolerance; a footprint that is equally valid; a decap distance that is fine in practice).",
         "  - The golden/reference design is itself wrong or poor practice.",
         "  - The verifier fails the faulted files for the wrong reason, or would reject a valid alternative "
         "repair (different E-series value, re-routing instead of restoring, keeping an allowed footprint).",
         "  - The verdict on the golden is anything but reward 1.",
         "- **Form:** fill `review.yaml` (first reviewer). The second reviewer copies `qa/review_template.yaml` to "
         "`review-<initials>.yaml` in the same packet dir, **without reading the first form**.",
         "- Unfilled fields count as pending; you can stop and resume at any time.", "",
         "## Acceptance rule", "",
         f"- Two independent EEs review every packet.",
         f"- Per reviewer, at least {AGREEMENT_MIN:.0%} of completed packets have `verifier_verdict_agrees: yes`, "
         f"`reference_fix_correct: yes` and `task_fair: yes` (computed by `tally`).",
         "- Every disputed packet (any `no`/`unsure`, any rejected alternative fix, or the two reviewers "
         "disagreeing) must be resolved before sign-off: the orchestrator decides whether the **task** "
         "(regenerate / drop it, fix the TASK.md writer or fault injector) or the **verifier** (assertion window, "
         "value bound, alt_partitions, check logic) is wrong, fixes it in the owning module, regenerates the "
         "affected tasks and packets, and the disputing reviewer re-reviews them. No task ships with an open dispute.",
         f"- The {AGREEMENT_MIN:.0%} threshold is not yet in `thresholds.yaml` (orchestrator-owned); "
         "proposed key `qa.ee_verifier_agreement_min: 0.95`.",
         "- Human sign-off is founder-owned. [`self_review.md`](self_review.md) is a pre-screen of 15 packets by "
         "the packaging agent (not a substitute); read its findings before starting, they list the cases most "
         "likely to be disputed.", "",
         "## Sample composition", "",
         "| family | packets |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(fams.items())] + [
         "", "| hint level | packets |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(hints.items())] + [
         "", "| faults per task | packets |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(nf.items())] + [
         "", "| fault type | packets containing it |", "|---|---|"] + [
         f"| `{k}` | {v} |" for k, v in sorted(ftypes.items())] + [
         "", "## Packets", "",
         "| # | task | family | faults | hint | why sampled | packet |", "|---|---|---|---|---|---|---|"]
    for s in summaries:
        L.append(f"| {s['packet'].split('-', 1)[0]} | `{s['id']}` | {s['family']} | {', '.join(s['faults'])} | {s['hint']} | "
                 f"{_md_escape('; '.join(s['reasons'])) or 'coverage'} | [README](packets/{s['packet']}/README.md) |")
    return "\n".join(L) + "\n"


def build(n: int, out: Path, seed: int, manifest: Path, tasks_root: Path, workers: int = 4,
          index: Path | None = None) -> list[dict]:
    rows = load_train_rows(manifest, tasks_root)
    metas = {r["id"]: json.loads((task_dir_of(tasks_root, r) / "hidden" / "meta.json").read_text())
             for r in rows}
    chosen = select_tasks(rows, metas, n, seed)
    chosen.sort(key=lambda r: (r["family"], r["id"]))
    out.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():
        if old.is_dir() and re.match(r"\d\d+-pcbr2?-", old.name):
            shutil.rmtree(old)
    width = max(2, len(str(len(chosen))))
    jobs = [(r, str(task_dir_of(tasks_root, r)), str(out), i + 1, task_features(r, metas[r["id"]])["reasons"], width)
            for i, r in enumerate(chosen)]
    if workers > 1 and len(jobs) > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(workers) as pool:
            summaries = pool.map(_build_job, jobs, chunksize=1)
    else:
        summaries = [_build_job(j) for j in jobs]
    idx = index if index is not None else out.parent / "INDEX.md"
    idx.write_text(render_index(summaries, n, seed), encoding="utf-8")
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


def _agrees(d: dict) -> bool:
    return (_norm(d.get("verifier_verdict_agrees")) == "yes" and _norm(d.get("reference_fix_correct")) == "yes"
            and _norm(d.get("task_fair")) == "yes")


def _disputes(d: dict) -> list[str]:
    out = []
    for k in ("task_fair", "solvable_from_public_material", "reference_fix_correct", "verifier_verdict_agrees"):
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
            keys = ("task_fair", "solvable_from_public_material", "reference_fix_correct", "verifier_verdict_agrees")
            if len({tuple(_norm(d.get(k)) for k in keys) for d in complete}) > 1:
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
    t = sub.add_parser("tally")
    t.add_argument("packets")
    t.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        t0 = time.monotonic()
        s = build(a.n, Path(a.out), a.seed, Path(a.manifest), Path(a.tasks), a.workers)
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
