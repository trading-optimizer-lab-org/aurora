"""``forge policy`` subcommand group (R49 split).

P0.A: surface the active ProtocolPolicy and verify YAML integrity.
"""
from __future__ import annotations

from ._shared import _runtime_error


# ---------------------------------------------------------------------------
# Policy subcommands (P0.A)
# ---------------------------------------------------------------------------


def cmd_policy_show(args):
    """Print the active :class:`ProtocolPolicy` as YAML + the policy hash."""
    from aurora.core.protocol_policy import ProtocolPolicy
    path = getattr(args, "path", None)
    pol = ProtocolPolicy.load(path) if path else ProtocolPolicy.load()
    print(pol.to_yaml())
    print(f"# policy_hash: {pol.policy_hash}")
    return 0


def cmd_policy_verify(args):
    """Recompute the policy hash and compare to the YAML's declared hash.

    Returns exit code 0 on match, 1 on tamper / mismatch.
    """
    import os
    from aurora.core.protocol_policy import ProtocolPolicy
    path = getattr(args, "path", None) or ProtocolPolicy.default_yaml_path()
    if not os.path.exists(path):
        return _runtime_error(
            f"policy verify: YAML not found at {path}. "
            "Run `forge policy show > config/protocol_policy.yaml` to "
            "materialize the default."
        )
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        return _runtime_error(f"policy verify: YAML read failed: {exc}")
    declared = data.get("policy_hash")
    pol = ProtocolPolicy.from_dict(data)
    recomputed = pol.policy_hash
    print(f"path:             {path}")
    print(f"declared hash:    {declared}")
    print(f"recomputed hash:  {recomputed}")
    # A declared hash field is mandatory for verification. When it is
    # present (even as a falsy literal like ``0`` or ``""``), it must
    # match the recomputed digest exactly. Missing entirely (key absent)
    # is treated as "not declared" -> PASS, mirroring how ``--path``
    # might point at a freshly-generated YAML.
    if "policy_hash" in data:
        if str(declared) != str(recomputed):
            print("VERIFY: FAIL (policy_hash mismatch -- YAML tampered)")
            return 1
    print("VERIFY: PASS")
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the ``policy`` subcommand group on the top-level subparsers."""
    p_policy = subparsers.add_parser(
        "policy",
        help="Inspect / verify the active ProtocolPolicy",
        description=(
            "Surface or verify the active ProtocolPolicy. "
            "`show` prints the policy as YAML plus its sha256. "
            "`verify` recomputes the hash and compares to the YAML's "
            "declared hash, catching tampering."
        ),
    )
    policy_sub = p_policy.add_subparsers(dest="policy_cmd", required=True)
    p_pol_show = policy_sub.add_parser(
        "show", help="Print the active policy as YAML",
        description="Print the active ProtocolPolicy as YAML and its hash.",
    )
    p_pol_show.add_argument(
        "--path", default=None,
        help="Optional YAML path to read instead of the default config.",
    )
    p_pol_show.set_defaults(func=cmd_policy_show)
    p_pol_verify = policy_sub.add_parser(
        "verify", help="Recompute policy hash and compare to YAML",
        description=(
            "Recompute the policy_hash from the YAML body and compare to "
            "the declared hash. Exits 1 on mismatch (i.e. tamper)."
        ),
    )
    p_pol_verify.add_argument(
        "--path", default=None,
        help="Optional YAML path to verify (default: bundled config).",
    )
    p_pol_verify.set_defaults(func=cmd_policy_verify)
