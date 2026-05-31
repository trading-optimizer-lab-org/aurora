"""Shared helpers used by 2+ ``aurora.cli.cmd_*`` modules (R49 split).

Anything that lives here is an implementation detail of the CLI dispatcher;
no public API stability guarantee.
"""
from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from aurora.core.costs import IBKR_costs, ZERO_costs

if TYPE_CHECKING:
    import pandas as pd  # noqa: F401  -- referenced in `"pd.Series"` annotations


# ---------------------------------------------------------------------------
# Error UX helpers
# ---------------------------------------------------------------------------


class _CLIArgError(SystemExit):
    """Argument error raised inside a command; converted to ``parser.error``
    by ``main`` so argparse prints the usage banner and exits with code 2."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _arg_error(message: str) -> None:
    """Raise a structured argument error.

    ``main`` catches this and routes it through ``parser.error`` so the user
    sees the standard argparse usage banner + exit code 2.
    """
    raise _CLIArgError(message)


def _runtime_error(message: str) -> int:
    """Print a runtime failure to stderr and return exit code 1.

    Use for environment / IO / dependency failures (not argument validation).
    """
    print(f"forge: {message}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------
# Strategy library helpers
# ---------------------------------------------------------------------------


def _strategy_library() -> dict:
    """Build name -> class map from aurora.strategies.library.__all__."""
    from aurora.strategies import library as lib_mod
    return {name: getattr(lib_mod, name) for name in lib_mod.__all__
            if hasattr(lib_mod, name)}


def _resolve_strategy(name: str):
    """Resolve a strategy by name with import fallback.

    Lookup order:
        1. ``aurora.strategies.library.__all__`` map.
        2. Direct import of ``aurora.strategies.library.<name>`` and pick
           a class attribute matching ``name``.
        3. Raise SystemExit listing the known strategies.
    """
    lib = _strategy_library()
    if name in lib:
        return lib[name]

    # Fallback: walk every submodule of ``aurora.strategies.library``
    # looking for a class attribute matching ``name`` exactly. Names like
    # ``MACross`` do not lowercase to a valid module path
    # (``ma_cross.py``), so the previous str.lower() guess silently
    # produced ``ImportError`` and skipped the fallback entirely. Using
    # ``pkgutil.iter_modules`` makes the lookup independent of how the
    # filename is spelled.
    import importlib
    import pkgutil

    from aurora.strategies import library as lib_pkg

    for info in pkgutil.iter_modules(lib_pkg.__path__):
        try:
            mod = importlib.import_module(
                f"{lib_pkg.__name__}.{info.name}"
            )
        except ImportError:
            continue
        cls = getattr(mod, name, None)
        if cls is not None and isinstance(cls, type):
            return cls

    _arg_error(f"Unknown strategy '{name}'. Available: {sorted(lib)}")


def _costs_from(name: str):
    return IBKR_costs if name == "ibkr" else ZERO_costs


# ---------------------------------------------------------------------------
# --tier helper (round-3 audit fix)
# ---------------------------------------------------------------------------
#
# Several CLI commands are post-validation analytics: they want to look
# at recent strategy behaviour, not run a fitness loop. Before round 3
# they all called ``load_asset(include_oos=True)`` on the full cached
# series, which silently included OOS_LOCKED (2021-2024) and FORWARD
# (>=2025) bars even when the user only wanted to inspect the
# protocol-public OOS_DEV slice. The audit asks for an explicit
# ``--tier`` switch so the read is bounded at the source.

# P0.A: valid tier choices come from
# :class:`aurora.core.protocol_policy.ProtocolPolicy`. The legacy
# ``is_all`` and ``full`` synthetic choices are kept (they are not
# protocol tiers themselves -- ``is_all`` is IS_TRAIN+IS_VALID and
# ``full`` is the env-gated all-tier pass-through), but the five
# protocol tier names are sourced from the active policy.
def _policy_tier_choices() -> tuple[str, ...]:
    """Return the lower-cased tier names declared by the active policy."""
    try:
        from aurora.core.protocol_policy import get_active_policy
        names = tuple(t.lower() for t in get_active_policy().tiers.keys())
    except Exception:
        # Defensive: never block the CLI if the policy fails to load.
        names = ("is_train", "is_valid", "oos_dev", "oos_locked", "forward")
    extras = ("is_all", "full")
    return tuple(list(names) + [e for e in extras if e not in names])


_TIER_CHOICES = _policy_tier_choices()

# Default tier for analytical CLI commands. OOS_DEV is the most common
# "look at recent post-validation behaviour" slice.
_DEFAULT_ANALYTICAL_TIER = "oos_dev"


def _policy_ceremony_env_flag(name: str) -> str:
    """Return the env_flag for a named ceremony from the active policy.

    Falls back to ``name`` itself if the policy is unavailable (defensive
    parity with :func:`_policy_tier_choices`).
    """
    try:
        from aurora.core.protocol_policy import get_active_policy
        cer = get_active_policy().oos_ceremonies.get(name)
        if cer is not None:
            return cer.env_flag
    except Exception:
        pass
    return name


def _resolve_tier_load(asset: str, tier: str) -> "pd.Series":
    """Load price series respecting the CLI ``--tier`` semantics.

    Round-3 audit fix: every analytical CLI command (run, tearsheet,
    factor, attribute, label, fracdiff, purge-cv) must route through
    this helper instead of calling
    ``load_asset(include_oos=True, oos_purpose=...)`` directly. The
    helper enforces the ceremony rules:

      * ``is_train`` / ``is_valid``: read only the relevant in-sample
        slice; no OOSGuard required.
      * ``oos_dev`` (default): read up to OOS_DEV_END under
        ``oos_purpose="cli_analysis"`` so the read is logged AND
        persisted to the lock file.
      * ``oos_locked``: requires an active
        ``OOSGuard("explicit_unlock_oos_locked")`` -- the ceremony
        wrap is the user's responsibility (the helper raises if the
        ceremony is missing).
      * ``forward``: requires an active
        ``OOSGuard("explicit_unlock_forward")``.
      * ``is_all``: IS_TRAIN + IS_VALID combined.
      * ``full``: the legacy "everything" pass-through. Requires the
        environment variable ``QF_ALLOW_FULL_TIER=1`` to opt in
        because it leaks every tier into the analyser, including
        OOS_LOCKED and FORWARD.
    """
    import os
    import pandas as pd  # noqa: F401  (used in type hint string)
    from aurora.core.data_layer import load_asset
    from aurora.core.data_tiers import (
        load_tier,
        load_up_to_tier,
    )

    tier_norm = (tier or _DEFAULT_ANALYTICAL_TIER).lower()
    if tier_norm not in _TIER_CHOICES:
        _arg_error(
            f"--tier must be one of {sorted(_TIER_CHOICES)} (got {tier!r})"
        )

    if tier_norm == "full":
        # Ceremony: explicit env var. Without it we refuse the read.
        from aurora.core.env_compat import aurora_env
        if aurora_env("AU_ALLOW_FULL_TIER", "QF_ALLOW_FULL_TIER") != "1":
            _arg_error(
                "--tier full is gated: set AU_ALLOW_FULL_TIER=1 to opt in. "
                "This tier leaks OOS_LOCKED + FORWARD into the analyser."
            )
        # P2.3 round-4 audit: the env var alone is not enough. Require
        # an active OOSGuard("explicit_unlock_full_tier") so the read
        # is auditable in the lock file alongside other ceremony unlocks.
        from aurora.core.data_layer import OOSGuard as _OOSGuard
        active = _OOSGuard.active()
        if active is None or active.phase != "explicit_unlock_full_tier":
            _arg_error(
                "--tier full requires an active "
                "OOSGuard('explicit_unlock_full_tier'); "
                "set QF_ALLOW_FULL_TIER=1 AND wrap the call in the ceremony "
                "context manager."
            )
        return load_asset(
            asset, include_oos=True,
            oos_purpose="cli_analysis_full_tier",
        )

    if tier_norm == "is_all":
        # IS_TRAIN + IS_VALID -- bounded by IS_VALID end (2012-12-31).
        # No OOS read; no guard required.
        return load_up_to_tier(asset, max_tier="IS_VALID")

    # Everything else maps directly to a tier slice.
    tier_upper_map = {
        "is_train": "IS_TRAIN",
        "is_valid": "IS_VALID",
        "oos_dev": "OOS_DEV",
        "oos_locked": "OOS_LOCKED",
        "forward": "FORWARD",
    }
    upper = tier_upper_map[tier_norm]
    # OOS-bearing tiers want an oos_purpose so the lock-file audit fires.
    purpose = (
        "cli_analysis"
        if upper in ("OOS_DEV", "OOS_LOCKED", "FORWARD")
        else None
    )
    return load_tier(asset, tier=upper, oos_purpose=purpose)


def _add_tier_arg(parser, *, default: str = _DEFAULT_ANALYTICAL_TIER) -> None:
    """Attach the standard ``--tier`` argument to an analytical subparser."""
    parser.add_argument(
        "--tier", default=default, choices=list(_TIER_CHOICES),
        help=(
            "Data tier to load (round-3 protocol fix). "
            "Default: oos_dev. "
            "'oos_locked' / 'forward' require an OOSGuard ceremony. "
            "'full' requires QF_ALLOW_FULL_TIER=1 in the environment."
        ),
    )


# ---------------------------------------------------------------------------
# Config loader (Task 1.5)
# ---------------------------------------------------------------------------


_KNOWN_TOP_LEVEL_CONFIG_KEYS = {
    "data", "costs", "validation", "ga", "seed", "log_level",
}


def _validate_config_schema(path) -> None:
    """Reject unknown top-level keys in the YAML/TOML config file.

    Pydantic's default behaviour is to silently drop unknown keys. We want
    early, loud failure on typos like ``cost`` instead of ``costs``.
    """
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        # Caller's loader will raise FileNotFoundError -> SystemExit; let it.
        return
    suffix = p.suffix.lower()
    raw: dict
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as e:
            raise SystemExit(_runtime_error(f"yaml not available to validate {p}: {e}")) from e
        with p.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    elif suffix == ".toml":
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError as e:
                raise SystemExit(_runtime_error(f"tomllib not available to validate {p}: {e}")) from e
        with p.open("rb") as f:
            raw = tomllib.load(f)
    else:
        _arg_error(
            f"Unsupported config extension: {suffix}. Use .yaml/.yml/.toml"
        )

    if not isinstance(raw, dict):
        _arg_error(f"Config root must be a mapping, got {type(raw).__name__}")

    unknown = sorted(set(raw) - _KNOWN_TOP_LEVEL_CONFIG_KEYS)
    if unknown:
        _arg_error(
            f"Config {p} has unknown top-level keys: {unknown}. "
            f"Allowed: {sorted(_KNOWN_TOP_LEVEL_CONFIG_KEYS)}"
        )


def _load_global_config(args):
    """Load ForgeConfig from --config path if provided, else defaults.

    Returns a ForgeConfig. Errors propagate as SystemExit.

    NOTE: at the moment the only subcommands that *act* on the loaded
    ``ForgeConfig`` are ``dry-run`` (via :func:`_dry_run_summary`) and
    ``config show``. The ``run``, ``search`` and ``validate`` subcommands
    still drive themselves from CLI flags and the per-strategy spec, so
    passing ``--config`` to them currently has no effect outside of a dry
    run. Threading ``cfg.validation.*`` and friends into those subcommands
    is tracked separately.
    """
    from aurora.core.config import default_config, load_config
    path = getattr(args, "config", None)
    if not path:
        return default_config()
    _validate_config_schema(path)
    try:
        return load_config(path)
    except FileNotFoundError as e:
        raise SystemExit(_runtime_error(f"Config file not found: {path}")) from e
    except Exception as e:
        raise SystemExit(_runtime_error(f"Failed to load config {path}: {e}")) from e


# ---------------------------------------------------------------------------
# Dry-run helper
# ---------------------------------------------------------------------------


def _dry_run_summary(args, cfg) -> None:
    """Print the resolved configuration that ``run/search/validate`` would use.

    Includes data range, strategy + params, costs profile, and the gate
    parameters relevant to the subcommand. Does not execute anything.
    """
    print("=" * 70)
    print(f"DRY-RUN: {getattr(args, 'cmd', '<cmd>')}")
    print("=" * 70)
    print(f"Strategy : {getattr(args, 'strategy', None)}")
    print(f"Asset    : {getattr(args, 'asset', None)}")
    print(f"Seed     : {getattr(args, 'seed', None)}")
    print(f"Costs    : {getattr(args, 'costs', None)}")
    print(
        "Data IS  : "
        f"{cfg.data.is_start} -> {cfg.data.is_end}"
    )
    print(
        "Data OOS : "
        f"{cfg.data.oos_start} -> {cfg.data.oos_end}"
    )
    if getattr(args, "cmd", None) == "validate":
        print(f"n-trials : {getattr(args, 'n_trials', None)}")
        print(f"mc-paths : {getattr(args, 'mc_paths', None)}")
    if getattr(args, "cmd", None) == "search":
        print(f"population : {getattr(args, 'population', None)}")
        print(f"generations: {getattr(args, 'generations', None)}")
        print(f"skip-oos   : {getattr(args, 'skip_oos', None)}")
        print(f"oos-top    : {getattr(args, 'oos_top', None)}")
    print(
        "Validation thresholds: "
        f"min_wf_pass={cfg.validation.min_wf_pass} "
        f"spp_max_cv={cfg.validation.spp_max_cv} "
        f"min_dsr={cfg.validation.min_dsr}"
    )
    print("=" * 70)


# ---------------------------------------------------------------------------
# Strategy spec helpers (used by research, export, triage)
# ---------------------------------------------------------------------------


def _strategy_spec_from_yaml(path):
    """Parse a YAML / JSON file into a :class:`StrategySpec`."""
    import json
    import os
    import yaml
    from aurora.research.factory import StrategySpec
    if not os.path.exists(path):
        _arg_error(f"spec file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        data = json.loads(text) if text.strip() else {}
    else:
        data = yaml.safe_load(text) or {}
    if "specs" in data and isinstance(data["specs"], list):
        # Caller passed a batch file to a single-submit command -- be loud.
        _arg_error(
            f"spec file {path!r} contains a 'specs' list; "
            "use `forge research batch` for multi-spec submission."
        )
    return StrategySpec.from_dict(data)


def _strategy_specs_from_yaml(path):
    """Parse a YAML / JSON file into a list of :class:`StrategySpec`."""
    import json
    import os
    import yaml
    from aurora.research.factory import StrategySpec
    if not os.path.exists(path):
        _arg_error(f"specs file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        data = json.loads(text) if text.strip() else {}
    else:
        data = yaml.safe_load(text) or {}
    raw_list = data.get("specs") if isinstance(data, dict) else None
    if not isinstance(raw_list, list):
        _arg_error(
            f"specs file {path!r} must have a top-level 'specs' list; "
            "use `forge research submit` for a single spec."
        )
    return [StrategySpec.from_dict(d) for d in raw_list]


# ---------------------------------------------------------------------------
# Triage helpers (used by cmd_triage and cmd_research_triage)
# ---------------------------------------------------------------------------


def _load_triage_config(args):
    """Load TriageConfig from --config-path / args overrides / bundled YAML."""
    import os
    from aurora.triage import TriageConfig

    cfg_path = getattr(args, "config_path", None)
    if cfg_path and os.path.exists(cfg_path):
        cfg = TriageConfig.from_yaml(cfg_path)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        bundled = os.path.normpath(
            os.path.join(here, "..", "config", "triage.yaml")
        )
        if os.path.exists(bundled):
            cfg = TriageConfig.from_yaml(bundled)
        else:
            cfg = TriageConfig()
    if getattr(args, "use_vectorbt", False):
        from dataclasses import replace as _replace
        cfg = _replace(cfg, use_vectorbt=True)
    if getattr(args, "tier", None):
        from dataclasses import replace as _replace
        cfg = _replace(cfg, triage_tier_only=str(args.tier).upper())
    return cfg


def _load_triage_prices(symbol: str, tier: str):
    """Load a price DataFrame for the given symbol on the given tier."""
    from aurora.core.data_tiers import load_tier
    ser = load_tier(symbol, tier=tier.upper())
    return ser.to_frame(name=symbol)


# ---------------------------------------------------------------------------
# Package version helper (used by forge.py dispatcher)
# ---------------------------------------------------------------------------


def _resolve_package_version() -> str:
    """Return the installed aurora package version, or "unknown"."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - py3.7 path; not supported
        return "unknown"
    try:
        return version("aurora")
    except PackageNotFoundError:
        return "unknown"


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--version",
        action="version",
        version=f"aurora {_resolve_package_version()}",
        help="Print the installed aurora version and exit.",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to ForgeConfig YAML/TOML. Defaults to built-in defaults.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logger level for the aurora namespace [default: INFO].",
    )
