"""Map synthesized gate violations back to RTL source lines."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .timing import TimingPath


@dataclass
class SourceLocation:
    filename: str
    line_number: int
    signal_name: str
    code_snippet: list[str] = field(default_factory=list)
    snippet_start_line: int = 1


@dataclass
class MappedViolation:
    path: TimingPath
    startpoint_loc: Optional[SourceLocation]
    endpoint_loc: Optional[SourceLocation]
    method: str = "unknown"   # "src_attr" | "signal_grep" | "none"


def _parse_src_attributes(netlist_path: str) -> dict[str, tuple[str, int]]:
    """
    Extract src attribute comments from a Yosys netlist written with -attr2comment.
    Returns {signal_name: (filename, line_number)}.
    """
    mapping: dict[str, tuple[str, int]] = {}
    try:
        content = Path(netlist_path).read_text()
    except OSError:
        return mapping

    # Match Yosys format: /* src = "file.v:42.1-42.10" */  (spaces around =, col info)
    src_pattern = re.compile(r'/\*\s*src\s*=\s*"([^"]+):(\d+)[^"]*"\s*\*/')
    # Wire/reg/port declarations: wire [15:0] foo;
    wire_pattern = re.compile(r'\b(?:wire|reg|input|output)\b[^;]*\b(\w+)\s*;')
    # Cell instantiations: sky130_fd_sc_hd__dfrtp_1 _421_ (
    cell_pattern = re.compile(r'^\s*\w[\w$]*\s+(\w+)\s*\(')

    lines = content.splitlines()
    for i, line in enumerate(lines):
        src_m = src_pattern.search(line)
        if src_m:
            src_file = src_m.group(1)
            src_line = int(src_m.group(2))
            # Look on this line and the next 2 for a signal/instance name
            search_range = lines[i:i+3]
            for search_line in search_range:
                wire_m = wire_pattern.search(search_line)
                if wire_m:
                    signal = wire_m.group(1)
                    mapping[signal] = (src_file, src_line)
                    break
                cell_m = cell_pattern.search(search_line)
                if cell_m:
                    signal = cell_m.group(1)
                    mapping[signal] = (src_file, src_line)
                    break

    return mapping


def _grep_signal_in_file(signal_name: str, verilog_file: str) -> Optional[tuple[str, int]]:
    """
    Fallback: find where a signal is assigned in the original RTL.
    Looks for: always blocks, assign statements, port/wire declarations.
    """
    try:
        lines = Path(verilog_file).read_text().splitlines()
    except OSError:
        return None

    # Clean signal name: strip hierarchy separators, take the last part
    base_signal = signal_name.split("/")[-1].split(".")[-1]
    # Strip trailing _reg suffix (Yosys adds _reg to flip-flops)
    base_signal_stripped = re.sub(r"_reg$", "", base_signal)
    # Strip bus index like [0], [31] to get the bare identifier (e.g. "b[0]" → "b")
    base_id = re.sub(r"\[\d+\]$", "", base_signal)

    patterns = [
        re.compile(rf"\b{re.escape(base_signal)}\s*<="),
        re.compile(rf"\bassign\s+{re.escape(base_signal)}\b"),
        re.compile(rf"\b(?:reg|wire)\s+.*\b{re.escape(base_signal)}\b"),
        re.compile(rf"\b{re.escape(base_signal_stripped)}\s*<="),
        re.compile(rf"\bassign\s+{re.escape(base_signal_stripped)}\b"),
    ]
    # If the signal had a bus index, also search for the bare port/wire declaration
    if base_id != base_signal:
        patterns += [
            re.compile(rf"\b(?:input|output|inout|reg|wire)\b.*\b{re.escape(base_id)}\b"),
            re.compile(rf"\b{re.escape(base_id)}\s*<="),
            re.compile(rf"\bassign\s+{re.escape(base_id)}\b"),
        ]

    for i, line in enumerate(lines, start=1):
        for pattern in patterns:
            if pattern.search(line):
                return (verilog_file, i)

    return None


def _get_snippet(filename: str, line_number: int, context: int = 2) -> tuple[list[str], int]:
    """Return a code snippet centered on line_number with `context` lines either side."""
    try:
        lines = Path(filename).read_text().splitlines()
    except OSError:
        return [], line_number

    start = max(0, line_number - 1 - context)
    end = min(len(lines), line_number + context)
    return lines[start:end], start + 1


def _resolve_signal(
    signal_name: str,
    src_map: dict[str, tuple[str, int]],
    original_verilog: str,
) -> Optional[SourceLocation]:
    """Try src attributes first, fall back to grep."""
    # Strip common Yosys hierarchy prefixes
    base = signal_name.split("/")[-1]

    # Method 1: src attribute map
    for candidate in [base, signal_name]:
        if candidate in src_map:
            filename, line_no = src_map[candidate]
            snippet, snippet_start = _get_snippet(filename, line_no)
            return SourceLocation(
                filename=filename,
                line_number=line_no,
                signal_name=candidate,
                code_snippet=snippet,
                snippet_start_line=snippet_start,
            )

    # Method 2: grep the original RTL
    if original_verilog:
        result = _grep_signal_in_file(base, original_verilog)
        if result:
            filename, line_no = result
            snippet, snippet_start = _get_snippet(filename, line_no)
            return SourceLocation(
                filename=filename,
                line_number=line_no,
                signal_name=base,
                code_snippet=snippet,
                snippet_start_line=snippet_start,
            )

    return None


def map_violations(
    paths: list[TimingPath],
    netlist_path: str,
    original_verilog: str,
) -> list[MappedViolation]:
    """
    Map each timing path to a source location in the original RTL.
    Only processes violating paths.
    """
    src_map = _parse_src_attributes(netlist_path)
    violations_only = [p for p in paths if p.is_violation]
    results = []

    for path in violations_only:
        start_loc = _resolve_signal(path.startpoint, src_map, original_verilog)
        end_loc = _resolve_signal(path.endpoint, src_map, original_verilog)

        method = "none"
        if start_loc or end_loc:
            # Determine which method succeeded
            base_start = path.startpoint.split("/")[-1]
            if base_start in src_map:
                method = "src_attr"
            else:
                method = "signal_grep"

        results.append(MappedViolation(
            path=path,
            startpoint_loc=start_loc,
            endpoint_loc=end_loc,
            method=method,
        ))

    return results
