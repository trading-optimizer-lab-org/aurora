"""``forge research`` subcommand group (R49 split).

P1.C: ResearchFactory pipeline (hypothesis -> review queue).

Note: the trailing ``research triage`` subparser is registered by
``cmd_triage.register_research_triage`` because it must appear after
the top-level ``triage`` group has been constructed -- mirroring the
order ``build_parser`` used before the split.
"""
from __future__ import annotations

from ._shared import (
    _runtime_error,
    _strategy_spec_from_yaml,
    _strategy_specs_from_yaml,
)


def _resolve_load_research_factory():
    """Return ``forge._load_research_factory`` so monkeypatching works.

    Tests in :mod:`tests.test_research_factory` do
    ``monkeypatch.setattr(forge, "_load_research_factory", fake)`` and
    expect the patched function to be picked up by the CLI commands.
    Calling ``forge._load_research_factory(args)`` at runtime keeps that
    contract intact across the R49 module split.
    """
    from . import forge as _forge_mod
    return _forge_mod._load_research_factory


# ---------------------------------------------------------------------------
# Research Factory subcommands (P1.C)
# ---------------------------------------------------------------------------


def _load_research_factory(args, *, with_data_loader=True):
    """Construct a :class:`ResearchFactory` for CLI commands.

    Loads the factory config from ``args.config_path`` (default
    ``quantforge/config/research_factory.yaml``), resolves the active
    :class:`ProtocolPolicy`, and wires in an
    :class:`~quantforge.registry.experiments.ExperimentTracker`. A noop
    auditor is left as None -- the auditor (P1.B) is a separate concern.
    """
    import os
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.registry.experiments import ExperimentTracker
    from aurora.research.factory import (
        ResearchFactory, ResearchPipelineConfig,
    )

    # Resolve config: explicit --config-path > bundled default.
    cfg_path = getattr(args, "config_path", None)
    if cfg_path and os.path.exists(cfg_path):
        cfg = ResearchPipelineConfig.from_yaml(cfg_path)
    else:
        # Bundled default location: quantforge/config/research_factory.yaml
        here = os.path.dirname(os.path.abspath(__file__))
        bundled = os.path.normpath(
            os.path.join(here, "..", "config", "research_factory.yaml")
        )
        if os.path.exists(bundled):
            cfg = ResearchPipelineConfig.from_yaml(bundled)
        else:
            cfg = ResearchPipelineConfig()

    pol = ProtocolPolicy.load()
    registry = ExperimentTracker()
    kwargs: dict = {}
    if not with_data_loader:
        # Used by tests / promote-flow to avoid the OOS_DEV cap that the
        # default loader applies. Promote is handled in cmd_research_promote
        # itself; the factory still hard-blocks any callers above OOS_DEV.
        pass
    return ResearchFactory(cfg, pol, registry, **kwargs)


def cmd_research_submit(args):
    """Submit a single :class:`StrategySpec` (YAML/JSON) to the factory."""
    factory = _resolve_load_research_factory()(args)
    spec = _strategy_spec_from_yaml(args.spec_path)
    outcome = factory.submit(spec)
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(outcome.candidate.to_dict(), default=str, indent=2))
    else:
        print(outcome.summary)
    return 0 if outcome.promising else 1


def cmd_research_batch(args):
    """Submit a batch of specs from a YAML/JSON file with a 'specs' list."""
    factory = _resolve_load_research_factory()(args)
    specs = _strategy_specs_from_yaml(args.specs_path)
    outcomes = factory.submit_batch(specs)
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(
            [o.candidate.to_dict() for o in outcomes],
            default=str, indent=2,
        ))
    else:
        for o in outcomes:
            print(o.summary)
    return 0 if all(o.promising for o in outcomes) else 1


def cmd_research_review_queue(args):
    """List pending review-queue candidates."""
    factory = _resolve_load_research_factory()(args)
    items = factory.list_review_queue()
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(
            [c.to_dict() for c in items], default=str, indent=2,
        ))
        return 0
    if not items:
        print("(review queue empty)")
        return 0
    for c in items:
        print(
            f"{c.candidate_id} {c.spec.name} "
            f"is_sharpe={(c.is_metrics or {}).get('sharpe', '?')} "
            f"oos_sharpe={(c.oos_dev_metrics or {}).get('sharpe', '?')}"
        )
    return 0


def cmd_research_archive(args):
    """List archived candidates with optional --reason filter."""
    factory = _resolve_load_research_factory()(args)
    items = factory.list_archived()
    reason = getattr(args, "reason", None)
    if reason:
        items = [
            c for c in items
            if c.rejection is not None and c.rejection.value == reason
        ]
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(
            [c.to_dict() for c in items], default=str, indent=2,
        ))
        return 0
    if not items:
        print("(archive empty)")
        return 0
    for c in items:
        rej = c.rejection.value if c.rejection else "?"
        detail = (c.rejection_detail or "")[:80]
        print(
            f"{c.candidate_id} {c.spec.name} reason={rej} "
            f"stage={c.stage.value} detail={detail!r}"
        )
    return 0


def cmd_research_lineage(args):
    """Print the lineage chain root -> spec_id and optionally write DOT."""
    factory = _resolve_load_research_factory()(args)
    chain = factory.get_lineage(args.spec_id)
    for c in chain:
        parent = c.spec.parent_spec_id or "-"
        print(
            f"{c.spec.spec_id} {c.spec.name} stage={c.stage.value} "
            f"parent={parent}"
        )
    if getattr(args, "graphviz", None):
        # Build a graph from EVERY known candidate (review + archive) so
        # the DOT shows the full DAG, not just the chain.
        from aurora.research.factory import LineageGraph
        graph = LineageGraph()
        graph.build(factory.list_review_queue())
        graph.build(factory.list_archived())
        with open(args.graphviz, "w", encoding="utf-8") as f:
            f.write(graph.dot_export())
        print(f"# wrote DOT graph to {args.graphviz}")
    return 0


def cmd_research_generate(args):
    """Bulk-generate strategy specs from a generator and write to a YAML file."""
    import yaml
    from aurora.research.factory import (
        StrategySpec,  # noqa: F401  (re-exported for parity)
        TemplateHypothesisGenerator,
    )
    gen_name = (args.generator or "template").lower()
    n = int(args.n)
    seed = int(args.seed)
    if gen_name == "template":
        # Use a small built-in template list. Real users override via a
        # custom generator in code; the CLI surface is just the demo path.
        templates = [
            (
                "macross_20_100",
                "aurora.strategies.library.ma_cross.MACross",
                {"fast": 20, "slow": 100, "allow_short": False},
                {"fast": (0.5, 1.5), "slow": (0.8, 1.5)},
            ),
            (
                "tsmom_60",
                "aurora.strategies.library.tsmom.TSMomentum",
                {"lookback": 60, "skip": 0},
                {"lookback": (0.5, 2.0)},
            ),
        ]
        gen = TemplateHypothesisGenerator(
            templates, universe=args.universe.split(","),
            rebalance=args.rebalance,
        )
    else:
        return _runtime_error(
            f"generator {gen_name!r} not supported by `forge research generate`. "
            "Implement a custom generator in code and call ResearchFactory.submit_batch."
        )
    specs = gen.generate(n=n, seed=seed)
    payload = {"specs": [s.to_dict() for s in specs]}
    with open(args.output, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False)
    print(f"wrote {len(specs)} specs to {args.output}")
    return 0


def cmd_research_promote(args):
    """Promote a review-queue candidate to OOS_LOCKED testing.

    Hard-gated by:
      1. ``--i-understand-promote-to-oos-locked`` flag (CLI ceremony).
      2. an active :class:`OOSGuard` whose phase is
         ``"explicit_unlock_oos_locked"``.

    The actual lockbox-aware validation is delegated to ``forge validate
    --tier oos_locked``; this command's job is to *enter* the lockbox
    ceremony in a controlled way and emit the relevant invocation.
    """
    if not getattr(args, "i_understand", False):
        return _runtime_error(
            "research promote requires --i-understand-promote-to-oos-locked. "
            "OOS_LOCKED is the protocol's single-look ceremony."
        )
    from aurora.core.data_layer import OOSGuard
    factory = _resolve_load_research_factory()(args)
    candidates = factory.list_review_queue()
    match = next(
        (c for c in candidates if c.candidate_id == args.candidate_id),
        None,
    )
    if match is None:
        return _runtime_error(
            f"candidate_id {args.candidate_id!r} not found in review queue."
        )
    active = OOSGuard.active()
    if active is None or active.phase != "explicit_unlock_oos_locked":
        return _runtime_error(
            "research promote requires an active "
            "OOSGuard('explicit_unlock_oos_locked'); none found. "
            "Wrap the call in `with OOSGuard(\"explicit_unlock_oos_locked\"):` "
            "and re-run, or use the lockbox CI workflow."
        )
    # The promotion itself is a controlled handoff: log the candidate's
    # spec_hash + auditor_report_hash to the OOSGuard's authorized_reads
    # trail, then exit 0. The actual OOS_LOCKED validation is invoked
    # separately by `forge validate --tier oos_locked`.
    active.record_oos_read(
        f"research_promote candidate_id={match.candidate_id} "
        f"spec_hash={match.spec.spec_hash[:12]} "
        f"auditor_hash={(match.auditor_report_hash or 'none')[:12]}"
    )
    print(
        f"PROMOTED {match.candidate_id} ({match.spec.name}) into OOS_LOCKED "
        f"ceremony. Run:\n"
        f"  forge validate --strategy {match.spec.strategy_class.rsplit('.', 1)[-1]} "
        f"--asset {match.spec.universe[0] if match.spec.universe else 'SPY'} "
        f"--tier oos_locked --i-understand-ceremony"
    )
    return 0


# ---------------------------------------------------------------------------
# Atlas subcommands (R173)
# ---------------------------------------------------------------------------


def _resolve_atlas():
    """Return a freshly seeded :class:`StrategyAtlas` for CLI commands.

    Indirection allows tests to monkeypatch the loader without rewriting
    the whole CLI module.
    """
    from aurora.research._atlas_seed import load_seed_atlas
    return load_seed_atlas()


def _resolve_idea_registry():
    """Return a freshly seeded :class:`IdeaSourceRegistry`."""
    from aurora.research.idea_sources import load_seed_sources
    return load_seed_sources()


def cmd_research_atlas_list(args):
    """List atlas entries, optionally filtered by status."""
    atlas = _resolve_atlas()
    status_filter = getattr(args, "status", None)
    entries = atlas.all_entries()
    if status_filter:
        from aurora.research.strategy_atlas import AtlasStatus
        try:
            wanted = AtlasStatus(status_filter)
        except ValueError:
            return _runtime_error(
                f"unknown atlas status {status_filter!r}; valid values: "
                f"{sorted(s.value for s in AtlasStatus)}"
            )
        entries = [e for e in entries if e.status is wanted]
    if getattr(args, "json", False):
        import json as _json
        payload = [
            {
                "name": e.name,
                "asset_class": e.asset_class,
                "status": e.status.value,
                "owner": e.owner,
                "benchmark_expectation": e.benchmark_expectation,
            }
            for e in entries
        ]
        print(_json.dumps(payload, indent=2))
        return 0
    if not entries:
        print("(atlas empty)")
        return 0
    for e in entries:
        print(
            f"{e.status.value:20s} {e.asset_class:14s} "
            f"{e.name}"
        )
    return 0


def cmd_research_atlas_show(args):
    """Show full details for one atlas entry."""
    atlas = _resolve_atlas()
    name = args.name
    if not atlas.has(name):
        return _runtime_error(f"atlas entry {name!r} not found")
    entry = atlas.get(name)
    if getattr(args, "json", False):
        import json as _json
        payload = {
            "name": entry.name,
            "asset_class": entry.asset_class,
            "data_requirements": list(entry.data_requirements),
            "required_engine_capabilities": list(
                entry.required_engine_capabilities
            ),
            "cost_sensitivity": entry.cost_sensitivity,
            "overfit_risk": entry.overfit_risk,
            "implementation_difficulty": entry.implementation_difficulty,
            "validation_gates": list(entry.validation_gates),
            "benchmark_expectation": entry.benchmark_expectation,
            "status": entry.status.value,
            "owner": entry.owner,
            "notes": entry.notes,
        }
        print(_json.dumps(payload, indent=2))
        return 0
    print(f"name:                      {entry.name}")
    print(f"asset_class:               {entry.asset_class}")
    print(f"status:                    {entry.status.value}")
    print(f"owner:                     {entry.owner}")
    print(f"data_requirements:         {', '.join(entry.data_requirements)}")
    print(
        "required_engine_capabilities: "
        f"{', '.join(entry.required_engine_capabilities)}"
    )
    print(f"cost_sensitivity:          {entry.cost_sensitivity}")
    print(f"overfit_risk:              {entry.overfit_risk}")
    print(f"implementation_difficulty: {entry.implementation_difficulty}")
    print(f"validation_gates:          {', '.join(entry.validation_gates)}")
    print(f"benchmark_expectation:     {entry.benchmark_expectation}")
    if entry.notes:
        print(f"notes:                     {entry.notes}")
    return 0


def cmd_research_atlas_classify(args):
    """Print counts of atlas entries grouped by status."""
    atlas = _resolve_atlas()
    from aurora.research.strategy_atlas import AtlasStatus
    counts: dict[str, int] = {s.value: 0 for s in AtlasStatus}
    for e in atlas.all_entries():
        counts[e.status.value] += 1
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(counts, indent=2))
        return 0
    print(f"total entries: {len(atlas)}")
    for status_value, count in counts.items():
        print(f"  {status_value:20s} {count}")
    return 0


def cmd_research_atlas_link_source(args):
    """Print metadata for an idea source (no atlas mutation).

    Source claims are metadata only -- this command does *not* change
    any atlas entry's status. It exists so a researcher can quickly
    cross-reference an upstream paper / blog when proposing an entry.
    """
    registry = _resolve_idea_registry()
    name = args.source_name
    if not registry.has(name):
        return _runtime_error(
            f"idea source {name!r} not found; available: "
            f"{[s.name for s in registry.all_sources()]}"
        )
    source = registry.get(name)
    if getattr(args, "json", False):
        import json as _json
        payload = {
            "name": source.name,
            "url": source.url,
            "claim": source.claim,
            "asset_class": source.asset_class,
            "data_needs": list(source.data_needs),
            "assumptions": list(source.assumptions),
            "testability_score": source.testability_score,
            "confidence": source.confidence,
        }
        print(_json.dumps(payload, indent=2))
        return 0
    print(f"name:              {source.name}")
    print(f"url:               {source.url}")
    print(f"asset_class:       {source.asset_class}")
    print(f"testability_score: {source.testability_score:.2f}")
    print(f"confidence:        {source.confidence:.2f}")
    print(f"claim:             {source.claim}")
    print(f"data_needs:        {', '.join(source.data_needs)}")
    print(f"assumptions:       {', '.join(source.assumptions)}")
    print(
        "note: source claims are metadata only; they do not promote any "
        "atlas entry"
    )
    return 0


# ---------------------------------------------------------------------------
# Papers subcommands (R174)
# ---------------------------------------------------------------------------


def _resolve_papers_registry_path(args) -> "Path":
    """Return the JSONL path used by ``research papers`` commands.

    The path is taken from ``--registry-path`` if provided, otherwise
    from ``AU_PAPERS_REGISTRY`` (or the legacy ``QF_PAPERS_REGISTRY``),
    otherwise ``$AU_DATA_DIR/papers.jsonl``.
    """
    import os
    from pathlib import Path
    explicit = getattr(args, "registry_path", None)
    if explicit:
        return Path(explicit)
    env = (
        os.environ.get("AU_PAPERS_REGISTRY")
        or os.environ.get("QF_PAPERS_REGISTRY")
    )
    if env:
        return Path(env)
    try:
        from aurora.core.runtime_paths import data_dir
        base = data_dir()
    except Exception:  # pragma: no cover - defensive
        base = Path(".")
    return Path(base) / "papers.jsonl"


def cmd_research_papers_ingest(args):
    """Ingest a local PDF or .txt fixture and append to the registry."""
    from pathlib import Path

    from aurora.research.literature import (
        PaperRegistry,
        ingest_pdf,
        ingest_text_fixture,
    )

    src = Path(args.path)
    if not src.exists():
        return _runtime_error(f"papers ingest: file not found: {src}")
    suffix = src.suffix.lower()
    if suffix == ".pdf":
        record, _text = ingest_pdf(src)
    elif suffix == ".txt":
        record, _text = ingest_text_fixture(src)
    else:
        return _runtime_error(
            f"papers ingest: unsupported extension {suffix!r}; "
            "expected .pdf or .txt"
        )

    registry_path = _resolve_papers_registry_path(args)
    registry = PaperRegistry.load(registry_path)
    if registry.has(record.paper_id):
        if getattr(args, "json", False):
            import json as _json
            print(_json.dumps(record.to_dict(), indent=2))
        else:
            print(
                f"papers ingest: paper {record.paper_id} already registered "
                f"(content hash {record.content_hash[:12]})"
            )
        return 0
    registry.register(record)
    registry.save(registry_path)
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(record.to_dict(), indent=2))
    else:
        print(
            f"papers ingest: registered {record.paper_id} "
            f"({record.title!r}) hash={record.content_hash[:12]} "
            f"status={record.extraction_status}"
        )
    return 0


def cmd_research_papers_list(args):
    """List registered papers."""
    from aurora.research.literature import PaperRegistry

    registry_path = _resolve_papers_registry_path(args)
    registry = PaperRegistry.load(registry_path)
    papers = registry.list_papers()
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps([r.to_dict() for r in papers], indent=2))
        return 0
    if not papers:
        print("(papers registry empty)")
        return 0
    for r in papers:
        print(
            f"{r.paper_id}  {r.extraction_status:18s}  "
            f"{r.year}  {r.title}"
        )
    return 0


def cmd_research_papers_claims(args):
    """Print structured claims for one paper."""
    from pathlib import Path

    from aurora.research.literature import (
        PaperRegistry,
        extract_claims_from_text,
        ingest_pdf,
        ingest_text_fixture,
    )

    registry_path = _resolve_papers_registry_path(args)
    registry = PaperRegistry.load(registry_path)
    if not registry.has(args.paper_id):
        return _runtime_error(
            f"papers claims: paper {args.paper_id!r} not registered"
        )
    record = registry.get(args.paper_id)
    src = Path(record.url_or_path)
    if not src.exists():
        return _runtime_error(
            f"papers claims: source file no longer present: {src}"
        )
    suffix = src.suffix.lower()
    if suffix == ".pdf":
        _record_again, text = ingest_pdf(src)
    elif suffix == ".txt":
        _record_again, text = ingest_text_fixture(src)
    else:
        return _runtime_error(
            f"papers claims: unsupported extension {suffix!r}"
        )

    claims = extract_claims_from_text(record, text)
    if getattr(args, "json", False):
        import json as _json
        payload = [
            {
                "claim_id": c.claim_id,
                "paper_id": c.paper_id,
                "claim_text": c.claim_text,
                "asset_class": c.asset_class,
                "sample_period": c.sample_period,
                "universe": c.universe,
                "data_frequency": c.data_frequency,
                "reported_metrics": c.reported_metrics,
                "transaction_costs_included": c.transaction_costs_included,
                "oos_included": c.oos_included,
                "assumptions": list(c.assumptions),
                "limitations": list(c.limitations),
                "replication_requirements": list(c.replication_requirements),
                "red_flags": list(c.red_flags),
                "page_reference": c.page_reference,
                "quote_excerpt": c.quote_excerpt,
            }
            for c in claims
        ]
        print(_json.dumps(payload, indent=2))
        return 0
    if not claims:
        print(f"(no claims extracted from {record.paper_id})")
        return 0
    for c in claims:
        print(
            f"{c.claim_id} asset={c.asset_class} freq={c.data_frequency} "
            f"oos={c.oos_included} costs={c.transaction_costs_included} "
            f"red_flags={list(c.red_flags)}"
        )
        if c.page_reference:
            print(f"  ref: {c.page_reference}")
        print(f"  quote: {c.quote_excerpt[:140]}")
    return 0


def cmd_research_triage(args):
    """Run triage as a screening pass on a research specs file."""
    from dataclasses import replace as _replace
    from aurora.core.protocol_policy import ProtocolPolicy
    from aurora.triage import StrategyVariant, TriageEngine

    from ._shared import _load_triage_config, _load_triage_prices

    cfg = _load_triage_config(args)
    threshold = getattr(args, "threshold", None)
    if threshold:
        for kv in str(threshold).split(","):
            if "=" in kv:
                k, _, v = kv.partition("=")
                k = k.strip()
                if k == "sharpe":
                    cfg = _replace(cfg, min_sharpe_threshold=float(v))
                elif k == "max_dd":
                    cfg = _replace(cfg, max_dd_threshold=float(v))
                elif k == "min_trades":
                    cfg = _replace(cfg, min_trades=int(v))
    policy = ProtocolPolicy.load()
    engine = TriageEngine(cfg, policy)
    specs = _strategy_specs_from_yaml(args.specs)
    if not specs:
        return _runtime_error("specs file produced zero specs")
    variants = [
        StrategyVariant.make(
            strategy_class=s.strategy_class,
            params=s.params,
            universe=s.universe,
            rebalance=s.rebalance,
        )
        for s in specs
    ]
    sym = specs[0].universe[0] if specs[0].universe else "SPY"
    prices = _load_triage_prices(sym, cfg.triage_tier_only)
    batch = engine.triage_batch(prices, variants)
    print(
        f"triage: {batch.n_variants} specs scored, "
        f"{batch.n_promising} promising"
    )
    for r in batch.results:
        flag = "PROMISING" if r.promising else "rejected"
        reason = r.rejection_reason or "-"
        print(
            f"  [{flag:9s}] {r.variant_id[:10]} "
            f"sharpe={r.sharpe:.2f} mdd={r.max_dd:.2f} "
            f"n_trades={r.n_trades} reason={reason}"
        )
    return 0 if batch.n_promising > 0 else 1


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


def register(subparsers, parent_parser=None):
    """Register the ``research`` subcommand group on the top-level subparsers.

    Returns the ``research_sub`` :class:`_SubParsersAction` so the
    dispatcher can let ``cmd_triage`` tack on the trailing ``research
    triage`` parser at the same insertion point as before the split.
    """
    p_research = subparsers.add_parser(
        "research",
        help="Research Factory: submit specs, list review queue / archive, "
             "lineage, generate, promote to OOS_LOCKED",
        description=(
            "P1.C Research Factory. Submit StrategySpec proposals to the "
            "automated IS / WF / OOS_DEV pipeline; failed candidates are "
            "archived with a categorical reason; promising candidates "
            "land in the review queue. Promotion to OOS_LOCKED requires "
            "the lockbox ceremony."
        ),
    )
    research_sub = p_research.add_subparsers(dest="research_cmd", required=True)

    p_rs_submit = research_sub.add_parser(
        "submit", help="Submit one StrategySpec (YAML or JSON) to the factory",
    )
    p_rs_submit.add_argument("spec_path",
                              help="Path to a single-spec YAML/JSON file")
    p_rs_submit.add_argument(
        "--config-path", default=None, dest="config_path",
        help="Optional path to a research_factory.yaml override",
    )
    p_rs_submit.add_argument("--json", action="store_true",
                              help="Print outcome as JSON")
    p_rs_submit.set_defaults(func=cmd_research_submit)

    p_rs_batch = research_sub.add_parser(
        "batch", help="Submit a batch (YAML/JSON with a 'specs' list)",
    )
    p_rs_batch.add_argument("specs_path",
                             help="Path to a YAML/JSON file with 'specs:'")
    p_rs_batch.add_argument(
        "--config-path", default=None, dest="config_path",
        help="Optional path to a research_factory.yaml override",
    )
    p_rs_batch.add_argument("--json", action="store_true",
                             help="Print outcomes as JSON")
    p_rs_batch.set_defaults(func=cmd_research_batch)

    p_rs_review = research_sub.add_parser(
        "review-queue", help="List candidates currently awaiting human review",
    )
    p_rs_review.add_argument("--config-path", default=None, dest="config_path")
    p_rs_review.add_argument("--json", action="store_true")
    p_rs_review.set_defaults(func=cmd_research_review_queue)

    p_rs_arch = research_sub.add_parser(
        "archive", help="List archived (rejected) candidates",
    )
    p_rs_arch.add_argument("--config-path", default=None, dest="config_path")
    p_rs_arch.add_argument(
        "--reason", default=None,
        help="Filter by RejectionReason value "
             "(e.g. spec_invalid, is_sharpe_too_low, wf_degradation, ...)",
    )
    p_rs_arch.add_argument("--json", action="store_true")
    p_rs_arch.set_defaults(func=cmd_research_archive)

    p_rs_lin = research_sub.add_parser(
        "lineage", help="Print lineage chain (root -> spec_id)",
    )
    p_rs_lin.add_argument("spec_id", help="Spec id whose lineage to print")
    p_rs_lin.add_argument("--config-path", default=None, dest="config_path")
    p_rs_lin.add_argument("--graphviz", default=None,
                            help="Optional path to write a DOT graph")
    p_rs_lin.set_defaults(func=cmd_research_lineage)

    p_rs_gen = research_sub.add_parser(
        "generate",
        help="Bulk-generate a YAML 'specs' list from a built-in generator",
    )
    p_rs_gen.add_argument(
        "--generator", default="template",
        help="Generator name. Currently 'template' is supported on the CLI; "
             "ga / llm generators are code-only.",
    )
    p_rs_gen.add_argument("--n", type=int, default=10,
                           help="Number of specs to emit")
    p_rs_gen.add_argument("--seed", type=int, default=42)
    p_rs_gen.add_argument("--universe", default="SPY",
                           help="Comma-separated tickers for the universe")
    p_rs_gen.add_argument("--rebalance", default="1d")
    p_rs_gen.add_argument("--output", required=True,
                           help="Output YAML path (will contain a 'specs:' list)")
    p_rs_gen.set_defaults(func=cmd_research_generate)

    p_rs_prom = research_sub.add_parser(
        "promote",
        help="Promote a review-queue candidate to OOS_LOCKED ceremony",
        description=(
            "Move a candidate from the review queue into the OOS_LOCKED "
            "single-look ceremony. Requires both "
            "--i-understand-promote-to-oos-locked AND an active "
            "OOSGuard('explicit_unlock_oos_locked')."
        ),
    )
    p_rs_prom.add_argument("candidate_id",
                             help="Candidate id from `research review-queue`")
    p_rs_prom.add_argument(
        "--i-understand-promote-to-oos-locked",
        action="store_true", dest="i_understand",
        help="Required acknowledgement that this enters the OOS_LOCKED ceremony.",
    )
    p_rs_prom.add_argument("--config-path", default=None, dest="config_path")
    p_rs_prom.set_defaults(func=cmd_research_promote)

    # ---- atlas (R173) ----------------------------------------------------
    p_rs_atlas = research_sub.add_parser(
        "atlas",
        help="Strategy atlas: list / show / classify entries, link "
             "upstream idea sources",
        description=(
            "Read-only views over the curated strategy atlas. Source "
            "claims are metadata only and do not promote any entry."
        ),
    )
    atlas_sub = p_rs_atlas.add_subparsers(dest="atlas_cmd", required=True)

    p_at_list = atlas_sub.add_parser(
        "list", help="List atlas entries (optionally filtered by status)",
    )
    p_at_list.add_argument(
        "--status", default=None,
        help="Filter by status value (supported, candidate, blocked, "
             "rejected, benchmark_only, external_data_only, "
             "needs_engine_support)",
    )
    p_at_list.add_argument("--json", action="store_true")
    p_at_list.set_defaults(func=cmd_research_atlas_list)

    p_at_show = atlas_sub.add_parser(
        "show", help="Show full details for one atlas entry",
    )
    p_at_show.add_argument("name", help="Atlas entry name")
    p_at_show.add_argument("--json", action="store_true")
    p_at_show.set_defaults(func=cmd_research_atlas_show)

    p_at_class = atlas_sub.add_parser(
        "classify", help="Print counts grouped by status",
    )
    p_at_class.add_argument("--json", action="store_true")
    p_at_class.set_defaults(func=cmd_research_atlas_classify)

    p_at_link = atlas_sub.add_parser(
        "link-source",
        help="Print metadata for an idea source (no atlas mutation)",
    )
    p_at_link.add_argument(
        "source_name",
        help="Name of an idea source from the registry",
    )
    p_at_link.add_argument("--json", action="store_true")
    p_at_link.set_defaults(func=cmd_research_atlas_link_source)

    # ---- papers (R174) ---------------------------------------------------
    p_rs_papers = research_sub.add_parser(
        "papers",
        help="Literature scout: ingest local PDFs / text fixtures, list "
             "papers, print structured claims",
        description=(
            "R174 literature pipeline. Ingests files from disk only "
            "(no web fetch). Paper claims are upstream evidence and "
            "do not promote any atlas entry."
        ),
    )
    papers_sub = p_rs_papers.add_subparsers(dest="papers_cmd", required=True)

    p_pp_ingest = papers_sub.add_parser(
        "ingest", help="Ingest a local PDF or .txt fixture",
    )
    p_pp_ingest.add_argument(
        "path", help="Path to a local .pdf or .txt file",
    )
    p_pp_ingest.add_argument(
        "--registry-path", default=None, dest="registry_path",
        help="Override the JSONL registry path "
             "(default: $AU_DATA_DIR/papers.jsonl)",
    )
    p_pp_ingest.add_argument("--json", action="store_true")
    p_pp_ingest.set_defaults(func=cmd_research_papers_ingest)

    p_pp_list = papers_sub.add_parser(
        "list", help="List registered papers",
    )
    p_pp_list.add_argument(
        "--registry-path", default=None, dest="registry_path",
    )
    p_pp_list.add_argument("--json", action="store_true")
    p_pp_list.set_defaults(func=cmd_research_papers_list)

    p_pp_claims = papers_sub.add_parser(
        "claims", help="Print structured claims for one registered paper",
    )
    p_pp_claims.add_argument(
        "paper_id", help="Paper id from `research papers list`",
    )
    p_pp_claims.add_argument(
        "--registry-path", default=None, dest="registry_path",
    )
    p_pp_claims.add_argument("--json", action="store_true")
    p_pp_claims.set_defaults(func=cmd_research_papers_claims)

    return research_sub
