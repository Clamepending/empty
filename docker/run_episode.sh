#!/bin/sh
# Host-side reference for the sandbox boundary: run one episode with the agent in the agent image
# and grading in the grader image. Usage: docker/run_episode.sh TASK_DIR [AGENT_COMMAND...]
# The default agent command just runs `pcbtool check` (a no-op policy).
set -eu
TASK="$(cd "$1" && pwd)"; shift
[ "$#" -gt 0 ] || set -- pcbtool check
WORK="$(mktemp -d)"; SUB="$(mktemp -d)"
trap 'rm -rf "$WORK" "$SUB"' EXIT
cp -R "$TASK/public/." "$WORK/"
chmod -R a+rwX "$WORK"
# 1. agent: public files only, no network, unprivileged, resource-limited
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
    --pids-limit 256 --memory 4g --cpus 2 \
    -v "$WORK:/work" pcb-repair-agent "$@" || true
# 2. copy ONLY the two deliverables out (regular files; the verifier re-checks)
for f in design.json board.kicad_pcb; do
    if [ -f "$WORK/$f" ] && [ ! -L "$WORK/$f" ]; then cp "$WORK/$f" "$SUB/$f"; fi
done
chmod -R a+rX "$SUB"
# 3. grader: hidden data + submission, both read-only, no network
docker run --rm --network none -v "$SUB:/submission:ro" -v "$TASK:/task:ro" pcb-repair-grader
