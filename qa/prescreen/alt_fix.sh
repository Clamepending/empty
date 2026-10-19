#!/bin/sh
# Try a repair on a TRAIN task and grade it with the real verifier.
# usage: qa/prescreen/alt_fix.sh TASK_ID golden|faulted "pcbtool args" ["pcbtool args" ...]
# Copies public/ into a fresh temp workdir; with `golden`, the deliverables are replaced by the
# hidden golden pair first (so only the alternative being tested differs from the reference fix).
set -e
R="$(cd "$(dirname "$0")/../.." && pwd)"; T="$R/tasks/train/$1"; base=$2; shift 2
case "$T" in *holdout*) echo "refusing holdout"; exit 2;; esac
W=$(mktemp -d "${TMPDIR:-/tmp}/qa_alt.XXXXXX")
cp -r "$T/public/." "$W/"
if [ "$base" = golden ]; then cp "$T/hidden/golden_design.json" "$W/design.json"; cp "$T/hidden/golden_board.kicad_pcb" "$W/board.kicad_pcb"; fi
cd "$W"
for c in "$@"; do echo "\$ pcbtool $c"; "$R/bin/pcbtool" $c 2>&1 | tail -3; done
cd "$R"
python3 -c "
import json; from pcbenv.verify import verify_isolated
r = verify_isolated('$W', '$T'); d = {k: v for k, v in r.detail.items() if k not in ('seconds', 'wall_seconds')}
print('VERIFY reward', r.reward, 'failing', [k for k, v in {**r.gates, **r.checks}.items() if not v], json.dumps(d)[:600])"
rm -rf "$W"
