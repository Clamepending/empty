#!/bin/sh
# Agent container entrypoint. /work holds the task's PUBLIC files only (TASK.md, design.json,
# board.kicad_pcb, spec.json, parts/). If they were mounted read-only at /task_public, copy them
# into the writable /work first. Never mount a task's hidden/ dir into this container.
set -eu
WORK="${WORK_DIR:-/work}"
PUB="${TASK_PUBLIC:-/task_public}"
if [ -e "$WORK/hidden" ] || [ -e "$PUB/hidden" ]; then
    echo "refusing to start: a hidden/ directory is visible inside the agent container" >&2
    exit 3
fi
if [ -d "$PUB" ] && [ ! -e "$WORK/design.json" ]; then
    cp -R "$PUB/." "$WORK/"
fi
cd "$WORK"
exec "$@"
