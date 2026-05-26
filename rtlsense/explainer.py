"""Anthropic API integration for timing violation explanations, with caching."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from .config import Config
from .mapper import MappedViolation

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior ASIC design engineer reviewing RTL code with a timing violation.
You are given the code, the timing path details, logic depth, and slack.
In 2-3 sentences, explain WHY this code causes a timing problem — be specific about
the logic structure (carry chains, wide muxes, deep case statements, priority encoders, etc.).
Then suggest ONE concrete RTL fix (pipelining, look-ahead carry, one-hot encoding,
logic restructuring, etc.).
Talk like an engineer, not a textbook. Reference actual signal names from the code.
Keep your total response under 60 words."""


def _cache_key(code_snippet: str, cells: list[str]) -> str:
    payload = code_snippet + "|" + ",".join(cells[:10])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _load_cache(cache_dir: str) -> dict:
    cache_file = Path(cache_dir) / "explanations.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(cache_dir: str, cache: dict) -> None:
    cache_file = Path(cache_dir) / "explanations.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, indent=2))


def explain_violation(
    violation: MappedViolation,
    cfg: Config,
    rtl_file: str = "",
) -> Optional[str]:
    """
    Return a 2-3 sentence AI explanation of the timing violation.
    Returns None if the API key is missing or the call fails.
    """
    if not cfg.anthropic_api_key:
        return None

    loc = violation.startpoint_loc or violation.endpoint_loc
    if loc and loc.code_snippet:
        code_snippet = "\n".join(loc.code_snippet)
    elif rtl_file:
        try:
            code_snippet = Path(rtl_file).read_text()
        except OSError:
            code_snippet = ""
    else:
        code_snippet = ""
    cell_names = [c.cell_type for c in violation.path.cells]

    key = _cache_key(code_snippet, cell_names)
    cache = _load_cache(cfg.cache_dir)
    if key in cache:
        logger.debug("Explanation cache hit for key %s", key)
        return cache[key]

    user_message = f"""
RTL code snippet (around the violation):
```verilog
{code_snippet}
```

Timing path details:
- Startpoint: {violation.path.startpoint}
- Endpoint: {violation.path.endpoint}
- Gate delay: {violation.path.path_delay:.3f}ns
- Estimated total delay (with wire): {violation.path.adjusted_delay:.3f}ns
- Slack: {violation.path.slack:.3f}ns
- Logic depth: {violation.path.logic_depth} levels
- Cells in path: {', '.join(cell_names[:8])}
"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        explanation = response.content[0].text.strip()
        cache[key] = explanation
        _save_cache(cfg.cache_dir, cache)
        return explanation
    except Exception as e:
        logger.warning("AI explanation failed: %s", e)
        return None
