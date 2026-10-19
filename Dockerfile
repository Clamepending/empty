# PCB-Repair images. Two targets from one file:
#
#   docker build --target agent  -t pcb-repair-agent  .   # what the agent runs in (NO hidden data)
#   docker build --target grader -t pcb-repair-grader .   # runs pcbenv.verify OUTSIDE the agent sandbox
#
# Security boundary (docs/SECURITY.md): the agent image contains only the code pcbtool needs
# (no family generators, fault injectors, tasks or tests) and gets a task's public/ files copied
# into /work. hidden/ is only ever mounted read-only into the grader container, which receives
# a copy of the two deliverables (design.json, board.kicad_pcb) after the episode ends.

# ---------------------------------------------------------------- base: KiCad 7 + ngspice
FROM ubuntu:24.04 AS base
ARG DEBIAN_FRONTEND=noninteractive
# kicad 7.0.11 ships in noble/universe; pcbnew's Python module is built for the distro python3 (3.12).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        kicad=7.0.11* kicad-footprints=7.0.11* \
        ngspice python3 python3-numpy python3-yaml ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -c "import pcbnew; assert pcbnew.Version().startswith('7.0'), pcbnew.Version()" \
 && ngspice --version | head -n 2
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 KICAD7_FOOTPRINT_DIR=/usr/share/kicad/footprints

# ---------------------------------------------------------------- agent: what the policy sees
FROM base AS agent
# Whitelist: only the modules pcbtool imports. Generators (families/, generate, faults*) are left
# out so an agent cannot regenerate goldens by brute-forcing seeds.
COPY pcbenv/__init__.py pcbenv/board.py pcbenv/boardnet.py pcbenv/checks.py pcbenv/design.py \
     pcbenv/drc.py pcbenv/erc.py pcbenv/golden.py pcbenv/layout.py pcbenv/parts.py \
     pcbenv/parts_lib.py pcbenv/router.py pcbenv/sim.py pcbenv/tool.py /opt/pcbenv/pcbenv/
COPY bin/pcbtool /opt/pcbenv/bin/pcbtool
COPY docker/agent-entrypoint.sh /usr/local/bin/agent-entrypoint
RUN chmod 0755 /opt/pcbenv/bin/pcbtool /usr/local/bin/agent-entrypoint \
 && ln -s /opt/pcbenv/bin/pcbtool /usr/local/bin/pcbtool \
 && chmod -R a-w /opt/pcbenv \
 && useradd --create-home --shell /bin/bash agent \
 && mkdir -p /work && chown agent:agent /work
USER agent
WORKDIR /work
ENTRYPOINT ["agent-entrypoint"]
CMD ["bash"]

# ---------------------------------------------------------------- grader: full package + tests
FROM base AS grader
RUN apt-get update && apt-get install -y --no-install-recommends python3-pytest \
 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md /opt/pcbenv/
COPY bin /opt/pcbenv/bin
COPY pcbenv /opt/pcbenv/pcbenv
COPY tests /opt/pcbenv/tests
COPY examples /opt/pcbenv/examples
COPY docker/grade.sh /usr/local/bin/pcb-grade
RUN chmod 0755 /usr/local/bin/pcb-grade /opt/pcbenv/bin/pcbtool \
 && ln -s /opt/pcbenv/bin/pcbtool /usr/local/bin/pcbtool \
 && useradd --create-home --shell /bin/bash grader
ENV PYTHONPATH=/opt/pcbenv
USER grader
WORKDIR /opt/pcbenv
# usage: docker run --rm --network none -v SUBMISSION:/submission:ro -v TASK:/task:ro pcb-repair-grader
ENTRYPOINT ["pcb-grade"]
