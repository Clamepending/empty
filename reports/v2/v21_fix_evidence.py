"""Evidence for the v2.1 verifier / generator fixes (QA pre-screen F1-F5, qa/self_review_v2.md).

    python3 reports/v2/v21_fix_evidence.py tasks/v2.0_archive > reports/v2/v21_fix_evidence_v2.0.txt
    python3 reports/v2/v21_fix_evidence.py tasks              > reports/v2/v21_fix_evidence_v2.1.txt

ROOT is a tasks root holding v2/<split> (or <split> directly for the archive). Graded with the CURRENT
code. Sections:
  F1  Kelvin: golden, golden with every shunt-net track end inside the shunt pad moved to the pad centre
      (QA's kelvin_centre.py counterexample), and every kelvin_sense_tap faulted board.
  F3  separation metric on goldens and analog_near_switch faulted boards: v2.0 (same layer) vs v2.1.
  F4  latent evidence gate (requirement sentences) over every latent fault.
  F5  flyback rule with the load connector's pins swapped on the golden.
"""
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pcbnew  # noqa: E402

from pcbenv import layout_rules as LR  # noqa: E402
from pcbenv import rules  # noqa: E402
from pcbenv.faults.common import swap_pins  # noqa: E402
from pcbenv.faults.latent import match_evidence  # noqa: E402


def split_dirs(root: Path, sp: str) -> list[Path]:
    for base in (root / "v2" / sp, root / sp):
        if base.is_dir():
            return sorted(base.glob("pcbr2-*"))
    return []


def f1(root: Path) -> None:
    print("## F1 Kelvin rule (golden / golden with track ends at the shunt-pad centre / kelvin-faulted board)")
    n = Counter()
    for td in split_dirs(root, "hard_layout") + split_dirs(root, "hard_layout_holdout"):
        meta = json.loads((td / "hidden" / "meta.json").read_text())
        k = (meta.get("layout_rules") or {}).get("kelvin")
        if not k:
            continue
        k, rp = k[0], meta["ref_parts"]
        gb = str(td / "hidden" / "golden_board.kicad_pcb")
        n["golden"] += 1
        n["golden_pass"] += LR.kelvin_ok(gb, k, rp)[0]
        b = pcbnew.LoadBoard(gb)
        sh = LR._pad(b, k["shunt_pin"], rp)
        c = sh.GetPosition()
        for t in b.GetTracks():
            if t.GetNetCode() != sh.GetNetCode() or t.GetClass() == "PCB_VIA":
                continue
            for get, set_ in ((t.GetStart, t.SetStart), (t.GetEnd, t.SetEnd)):
                p = get()
                if sh.HitTest(p) and p != c:
                    set_(pcbnew.VECTOR2I(c.x, c.y))
        with tempfile.TemporaryDirectory() as tmp:
            bp = str(Path(tmp) / "b.kicad_pcb")
            b.Save(bp)
            ok, why = LR.kelvin_ok(bp, k, rp)
        n["centre_pass"] += ok
        if td.name in ("pcbr2-hard_layout-5dd2d0dd", "pcbr2-hard_layout-f7d8d9c0") or not ok:
            print(f"  centre variant {td.name}: kelvin_ok={ok} {why}")
        if any(f["type"] == "kelvin_sense_tap" for f in meta["faults"]):
            ok, why = LR.kelvin_ok(str(td / "public" / "board.kicad_pcb"), k, rp)
            n["fault"] += 1
            n["fault_still_failing"] += not ok
            if ok:
                print(f"  kelvin fault NOT failing under the v2.1 rule: {td.name}")
    print(f"  goldens passing {n['golden_pass']}/{n['golden']}; centre variants passing {n['centre_pass']}/{n['golden']} "
          f"(a failing centre variant = moving the ends made the two tracks merge before the pad edge); "
          f"kelvin-faulted boards still failing {n['fault_still_failing']}/{n['fault']}")


def f3(root: Path) -> None:
    print("## F3 separation: parallel length within 1 mm (v2.0 same-layer / v2.1 both layers), limit 3 mm")
    g = []
    for td in split_dirs(root, "hard_layout") + split_dirs(root, "hard_layout_holdout"):
        meta = json.loads((td / "hidden" / "meta.json").read_text())
        r = (meta.get("layout_rules") or {}).get("separation")
        if not r:
            continue
        r, rp = r[0], meta["ref_parts"]
        gb = str(td / "hidden" / "golden_board.kicad_pcb")
        g.append((LR.separation_length(gb, r, rp, True), LR.separation_length(gb, r, rp)))
        if any(f["type"] == "analog_near_switch" for f in meta["faults"]):
            pb = str(td / "public" / "board.kicad_pcb")
            print(f"  fault {td.name}: v2.0 {LR.separation_length(pb, r, rp, True):.2f} mm, "
                  f"v2.1 {LR.separation_length(pb, r, rp):.2f} mm")
    print(f"  goldens: {len(g)}; max v2.0 {max(a for a, _ in g):.2f} mm, max v2.1 {max(b for _, b in g):.2f} mm; "
          f"goldens over the 0.8x golden target (2.4 mm) under v2.1: {sum(b > 2.4 for _, b in g)}")


def f4(root: Path) -> None:
    print("## F4 latent evidence gate (requirement sentences only)")
    n, bad = Counter(), Counter()
    for sp in ("hard", "hard_holdout", "hard_layout", "hard_layout_holdout"):
        for td in split_dirs(root, sp):
            pub = td / "public"
            srcs = [("TASK.md", (pub / "TASK.md").read_text()), ("spec.json", (pub / "spec.json").read_text())]
            srcs += [(f"parts/{f.name}", f.read_text()) for f in sorted((pub / "parts").glob("*.md"))]
            meta = json.loads((td / "hidden" / "meta.json").read_text())
            for f in meta["faults"]:
                if f.get("category") != "latent":
                    continue
                n[f["type"]] += 1
                if not all(m["found"] for m in match_evidence(f, srcs)):
                    bad[f["type"]] += 1
                    print(f"  missing evidence: {td.name} {f['type']}")
    for t in sorted(n):
        print(f"  {t:22s} {n[t]:4d} latent faults, evidence missing {bad[t]}")


def f5(root: Path) -> None:
    print("## F5 flyback rule on goldens with the 2-pin load connector's pins swapped")
    n = Counter()
    for sp in ("hard", "hard_holdout", "hard_layout", "hard_layout_holdout"):
        for td in split_dirs(root, sp):
            meta = json.loads((td / "hidden" / "meta.json").read_text())
            ctx = meta.get("rules") or {}
            if not ctx.get("inductive_loads"):
                continue
            g = json.loads((td / "hidden" / "golden_design.json").read_text())
            for ld in ctx["inductive_loads"]:
                d = json.loads(json.dumps(g))
                swap_pins(d, ld["supply_pin"], ld["switched_pin"])
                n["swapped"] += 1
                n["flyback_violation"] += any(v.code == "flyback" for v in rules.run_rules(d, ctx))
            n["swap_faults"] += sum(f["type"] == "connector_pin_swap" and sorted(f["data"]["pins"]) ==
                                    sorted([ld["supply_pin"], ld["switched_pin"]]) for f in meta["faults"])
    print(f"  goldens with an inductive load: {n['swapped']}; flyback violation reported after swapping its connector "
          f"pins: {n['flyback_violation']}; shipped connector_pin_swap faults on that load connector: {n['swap_faults']}")


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for fn in (f1, f3, f4, f5):
        fn(root)
        print()
