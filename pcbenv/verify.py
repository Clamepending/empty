"""The grader (SPEC §7): `verify(workdir, task_dir) -> VerifyResult`.

Trust boundary
- From `workdir` only `design.json` and `board.kicad_pcb` are read: each must be a regular
  file (not a symlink, opened with O_NOFOLLOW), at most 5 MB. The bytes are copied into a
  fresh temp dir and everything is parsed from there. Nothing in `workdir` is imported,
  executed, or used as configuration (DRC rules are canonical, see `drc.py`).
- Everything else -- the golden design/board, ref->part map, assertions, power nets,
  decoupling, value bounds, alt partitions -- comes from `task_dir/hidden/`.
- Any exception inside `verify` gives reward 0 with the error in `detail["error"]`.
  `verify_isolated` additionally runs it in a fresh subprocess (KiCad's SWIG layer leaks
  memory and could in principle crash on a hostile file).

Hard gates (reward 0 if any fails): parse, components, topology, consistency, integrity.
Checks (all must pass for reward 1): drc, erc, spec, values, layout, and -- only for tasks whose
meta carries a rule context (`rules` hard tier / `rules_power`) -- `rules` (`pcbenv/rules.py`,
datasheet design rules that pcbtool does not run). Reward is binary.
`values`: every ref in `meta["value_bounds"]` (ref -> [min, max]) has a design value inside its
range (old tasks without the key: nothing to check, the check passes).

Topology is compared up to swapping the two pins of symmetric parts (R, C, L, crystals);
see `layout.same_topology`. Board pads are named through the GOLDEN ref->part map.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_FILE_BYTES = 5 * 1024 * 1024
DELIVERABLES = ("design.json", "board.kicad_pcb")
GATES = ("parse", "components", "topology", "consistency", "integrity")
CHECKS = ("drc", "erc", "spec", "values", "layout")
ROOT = str(Path(__file__).resolve().parent.parent)
_MARK = "PCBENV_VERIFY_JSON:"


@dataclass
class VerifyResult:
    reward: float
    gates: dict[str, bool] = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)
    detail: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, d: dict) -> "VerifyResult":
        return cls(float(d["reward"]), dict(d.get("gates", {})), dict(d.get("checks", {})), dict(d.get("detail", {})))


class UnsafeInput(ValueError):
    pass


def safe_copy(workdir: str, name: str, dst_dir: str) -> str:
    """Copy workdir/name into dst_dir after checking it is a small regular non-symlink file."""
    src = os.path.join(workdir, name)
    try:
        st = os.lstat(src)
    except FileNotFoundError:
        raise UnsafeInput(f"{name}: missing") from None
    if stat.S_ISLNK(st.st_mode):
        raise UnsafeInput(f"{name}: is a symlink")
    if not stat.S_ISREG(st.st_mode):
        raise UnsafeInput(f"{name}: not a regular file")
    if st.st_size > MAX_FILE_BYTES:
        raise UnsafeInput(f"{name}: larger than {MAX_FILE_BYTES} bytes")
    fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    try:
        st2 = os.fstat(fd)
        if not stat.S_ISREG(st2.st_mode) or (st2.st_dev, st2.st_ino) != (st.st_dev, st.st_ino):
            raise UnsafeInput(f"{name}: changed while reading")
        chunks, total = [], 0
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            total += len(b)
            if total > MAX_FILE_BYTES:
                raise UnsafeInput(f"{name}: larger than {MAX_FILE_BYTES} bytes")
            chunks.append(b)
    finally:
        os.close(fd)
    dst = os.path.join(dst_dir, name)
    with open(dst, "wb") as f:
        f.write(b"".join(chunks))
    return dst


def _fail(result: VerifyResult, key: str, msgs: list[str], gate: bool) -> None:
    (result.gates if gate else result.checks)[key] = not msgs
    if msgs:
        result.detail[key] = msgs[:50]


def _hidden(task_dir: str) -> tuple[dict, dict, str]:
    from pcbenv import taskio
    meta = taskio.load_meta(task_dir)
    gdesign = taskio.load_golden_design(task_dir)
    gboard = taskio.golden_board_path(task_dir)
    if not os.path.isfile(gboard):
        raise FileNotFoundError("hidden golden board missing")
    if "ref_parts" not in meta:
        meta["ref_parts"] = {r: c["part"] for r, c in gdesign["components"].items()}
    if "power_net_pins" not in meta:
        meta["power_net_pins"] = {n: sorted(gdesign["nets"].get(n, [])) for n in meta.get("power_nets", {})}
    return meta, gdesign, gboard


def _verify(workdir: str, task_dir: str, td: str) -> VerifyResult:
    import pcbnew

    from pcbenv import boardnet, drc, erc, layout, sim
    from pcbenv import design as D
    from pcbenv.parts import PARTS, values_equal

    res = VerifyResult(0.0)
    meta, gdesign, gboard_path = _hidden(task_dir)
    ref_parts: dict[str, str] = meta["ref_parts"]

    # ---------------------------------------------------------------- parse
    msgs: list[str] = []
    design = board = None
    try:
        dpath = safe_copy(workdir, "design.json", td)
        bpath = safe_copy(workdir, "board.kicad_pcb", td)
    except (UnsafeInput, OSError) as e:
        _fail(res, "parse", [str(e)], True)
        return res
    try:
        with open(dpath, encoding="utf-8") as f:
            design = json.load(f)
        D.validate(design)
    except Exception as e:  # noqa: BLE001
        msgs.append(f"design.json: {type(e).__name__}: {e}"[:500])
        design = None
    try:
        board = pcbnew.LoadBoard(bpath)
        if board is None:
            raise RuntimeError("LoadBoard returned None")
    except Exception as e:  # noqa: BLE001
        msgs.append(f"board.kicad_pcb: {type(e).__name__}: {e}"[:500])
        board = None
    _fail(res, "parse", msgs, True)
    if msgs:
        return res

    gboard = boardnet.load_board(gboard_path)
    info = boardnet.board_info(board, parts=ref_parts)
    ginfo = boardnet.board_info(gboard, parts=ref_parts)
    comps = design["components"]

    # ----------------------------------------------------------- components
    msgs = []
    if set(comps) != set(ref_parts):
        msgs.append(f"design refs differ from golden: missing {sorted(set(ref_parts) - set(comps))}, "
                    f"extra {sorted(set(comps) - set(ref_parts))}")
    if info.duplicate_refs:
        msgs.append(f"duplicate refs on board: {info.duplicate_refs}")
    if set(info.footprints) != set(ref_parts):
        msgs.append(f"board footprints differ from golden: missing {sorted(set(ref_parts) - set(info.footprints))}, "
                    f"extra {sorted(set(info.footprints) - set(ref_parts))}")
    for ref in sorted(set(comps) & set(ref_parts)):
        c = comps[ref]
        if c["part"] != ref_parts[ref]:
            msgs.append(f"{ref}: part {c['part']} != golden {ref_parts[ref]}")
            continue
        fpid = c["footprint"]
        if fpid not in PARTS[c["part"]].footprints:
            msgs.append(f"{ref}: footprint {fpid} not allowed for part {c['part']}")
        bf = info.footprints.get(ref)
        if bf is None:
            continue
        if bf != fpid:
            msgs.append(f"{ref}: board footprint {bf} != design footprint {fpid}")
            continue
        if fpid not in PARTS[c["part"]].footprints:
            continue  # never look up a library path the agent chose
        lib = boardnet.library_pad_fingerprint(bf)
        if lib is None or info.pad_fingerprint.get(ref) != lib:
            msgs.append(f"{ref}: footprint pads/courtyard differ from library footprint {bf}")
        fp = board.FindFootprintByReference(ref)
        proto = boardnet.library_footprint(bf)
        if fp is None or proto is None or _copper_graphics(fp) != _copper_graphics(proto):
            msgs.append(f"{ref}: footprint copper graphics differ from library")
    _fail(res, "components", msgs, True)

    # ------------------------------------------------------------- topology
    dpart = D.partition(design)
    gpart = D.partition(gdesign)
    alts = [frozenset(frozenset(n) for n in alt) for alt in meta.get("alt_partitions", [])]
    ok = any(layout.same_topology(dpart, p, ref_parts) for p in [gpart, *alts])
    _fail(res, "topology", [] if ok else [_partition_diff(dpart, gpart)], True)

    # ---------------------------------------------------------- consistency
    msgs = []
    if info.partition != dpart:
        msgs.append("board connectivity != design.json: " + _partition_diff(info.partition, dpart))
    for ref in sorted(comps):
        if ref in info.values and not values_equal(info.values[ref], comps[ref].get("value", ""), comps[ref]["part"]):
            msgs.append(f"{ref}: board value {info.values[ref]!r} != design value {comps[ref].get('value', '')!r}")
    _fail(res, "consistency", msgs, True)

    # ------------------------------------------------------------ integrity
    msgs = []
    if info.outline_fingerprint != ginfo.outline_fingerprint:
        msgs.append("board outline (Edge.Cuts) differs from the golden")
    if info.marker_count or info.exclusion_count:
        msgs.append(f"DRC markers/exclusions present ({info.marker_count}/{info.exclusion_count})")
    if info.zone_count > ginfo.zone_count:
        msgs.append(f"zones added ({info.zone_count} > {ginfo.zone_count})")
    if board.GetCopperLayerCount() != gboard.GetCopperLayerCount():
        msgs.append(f"copper layer count {board.GetCopperLayerCount()} != {gboard.GetCopperLayerCount()}")
    bad_layers = sorted({t.GetLayerName() for t in board.GetTracks()
                         if t.GetClass() != "PCB_VIA" and t.GetLayer() not in (pcbnew.F_Cu, pcbnew.B_Cu)})
    if bad_layers:
        msgs.append(f"tracks on non-outer layers {bad_layers}")
    if _board_copper_drawings(board) > _board_copper_drawings(gboard):
        msgs.append("copper graphics/text added to the board")
    _fail(res, "integrity", msgs, True)

    # ---------------------------------------------------------------- checks
    r = drc.run_drc(bpath, gboard_path)
    msgs = [f"{e['type']}: {e['description']} @ {e['pos']}" for e in r.errors]
    if r.unconnected:
        msgs.append(f"{r.unconnected} unconnected items")
    _fail(res, "drc", msgs, False)

    _fail(res, "erc", [f"{i.code}: {i.detail}" for i in erc.errors(erc.run_erc(design))], False)

    try:
        ares = sim.run_assertions(design, meta.get("assertions", []))
        msgs = [f"{a.name}: measured {a.measured} expected {a.expected} {a.detail}".strip() for a in ares if not a.passed]
        if len(ares) != len(meta.get("assertions", [])):
            msgs.append("assertion count mismatch")
    except Exception as e:  # noqa: BLE001
        msgs = [f"simulation error: {e}"]
    _fail(res, "spec", msgs, False)

    from pcbenv.checks import value_violations
    _fail(res, "values", value_violations(design, meta.get("value_bounds") or {}), False)

    lay = layout.run_layout_checks(info, meta, board=board, ref_parts=ref_parts)
    if not res.gates.get("topology"):
        # a golden power net cannot be found by its pin set because the connectivity is wrong: that
        # is the topology gate's finding, not a layout one (QA F9); reported as a skip, not a failure
        skipped = [i for i in lay if i.code == "power_net_missing"]
        if skipped:
            res.detail["layout_skipped"] = [f"{i.detail} (connectivity differs: see topology)" for i in skipped][:20]
        lay = [i for i in lay if i.code != "power_net_missing"]
    _fail(res, "layout", [f"{i.code}: {i.detail}" for i in lay], False)

    # Datasheet design rules (`pcbenv/rules.py`): only for tasks whose hidden meta carries a rule
    # context -- hard tier: all rules (`rules`); all-tier v2 tasks: resistor power (`rules_power`).
    rctx = meta.get("rules") or meta.get("rules_power")
    if rctx:
        from pcbenv import rules as RL
        _fail(res, "rules", [f"{v.code}: {v.detail}" for v in RL.run_rules(design, rctx)], False)

    ok = (all(res.gates.get(g) for g in GATES) and all(res.checks.get(c) for c in CHECKS)
          and all(res.checks.values()))
    res.reward = 1.0 if ok else 0.0
    return res


def _copper_graphics(fp) -> int:
    import pcbnew
    return sum(1 for g in fp.GraphicalItems() if g.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu)) + len(fp.Zones())


def _board_copper_drawings(board) -> int:
    import pcbnew
    n = sum(1 for d in board.GetDrawings() if d.IsOnLayer(pcbnew.F_Cu) or d.IsOnLayer(pcbnew.B_Cu))
    return n + sum(1 for fp in board.GetFootprints() for g in fp.GraphicalItems()
                   if g.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu))


def _partition_diff(a: frozenset, b: frozenset) -> str:
    only_a = sorted(sorted(n) for n in a - b)
    only_b = sorted(sorted(n) for n in b - a)
    return f"nets only in candidate: {only_a[:8]}; nets only in reference: {only_b[:8]}"[:1500]


def verify(workdir: str, task_dir: str) -> VerifyResult:
    """Grade the deliverables in `workdir` against `task_dir/hidden`. Never raises."""
    t0 = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="pcbverify_") as td:
            res = _verify(os.fspath(workdir), os.fspath(task_dir), td)
            # temp paths in messages (e.g. KiCad parse errors) would make results differ per run
            res.detail = json.loads(json.dumps(res.detail, default=str).replace(td, "<tmp>"))
    except Exception as e:  # noqa: BLE001 - any error = reward 0
        res = VerifyResult(0.0, detail={"error": f"{type(e).__name__}: {e}"[:2000]})
    for g in GATES:
        res.gates.setdefault(g, False)
    for c in CHECKS:
        res.checks.setdefault(c, False)
    if "rules" not in res.checks and _has_rules(task_dir):
        res.checks["rules"] = False
    if not (all(res.gates.values()) and all(res.checks.values())):
        res.reward = 0.0
    res.detail["seconds"] = round(time.monotonic() - t0, 3)
    return res


def _has_rules(task_dir: str) -> bool:
    try:
        from pcbenv import taskio
        m = taskio.load_meta(task_dir)
        return bool(m.get("rules") or m.get("rules_power"))
    except Exception:  # noqa: BLE001
        return False


def verify_isolated(workdir: str, task_dir: str, timeout: float = 120.0) -> VerifyResult:
    """`verify` in a fresh `python3 -I` subprocess (own cwd, no env-controlled imports)."""
    t0 = time.monotonic()
    code = f"import sys; sys.path.insert(0, {ROOT!r}); from pcbenv.verify import main; sys.exit(main())"
    with tempfile.TemporaryDirectory(prefix="pcbverify_run_") as cwd:
        try:
            proc = subprocess.run([sys.executable, "-I", "-c", code, os.path.abspath(workdir),
                                   os.path.abspath(task_dir)], cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return VerifyResult(0.0, detail={"error": f"verify timed out after {timeout} s"})
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(_MARK):
            try:
                res = VerifyResult.from_dict(json.loads(line[len(_MARK):]))
            except Exception as e:  # noqa: BLE001
                break
            res.detail["wall_seconds"] = round(time.monotonic() - t0, 3)
            return res
    tail = (proc.stderr or proc.stdout)[-1500:]
    return VerifyResult(0.0, detail={"error": f"verify subprocess failed (exit {proc.returncode}): {tail}"})


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python3 -m pcbenv.verify WORKDIR TASKDIR", file=sys.stderr)
        res = VerifyResult(0.0, detail={"error": "bad arguments"})
    else:
        res = verify(args[0], args[1])
    sys.stdout.flush()
    print(_MARK + res.to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
