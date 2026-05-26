"""Configuration loading: CLI flags > project yaml > user yaml > defaults."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Config:
    pdk: str = "sky130"
    clock_period_ns: float = 2.0
    input_delay_pct: float = 0.2
    output_delay_pct: float = 0.2
    wire_delay_factor: float = 1.4
    warning_threshold_pct: float = 0.2
    yosys_path: str = "yosys"
    sta_path: str = "sta"
    sky130_lib_path: str = ""
    asap7_lib_path: str = ""
    cache_dir: str = ".rtlsense_cache"
    anthropic_api_key: str = ""
    verbose: bool = False

    @property
    def liberty_path(self) -> str:
        if self.pdk == "asap7":
            return self.asap7_lib_path
        return self.sky130_lib_path

    @property
    def warning_slack_ns(self) -> float:
        return -self.clock_period_ns * self.warning_threshold_pct


def _parse_clock(clock_str: str) -> float:
    """Convert a clock string like '500MHz' or '1GHz' to a period in nanoseconds."""
    clock_str = clock_str.strip()
    match = re.match(r"^([0-9.]+)\s*(MHz|GHz|KHz|Hz)$", clock_str, re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot parse clock '{clock_str}'. Use format like '500MHz' or '1GHz'.")
    value = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "GHZ":
        return 1.0 / value
    elif unit == "MHZ":
        return 1000.0 / value
    elif unit == "KHZ":
        return 1_000_000.0 / value
    else:
        return 1_000_000_000.0 / value


def _find_default_lib(pdk: str) -> str:
    """Search common locations for the liberty file."""
    search_dirs = [
        Path(__file__).parent.parent / "pdk" / pdk,
        Path.home() / ".rtlsense" / "pdk" / pdk,
        Path("/usr/local/share/rtlsense/pdk") / pdk,
    ]
    patterns = {
        "sky130": "sky130_fd_sc_hd__tt_025C_1v80.lib",
        "asap7": "*.lib",
    }
    pattern = patterns.get(pdk, "*.lib")
    for d in search_dirs:
        candidates = list(d.glob(pattern))
        if candidates:
            return str(candidates[0])
    return ""


def load_config(
    clock: Optional[str] = None,
    pdk: Optional[str] = None,
    wire_factor: Optional[float] = None,
    verbose: bool = False,
) -> Config:
    """Load config from yaml files and apply CLI overrides."""
    raw: dict = {}

    # Load user-level config first, then project-level (project wins)
    for path in [Path.home() / ".rtlsense.yaml", Path("rtlsense.yaml")]:
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
                raw.update(data)

    cfg = Config()

    cfg.pdk = pdk or raw.get("pdk", cfg.pdk)
    cfg.wire_delay_factor = wire_factor or float(raw.get("wire_delay_factor", cfg.wire_delay_factor))
    cfg.input_delay_pct = float(raw.get("input_delay_pct", cfg.input_delay_pct))
    cfg.output_delay_pct = float(raw.get("output_delay_pct", cfg.output_delay_pct))
    cfg.warning_threshold_pct = float(raw.get("warning_threshold_pct", cfg.warning_threshold_pct))
    cfg.yosys_path = raw.get("yosys_path", cfg.yosys_path)
    cfg.sta_path = raw.get("sta_path", cfg.sta_path)
    cfg.cache_dir = raw.get("cache_dir", cfg.cache_dir)
    cfg.verbose = verbose

    if clock:
        cfg.clock_period_ns = _parse_clock(clock)
    elif "clock_period_ns" in raw:
        cfg.clock_period_ns = float(raw["clock_period_ns"])

    # Resolve liberty file path
    cfg.sky130_lib_path = raw.get("sky130_lib_path", "") or _find_default_lib("sky130")
    cfg.asap7_lib_path = raw.get("asap7_lib_path", "") or _find_default_lib("asap7")

    # API key from config or environment
    cfg.anthropic_api_key = (
        raw.get("anthropic_api_key", "")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    # Resolve ${ENV_VAR} syntax in the yaml value
    if cfg.anthropic_api_key.startswith("${") and cfg.anthropic_api_key.endswith("}"):
        env_var = cfg.anthropic_api_key[2:-1]
        cfg.anthropic_api_key = os.environ.get(env_var, "")

    return cfg
