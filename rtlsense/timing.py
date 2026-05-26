"""OpenSTA wrapper and timing report parser."""

import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config

logger = logging.getLogger(__name__)


@dataclass
class TimingCell:
    name: str
    cell_type: str
    delay: float
    arrival: float


@dataclass
class TimingPath:
    startpoint: str
    endpoint: str
    path_delay: float          # gate-only delay from OpenSTA
    adjusted_delay: float      # path_delay * wire_delay_factor
    required_time: float
    slack: float               # adjusted slack (negative = violation)
    raw_slack: float           # slack before wire factor
    logic_depth: int
    cells: list[TimingCell] = field(default_factory=list)

    @property
    def is_violation(self) -> bool:
        return self.slack < 0

    @property
    def is_warning(self, threshold: float = 0.0) -> bool:
        return self.slack >= 0 and self.slack < threshold


@dataclass
class TimingReport:
    success: bool
    module_name: str
    clock_period_ns: float
    wns: float = 0.0           # worst negative slack (adjusted)
    tns: float = 0.0           # total negative slack (adjusted)
    paths: list[TimingPath] = field(default_factory=list)
    error_message: str = ""
    raw_output: str = ""

    @property
    def violations(self) -> list[TimingPath]:
        return [p for p in self.paths if p.is_violation]

    @property
    def met_count(self) -> int:
        return sum(1 for p in self.paths if not p.is_violation)


def _build_sta_script(
    liberty_path: str,
    netlist_path: str,
    module_name: str,
    clock_period_ns: float,
    input_delay_ns: float,
    output_delay_ns: float,
) -> str:
    return f"""
read_liberty {liberty_path}
read_verilog {netlist_path}
link_design {module_name}
create_clock -period {clock_period_ns:.4f} [get_ports {{clk}}]
set_input_delay {input_delay_ns:.4f} -clock clk [all_inputs]
set_output_delay {output_delay_ns:.4f} -clock clk [all_outputs]
set_false_path -from [get_ports {{rst_n rst reset RST RST_N}}]
report_checks -path_delay max -format full_clock_expanded \
    -fields {{capacitance slew input_pins nets fanout}} -digits 4
report_checks -path_delay max -endpoint_count 20
report_tns
report_wns
exit
"""


def _parse_path_block(block: str) -> Optional[TimingPath]:
    """
    Parse a single path block from OpenSTA's report_checks output.

    OpenSTA format puts the numeric value BEFORE the label, e.g.:
        1.8283   data required time
        0.4000   data arrival time
        1.4283   slack (MET)
    """
    m = re.search(r"Startpoint:\s+(\S+)", block)
    if not m:
        return None
    startpoint = m.group(1)

    m = re.search(r"Endpoint:\s+(\S+)", block)
    if not m:
        return None
    endpoint = m.group(1)

    # Values come BEFORE their label
    m = re.search(r"(-?[0-9.]+)\s+data arrival time", block)
    path_delay = float(m.group(1)) if m else 0.0

    m = re.search(r"(-?[0-9.]+)\s+data required time", block)
    required_time = float(m.group(1)) if m else 0.0

    m = re.search(r"(-?[0-9.]+)\s+slack \((?:MET|VIOLATED)\)", block)
    slack = float(m.group(1)) if m else (required_time - path_delay)

    # Cell lines: [fanout] [cap] [slew] [delay] [time] [^v] cell (type)
    # The full_clock_expanded format has 5 numeric columns before the direction marker
    cell_pattern = re.compile(
        r"^\s+(?:\d+\s+)?(?:[0-9.]+\s+){2,4}([0-9.]+)\s+([0-9.]+)\s+[v^]\s+(\S+)\s+\((\S+)\)",
        re.MULTILINE,
    )
    cells: list[TimingCell] = []
    for cm in cell_pattern.finditer(block):
        cells.append(TimingCell(
            name=cm.group(3),
            cell_type=cm.group(4),
            delay=float(cm.group(1)),
            arrival=float(cm.group(2)),
        ))

    # Logic depth = non-buffer cells in path
    logic_depth = len([
        c for c in cells
        if not any(c.cell_type.startswith(p) for p in
                   ("sky130_fd_sc_hd__buf", "sky130_fd_sc_hd__clkbuf"))
    ])

    return TimingPath(
        startpoint=startpoint,
        endpoint=endpoint,
        path_delay=path_delay,
        adjusted_delay=path_delay,
        required_time=required_time,
        slack=slack,
        raw_slack=slack,
        logic_depth=max(logic_depth, 1),
        cells=cells,
    )


def _apply_wire_factor(path: TimingPath, wire_factor: float, clock_period_ns: float) -> TimingPath:
    """Scale the gate-only delay by wire_factor and recompute slack."""
    path.adjusted_delay = path.path_delay * wire_factor
    # Required time stays the same (it's set by the clock constraint)
    path.slack = path.required_time - path.adjusted_delay
    return path


def _parse_report(
    output: str,
    wire_factor: float,
    clock_period_ns: float,
) -> tuple[list[TimingPath], float, float]:
    """Parse full OpenSTA stdout. Returns (paths, wns, tns)."""
    # Split into path blocks on "Startpoint:"
    raw_blocks = re.split(r"(?=Startpoint:)", output)

    paths = []
    for block in raw_blocks:
        if "Startpoint:" not in block:
            continue
        path = _parse_path_block(block)
        if path:
            path = _apply_wire_factor(path, wire_factor, clock_period_ns)
            paths.append(path)

    # Parse WNS and TNS from dedicated report lines
    wns = 0.0
    tns = 0.0
    m = re.search(r"wns\s+(-?[0-9.]+)", output)
    if m:
        wns = float(m.group(1)) * wire_factor if float(m.group(1)) < 0 else float(m.group(1))
    m = re.search(r"tns\s+(-?[0-9.]+)", output)
    if m:
        tns = float(m.group(1)) * wire_factor if float(m.group(1)) < 0 else float(m.group(1))

    # If WNS wasn't in the report, derive from paths
    if wns == 0.0 and paths:
        violations = [p for p in paths if p.slack < 0]
        if violations:
            wns = min(p.slack for p in violations)

    if tns == 0.0 and paths:
        tns = sum(p.slack for p in paths if p.slack < 0)

    return paths, wns, tns


def run_timing(
    netlist_path: str,
    module_name: str,
    cfg: Config,
) -> TimingReport:
    """Run OpenSTA on a synthesized netlist and return parsed timing results."""
    if not Path(netlist_path).exists():
        return TimingReport(
            success=False,
            module_name=module_name,
            clock_period_ns=cfg.clock_period_ns,
            error_message=f"Netlist not found: {netlist_path}",
        )

    if not cfg.liberty_path or not Path(cfg.liberty_path).exists():
        return TimingReport(
            success=False,
            module_name=module_name,
            clock_period_ns=cfg.clock_period_ns,
            error_message=f"Liberty file not found: '{cfg.liberty_path}'.",
        )

    input_delay_ns = cfg.clock_period_ns * cfg.input_delay_pct
    output_delay_ns = cfg.clock_period_ns * cfg.output_delay_pct

    script = _build_sta_script(
        liberty_path=cfg.liberty_path,
        netlist_path=netlist_path,
        module_name=module_name,
        clock_period_ns=cfg.clock_period_ns,
        input_delay_ns=input_delay_ns,
        output_delay_ns=output_delay_ns,
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".tcl", delete=False) as f:
        f.write(script)
        script_path = f.name

    logger.debug("OpenSTA script:\n%s", script)

    try:
        result = subprocess.run(
            [cfg.sta_path, "-no_init", "-no_splash", "-exit", script_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return TimingReport(
            success=False,
            module_name=module_name,
            clock_period_ns=cfg.clock_period_ns,
            error_message=(
                f"OpenSTA not found at '{cfg.sta_path}'. "
                "Build from: https://github.com/The-OpenROAD-Project/OpenSTA"
            ),
        )
    except subprocess.TimeoutExpired:
        return TimingReport(
            success=False,
            module_name=module_name,
            clock_period_ns=cfg.clock_period_ns,
            error_message="OpenSTA timed out after 120s.",
        )
    finally:
        Path(script_path).unlink(missing_ok=True)

    stdout = result.stdout + result.stderr
    logger.debug("OpenSTA output:\n%s", stdout)

    # OpenSTA exits 0 even on some errors; check for common failure strings
    if "Error" in stdout and "Startpoint" not in stdout:
        error_lines = [l for l in stdout.splitlines() if "Error" in l or "error" in l.lower()]
        return TimingReport(
            success=False,
            module_name=module_name,
            clock_period_ns=cfg.clock_period_ns,
            error_message=error_lines[0] if error_lines else "OpenSTA reported an error.",
            raw_output=stdout,
        )

    paths, wns, tns = _parse_report(stdout, cfg.wire_delay_factor, cfg.clock_period_ns)

    return TimingReport(
        success=True,
        module_name=module_name,
        clock_period_ns=cfg.clock_period_ns,
        wns=wns,
        tns=tns,
        paths=paths,
        raw_output=stdout,
    )
