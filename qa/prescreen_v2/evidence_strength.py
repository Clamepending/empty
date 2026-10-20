"""Population check (train splits only): is each latent fault's evidence-gate match a real
statement of the requirement, or only an incidental mention (spec assertion lines, spec.json)?"""
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, "/home/user/empty")
from pcbenv import qa
from pcbenv.faults.latent import evidence_groups
ROOT = Path("/home/user/empty"); T = ROOT / "tasks"
rows = qa.load_train_rows(T / "manifest.jsonl", T)
ASSERT = re.compile(r"^- `[^`]+`: ")          # spec assertion bullet lines in TASK.md
stats = defaultdict(Counter); examples = defaultdict(list)
for r in rows:
    td = qa.task_dir_of(T, r)
    meta = json.loads((td / "hidden" / "meta.json").read_text())
    srcs = qa.public_sources(td)
    for f in meta["faults"]:
        if f.get("category") != "latent":
            continue
        weak_groups = 0
        for g in evidence_groups(f):
            strong = False
            for alt in g:
                for fname, text in srcs:
                    if fname == "spec.json":
                        continue
                    for ln in text.splitlines():
                        if ASSERT.match(ln):
                            continue
                        if alt.startswith("line:"):
                            a, b = alt[5:].split("&", 1)
                            if re.search(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", ln) and b in ln:
                                strong = True
                        elif alt in ln:
                            strong = True
            weak_groups += not strong
        t = f["type"]
        stats[t]["faults"] += 1
        stats[t]["only_incidental_evidence"] += bool(weak_groups)
        if weak_groups and len(examples[t]) < 4:
            examples[t].append(f"{r['id']} ({r.get('intent')}): {f['detail']}")
print("latent type | faults (train) | evidence found only in spec assertion lines / spec.json")
for t in sorted(stats):
    print(f"{t:22s} {stats[t]['faults']:4d} {stats[t]['only_incidental_evidence']:4d}")
for t, ex in sorted(examples.items()):
    print("\n" + t); print("\n".join("  " + e for e in ex))
