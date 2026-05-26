"""Rich terminal output and JSON formatter for timing results."""

import json
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich import box

from .config import Config
from .mapper import MappedViolation
from .synthesizer import SynthesisResult
from .timing import TimingReport

console = Console(stderr=True)


def _slack_color(slack: float, clock_period: float, warning_threshold: float) -> str:
    if slack < 0:
        return "bold red"
    if slack < clock_period * warning_threshold:
        return "bold yellow"
    return "bold green"


def _timing_budget_bar(
    adjusted_delay: float,
    gate_delay: float,
    clock_period: float,
    width: int = 24,
) -> str:
    """Render a simple ASCII timing budget bar."""
    fill = min(width, int((adjusted_delay / clock_period) * width))
    bar = "█" * fill + "░" * (width - fill)
    wire_delay = adjusted_delay - gate_delay
    margin = max(0.0, clock_period - adjusted_delay)
    pct = int((adjusted_delay / clock_period) * 100)
    return (
        f"[{bar}] {adjusted_delay:.3f}ns / {clock_period:.3f}ns ({pct}%)\n"
        f"  gates: {gate_delay:.3f}ns  wire est: {wire_delay:.3f}ns  margin: {margin:.3f}ns"
    )


def _format_violation(
    v: MappedViolation,
    explanation: Optional[str],
    cfg: Config,
    index: int,
) -> Panel:
    loc = v.startpoint_loc or v.endpoint_loc
    filename = loc.filename if loc else "unknown"
    line_no = loc.line_number if loc else 0

    title_color = "red" if v.path.slack < 0 else "yellow"
    title = f"[{title_color}]TIMING VIOLATION #{index}[/{title_color}]  {filename}:{line_no}"

    body = Text()

    # Code snippet
    if loc and loc.code_snippet:
        body.append("\n")
        for i, line in enumerate(loc.code_snippet):
            actual_line = loc.snippet_start_line + i
            if actual_line == loc.line_number:
                body.append(f"  {actual_line:4d} │ {line}\n", style="bold red on dark_red")
            else:
                body.append(f"  {actual_line:4d} │ {line}\n", style="dim")
        body.append("\n")

    # Metrics row
    slack_style = _slack_color(v.path.slack, cfg.clock_period_ns, cfg.warning_threshold_pct)
    body.append("  Slack: ", style="bold")
    body.append(f"{v.path.slack:+.3f}ns", style=slack_style)
    body.append("   Logic depth: ", style="bold")
    body.append(f"{v.path.logic_depth} levels", style="cyan")
    body.append("   Path delay: ", style="bold")
    body.append(f"{v.path.adjusted_delay:.3f}ns\n", style="white")

    # Timing budget bar
    body.append("\n  Timing Budget ")
    budget_str = _timing_budget_bar(
        v.path.adjusted_delay,
        v.path.path_delay,
        cfg.clock_period_ns,
    )
    body.append(budget_str + "\n", style="cyan")

    # Path info
    body.append(f"\n  Path: {v.path.startpoint} → {v.path.endpoint}\n", style="dim")

    # AI explanation
    if explanation:
        body.append("\n  [bold blue]AI Suggestion:[/bold blue] ", style="")
        body.append(explanation + "\n", style="italic")

    border_color = "red" if v.path.slack < 0 else "yellow"
    return Panel(body, title=title, border_style=border_color, expand=False)


def print_synthesis_info(synth: SynthesisResult) -> None:
    console.print(
        f"  [dim]Synthesis:[/dim] {synth.cell_count} cells, "
        f"{synth.cell_area:.1f} μm², "
        f"~{synth.logic_levels} logic levels",
        style="dim",
    )


def print_results(
    report: TimingReport,
    synth: SynthesisResult,
    violations: list[MappedViolation],
    explanations: dict[int, Optional[str]],
    cfg: Config,
) -> None:
    """Print the full timing analysis result to the terminal."""
    if not report.success:
        console.print(f"\n[bold red]Analysis failed:[/bold red] {report.error_message}\n")
        return

    console.print()
    print_synthesis_info(synth)
    console.print()

    if not violations and not report.paths:
        console.print("[dim]No timing paths found. Check that your module has registered outputs.[/dim]")
        return

    if not violations:
        console.print(
            f"[bold green]✓ All timing paths met[/bold green]  "
            f"WNS: [green]+{abs(report.wns):.3f}ns[/green]  "
            f"Paths: {report.met_count}"
        )
    else:
        for i, v in enumerate(violations, start=1):
            panel = _format_violation(v, explanations.get(i), cfg, i)
            console.print(panel)

    # Summary line
    violation_count = len(violations)
    warning_threshold_ns = cfg.clock_period_ns * cfg.warning_threshold_pct
    warning_count = sum(
        1 for p in report.paths
        if not p.is_violation and p.slack < warning_threshold_ns
    )
    met_count = report.met_count - warning_count

    wns_str = f"{report.wns:+.3f}ns"
    wns_style = "red" if report.wns < 0 else "green"

    summary = (
        f"[bold red]{violation_count} violations[/bold red]  "
        f"[yellow]{warning_count} warnings[/yellow]  "
        f"[green]{met_count} paths met[/green]  "
        f"WNS: [{wns_style}]{wns_str}[/{wns_style}]  "
        f"TNS: {report.tns:.3f}ns"
    )
    console.rule()
    console.print(summary)
    console.print()


def print_diff(
    label_a: str,
    label_b: str,
    report_a: TimingReport,
    report_b: TimingReport,
    cfg: Config,
) -> None:
    """Print a diff comparison between two timing reports."""
    console.print(f"\n[bold]Timing Diff:[/bold] {label_a} → {label_b}\n")

    # Index paths by (startpoint, endpoint)
    paths_a = {(p.startpoint, p.endpoint): p for p in report_a.paths}
    paths_b = {(p.startpoint, p.endpoint): p for p in report_b.paths}

    table = Table(box=box.SIMPLE, show_header=True)
    table.add_column("Path", style="dim", max_width=40)
    table.add_column(f"Slack ({label_a})", justify="right")
    table.add_column(f"Slack ({label_b})", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Status")

    regressions = []
    for key, path_b in sorted(paths_b.items(), key=lambda x: x[1].slack):
        path_a = paths_a.get(key)
        slack_b = path_b.slack
        slack_a = path_a.slack if path_a else None
        delta = (slack_b - slack_a) if slack_a is not None else None

        path_label = f"{key[0]}→{key[1]}"[:38]

        if slack_a is None:
            status = "[red]NEW[/red]" if slack_b < 0 else "[yellow]NEW[/yellow]"
            table.add_row(
                path_label, "—", f"{slack_b:+.3f}ns",
                "new", status,
            )
            if slack_b < 0:
                regressions.append((path_label, delta, slack_b))
        else:
            delta_str = f"{delta:+.3f}ns"
            if delta < -0.01:
                delta_style = "red"
                status = "[red]WORSE[/red]"
                regressions.append((path_label, delta, slack_b))
            elif delta > 0.01:
                delta_style = "green"
                status = "[green]BETTER[/green]"
            else:
                delta_style = "dim"
                status = "[dim]SAME[/dim]"

            table.add_row(
                path_label,
                f"{slack_a:+.3f}ns",
                f"{slack_b:+.3f}ns",
                Text(delta_str, style=delta_style),
                status,
            )

    console.print(table)
    console.rule()

    wns_delta = report_b.wns - report_a.wns
    depth_a = max((p.logic_depth for p in report_a.paths), default=0)
    depth_b = max((p.logic_depth for p in report_b.paths), default=0)

    wns_style = "red" if wns_delta < 0 else "green"
    new_violations = len([r for r in regressions if r[1] is None or r[2] < 0])

    console.print(
        f"WNS change: [{wns_style}]{wns_delta:+.3f}ns[/{wns_style}]  "
        f"Max logic depth: {depth_a} → {depth_b} levels  "
        f"New violations: [red]{new_violations}[/red]"
    )
    console.print()


def format_json(
    report: TimingReport,
    violations: list[MappedViolation],
    explanations: dict[int, Optional[str]],
) -> str:
    """Return VS Code-compatible JSON diagnostics, one per source line (worst slack wins)."""
    # Deduplicate: keep only the worst-slack violation per (file, line)
    worst: dict[tuple[str, int], tuple[MappedViolation, int]] = {}
    for i, v in enumerate(violations, start=1):
        loc = v.startpoint_loc or v.endpoint_loc
        key = (loc.filename if loc else "", loc.line_number if loc else 0)
        if key not in worst or v.path.slack < worst[key][0].path.slack:
            worst[key] = (v, i)

    diagnostics = []
    for (filename, line_no), (v, i) in sorted(worst.items(), key=lambda x: x[0]):
        diagnostics.append({
            "file": filename,
            "line": line_no,
            "column": 0,
            "severity": "error" if v.path.slack < 0 else "warning",
            "message": (
                f"Timing violation: slack {v.path.slack:+.3f}ns, "
                f"path delay {v.path.adjusted_delay:.3f}ns, "
                f"logic depth {v.path.logic_depth}"
            ),
            "path_delay": v.path.adjusted_delay,
            "slack": v.path.slack,
            "logic_depth": v.path.logic_depth,
            "startpoint": v.path.startpoint,
            "endpoint": v.path.endpoint,
            "suggestion": explanations.get(i),
        })
    return json.dumps({"wns": report.wns, "tns": report.tns, "diagnostics": diagnostics}, indent=2)
