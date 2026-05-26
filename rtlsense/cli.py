"""Click-based CLI entry point for RTLSense."""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import click
from rich.console import Console

from .config import load_config, Config
from .explainer import explain_violation
from .formatter import format_json, print_results, print_diff, console
from .mapper import map_violations
from .synthesizer import synthesize, extract_modules_from_file
from .timing import run_timing, TimingReport


# ---------------------------------------------------------------------------
# Shared pipeline
# ---------------------------------------------------------------------------

def _run_pipeline(
    verilog_file: str,
    module_name: str,
    cfg: Config,
    no_ai: bool,
    json_output: bool,
) -> Optional[TimingReport]:
    """Run the full synthesis → timing → map → explain → format pipeline."""
    t0 = time.time()

    console.print(f"\n[bold]RTLSense[/bold]  [dim]{verilog_file}[/dim]  module: [cyan]{module_name}[/cyan]")
    console.print(f"[dim]Clock: {cfg.clock_period_ns:.3f}ns  PDK: {cfg.pdk}  "
                  f"Wire factor: {cfg.wire_delay_factor}x[/dim]")
    console.rule()

    # Step 1: Synthesis
    console.print("[dim]Synthesizing...[/dim]", end="\r")
    synth = synthesize(verilog_file, module_name, cfg)
    if not synth.success:
        console.print(f"[red]Synthesis error:[/red] {synth.error_message}")
        return None
    console.print(f"[dim]Synthesis done in {time.time()-t0:.1f}s[/dim]", end="\r")

    # Step 2: Timing analysis
    t1 = time.time()
    console.print("[dim]Running STA...[/dim]     ", end="\r")
    report = run_timing(synth.netlist_path, module_name, cfg)
    if not report.success:
        console.print(f"[red]Timing error:[/red] {report.error_message}")
        return None

    elapsed = time.time() - t0
    console.print(f"[dim]Analysis complete in {elapsed:.1f}s[/dim]   ")

    # Step 3: Map violations to source
    violations = map_violations(report.paths, synth.netlist_path, verilog_file)

    # Step 4: AI explanations
    explanations: dict = {}
    if not no_ai and cfg.anthropic_api_key:
        for i, v in enumerate(violations, start=1):
            explanations[i] = explain_violation(v, cfg, rtl_file=verilog_file)

    # Step 5: Output
    if json_output:
        click.echo(format_json(report, violations, explanations))
    else:
        print_results(report, synth, violations, explanations, cfg)

    return report


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

@click.group()
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def rtlsense(ctx: click.Context, verbose: bool) -> None:
    """RTLSense — real-time timing analysis for Verilog designers."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@rtlsense.command()
@click.argument("verilog_file", type=click.Path(exists=True))
@click.option("--clock", required=True, help="Clock frequency, e.g. 500MHz or 1GHz.")
@click.option("--module", default="", help="Module name to analyze (default: first module found).")
@click.option("--pdk", default="", help="PDK to use: sky130 (default) or asap7.")
@click.option("--wire-factor", default=0.0, type=float, help="Wire delay scaling factor (default: 1.4).")
@click.option("--no-ai", is_flag=True, help="Skip AI explanations.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON diagnostics.")
@click.pass_context
def check(
    ctx: click.Context,
    verilog_file: str,
    clock: str,
    module: str,
    pdk: str,
    wire_factor: float,
    no_ai: bool,
    json_output: bool,
) -> None:
    """Analyze a Verilog file for timing violations."""
    cfg = load_config(
        clock=clock,
        pdk=pdk or None,
        wire_factor=wire_factor or None,
        verbose=ctx.obj.get("verbose", False),
    )

    modules = extract_modules_from_file(verilog_file)
    if not modules:
        console.print(f"[red]No modules found in {verilog_file}[/red]")
        sys.exit(1)

    target = module or modules[0]
    if target not in modules:
        console.print(f"[red]Module '{target}' not found. Available: {modules}[/red]")
        sys.exit(1)

    result = _run_pipeline(verilog_file, target, cfg, no_ai, json_output)
    if result is None:
        sys.exit(2)
    if result.violations:
        sys.exit(1)


@rtlsense.command()
@click.argument("directory", type=click.Path(exists=True))
@click.option("--clock", required=True, help="Clock frequency, e.g. 500MHz.")
@click.option("--pdk", default="", help="PDK: sky130 or asap7.")
@click.option("--no-ai", is_flag=True)
@click.pass_context
def watch(
    ctx: click.Context,
    directory: str,
    clock: str,
    pdk: str,
    no_ai: bool,
) -> None:
    """Watch a directory and re-analyze on every Verilog file save."""
    from .watcher import watch_directory

    cfg = load_config(clock=clock, pdk=pdk or None, verbose=ctx.obj.get("verbose", False))

    def on_change(filepath: str, modules: list[str]) -> None:
        console.clear()
        console.print(f"[dim]{time.strftime('%H:%M:%S')}[/dim]  File changed: [bold]{filepath}[/bold]")
        for mod in modules:
            _run_pipeline(filepath, mod, cfg, no_ai, json_output=False)

    watch_directory(directory, on_change, cfg.cache_dir)


@rtlsense.command()
@click.argument("file_a", type=click.Path(exists=True))
@click.argument("file_b", type=click.Path(exists=True))
@click.option("--clock", required=True, help="Clock frequency.")
@click.option("--module", default="", help="Module name (must exist in both files).")
@click.option("--pdk", default="", help="PDK: sky130 or asap7.")
@click.option("--wire-factor", default=0.0, type=float)
@click.pass_context
def diff(
    ctx: click.Context,
    file_a: str,
    file_b: str,
    clock: str,
    module: str,
    pdk: str,
    wire_factor: float,
) -> None:
    """Compare timing between two versions of a Verilog module."""
    cfg = load_config(
        clock=clock,
        pdk=pdk or None,
        wire_factor=wire_factor or None,
        verbose=ctx.obj.get("verbose", False),
    )

    def get_module(f: str) -> str:
        mods = extract_modules_from_file(f)
        if not mods:
            console.print(f"[red]No modules in {f}[/red]")
            sys.exit(1)
        return module or mods[0]

    mod_a = get_module(file_a)
    mod_b = get_module(file_b)

    console.print(f"\n[bold]Synthesizing {file_a}...[/bold]")
    synth_a = synthesize(file_a, mod_a, cfg)
    if not synth_a.success:
        console.print(f"[red]Synthesis failed (A):[/red] {synth_a.error_message}")
        sys.exit(1)

    console.print(f"[bold]Synthesizing {file_b}...[/bold]")
    synth_b = synthesize(file_b, mod_b, cfg)
    if not synth_b.success:
        console.print(f"[red]Synthesis failed (B):[/red] {synth_b.error_message}")
        sys.exit(1)

    report_a = run_timing(synth_a.netlist_path, mod_a, cfg)
    report_b = run_timing(synth_b.netlist_path, mod_b, cfg)

    if not report_a.success or not report_b.success:
        console.print("[red]Timing analysis failed.[/red]")
        sys.exit(1)

    label_a = Path(file_a).stem
    label_b = Path(file_b).stem
    print_diff(label_a, label_b, report_a, report_b, cfg)
