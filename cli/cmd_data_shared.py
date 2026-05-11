"""Shared helpers for the ``aurora.cli.cmd_data`` package.

Output formatters, factory resolvers, gate-error helper, and the
R155/R156 role partition used by ``provider-status``. All members are
package-private (single underscore prefix); consumers should not depend
on them outside the ``cmd_data`` package.
"""
from __future__ import annotations

import json
import os
import sys


# ---------------------------------------------------------------------------
# Role partitioning for provider-status (R155 baseline vs R156 complementary)
# ---------------------------------------------------------------------------

# R155 free-bulk daily-data programme roles. provider-status without
# --include-complementary lists only these (back-compat with the R155
# operator UX).
_R155_ROLE_VALUES = (
    "UNIVERSE",
    "PRICE_PRIMARY",
    "PRICE_FALLBACK",
    "CRYPTO_PRIMARY",
    "CRYPTO_METADATA",
    "CRYPTO_MULTI",
    "MACRO",
    "EXPERIMENTAL",
)

# R156 complementary roles. Surfaced by provider-status when the
# --include-complementary flag is passed.
_R156_ROLE_VALUES = (
    "IDENTITY_MAPPING",
    "FUNDAMENTALS",
    "MACRO_MULTI_SOURCE",
    "CRYPTO_METRICS",
    "FX_REFERENCE",
    "OPTIONAL_PRICE_FALLBACK",
)


def _print_table(rows, headers):
    """Pretty-print a list of dict rows as a fixed-width table.

    Used by R156 fetch / search / status subcommands when ``--output``
    is left at the default ``table`` value.
    """
    if not rows:
        print("(no rows)")
        return
    widths = {h: max(len(h), max(len(str(r.get(h, ""))) for r in rows)) for h in headers}
    print("  ".join(f"{h:<{widths[h]}}" for h in headers))
    for r in rows:
        print("  ".join(f"{str(r.get(h, '')):<{widths[h]}}" for h in headers))


def _emit_json_or_table(args, rows, *, headers):
    """Emit ``rows`` as JSON or a fixed-width table based on ``args.output``.

    ``args.output`` is one of ``json`` / ``table`` (default ``table``).
    """
    fmt = getattr(args, "output", "table") or "table"
    if fmt == "json":
        print(json.dumps(rows, indent=2, default=str))
    else:
        _print_table(rows, headers)


def _gate_error(message: str) -> int:
    """Print a provider-gate hint to stderr and return exit code 1.

    Used by R156 subcommands when a client raises ``RuntimeError`` /
    ``ProviderUnavailable`` because credentials or HTTP transport are
    not configured. Prints the gate's operator-facing message verbatim;
    no traceback.
    """
    print(f"forge: {message}", file=sys.stderr)
    return 1


def _resolve_factory_callable(env_name: str):
    """Look up a ``module:attr`` factory in the env and call it.

    The factory must be a zero-arg callable that returns the http
    transport. We only ever consult env vars to keep tests hermetic;
    no live network is opened by the CLI itself.
    """
    spec = os.environ.get(env_name, "").strip()
    if not spec:
        return None
    if ":" not in spec:
        raise RuntimeError(
            f"{env_name}={spec!r} must be of the form 'module:callable'"
        )
    module_name, attr = spec.split(":", 1)
    import importlib
    mod = importlib.import_module(module_name)
    factory = getattr(mod, attr)
    return factory()


def _resolve_http_post_for_openfigi():
    """Return an http_post callable for OpenFIGI.

    Tests inject a mock via ``AU_OPENFIGI_HTTP_POST_FACTORY`` (an
    importable ``module:attr`` reference yielding a callable); the
    production path returns ``None`` so the client raises its
    documented gate ``RuntimeError`` and the CLI surfaces the operator
    hint to stderr.
    """
    return _resolve_factory_callable("AU_OPENFIGI_HTTP_POST_FACTORY")


def _resolve_http_get_for(env_name: str):
    """Return an http_get callable resolved via ``env_name``.

    Same shape as :func:`_resolve_http_post_for_openfigi`. When the env
    var is unset, returns ``None`` so the underlying client raises its
    own gate error (which the CLI surfaces verbatim).
    """
    return _resolve_factory_callable(env_name)


def _resolve_first_dataset_http_clients_factory():
    """Resolve an injected ``http_clients`` mapping for first-dataset.

    Tests register a zero-arg factory under
    ``AU_FIRST_DATASET_HTTP_CLIENTS_FACTORY`` (form ``module:attr``).
    The factory returns a ``Mapping[str, Callable]`` mapping provider
    names to deterministic stubs. Production runs leave the env var
    unset and rely on operator-supplied transports passed via the
    public Python API; the CLI itself never opens the network.
    """
    return _resolve_factory_callable("AU_FIRST_DATASET_HTTP_CLIENTS_FACTORY")
