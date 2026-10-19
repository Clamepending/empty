"""Spec-assertion engine: builds ngspice decks from a design and checks assertions (SPEC §5).

Conventions
- Assertions reference pins (`REF.PIN`), never net names.
- Ground reference: the net containing `assertion["ground_pin"]`; default = the `GND` pin of the
  first IC (ref starting with "U", sorted) if present, else `J1.2`. That node is SPICE node 0.
- Stimulus comes only from the assertion:
    supply:  {"pin": P, "volts": V, "r": 1e-3}            (or a list of these)
    source:  {"pin": P, "dc": V, "ac": A, "r": 1e-3}       DC / AC voltage source (or a list)
             {"pin": P, "kind": "step", "v0": 0, "v1": V, "r": R}   step at t0 (rise_time)
             {"pin": P, "kind": "release", "r_on": 10}     open-drain pin held low, released at t0
    loads:   [{"pin": P, "to": P2 (default ground), "r": R, "l": L, "c": C}]  series R-L-C branch
- `dc_voltage` may carry an optional `ref_pin`: the result is then V(net_pin) - V(ref_pin)
  (e.g. the supply voltage seen across an IC's VDD/GND pins).
- Every pin not on a net gets its own node; every node has a 1e12 Ω leak to ground.
- A design that fails to simulate yields failed results, never an exception.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pcbenv.parts import PARTS

NGSPICE_TIMEOUT_S = 20.0
LEAK_OHMS = 1e12
SWEEP_PTS_PER_DEC = 50
SPICE_TYPES = {"dc_voltage": "op", "dc_current": "op", "ac_gain": "ac", "cutoff": "ac", "rise_time": "tran"}


@dataclass
class AssertionResult:
    name: str
    passed: bool
    measured: float | None
    expected: str
    detail: str = ""


class SimError(RuntimeError):
    pass


def _san(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", s)


def assertion_name(a: dict) -> str:
    if a.get("name"):
        return str(a["name"])
    t = a.get("type", "?")
    key = a.get("net_pin") or a.get("element") or a.get("out_pin") or a.get("check") or ""
    return f"{t}:{key}"


def default_ground_pin(design: dict) -> str:
    for ref in sorted(design.get("components", {})):
        if ref.startswith("U"):
            part = PARTS.get(design["components"][ref].get("part"))
            if part and "GND" in part.pins:
                return f"{ref}.GND"
    return "J1.2"


def _as_list(x) -> list:
    if x is None:
        return []
    return list(x) if isinstance(x, list) else [x]


# --------------------------------------------------------------------------- netlist

class Netlist:
    """Pin -> SPICE node mapping for a design under a chosen ground pin."""

    def __init__(self, design: dict, ground_pin: str, sense_pins: list[str] = ()):
        self.design = design
        self.pin_node: dict[str, str] = {}   # pin -> node at the net side
        gnd_net = None
        for name, pins in design["nets"].items():
            if ground_pin in pins:
                gnd_net = name
        for i, (name, pins) in enumerate(sorted(design["nets"].items())):
            node = "0" if name == gnd_net else f"n{i}_{_san(name)[:24]}"
            for p in pins:
                self.pin_node[p] = node
        k = 0
        for ref, c in sorted(design["components"].items()):
            for pin in PARTS[c["part"]].pins:
                p = f"{ref}.{pin}"
                if p not in self.pin_node:
                    k += 1
                    self.pin_node[p] = "0" if p == ground_pin else f"u{k}_{_san(ref)}_{_san(pin)}"
        if ground_pin not in self.pin_node:
            raise SimError(f"ground pin {ground_pin} does not exist")
        # pin -> node as seen by the part (differs only for current-sensed pins)
        self.part_node = dict(self.pin_node)
        self.sense: dict[str, str] = {}  # pin -> V-source name
        for j, p in enumerate(sense_pins):
            if p in self.sense:
                continue
            if p not in self.pin_node:
                raise SimError(f"unknown pin {p}")
            self.part_node[p] = f"s{j}_{_san(p)}"
            self.sense[p] = f"vsense{j}"

    def node(self, pin: str) -> str:
        if pin not in self.pin_node:
            raise SimError(f"unknown pin {pin}")
        return self.pin_node[pin]

    def pnode(self, pin: str) -> str:
        """Node at the pin itself (after any current-sense source); stimulus attaches here."""
        if pin not in self.part_node:
            raise SimError(f"unknown pin {pin}")
        return self.part_node[pin]

    def lines(self) -> list[str]:
        out: list[str] = []
        models: dict[str, str] = {}
        for ref, c in sorted(self.design["components"].items()):
            part = PARTS[c["part"]]
            nodes = {pin: self.part_node[f"{ref}.{pin}"] for pin in part.pins}
            txt = part.spice(_san(ref), nodes, c.get("value", ""))
            if txt:
                out.append(txt)
            if part.models:
                models[part.name] = part.models
        for p, vname in self.sense.items():
            out.append(f"{vname} {self.pin_node[p]} {self.part_node[p]} DC 0")
        out.extend(models.values())
        nodes = sorted({n for n in list(self.pin_node.values()) + list(self.part_node.values()) if n != "0"})
        for i, n in enumerate(nodes):
            out.append(f"Rzleak{i} {n} 0 {LEAK_OHMS:g}")
        return out


def _stimulus_lines(nl: Netlist, a: dict, t0: float = 0.0, edge: float = 1e-9) -> list[str]:
    out = []
    for i, s in enumerate(_as_list(a.get("supply"))):
        node = nl.pnode(s["pin"])
        out.append(f"Vzsup{i} zsup{i} 0 DC {float(s['volts']):.9g}")
        out.append(f"Rzsup{i} zsup{i} {node} {float(s.get('r', 1e-3)):.6g}")
    for i, s in enumerate(_as_list(a.get("source"))):
        node = nl.pnode(s["pin"])
        kind = s.get("kind", "dc")
        if kind == "release":
            out.append(f"Vzctl{i} zctl{i} 0 PWL(0 1 {t0:.6g} 1 {t0 + edge:.6g} 0)")
            out.append(f"Szsw{i} {node} 0 zctl{i} 0 zswmod{i}")
            out.append(f".model zswmod{i} SW(VT=0.5 VH=0.1 RON={float(s.get('r_on', 10)):.6g} ROFF=1e13)")
        else:
            if kind == "step":
                v0, v1 = float(s.get("v0", 0.0)), float(s["v1"])
                spec = f"PWL(0 {v0:.9g} {t0:.6g} {v0:.9g} {t0 + edge:.6g} {v1:.9g})"
            else:
                spec = f"DC {float(s.get('dc', 0.0)):.9g} AC {float(s.get('ac', 0.0)):.9g}"
            out.append(f"Vzsrc{i} zsrc{i} 0 {spec}")
            out.append(f"Rzsrc{i} zsrc{i} {node} {float(s.get('r', 1e-3)):.6g}")
    for i, ld in enumerate(_as_list(a.get("loads"))):
        a_node = nl.pnode(ld["pin"])
        b_node = nl.pnode(ld["to"]) if ld.get("to") else "0"
        chain = [(k, float(ld[k])) for k in ("r", "l", "c") if ld.get(k) is not None]
        if not chain:
            continue
        cur = a_node
        for j, (k, val) in enumerate(chain):
            nxt = b_node if j == len(chain) - 1 else f"zld{i}_{j}"
            out.append(f"{k.upper()}zld{i}_{j} {cur} {nxt} {val:.6g}")
            cur = nxt
    return out


# --------------------------------------------------------------------------- ngspice

class NonConvergence(SimError):
    """The DC operating point could not be found reliably (never replaced by a guess)."""


NOT_CONVERGED = "simulation did not converge"
# Process-local counters (diagnostics/tests): how often the plain solve was rejected and the
# robust re-derivation was needed / failed.
STATS = {"rescued": 0, "not_converged": 0}
# ngspice prints these when Newton, gmin stepping and source stepping all failed and it falls back
# to a pseudo-transient "transient op". That point is not a DC solution (seen: LDO output 36 V
# from a 12 V input), so it is never accepted.
_FALLBACK_MARKERS = ("Transient op started", "transient op started")
_BASE_OPTIONS = ".options itl1=500 itl2=200 itl4=50 gmin=1e-13"
_RETRY_OPTIONS = ".options itl1=2000 itl2=500 itl4=100 gmin=1e-13 gminsteps=200 srcsteps=200"
_SANITY_REL, _SANITY_ABS = 0.02, 0.05
# Every 2-terminal stimulus-free node voltage of a DC solution lies within the span of the
# stimulus voltages (and 0 V): the parts are passive or rail-limited (op-amp output within its
# supply pins, LDO output within VIN). A point outside that span is a numerical artefact.


def _deck_nodes(body: list[str]) -> list[str]:
    """Top-level circuit nodes (every Netlist node has exactly one `Rzleak` line)."""
    out = []
    for line in body:
        if line.startswith("Rzleak"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] != "0":
                out.append(parts[1])
    return out


_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _stimulus_span(body: list[str]) -> tuple[float, float]:
    """(lowest, highest) voltage any stimulus source can apply (always includes 0 V)."""
    lo = hi = 0.0
    for line in body:
        if not line.startswith(("Vzsup", "Vzsrc")):
            continue
        rest = line.split(None, 3)[3] if len(line.split(None, 3)) > 3 else ""
        rest = re.sub(r"\bAC\s+\S+", "", rest)  # AC magnitude is small-signal, not a DC level
        for tok in _NUM_RE.findall(rest):
            v = float(tok)
            lo, hi = min(lo, v), max(hi, v)
    return lo, hi


def _sane(values: list[float], span: tuple[float, float]) -> bool:
    lo, hi = span
    m = _SANITY_REL * (hi - lo) + _SANITY_ABS
    return all(math.isfinite(v) and lo - m <= v <= hi + m for v in values)


def _exec(deck: list[str], outfiles: list[str]) -> tuple[dict[str, str], str]:
    """Run one deck; returns ({outfile: text} for the files that were written, log)."""
    with tempfile.TemporaryDirectory(prefix="pcbsim_") as td:
        Path(td, "deck.cir").write_text("\n".join(deck))
        try:
            proc = subprocess.run(["ngspice", "-b", "deck.cir"], cwd=td, capture_output=True,
                                  text=True, timeout=NGSPICE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            raise SimError("ngspice timeout") from None
        log = proc.stdout + proc.stderr
        data = {f: Path(td, f).read_text() for f in outfiles if Path(td, f).exists()}
    return data, log


def _rows(text: str | None) -> list[list[float]] | None:
    """Numeric rows of a `wrdata` file (non-numeric lines skipped); None if the file is missing."""
    if text is None:
        return None
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            rows.append([float(x) for x in parts])
        except ValueError:
            continue
    return rows


def _raw_voltages(text: str | None) -> dict[str, float] | None:
    """All node voltages (top-level and subcircuit-internal) at the last point of an ASCII rawfile."""
    if not text or "Values:" not in text:
        return None
    head, values = text.split("Values:", 1)
    names: list[tuple[str, str]] = []
    in_vars = False
    for line in head.splitlines():
        if line.startswith("Variables:"):
            in_vars = True
            continue
        if in_vars:
            parts = line.split()
            if len(parts) >= 3:
                names.append((parts[1], parts[2]))
    toks = values.split()
    n = len(names)
    if n == 0 or len(toks) < n + 1:
        return None
    last = toks[-(n + 1):]
    try:
        vals = [float(x.split(",")[0]) for x in last[1:]]
    except ValueError:
        return None
    out = {}
    for (name, kind), v in zip(names, vals):
        if kind != "voltage" or not math.isfinite(v):
            continue
        name = name[2:-1] if name.lower().startswith("v(") and name.endswith(")") else name
        out[name.lower()] = v
    return out


def _deck(body: list[str], control: list[str], options: str = _BASE_OPTIONS,
          nodeset: dict[str, float] | None = None) -> list[str]:
    ns = []
    if nodeset:
        ns = [".nodeset " + " ".join(f"v({n})={v:.9g}" for n, v in sorted(nodeset.items()))]
    return ["* pcbenv deck", options, *body, *ns,
            ".control", "set wr_singlescale", "set filetype=ascii", "option numdgt=10", *control, "quit", ".endc",
            ".end", ""]


def _fell_back(log: str) -> bool:
    return any(m in log for m in _FALLBACK_MARKERS)


def _op_all(body: list[str], nodes: list[str], span, options: str,
            nodeset: dict[str, float] | None = None) -> dict[str, float] | None:
    """Every node voltage of a trustworthy DC solution (converged Newton, no transient-op fallback,
    top-level nodes within the stimulus span), or None."""
    data, log = _exec(_deck(body, ["op", "write op.raw"], options, nodeset), ["op.raw"])
    if _fell_back(log):
        return None
    allv = _raw_voltages(data.get("op.raw"))
    if allv is None or any(n.lower() not in allv for n in nodes):
        return None
    if not _sane([allv[n.lower()] for n in nodes], span):
        return None
    return allv


def _ramp_estimate(body: list[str]) -> dict[str, float] | None:
    """All node voltages after a pseudo-transient power-up from 0 V (uic), used only as a
    `.nodeset` starting point for a fresh Newton solve, never as a result."""
    data, _ = _exec(_deck(body, ["tran 10u 50m 0 100u uic", "write ramp.raw"], _RETRY_OPTIONS), ["ramp.raw"])
    return _raw_voltages(data.get("ramp.raw"))


Solution = tuple[str, dict[str, float]]   # (options line, full nodeset) that reproduces a verified op


def robust_nodeset(body: list[str]) -> Solution:
    """A verified DC operating point, found by escalating strategies: (1) Newton with gmin/source
    stepping, (2) the same with more steps, (3) a pseudo-transient power-up whose end state (all
    nodes, subcircuit-internal ones included) seeds a `.nodeset` for a fresh Newton solve, (4) a
    high-gmin solve used the same way. A candidate counts only if ngspice converged without its
    transient-op fallback and every top-level node lies within the stimulus span. Returns the
    options and the full node-voltage set, so the caller's analysis can be re-run from exactly
    that point. Raises NonConvergence otherwise."""
    nodes = _deck_nodes(body)
    span = _stimulus_span(body)
    for opts in (_BASE_OPTIONS, _RETRY_OPTIONS):
        sol = _op_all(body, nodes, span, opts)
        if sol is not None:
            return opts, sol
    seeds = []
    ramp = _ramp_estimate(body)
    if ramp is not None:
        seeds.append(ramp)
    loose = _op_all(body, [], (-math.inf, math.inf), _RETRY_OPTIONS.replace("gmin=1e-13", "gmin=1e-6"))
    if loose is not None:
        seeds.append(loose)
    top = {n.lower() for n in nodes}
    for seed in seeds:
        ns = {n: (min(max(v, span[0]), span[1]) if n in top else v) for n, v in seed.items()}
        sol = _op_all(body, nodes, span, _RETRY_OPTIONS, ns)
        if sol is not None:
            return _RETRY_OPTIONS, sol
    raise NonConvergence(NOT_CONVERGED)


def _run_deck(body: list[str], control: list[str], outfile: str) -> list[list[float]]:
    """Run an analysis and return the rows of `outfile` (first column = scale).

    The DC operating point (the `op` analysis itself, or the bias point of `ac` / `tran`) must be
    a converged Newton solution: if ngspice falls back to its transient-op guess, or an `op`
    result has a node voltage outside the stimulus span, the operating point is re-derived with
    `robust_nodeset` and the analysis re-run from it; if that fails too, NonConvergence
    ("simulation did not converge") is raised -- never a fabricated measurement."""
    is_op = bool(control) and control[0].split()[0] == "op"
    nodes = _deck_nodes(body)
    span = _stimulus_span(body)
    check = [f"wrdata zsanity.txt {' '.join(f'v({n})' for n in nodes)}"] if is_op and nodes else []
    ctl = [control[0], *check, *control[1:]]

    def attempt(options: str, nodeset: dict[str, float] | None) -> tuple[list[list[float]] | None, str, bool]:
        data, log = _exec(_deck(body, ctl, options, nodeset), [outfile, "zsanity.txt"])
        rows = _rows(data.get(outfile))
        ok = rows is not None and not _fell_back(log)
        if ok and check:
            srows = _rows(data.get("zsanity.txt"))
            ok = bool(srows) and _sane(srows[0][1:], span)
        return rows, log, ok

    rows, log, ok = attempt(_BASE_OPTIONS, None)
    uses_uic = any(" uic" in c for c in control)
    if not ok and not uses_uic:
        try:
            opts, ns = robust_nodeset(body)
            rows, log, ok = attempt(opts, ns)
        except NonConvergence:
            ok = False
        if not ok:
            STATS["not_converged"] += 1
            raise NonConvergence(NOT_CONVERGED)
        STATS["rescued"] += 1
    if rows is None:
        tail = log.strip().splitlines()[-6:]
        raise SimError("simulation failed: " + " | ".join(tail))
    if not rows:
        raise SimError("no simulation data")
    for r in rows:
        if any(math.isnan(x) or math.isinf(x) for x in r):
            raise SimError("simulation produced NaN/inf")
    return rows


def _vec(node: str) -> str | None:
    return None if node == "0" else f"v({node})"


def _collect(rows: list[list[float]], exprs: list[str | None], complex_: bool) -> list[list]:
    """Per-expression column data from wrdata rows (first column = scale)."""
    real_exprs = [e for e in exprs if e is not None]
    width = 1 + len(real_exprs) * (2 if complex_ else 1)
    if any(len(r) != width for r in rows):
        raise SimError("unexpected simulation output shape")
    cols, k = [], 0
    for e in exprs:
        if e is None:
            cols.append([0.0] * len(rows))
            continue
        if complex_:
            cols.append([complex(r[1 + 2 * k], r[2 + 2 * k]) for r in rows])
        else:
            cols.append([r[1 + k] for r in rows])
        k += 1
    return cols


# --------------------------------------------------------------------------- analyses

def _ok(a: dict, x: float) -> bool:
    lo = a.get("min", -math.inf)
    hi = a.get("max", math.inf)
    return lo <= x <= hi


def _expected(a: dict) -> str:
    return f"[{a.get('min', '-inf')}, {a.get('max', 'inf')}]"


def _result(a: dict, measured: float | None, detail: str = "") -> AssertionResult:
    passed = measured is not None and _ok(a, measured)
    return AssertionResult(assertion_name(a), passed, measured, _expected(a), detail)


def _element_sense_pin(design: dict, element: str) -> str:
    if "." in element:
        return element
    c = design["components"].get(element)
    if c is None:
        raise SimError(f"unknown element {element}")
    pins = list(PARTS[c["part"]].pins)
    return f"{element}.{pins[0]}"


def _run_op(design: dict, ground: str, group: list[dict]) -> list[AssertionResult]:
    sense = [_element_sense_pin(design, a["element"]) for a in group if a["type"] == "dc_current"]
    nl = Netlist(design, ground, sense)
    exprs: list[str | None] = []
    slots: list[tuple[int, int | None]] = []
    for a in group:
        if a["type"] == "dc_voltage":
            exprs.append(_vec(nl.node(a["net_pin"])))
            ref = None
            if a.get("ref_pin"):
                exprs.append(_vec(nl.node(a["ref_pin"])))
                ref = len(exprs) - 1
            slots.append((len(exprs) - 1 - (ref is not None), ref))
        else:
            exprs.append(f"i({nl.sense[_element_sense_pin(design, a['element'])]})")
            slots.append((len(exprs) - 1, None))
    real = [e for e in exprs if e]
    if real:
        rows = _run_deck(nl.lines() + _stimulus_lines(nl, group[0]),
                         ["op", f"wrdata out.txt {' '.join(real)}"], "out.txt")
        vals = [c[0] for c in _collect(rows[:1], exprs, False)]
    else:
        vals = [0.0] * len(exprs)
    res = []
    for a, (i, j) in zip(group, slots):
        v = vals[i] - (vals[j] if j is not None else 0.0)
        res.append(_result(a, abs(v) if a["type"] == "dc_current" else v))
    return res


def _cutoff(freqs: list[float], mags: list[float], edge: str) -> float | None:
    peak_i = max(range(len(mags)), key=lambda i: mags[i])
    ref = mags[peak_i]
    if ref <= 0:
        return None
    thr = ref / math.sqrt(2)
    rng = range(peak_i, len(mags) - 1) if edge == "high" else range(peak_i, 0, -1)
    step = 1 if edge == "high" else -1
    for i in rng:
        j = i + step
        if mags[j] < thr <= mags[i]:
            # interpolate in log f vs dB
            d1, d2, dt = (20 * math.log10(max(m, 1e-300)) for m in (mags[i], mags[j], thr))
            lf1, lf2 = math.log10(freqs[i]), math.log10(freqs[j])
            t = (dt - d1) / (d2 - d1) if d2 != d1 else 0.0
            return 10 ** (lf1 + t * (lf2 - lf1))
    return None


def _run_ac(design: dict, ground: str, group: list[dict]) -> list[AssertionResult]:
    nl = Netlist(design, ground)
    body = nl.lines() + _stimulus_lines(nl, group[0])
    res: list[AssertionResult] = []
    for a in group:
        try:
            vin, vout = _vec(nl.node(a["in_pin"])), _vec(nl.node(a["out_pin"]))
            if vin is None:
                raise SimError("input pin is on the ground net")
            exprs = [vin, vout]
            if a["type"] == "ac_gain":
                f = float(a["freq"])
                ctl = [f"ac lin 1 {f:.9g} {f:.9g}"]
            else:
                f1, f2 = float(a.get("fstart", 0.1)), float(a.get("fstop", 1e8))
                ctl = [f"ac dec {SWEEP_PTS_PER_DEC} {f1:.9g} {f2:.9g}"]
            ctl.append(f"wrdata out.txt {' '.join(e for e in exprs if e)}")
            rows = _run_deck(body, ctl, "out.txt")
            ci, co = _collect(rows, exprs, True)
            gains = [abs(o / i) if abs(i) > 1e-30 else 0.0 for i, o in zip(ci, co)]
            if a["type"] == "ac_gain":
                res.append(_result(a, gains[0]))
            else:
                fc = _cutoff([r[0] for r in rows], gains, a.get("edge", "high"))
                res.append(_result(a, fc, "" if fc is not None else "no -3 dB crossing in sweep"))
        except NonConvergence:
            res.append(AssertionResult(assertion_name(a), False, None, _expected(a), NOT_CONVERGED))
        except SimError as e:
            res.append(AssertionResult(assertion_name(a), False, None, _expected(a), str(e)))
    return res


def _transition_time(ts: list[float], vs: list[float], t0: float,
                     levels: tuple[float, float] = (0.1, 0.9)) -> float | None:
    i0 = max(i for i, t in enumerate(ts) if t <= t0) if ts[0] <= t0 else 0
    v0, v1 = vs[i0], vs[-1]
    if abs(v1 - v0) < 1e-3:
        return None
    sgn = 1 if v1 > v0 else -1

    def cross(level: float, start: int) -> tuple[float, int] | None:
        for i in range(start, len(ts) - 1):
            a, b = sgn * (vs[i] - level), sgn * (vs[i + 1] - level)
            if a < 0 <= b:
                t = ts[i] + (ts[i + 1] - ts[i]) * (-a / (b - a) if b != a else 0.0)
                return t, i
        return None

    lo, hi = levels
    c10 = cross(v0 + lo * (v1 - v0), i0)
    if c10 is None:
        return None
    c90 = cross(v0 + hi * (v1 - v0), c10[1])
    if c90 is None:
        return None
    return c90[0] - c10[0]


def _run_tran(design: dict, ground: str, group: list[dict]) -> list[AssertionResult]:
    tstop = max(float(a.get("tstop", 10 * float(a.get("max", 1e-3)))) for a in group)
    t0 = tstop * 0.02
    nl = Netlist(design, ground)
    body = nl.lines() + _stimulus_lines(nl, group[0], t0=t0, edge=tstop * 1e-5)
    exprs = [_vec(nl.node(a["net_pin"])) for a in group]
    real = [e for e in exprs if e]
    if not real:
        return [_result(a, None, "probe is on ground") for a in group]
    step = tstop / 4000
    ctl = [f"tran {step:.6g} {tstop:.6g} 0 {step:.6g}", f"wrdata out.txt {' '.join(real)}"]
    rows = _run_deck(body, ctl, "out.txt")
    ts = [r[0] for r in rows]
    cols = _collect(rows, exprs, False)
    return [_result(a, _transition_time(ts, col, t0, _levels(a))) for a, col in zip(group, cols)]


def _levels(a: dict) -> tuple[float, float]:
    """Transition-time thresholds as fractions of the swing: `levels: [lo, hi]` (default 10-90 %;
    I2C rise time per UM10204 uses [0.3, 0.7])."""
    lv = a.get("levels") or (0.1, 0.9)
    lo, hi = float(lv[0]), float(lv[1])
    if not 0.0 <= lo < hi <= 1.0:
        raise SimError(f"bad levels {lv!r}")
    return lo, hi


_RUNNERS = {"op": _run_op, "ac": _run_ac, "tran": _run_tran}


# --------------------------------------------------------------------------- entry point

def run_assertions(design: dict, assertions: list[dict]) -> list[AssertionResult]:
    """Evaluate every assertion; results are returned in input order. Never raises."""
    from pcbenv import checks

    results: list[AssertionResult | None] = [None] * len(assertions)
    groups: dict[str, list[int]] = {}
    for i, a in enumerate(assertions):
        try:
            t = a.get("type")
            if t == "analytic":
                results[i] = checks.run_check(design, a)
                continue
            if t not in SPICE_TYPES:
                raise SimError(f"unknown assertion type {t!r}")
            ground = a.get("ground_pin") or default_ground_pin(design)
            key = json.dumps([SPICE_TYPES[t], ground, a.get("supply"), a.get("source"), a.get("loads")],
                             sort_keys=True)
            groups.setdefault(key, []).append(i)
        except Exception as e:  # noqa: BLE001 - assertions must never raise
            results[i] = AssertionResult(assertion_name(a), False, None, _expected(a), f"error: {e}")
    for key, idx in groups.items():
        analysis, ground = json.loads(key)[:2]
        group = [assertions[i] for i in idx]
        try:
            res = _RUNNERS[analysis](design, ground, group)
        except NonConvergence:
            res = [AssertionResult(assertion_name(a), False, None, _expected(a), NOT_CONVERGED) for a in group]
        except Exception as e:  # noqa: BLE001
            res = [AssertionResult(assertion_name(a), False, None, _expected(a), f"sim error: {e}") for a in group]
        for i, r in zip(idx, res):
            results[i] = r
    return [r for r in results if r is not None]


def all_pass(design: dict, assertions: list[dict]) -> bool:
    return all(r.passed for r in run_assertions(design, assertions))
