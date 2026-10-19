#!/bin/sh
# Grader container entrypoint: verify /submission (design.json + board.kicad_pcb) against /task
# (a full task dir incl. hidden/). Prints the VerifyResult JSON on stdout; exit 0 iff reward == 1.
# Run with --network none and both mounts read-only.
set -eu
PCBENV_ROOT="${PCBENV_ROOT:-/opt/pcbenv}"
SUB="${1:-/submission}"
TASK="${2:-/task}"
OUT="$(cd /tmp && python3 -I -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from pcbenv.verify import main; sys.exit(main())' "$PCBENV_ROOT" "$SUB" "$TASK")"
JSON="$(printf '%s\n' "$OUT" | sed -n 's/^PCBENV_VERIFY_JSON://p' | tail -n 1)"
printf '%s\n' "$JSON"
printf '%s' "$JSON" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin)["reward"] == 1.0 else 1)'
