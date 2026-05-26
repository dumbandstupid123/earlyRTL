"""Yosys synthesis wrapper with src attribute preservation."""

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
class SynthesisResult:
    success: bool
    module_name: str
    netlist_path: str = ""
    cell_count: int = 0
    cell_area: float = 0.0
    logic_levels: int = 0
    error_message: str = ""
    raw_output: str = ""


def _build_yosys_script(
    input_file: str,
    module_name: str,
    liberty_path: str,
    output_netlist: str,
    clock_period_ps: int = 2000,
) -> str:
    return f"""
read_verilog -sv {input_file}
hierarchy -check -top {module_name}
proc
opt
fsm
opt
memory
opt
techmap
dfflibmap -liberty {liberty_path}
abc -liberty {liberty_path} -D {clock_period_ps}
clean
stat -liberty {liberty_path}
write_verilog -attr2comment {output_netlist}
"""


def _clean_netlist(netlist_path: str) -> None:
    """
    Remove duplicate port declarations that Yosys emits but OpenSTA rejects.
    Yosys writes:  input clk;  wire clk;   (or output result;  reg result;)
    OpenSTA only accepts the port declaration — strip the redundant reg/wire.
    """
    content = Path(netlist_path).read_text()
    port_names: set[str] = set()

    # Collect all port-declared signal names
    for m in re.finditer(r"^\s*(?:input|output|inout)\s+(?:\[\d+:\d+\]\s+)?(\w+)\s*;",
                         content, re.MULTILINE):
        port_names.add(m.group(1))

    # Remove any bare `wire` or `reg` redeclaration of a port
    def should_drop(line: str) -> bool:
        m = re.match(r"^\s*(?:wire|reg)\s+(?:\[\d+:\d+\]\s+)?(\w+)\s*;", line)
        return bool(m and m.group(1) in port_names)

    cleaned = "\n".join(
        line for line in content.splitlines() if not should_drop(line)
    )
    Path(netlist_path).write_text(cleaned)


def _parse_yosys_output(stdout: str) -> tuple[int, float, int]:
    """Return (cell_count, cell_area, logic_levels) from Yosys stdout."""
    cell_count = 0
    cell_area = 0.0
    logic_levels = 0

    # Cell count from stat output: "Number of cells:  42"
    m = re.search(r"Number of cells:\s+(\d+)", stdout)
    if m:
        cell_count = int(m.group(1))

    # Cell area from stat: "Chip area for module ...: 123.456"
    m = re.search(r"Chip area for (?:top )?module.*?:\s+([0-9.]+)", stdout)
    if m:
        cell_area = float(m.group(1))

    # Logic levels from abc: "ABC: Delay =  1.23" or "Delay: 1.23"
    # abc reports in library delay units; we use it as a logic depth proxy
    m = re.search(r"ABC:\s+Delay\s*=\s*([0-9.]+)", stdout)
    if m:
        # Approximate logic depth: abc delay divided by a typical cell delay
        # This is a rough estimate; OpenSTA gives the authoritative number
        logic_levels = max(1, int(float(m.group(1)) / 100))

    # Better: count from "Levels ="
    m = re.search(r"Levels\s*=\s*(\d+)", stdout)
    if m:
        logic_levels = int(m.group(1))

    return cell_count, cell_area, logic_levels


def _extract_module_names(verilog_content: str) -> list[str]:
    """Return all module names declared in a Verilog file."""
    return re.findall(r"\bmodule\s+(\w+)\s*[#(;]", verilog_content)


def synthesize(
    verilog_file: str,
    module_name: str,
    cfg: Config,
    output_dir: Optional[str] = None,
) -> SynthesisResult:
    """
    Synthesize a single Verilog module against the configured PDK.
    Returns a SynthesisResult with the netlist path and statistics.
    """
    verilog_path = Path(verilog_file)
    if not verilog_path.exists():
        return SynthesisResult(
            success=False,
            module_name=module_name,
            error_message=f"File not found: {verilog_file}",
        )

    if not cfg.liberty_path or not Path(cfg.liberty_path).exists():
        return SynthesisResult(
            success=False,
            module_name=module_name,
            error_message=(
                f"Liberty file not found: '{cfg.liberty_path}'. "
                "Run setup.sh to download the PDK files."
            ),
        )

    work_dir = Path(output_dir) if output_dir else Path(cfg.cache_dir) / "synthesis"
    work_dir.mkdir(parents=True, exist_ok=True)

    netlist_path = str(work_dir / f"{module_name}_synth.v")
    script = _build_yosys_script(
        input_file=str(verilog_path.resolve()),
        module_name=module_name,
        liberty_path=cfg.liberty_path,
        output_netlist=netlist_path,
        clock_period_ps=int(cfg.clock_period_ns * 1000),
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".ys", delete=False) as f:
        f.write(script)
        script_path = f.name

    logger.debug("Yosys script:\n%s", script)

    try:
        result = subprocess.run(
            [cfg.yosys_path, "-s", script_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return SynthesisResult(
            success=False,
            module_name=module_name,
            error_message=(
                f"Yosys not found at '{cfg.yosys_path}'. "
                "Install with: brew install yosys"
            ),
        )
    except subprocess.TimeoutExpired:
        return SynthesisResult(
            success=False,
            module_name=module_name,
            error_message="Yosys timed out after 120s. Module may be too large.",
        )
    finally:
        Path(script_path).unlink(missing_ok=True)

    stdout = result.stdout + result.stderr
    logger.debug("Yosys output:\n%s", stdout)

    if result.returncode != 0:
        # Extract the most useful error line from Yosys output
        error_lines = [
            line for line in stdout.splitlines()
            if "ERROR" in line or "error" in line.lower()
        ]
        error_msg = error_lines[0] if error_lines else f"Yosys exited with code {result.returncode}"
        return SynthesisResult(
            success=False,
            module_name=module_name,
            error_message=error_msg,
            raw_output=stdout,
        )

    cell_count, cell_area, logic_levels = _parse_yosys_output(stdout)
    _clean_netlist(netlist_path)

    return SynthesisResult(
        success=True,
        module_name=module_name,
        netlist_path=netlist_path,
        cell_count=cell_count,
        cell_area=cell_area,
        logic_levels=logic_levels,
        raw_output=stdout,
    )


def extract_modules_from_file(verilog_file: str) -> list[str]:
    """Return all module names in a Verilog file."""
    try:
        content = Path(verilog_file).read_text()
        return _extract_module_names(content)
    except OSError:
        return []
