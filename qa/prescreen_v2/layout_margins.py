"""hard_layout train tasks: layout-rule metrics of golden vs faulted board, per layout-latent fault
type. Shows how far the injected fault goes past the limit (is it a real defect or a hair over?)."""
import json, sys
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, "/home/user/empty")
from pcbenv import qa
T = Path("/home/user/empty/tasks")
rows = [r for r in qa.load_train_rows(T / "manifest.jsonl", T) if qa.tier_of(r) == "hard_layout"]

def job(r):
    td = qa.task_dir_of(T, r)
    meta = json.loads((td / "hidden" / "meta.json").read_text())
    g = qa.layout_metrics(str(td / "hidden" / "golden_board.kicad_pcb"), meta)
    f = qa.layout_metrics(str(td / "public" / "board.kicad_pcb"), meta)
    lt = [x["type"] for x in meta["faults"] if x["type"] in qa.LAYOUT_LATENT]
    return r["id"], lt, g, f

def num(x):
    return x if isinstance(x, (int, float)) else None

if __name__ == "__main__":
    with Pool(4) as p:
        res = p.map(job, rows)
    KEYS = {"switching-loop": "loop area mm2 (limit 60)", "crystal copper path": "crystal path mm (limit 10)",
            "separation": "analog parallel mm within 1 mm (limit 3)", "decoupling copper path": "decap path mm (limit per task)",
            "decoupling straight": "decap straight mm (limit 5)"}
    gold = defaultdict(list); fault = defaultdict(list)
    TYPEKEY = {"switch_loop_spread": "switching-loop", "crystal_far": "crystal copper path",
               "analog_near_switch": "separation", "decap_long_path": "decoupling copper path"}
    for tid, lt, g, f in res:
        for k, (v, lim, unit, ok) in g.items():
            for pre in KEYS:
                if k.startswith(pre) and num(v) is not None:
                    gold[pre].append((v / lim if lim else v, v, lim))
        for t in lt:
            pre = TYPEKEY.get(t)
            if pre is None:
                continue
            # worst ratio among the faulted metrics with this prefix that changed vs golden
            best = None
            for k, (v, lim, unit, ok) in f.items():
                if k.startswith(pre) and num(v) is not None and not ok:
                    r_ = v / lim
                    if best is None or r_ > best[0]:
                        best = (r_, v, lim, k)
            fault[t].append(best)
    print("GOLDEN boards (train hard_layout): metric / limit")
    for pre, vals in gold.items():
        rs = sorted(x[0] for x in vals)
        print(f"  {KEYS[pre]:45s} n={len(rs):3d} min={rs[0]:.2f} median={rs[len(rs)//2]:.2f} max={rs[-1]:.2f}")
    print("FAULTED boards: violated metric / limit for the layout-latent fault")
    for t, vals in sorted(fault.items()):
        ok = [x for x in vals if x]
        rs = sorted(x[0] for x in ok)
        under = sum(1 for x in rs if x < 1.25)
        print(f"  {t:20s} n={len(vals):3d} measured={len(ok):3d} min={rs[0]:.2f} median={rs[len(rs)//2]:.2f} max={rs[-1]:.2f}  <1.25x limit: {under}")
        print("     lowest: " + "; ".join(f"{x[3]}={x[1]:.2f} (lim {x[2]:g})" for x in sorted(ok)[:3]))
    cx = [(tid, f) for tid, lt, g, f in res if "crystal_via" in lt]
    print("crystal_via faulted:", [(tid, {k: v[0] for k, v in f.items() if 'vias' in k}) for tid, f in cx[:3]])
