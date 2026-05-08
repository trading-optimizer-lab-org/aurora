"""LLM research assistant for QuantForge.

Wraps the Anthropic API to support strategy ideation, drafting, and critique.

Security:
- API key is read STRICTLY from an environment variable. It is never accepted
  via config, code, or log files.
- Tests must inject a mock client via the `client` constructor parameter; this
  removes any need for a real API key during unit testing.
"""
from __future__ import annotations

import ast
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


log = logging.getLogger(__name__)


# Whitelist of importable modules for LLM-drafted strategy code. Anything
# outside this set is rejected at parse time so a malicious or careless model
# response cannot pull in os/subprocess/socket/etc. Sub-imports of these
# packages (e.g. ``numpy.linalg``) are also allowed.
_ALLOWED_IMPORTS = frozenset({
    "__future__",  # ``from __future__ import annotations`` is benign.
    "numpy",
    "pandas",
    "quantforge.strategies.base",
})

# Names that must never appear at AST level - they are common sandbox-escape
# vectors (eval/exec, dynamic imports, dunder-attribute walks).
_FORBIDDEN_NAMES = frozenset({
    "exec",
    "eval",
    "__import__",
    "compile",
    "open",
    "input",
    "globals",
    "locals",
    "vars",
    "getattr",
    "setattr",
    "delattr",
    "breakpoint",
})

# Method/function call names that perform runtime IO via numpy/pandas. These
# slip past the import allowlist because numpy/pandas are themselves allowed,
# but a drafted strategy should never be touching the filesystem at runtime.
_BLOCKED_CALLS = frozenset({
    "read_csv",
    "read_json",
    "read_parquet",
    "read_excel",
    "read_pickle",
    "to_csv",
    "to_json",
    "to_parquet",
    "to_pickle",
    "load",
    "save",
    "fromfile",
    "tofile",
    "memmap",
})


def _import_root(name: str) -> str:
    """Return the root package of a dotted module name."""
    return name.split(".", 1)[0]


def _is_allowed_module(module: Optional[str]) -> bool:
    """True if ``module`` (dotted) is in the import allowlist."""
    if not module:
        return False
    if module in _ALLOWED_IMPORTS:
        return True
    root = _import_root(module)
    for allowed in _ALLOWED_IMPORTS:
        if module == allowed:
            return True
        # Allow ``numpy.linalg`` when ``numpy`` is whitelisted, etc.
        if module.startswith(allowed + "."):
            return True
        if root == _import_root(allowed) and "." not in allowed:
            return True
    return False


def _validate_drafted_code_ast(code: str) -> None:
    """Walk ``code`` AST and reject sandbox escapes.

    Rules:
        * ``Import`` / ``ImportFrom`` modules must be in :data:`_ALLOWED_IMPORTS`
          (or a sub-package thereof).
        * Calling or referring to :data:`_FORBIDDEN_NAMES` (``exec``, ``eval``,
          ``__import__``, etc.) is forbidden.
        * Direct attribute access on a name beginning and ending with double
          underscores (e.g. ``x.__class__``, ``__builtins__.foo``) is rejected
          to block reflection-based escapes.
        * Bare references to ``__builtins__`` are rejected.
        * Calls to numpy/pandas IO methods listed in :data:`_BLOCKED_CALLS`
          (e.g. ``pd.read_csv``, ``np.load``, ``df.to_pickle``) are rejected
          so a drafted strategy cannot perform runtime filesystem IO even
          though numpy/pandas are otherwise importable.

    Raises ValueError on the first violation.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"draft_strategy: LLM output is not valid Python. {e}") from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_allowed_module(alias.name):
                    raise ValueError(
                        f"draft_strategy: import of {alias.name!r} not allowed; "
                        f"permitted roots: {sorted(_ALLOWED_IMPORTS)}"
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            # Block relative imports outright.
            if node.level and node.level > 0:
                raise ValueError(
                    "draft_strategy: relative imports are not allowed "
                    f"(level={node.level}, module={mod!r})"
                )
            if not _is_allowed_module(mod):
                raise ValueError(
                    f"draft_strategy: from-import of {mod!r} not allowed; "
                    f"permitted roots: {sorted(_ALLOWED_IMPORTS)}"
                )
        elif isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_NAMES or node.id == "__builtins__":
                raise ValueError(
                    f"draft_strategy: reference to forbidden name {node.id!r}"
                )
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__"):
                raise ValueError(
                    f"draft_strategy: dunder attribute access {attr!r} is not allowed"
                )
        elif isinstance(node, ast.Call):
            func = node.func
            # Reject ``pd.read_csv(...)``, ``df.to_pickle(...)``, ``np.load(...)`` etc.
            if isinstance(func, ast.Attribute) and func.attr in _BLOCKED_CALLS:
                raise ValueError(
                    f"draft_strategy: call to {func.attr!r} is not allowed "
                    "(runtime IO bypass)"
                )
            # Reject bare-name calls like ``load(...)`` after ``from numpy import load``.
            if isinstance(func, ast.Name) and func.id in _BLOCKED_CALLS:
                raise ValueError(
                    f"draft_strategy: call to {func.id!r} is not allowed "
                    "(runtime IO bypass)"
                )


try:
    import anthropic  # type: ignore
    ANTHROPIC_AVAILABLE = True
except Exception:
    anthropic = None  # type: ignore
    ANTHROPIC_AVAILABLE = False


SYSTEM_PROMPT = """You are a quantitative research assistant for QuantForge, a backtesting framework.

QuantForge Strategy interface conventions:
- Strategy subclasses live in quantforge/strategies/library/.
- Each subclass inherits from quantforge.strategies.base.Strategy.
- Implement signals(self, prices: pd.Series) -> np.ndarray.
- Output array length matches len(prices); values in [-1.0, 1.0]; no NaN.
- weights[i] is the position at the close of bar i; it is applied to the
  return of bar i+1. weights[i] must use prices[:i+1] only (no lookahead).
- Override classmethod spec() returning a StrategySpec with params and
  param_ranges for GA encoding. param_ranges entries are (low, high) for
  numeric params or a list of allowed values for categorical params.
- Constructor parameters mirror the keys in StrategySpec.params.
- Imports allowed: numpy as np, pandas as pd, and quantforge.strategies.base.

When asked for ideas, return STRICT JSON: a list of objects with keys
{name, hypothesis, signal_logic, params, rationale}. No prose outside the JSON.

When asked for code, return ONLY valid Python source for the Strategy
subclass; no markdown fences, no commentary, no surrounding text."""


@dataclass
class LLMConfig:
    api_key_env: str = "ANTHROPIC_API_KEY"
    model: str = "claude-sonnet-4-5"
    max_tokens: int = 4096
    temperature: float = 0.7


def _extract_text(response: Any) -> str:
    """Pull text out of an Anthropic Messages API response or a mock."""
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    if content is None:
        return str(response)
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(text)
    return "".join(parts).strip()


def _strip_code_fences(text: str) -> str:
    """Remove ```python ... ``` or ``` ... ``` fences if the model added them."""
    s = text.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_array(text: str) -> str:
    """Best-effort extraction of the first top-level JSON array in text."""
    s = _strip_code_fences(text)
    start = s.find("[")
    end = s.rfind("]")
    if start == -1 or end == -1 or end < start:
        return s
    return s[start:end + 1]


class LLMResearchAssistant:
    """Anthropic-backed assistant. Inject `client` for tests; otherwise the
    constructor lazily builds a real client using the env-var API key."""

    def __init__(self, config: LLMConfig, client: Any = None):
        self.config = config
        if client is not None:
            self._client = client
            return
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic SDK is not installed. Install it or pass a mock "
                "client via the `client` argument for offline testing."
            )
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Environment variable {config.api_key_env} is not set. "
                "Set it to your Anthropic API key, or pass a mock client."
            )
        self._client = anthropic.Anthropic(api_key=api_key)

    # -- IO helpers ----------------------------------------------------------

    def read_research_log(self, path: str) -> str:
        """Read a research-log file, rejecting ``..`` traversal escapes.

        Security model
        --------------
        Relative paths are resolved against the project root (the parent
        of the ``quantforge`` package directory) and must stay within it
        after resolution. A relative path that escapes the project root
        via ``..`` segments is rejected with :class:`ValueError`.

        Absolute paths are allowed: callers asking for an absolute path
        have already made an explicit choice about where to read from.
        However, an absolute path containing ``..`` segments before
        resolution is also rejected as a defense-in-depth check, since
        such forms typically indicate untrusted concatenation.
        """
        project_root = Path(__file__).resolve().parents[2]
        raw = Path(path)
        # Defense in depth: reject any ``..`` segments in the input,
        # regardless of whether the resolved form would escape the root.
        if any(part == ".." for part in raw.parts):
            raise ValueError(
                f"refusing to read research log: path contains '..' "
                f"traversal segments: {path!r}"
            )
        if raw.is_absolute():
            resolved = raw.resolve()
        else:
            resolved = (project_root / raw).resolve()
            try:
                resolved.relative_to(project_root)
            except ValueError as exc:
                raise ValueError(
                    f"refusing to read research log outside project root: "
                    f"{path!r} resolved to {resolved}, "
                    f"project_root={project_root}"
                ) from exc
        return resolved.read_text(encoding="utf-8")

    # -- Internal call -------------------------------------------------------

    def _call(self, user_prompt: str, system: Optional[str] = None) -> str:
        msg = self._client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system=system or SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return _extract_text(msg)

    # -- Public API ----------------------------------------------------------

    def propose_ideas(self, context: str, n: int = 5) -> list[dict]:
        """Ask the LLM for n strategy ideas. Returns a parsed JSON list."""
        prompt = (
            f"Research context:\n{context}\n\n"
            f"Propose {n} concrete strategy ideas suitable for the QuantForge "
            "Strategy interface. Return ONLY a JSON list with objects keyed by "
            "name, hypothesis, signal_logic, params, rationale. No prose."
        )
        raw = self._call(prompt)
        candidate = _extract_json_array(raw)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as e:
            # The raw LLM text is logged at DEBUG only - surfacing it through
            # ValueError can leak prompt-injected content into upstream logs
            # or user-facing error pages. We additionally sanitise to ASCII so
            # an attacker cannot smuggle log-shaping control characters or
            # zero-width unicode into structured logging pipelines.
            sanitized = raw[:200].encode("ascii", "replace").decode("ascii", "replace")
            log.debug(
                "propose_ideas: LLM JSON decode failed; raw output (sanitized, truncated): %r",
                sanitized,
            )
            raise ValueError(
                "propose_ideas: LLM did not return valid JSON."
            ) from e
        if not isinstance(data, list):
            raise ValueError(
                f"propose_ideas: expected a JSON list, got {type(data).__name__}."
            )
        return data

    def draft_strategy(self, idea: dict) -> str:
        """Return Python source implementing the idea.

        Validated through an AST walk that rejects any imports outside
        :data:`_ALLOWED_IMPORTS`, references to ``exec`` / ``eval`` /
        ``__import__``, dunder attribute access, and similar
        sandbox-escape vectors.
        """
        prompt = (
            "Implement the following strategy idea as a complete Python module "
            "containing a Strategy subclass. Follow the QuantForge conventions "
            "described in the system prompt exactly. Output ONLY Python source.\n\n"
            f"Idea (JSON):\n{json.dumps(idea, indent=2)}"
        )
        raw = self._call(prompt)
        code = _strip_code_fences(raw)
        # Raises ValueError with a precise reason on any rule violation.
        _validate_drafted_code_ast(code)
        return code

    def critique_strategy(self, code: str, results: dict) -> str:
        """Return a critique of the strategy code given backtest results."""
        prompt = (
            "Critique the following strategy code in light of the backtest "
            "results. Identify weaknesses (lookahead risk, overfitting, "
            "instability, cost sensitivity), then propose concrete, testable "
            "improvements. Be concise and specific.\n\n"
            f"Strategy code:\n```python\n{code}\n```\n\n"
            f"Backtest results (JSON):\n{json.dumps(results, indent=2)}"
        )
        return self._call(prompt)

    def summarize_research_log(self, path: str, max_words: int = 300) -> str:
        """Summarize a research log file into at most `max_words` words."""
        content = self.read_research_log(path)
        prompt = (
            f"Summarize the following QuantForge research log in at most "
            f"{max_words} words. Focus on hypotheses tested, what worked, "
            "what failed, and open questions.\n\n"
            f"Log:\n{content}"
        )
        summary = self._call(prompt)
        words = summary.split()
        if len(words) > max_words:
            summary = " ".join(words[:max_words])
        return summary
