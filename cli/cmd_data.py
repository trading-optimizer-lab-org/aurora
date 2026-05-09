"""``forge data`` subcommand group (R49 split).

DataProviderRegistry CLI surface (P0.B): list-providers, fetch, verify.
"""
from __future__ import annotations

from ._shared import _runtime_error


# ---------------------------------------------------------------------------
# data subcommands (P0.B DataProviderRegistry)
# ---------------------------------------------------------------------------


def cmd_data_list_providers(args):
    """Print the registered data providers + their PIT/tier posture."""
    from aurora.core.data_providers import get_default_registry
    registry = get_default_registry()
    rows = registry.describe()
    if not rows:
        print("(no providers registered)")
        return 0
    name_w = max(len(r["name"]) for r in rows)
    ver_w = max(len(str(r["version"])) for r in rows)
    print(
        f"{'NAME':<{name_w}}  "
        f"{'VERSION':<{ver_w}}  "
        f"{'PIT':<5}  TIER_PERMISSION  SUPPORTED_TIERS"
    )
    for r in rows:
        pit = "yes" if r["point_in_time"] else "no"
        print(
            f"{r['name']:<{name_w}}  "
            f"{str(r['version']):<{ver_w}}  "
            f"{pit:<5}  {r['tier_permission']:<15}  "
            f"{','.join(r['supported_tiers'])}"
        )
    return 0


def cmd_data_fetch(args):
    """Fetch a Dataset from a provider and write parquet + sidecar."""
    import json
    import os
    from aurora.core.data_providers import get_default_registry
    registry = get_default_registry()
    try:
        ds = registry.fetch(
            args.provider, args.symbol, start=args.start, end=args.end,
        )
    except Exception as exc:
        return _runtime_error(f"data fetch: {exc}")
    out = args.output
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    raw = ds.data
    try:
        import pandas as pd
        if isinstance(raw, pd.Series):
            raw.to_frame(raw.name or "value").to_parquet(out)
        else:
            raw.to_parquet(out)
    except Exception as exc:
        return _runtime_error(f"data fetch: parquet write failed: {exc}")
    sidecar_path = out + ".meta.json"
    meta_payload = {
        "name": ds.metadata.name,
        "source": ds.metadata.source,
        "source_version": ds.metadata.source_version,
        "asof_date": ds.metadata.asof_date.isoformat(),
        "point_in_time": ds.metadata.point_in_time,
        "content_hash": ds.metadata.content_hash,
        "tier_permission": ds.metadata.tier_permission,
        "schema_version": ds.metadata.schema_version,
        "extra": ds.metadata.extra,
    }
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(meta_payload, f, indent=2, default=str)
    print(f"Wrote {out} ({len(raw)} rows)")
    print(f"Sidecar metadata: {sidecar_path}")
    print(f"  content_hash: {ds.metadata.content_hash}")
    print(f"  asof_date:    {ds.metadata.asof_date.isoformat()}")
    print(f"  point_in_time:{ds.metadata.point_in_time}")
    print(f"  tier_permission:{ds.metadata.tier_permission}")
    return 0


def cmd_data_verify(args):
    """Recompute content_hash and check tier permission of a fetched parquet."""
    import json
    import os
    parquet = args.parquet
    sidecar = parquet + ".meta.json"
    if not os.path.exists(parquet):
        return _runtime_error(f"data verify: file not found: {parquet}")
    if not os.path.exists(sidecar):
        return _runtime_error(f"data verify: sidecar not found: {sidecar}")
    try:
        with open(sidecar, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception as exc:
        return _runtime_error(f"data verify: sidecar read failed: {exc}")

    import pandas as pd
    df = pd.read_parquet(parquet)
    from aurora.core.data_providers import compute_content_hash
    if df.shape[1] == 1:
        recomputed = compute_content_hash(df.iloc[:, 0])
    else:
        recomputed = compute_content_hash(df)
    expected = meta.get("content_hash")
    print(f"file:           {parquet}")
    print(f"expected hash:  {expected}")
    print(f"recomputed hash:{recomputed}")
    if recomputed != expected:
        print("VERIFY: FAIL (content_hash mismatch -- file tampered)")
        return 1
    print("VERIFY: PASS (content_hash matches)")
    print(f"tier_permission: {meta.get('tier_permission')}")
    print(f"point_in_time:   {meta.get('point_in_time')}")
    return 0


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None) -> None:
    """Register the ``data`` subcommand group on the top-level subparsers."""
    p_data = subparsers.add_parser(
        "data",
        help="Data provider registry (list-providers, fetch, verify)",
        description=(
            "Manage the DataProviderRegistry: list registered providers, "
            "fetch a dataset to parquet (with sidecar metadata), or "
            "verify the content_hash of a previously-fetched file."
        ),
    )
    data_sub = p_data.add_subparsers(dest="data_cmd", required=True)

    p_data_ls = data_sub.add_parser(
        "list-providers",
        help="List registered providers and their PIT/tier posture",
    )
    p_data_ls.set_defaults(func=cmd_data_list_providers)

    p_data_fetch = data_sub.add_parser(
        "fetch", help="Fetch a Dataset and write parquet + sidecar metadata",
    )
    p_data_fetch.add_argument("provider", help="Registered provider name")
    p_data_fetch.add_argument("symbol", help="Ticker symbol")
    p_data_fetch.add_argument("--start", default=None, help="ISO start date")
    p_data_fetch.add_argument("--end", default=None, help="ISO end date")
    p_data_fetch.add_argument(
        "--output", required=True,
        help="Path to write the parquet file (sidecar gets .meta.json suffix)",
    )
    p_data_fetch.set_defaults(func=cmd_data_fetch)

    p_data_verify = data_sub.add_parser(
        "verify", help="Recompute content_hash and check tier permission",
    )
    p_data_verify.add_argument("parquet", help="Path to a parquet emitted by ``data fetch``")
    p_data_verify.set_defaults(func=cmd_data_verify)
