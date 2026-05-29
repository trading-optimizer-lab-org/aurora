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
    from aurora.research.protocol_enforcement import (
        ensure_mandatory_research_protocol,
        make_project_id,
    )

    factory = _resolve_load_research_factory()(args)
    spec = _strategy_spec_from_yaml(args.spec_path)
    ensure_mandatory_research_protocol(
        project_id=getattr(args, "project_id", None)
        or make_project_id("factory", spec.spec_id, spec.name),
        objective=spec.hypothesis or f"Research factory submit: {spec.name}",
        metric="research_factory_promising",
        universe=tuple(spec.universe),
        providers=("research_factory_loader",),
        date_range={"max_tier": "OOS_DEV", "rebalance": spec.rebalance},
        features=(spec.strategy_class,),
        seed=spec.spec_hash[:16],
        candidate_id=spec.spec_id,
        allowed_selection_phases=("is_train", "is_valid", "oos_dev"),
        locked_phases=("oos_locked", "forward"),
        constraints={
            "command": "research submit",
            "spec_hash": spec.spec_hash,
            "generator": spec.generator,
        },
        actor="aurora_cli",
        ledger_path=getattr(args, "protocol_ledger", None),
    )
    outcome = factory.submit(spec)
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(outcome.candidate.to_dict(), default=str, indent=2))
    else:
        print(outcome.summary)
    return 0 if outcome.promising else 1


def cmd_research_batch(args):
    """Submit a batch of specs from a YAML/JSON file with a 'specs' list."""
    from aurora.research.protocol_enforcement import (
        ensure_mandatory_research_protocol,
        make_project_id,
    )

    factory = _resolve_load_research_factory()(args)
    specs = _strategy_specs_from_yaml(args.specs_path)
    for spec in specs:
        ensure_mandatory_research_protocol(
            project_id=make_project_id("factory", spec.spec_id, spec.name),
            objective=spec.hypothesis or f"Research factory batch: {spec.name}",
            metric="research_factory_promising",
            universe=tuple(spec.universe),
            providers=("research_factory_loader",),
            date_range={"max_tier": "OOS_DEV", "rebalance": spec.rebalance},
            features=(spec.strategy_class,),
            seed=spec.spec_hash[:16],
            candidate_id=spec.spec_id,
            allowed_selection_phases=("is_train", "is_valid", "oos_dev"),
            locked_phases=("oos_locked", "forward"),
            constraints={
                "command": "research batch",
                "spec_hash": spec.spec_hash,
                "generator": spec.generator,
            },
            actor="aurora_cli",
            ledger_path=getattr(args, "protocol_ledger", None),
        )
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


def _resolve_papers_registry_path(args):
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
    from aurora.research.protocol_enforcement import (
        ensure_mandatory_research_protocol,
        make_project_id,
    )

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
    ensure_mandatory_research_protocol(
        project_id=getattr(args, "project_id", None)
        or make_project_id("research_triage", sym, len(specs)),
        objective=f"Triage {len(specs)} strategy specs for {sym}",
        metric="triage_promising_count",
        universe=(sym,),
        providers=("triage_loader",),
        date_range={"tier": cfg.triage_tier_only},
        features=tuple(s.strategy_class for s in specs),
        seed="spec_file",
        candidate_id=make_project_id("triage_batch", sym, len(specs)),
        allowed_selection_phases=("is_train", "is_valid", "oos_dev"),
        locked_phases=("oos_locked", "forward"),
        constraints={"command": "research triage"},
        actor="aurora_cli",
        ledger_path=getattr(args, "protocol_ledger", None),
    )
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


def cmd_research_sp500_long_short(args):
    """Run the SPY/S&P 500 always-long-or-short research sweep."""
    from pathlib import Path

    from aurora.research.sp500_long_short import (
        report_to_markdown,
        run_default_spy_search,
    )

    try:
        report, paths = run_default_spy_search(
            output_dir=Path(args.output_dir) if args.output_dir else None,
            symbol=args.symbol,
            top_train=args.top_train,
            top_valid=args.top_valid,
            min_train_calmar=args.min_train_calmar,
            min_valid_calmar=args.min_valid_calmar,
            require_valid_beats_long=not args.allow_valid_underperform_long,
            min_valid_short_fraction=args.min_valid_short_fraction,
            min_valid_trades=args.min_valid_trades,
            open_locked_report=args.open_locked_report,
        )
    except Exception as exc:
        return _runtime_error(f"sp500 long/short search failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        payload = report.to_dict()
        payload["paths"] = {k: str(v) for k, v in paths.items()}
        print(_json.dumps(payload, indent=2, default=str))
        return 0

    print(report_to_markdown(report))
    print("Artifacts:")
    for label, path in paths.items():
        print(f"  {label}: {path}")
    return 0


def cmd_research_sp500_nfci_stress(args):
    """Build the formal SPY NFCI stress candidate report."""
    from pathlib import Path

    from aurora.research.sp500_nfci_stress import (
        build_nfci_stress_report,
        report_to_markdown,
    )

    try:
        report, paths = build_nfci_stress_report(
            symbol=args.symbol,
            output_dir=Path(args.output_dir) if args.output_dir else None,
        )
    except Exception as exc:
        return _runtime_error(f"sp500 NFCI stress report failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        payload = report.to_dict()
        payload["paths"] = {k: str(v) for k, v in paths.items()}
        print(_json.dumps(payload, indent=2, default=str))
        return 0

    print(report_to_markdown(report))
    print("Artifacts:")
    for label, path in paths.items():
        print(f"  {label}: {path}")
    return 0


def cmd_research_discover_sources(args):
    """Discover candidate data sources for future research."""
    from pathlib import Path

    from aurora.research.source_discovery import (
        SourceDiscoveryConfig,
        discover_sources,
        source_report_to_markdown,
    )

    try:
        cfg = SourceDiscoveryConfig(
            categories=tuple(args.category or ()),
            free_only=not args.include_paid,
            useful_for_sp500_only=args.sp500_only,
            min_history_year=args.min_history_year,
            verify_urls=args.verify_urls,
            output_dir=str(Path(args.output_dir)) if args.output_dir else None,
            include_integrated=not args.only_new,
        )
        report = discover_sources(cfg)
    except Exception as exc:
        return _runtime_error(f"source discovery failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
        return 0

    print(source_report_to_markdown(report))
    print(f"\nArtifacts: {report.output_dir}")
    return 0


def cmd_research_autosearch_sp500(args):
    """Run or resume the persistent SPY autosearch loop."""
    from pathlib import Path

    from aurora.research.sp500_autosearch import (
        AutosearchConfig,
        report_to_markdown,
        run_sp500_autosearch,
    )

    try:
        cfg = AutosearchConfig(
            target_calmar=args.target_calmar,
            symbol=args.symbol,
            max_rounds=args.max_rounds,
            max_candidates_per_round=args.max_candidates_per_round,
            max_hours=args.max_hours,
            checkpoint_every=args.checkpoint_every,
            open_locked_final=args.open_locked_final,
            output_dir=str(Path(args.output_dir)) if args.output_dir else None,
            resume=args.resume,
        )
        report = run_sp500_autosearch(cfg)
    except Exception as exc:
        return _runtime_error(f"sp500 autosearch failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
        return 0 if report.best.passed else 1

    print(report_to_markdown(report))
    return 0 if report.best.passed else 1


def cmd_research_price_action_ga(args):
    """Run the price-action-only SPY GA."""
    from aurora.research.price_action_ga import (
        PriceActionGAConfig,
        report_to_markdown,
        run_price_action_ga,
    )

    try:
        report = run_price_action_ga(
            PriceActionGAConfig(
                run_id=args.run_id,
                target_calmar=args.target_calmar,
                symbol=args.symbol,
                population=args.population,
                generations=args.generations,
                workers=args.workers,
                seed=args.seed,
                no_costs=args.no_costs,
                train_only=args.train_only,
                run_root=args.run_root,
                top_n=args.top_n,
                stop_when_target_met=not args.keep_searching,
                validation_target_calmar=args.validation_target_calmar,
                resume_hall_of_fame=not args.no_resume_hall_of_fame,
                cache_evaluations=not args.no_cache_evaluations,
            )
        )
    except Exception as exc:
        return _runtime_error(f"price-action-ga failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(report_to_markdown(report))
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.objective_met else 1


def cmd_research_price_action_gp(args):
    """Run the price-action-only SPY genetic programming search."""
    from aurora.research.price_action_gp import PriceActionGPConfig, run_price_action_gp

    try:
        report = run_price_action_gp(
            PriceActionGPConfig(
                run_id=args.run_id,
                target_calmar=args.target_calmar,
                validation_target_calmar=args.validation_target_calmar,
                symbol=args.symbol,
                population=args.population,
                generations=args.generations,
                workers=args.workers,
                seed=args.seed,
                max_depth=args.max_depth,
                top_n=args.top_n,
                run_root=args.run_root,
                train_only=args.train_only,
                no_costs=args.no_costs,
                keep_searching=args.keep_searching,
                random_immigrant_fraction=args.random_immigrant_fraction,
            )
        )
    except Exception as exc:
        return _runtime_error(f"price-action-gp failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        best = report.best.metrics.calmar if report.best else None
        print(f"Price-action GP status: {report.status}")
        print(f"Best train Calmar: {best}")
        if report.validation_best is not None:
            print(f"Validation Calmar: {report.validation_best.metrics.calmar}")
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.objective_met else 1


def cmd_research_kronos_install(args):
    """Install or register the optional external Kronos tool."""
    from aurora.research.kronos_tool import KronosInstallConfig, run_kronos_install

    try:
        manifest = run_kronos_install(
            KronosInstallConfig(
                model=args.model,
                repo_url=args.repo_url,
                tools_root=args.tools_root,
                clone_repo=not args.skip_clone,
                force=args.force,
            )
        )
    except Exception as exc:
        return _runtime_error(f"kronos install failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(manifest, indent=2, default=str))
    else:
        print("Kronos tool registered")
        print(f"Repo:      {manifest['repo_dir']}")
        print(f"Model:     {manifest['model']}")
        print(f"Tokenizer: {manifest['tokenizer_id']}")
        print("Model weights are loaded lazily through the Hugging Face cache.")
    return 0


def cmd_research_kronos_forecast(args):
    """Run Kronos rolling forecasts and write forecast artifacts."""
    from pathlib import Path

    from aurora.core.runtime_paths import base_data_dir
    from aurora.research.kronos_tool import KronosToolConfig, run_kronos_forecast

    try:
        cfg = _kronos_config_from_args(args)
        forecasts = run_kronos_forecast(cfg)
        output_dir = (
            Path(args.run_root) if args.run_root else base_data_dir() / "agent_loop"
        ) / args.run_id / "kronos"
        output_dir.mkdir(parents=True, exist_ok=True)
        forecasts.to_parquet(output_dir / "forecasts.parquet", engine="pyarrow", compression="snappy")
        status = {
            "status": "completed",
            "locked_opened": False,
            "run_id": args.run_id,
            "model": args.model,
            "symbol": args.symbol,
            "forecasts_generated": int(len(forecasts)),
            "output_dir": str(output_dir),
        }
        (output_dir / "status.json").write_text(
            __import__("json").dumps(status, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        return _runtime_error(f"kronos forecast failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(status, indent=2, default=str))
    else:
        print(f"Kronos forecasts: {len(forecasts)}")
        print(f"Artifacts: {output_dir}")
    return 0


def cmd_research_kronos_search(args):
    """Run Kronos forecast-to-signal search."""
    from aurora.research.kronos_tool import report_to_markdown, run_kronos_search

    try:
        report = run_kronos_search(_kronos_config_from_args(args))
    except Exception as exc:
        return _runtime_error(f"kronos search failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(report_to_markdown(report))
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.objective_met else 1


def cmd_research_kronos_ingest_crypto_5m(args):
    """Fetch and store Binance crypto 5m OHLCV history for Kronos."""
    from aurora.research.kronos_tool import Crypto5mIngestionConfig, ingest_binance_crypto_5m

    try:
        status = ingest_binance_crypto_5m(
            Crypto5mIngestionConfig(
                symbol=args.symbol,
                library=args.library,
                interval=args.interval,
                start=args.start,
                end=args.end,
                version=args.version,
                run_id=args.run_id,
                run_root=args.run_root,
                replace=args.replace,
            )
        )
    except Exception as exc:
        return _runtime_error(f"kronos crypto 5m ingest failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(status.to_dict(), indent=2, default=str))
    else:
        print("Kronos crypto 5m data ingested")
        print(f"Symbol: {status.symbol}")
        print(f"Rows: {status.rows} / expected {status.expected_rows}")
        print(f"Missing candles: {status.missing_candles}")
        print(f"Duplicate candles: {status.duplicate_candles}")
        print(f"Version: {status.version}")
    return 0


def cmd_research_kronos_direction_backtest(args):
    """Run Kronos next-candle direction backtest for crypto 5m data."""
    from aurora.research.kronos_tool import (
        KronosDirectionBacktestConfig,
        direction_report_to_markdown,
        run_kronos_direction_backtest,
    )

    try:
        report = run_kronos_direction_backtest(
            KronosDirectionBacktestConfig(
                run_id=args.run_id,
                symbol=args.symbol,
                library=args.library,
                version=args.version,
                model=args.model,
                run_root=args.run_root,
                allow_volume=args.allow_volume,
                lookbacks=_csv_ints(args.lookbacks),
                temperatures=_csv_floats(args.temperatures),
                top_ps=_csv_floats(args.top_ps),
                sample_counts=_csv_ints(args.sample_counts),
                confidence_bps=_csv_floats(args.confidence_bps),
                max_confidence_bps=_csv_floats(args.max_confidence_bps),
                prediction_sides=tuple(
                    item.strip().lower()
                    for item in str(args.prediction_sides).split(",")
                    if item.strip()
                ),
                hour_windows=tuple(
                    item.strip().lower()
                    for item in str(args.hour_windows).split(",")
                    if item.strip()
                ),
                train_fraction=args.train_fraction,
                validation_fraction=args.validation_fraction,
                max_train_windows=args.max_train_windows,
                max_validation_windows=args.max_validation_windows,
                min_train_predictions=args.min_train_predictions,
                direction_rules=tuple(
                    item.strip().lower()
                    for item in str(args.direction_rules).split(",")
                    if item.strip()
                ),
                selection_mode=args.selection_mode,
                device=args.device,
            )
        )
    except Exception as exc:
        return _runtime_error(f"kronos direction backtest failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(direction_report_to_markdown(report))
        print(f"Artifacts: {report.output_dir}")
    return 0


def cmd_research_crypto_direction_ml(args):
    """Run BTC/crypto 5m next-bar direction search with optional ML models."""
    from aurora.research.crypto_direction_ml import (
        CryptoDirectionMLConfig,
        report_to_markdown,
        run_crypto_direction_ml,
    )

    try:
        report = run_crypto_direction_ml(
            CryptoDirectionMLConfig(
                run_id=args.run_id,
                symbol=args.symbol,
                library=args.library,
                version=args.version,
                models=tuple(
                    item.strip()
                    for item in str(args.models).split(",")
                    if item.strip()
                ),
                workers=args.workers,
                target_accuracy=args.target_accuracy,
                train_fraction=args.train_fraction,
                validation_fraction=args.validation_fraction,
                seed=args.seed,
                max_candidates=args.max_candidates,
                run_root=args.run_root,
                no_locked=args.no_locked,
                top_n=args.top_n,
            )
        )
    except Exception as exc:
        return _runtime_error(f"crypto-direction-ml failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(report_to_markdown(report))
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.objective_met else 1


def cmd_research_crypto_direction_ml_regime(args):
    """Run crypto 5m direction search with regime-specific specialists."""
    from aurora.research.crypto_direction_ml import (
        CryptoDirectionMLRegimeConfig,
        report_to_markdown,
        run_crypto_direction_ml_regime_search,
    )

    try:
        report = run_crypto_direction_ml_regime_search(
            CryptoDirectionMLRegimeConfig(
                run_id=args.run_id,
                symbol=args.symbol,
                library=args.library,
                version=args.version,
                models=tuple(
                    item.strip()
                    for item in str(args.models).split(",")
                    if item.strip()
                ),
                workers=args.workers,
                target_accuracy=args.target_accuracy,
                train_fraction=args.train_fraction,
                validation_fraction=args.validation_fraction,
                seed=args.seed,
                max_candidates=args.max_candidates,
                run_root=args.run_root,
                no_locked=args.no_locked,
                top_n=args.top_n,
                partitions=tuple(
                    item.strip()
                    for item in str(args.partitions).split(",")
                    if item.strip()
                ),
                feature_sets=tuple(
                    item.strip()
                    for item in str(args.feature_sets).split(",")
                    if item.strip()
                ),
                min_bucket_rows=args.min_bucket_rows,
            )
        )
    except Exception as exc:
        return _runtime_error(f"crypto-direction-ml-regime failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(report_to_markdown(report))
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.objective_met else 1


def cmd_research_crypto_direction_signal_search(args):
    """Run filtered crypto 5m signal search."""
    from aurora.research.crypto_direction_ml import (
        CryptoDirectionSignalSearchConfig,
        run_crypto_direction_signal_search,
        signal_report_to_markdown,
    )

    try:
        report = run_crypto_direction_signal_search(
            CryptoDirectionSignalSearchConfig(
                run_id=args.run_id,
                symbol=args.symbol,
                library=args.library,
                version=args.version,
                models=tuple(
                    item.strip()
                    for item in str(args.models).split(",")
                    if item.strip()
                ),
                workers=args.workers,
                target_accuracy=args.target_accuracy,
                train_fraction=args.train_fraction,
                validation_fraction=args.validation_fraction,
                seed=args.seed,
                max_candidates=args.max_candidates,
                run_root=args.run_root,
                no_locked=args.no_locked,
                top_n=args.top_n,
                horizons=tuple(_csv_ints(args.horizons)),
                move_threshold_bps=tuple(_csv_floats(args.move_threshold_bps)),
                confidence_thresholds=tuple(_csv_floats(args.confidence_thresholds)),
                hour_windows=tuple(
                    item.strip()
                    for item in str(args.hour_windows).split(",")
                    if item.strip()
                ),
                sides=tuple(
                    item.strip()
                    for item in str(args.sides).split(",")
                    if item.strip()
                ),
                feature_sets=tuple(
                    item.strip()
                    for item in str(args.feature_sets).split(",")
                    if item.strip()
                ),
                min_train_signals=args.min_train_signals,
                min_validation_signals=args.min_validation_signals,
                max_model_candidates=args.max_model_candidates,
            )
        )
    except Exception as exc:
        return _runtime_error(f"crypto-direction-signal-search failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(signal_report_to_markdown(report))
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.objective_met else 1


def cmd_research_ml_search(args):
    """Run the train-first ML strategy search."""
    from aurora.research.ml_search import MLSearchConfig, report_to_markdown, run_ml_search

    try:
        report = run_ml_search(
            MLSearchConfig(
                run_id=args.run_id,
                symbol=args.symbol,
                library=args.library,
                target_calmar=args.target_calmar,
                validation_target_calmar=args.validation_target_calmar,
                train_end=args.train_end,
                validation_start=args.validation_start,
                validation_end=args.validation_end,
                locked_start=args.locked_start,
                workers=args.workers,
                max_candidates=args.max_candidates,
                batch_size=args.batch_size,
                seed=args.seed,
                run_root=args.run_root,
                no_costs=args.no_costs,
                no_locked=args.no_locked,
                include_kronos=args.include_kronos,
                include_classic_ml=not args.no_classic_ml,
                include_sequence_models=args.include_sequence_models,
                include_pending_features=args.include_pending_features,
                pending_feature_library=args.pending_feature_library,
                pending_feature_version=args.pending_feature_version,
                models=tuple(
                    item.strip()
                    for item in args.models.split(",")
                    if item.strip()
                ),
                top_n=args.top_n,
                target_objective_count=args.target_objective_count,
                min_feature_jaccard_distance=args.min_feature_jaccard_distance,
                min_behavior_distance=args.min_behavior_distance,
                train_subperiod_count=args.train_subperiod_count,
                validation_subperiod_count=args.validation_subperiod_count,
                min_train_subperiod_calmar=args.min_train_subperiod_calmar,
                min_validation_subperiod_calmar=args.min_validation_subperiod_calmar,
                min_train_cagr=args.min_train_cagr,
                min_validation_cagr=args.min_validation_cagr,
                max_train_mdd=args.max_train_mdd,
                max_validation_mdd=args.max_validation_mdd,
                min_train_annual_return=args.min_train_annual_return,
                min_validation_annual_return=args.min_validation_annual_return,
                min_train_annual_calmar=args.min_train_annual_calmar,
                min_validation_annual_calmar=args.min_validation_annual_calmar,
                max_train_validation_calmar_ratio=args.max_train_validation_calmar_ratio,
                min_validation_excess_pvalue=args.min_validation_excess_pvalue,
                min_validation_bootstrap_calmar_p05=args.min_validation_bootstrap_calmar_p05,
                min_validation_bootstrap_excess_calmar_p05=args.min_validation_bootstrap_excess_calmar_p05,
                max_validation_random_baseline_pvalue=args.max_validation_random_baseline_pvalue,
                min_validation_deflated_sharpe=args.min_validation_deflated_sharpe,
                max_validation_pbo=args.max_validation_pbo,
                min_feature_ablation_validation_calmar=args.min_feature_ablation_validation_calmar,
                min_validation_regime_calmar=args.min_validation_regime_calmar,
                max_validation_trade_concentration=args.max_validation_trade_concentration,
                statistical_bootstrap_paths=args.statistical_bootstrap_paths,
                statistical_bootstrap_block=args.statistical_bootstrap_block,
                statistical_random_shuffles=args.statistical_random_shuffles,
                statistical_pbo_splits=args.statistical_pbo_splits,
                min_trades_per_year=args.min_trades_per_year,
                max_trades_per_year=args.max_trades_per_year,
                min_long_fraction=args.min_long_fraction,
                max_long_fraction=args.max_long_fraction,
                max_features_per_candidate=args.max_features_per_candidate,
                reject_same_feature_family=args.reject_same_feature_family,
                adaptive_family_search=args.adaptive_family_search,
                adaptive_quick_screen_candidates=args.adaptive_quick_screen_candidates,
                adaptive_family_min_weight=args.adaptive_family_min_weight,
                adaptive_family_reward=args.adaptive_family_reward,
                penalized_feature_pools=tuple(
                    item.strip()
                    for item in args.penalized_feature_pools.split(",")
                    if item.strip()
                ),
                penalized_feature_pool_factor=args.penalized_feature_pool_factor,
                defer_robustness_until_basic_pass=args.defer_robustness_until_basic_pass,
                effective_dsr_trials=args.effective_dsr_trials,
                time_limit_seconds=args.time_limit_seconds,
            )
        )
    except Exception as exc:
        return _runtime_error(f"ml-search failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(report_to_markdown(report))
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.objective_met else 1


def cmd_research_sp500_route_tournament(args):
    """Run the nine-route all-feature SP500 tournament."""
    from aurora.research.sp500_route_tournament import (
        SP500RouteTournamentConfig,
        run_sp500_route_tournament,
    )

    try:
        report = run_sp500_route_tournament(
            SP500RouteTournamentConfig(
                run_id=args.run_id,
                symbol=args.symbol,
                library=args.library,
                workers=args.workers,
                minutes_per_route=args.minutes_per_route,
                feature_mode=args.feature_mode,
                pending_feature_library=args.pending_feature_library,
                pending_feature_version=args.pending_feature_version,
                run_root=args.run_root,
                no_costs=args.no_costs,
                no_locked=args.no_locked,
                max_candidates_per_route=args.max_candidates_per_route,
                batch_size=args.batch_size,
                seed=args.seed,
                target_calmar=args.target_calmar,
                validation_target_calmar=args.validation_target_calmar,
                train_end=args.train_end,
                validation_start=args.validation_start,
                validation_end=args.validation_end,
                locked_start=args.locked_start,
                routes=tuple(args.route) if args.route else None,
                literature_max_queries=args.literature_max_queries,
                literature_per_query=args.literature_per_query,
                literature_max_papers_to_enrich=args.literature_max_papers_to_enrich,
                literature_use_ai=args.literature_use_ai,
                literature_enabled=not args.no_literature_evidence,
                literature_extra_ideas_path=args.literature_extra_ideas_path,
            )
        )
    except Exception as exc:
        return _runtime_error(f"sp500-route-tournament failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(f"SP500 route tournament: {report.status}")
        print(f"Artifacts: {report.output_dir}")
    return 0


def cmd_research_sp500_literature_build(args):
    """Build a SP500 literature corpus ledger for later strategy tests."""
    from aurora.research.sp500_literature_build import (
        SP500LiteratureBuildConfig,
        run_sp500_literature_build,
    )

    try:
        report = run_sp500_literature_build(
            SP500LiteratureBuildConfig(
                run_id=args.run_id,
                symbol=args.symbol,
                max_studies=args.max_studies,
                pdf_mode=args.pdf_mode,
                output=args.output,
                run_root=args.run_root,
                no_locked=args.no_locked,
                per_query=args.per_query,
                timeout_seconds=args.timeout_seconds,
                ai_timeout_seconds=args.ai_timeout_seconds,
            )
        )
    except Exception as exc:
        return _runtime_error(f"sp500-literature-build failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(f"SP500 literature build: {report.status}")
        print(f"Studies selected: {report.studies_selected}/{report.studies_found}")
        print(f"Ideas generated: {report.strategy_ideas_count}")
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.status == "completed" else 1


def cmd_research_literature_corpus_build(args):
    """Build a broad literature corpus ledger of strategy ideas."""
    from aurora.research.literature_corpus_build import (
        LiteratureCorpusBuildConfig,
        run_literature_corpus_build,
    )

    try:
        report = run_literature_corpus_build(
            LiteratureCorpusBuildConfig(
                run_id=args.run_id,
                run_root=args.run_root,
                per_page=args.per_page,
                pages_per_query=args.pages_per_query,
                sorts=tuple(args.sorts.split(",")) if args.sorts else ("relevance", "citations", "date"),
                max_studies_to_enrich=args.max_studies_to_enrich,
                timeout_seconds=args.timeout_seconds,
                ai_timeout_seconds=args.ai_timeout_seconds,
                no_locked=args.no_locked,
                backtest_enabled=False,
            )
        )
    except Exception as exc:
        return _runtime_error(f"literature-corpus-build failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(f"Literature corpus build: {report.status}")
        print(f"Studies found: {report.studies_found}")
        print(f"Studies enriched: {report.studies_enriched}")
        print(f"Ideas ready to test: {report.ideas_ready_to_test}")
        print(f"Ideas pending data: {report.ideas_pending_data}")
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.status == "completed" else 1


def cmd_research_rl_trader_league(args):
    """Run the train-first RL trader league search."""
    from aurora.research.rl_trader_league import (
        RLTraderLeagueConfig,
        report_to_markdown,
        run_rl_trader_league,
    )

    try:
        report = run_rl_trader_league(
            RLTraderLeagueConfig(
                run_id=args.run_id,
                symbol=args.symbol,
                library=args.library,
                target_count=args.target_count,
                target_calmar=args.target_calmar,
                validation_target_calmar=args.validation_target_calmar,
                workers=args.workers,
                max_traders=args.max_traders,
                training_steps=args.training_steps,
                seed=args.seed,
                run_root=args.run_root,
                top_n=args.top_n,
                no_costs=args.no_costs,
                no_locked=args.no_locked,
                train_subperiod_count=args.train_subperiod_count,
                min_train_subperiod_calmar=args.min_train_subperiod_calmar,
                min_train_annual_return=args.min_train_annual_return,
                min_behavior_distance=args.min_behavior_distance,
            )
        )
    except Exception as exc:
        return _runtime_error(f"rl-trader-league failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(report_to_markdown(report))
        print(f"Artifacts: {report.output_dir}")
    return 0 if report.objective_met else 1


def _kronos_config_from_args(args):
    from aurora.research.kronos_tool import KronosToolConfig

    return KronosToolConfig(
        run_id=args.run_id,
        symbol=args.symbol,
        library=args.library,
        model=args.model,
        target_calmar=args.target_calmar,
        validation_target_calmar=args.validation_target_calmar,
        run_root=args.run_root,
        allow_volume=args.allow_volume,
        train_only=args.train_only,
        no_costs=args.no_costs,
        lookback=args.lookback,
        forecast_step=args.forecast_step,
        max_windows=args.max_windows,
        temperature=args.temperature,
        top_p=args.top_p,
        sample_count=args.sample_count,
        device=args.device,
        workers=args.workers,
    )


def _csv_floats(raw: str) -> tuple[float, ...]:
    return tuple(float(part.strip()) for part in str(raw).split(",") if part.strip())


def _csv_ints(raw: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in str(raw).split(",") if part.strip())


def _add_kronos_common_args(parser) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--library", default="prices_daily")
    parser.add_argument("--model", default="Kronos-mini")
    parser.add_argument("--target-calmar", type=float, default=1.0)
    parser.add_argument("--validation-target-calmar", type=float, default=None)
    parser.add_argument("--run-root", default=None)
    parser.add_argument(
        "--allow-volume",
        action="store_true",
        help="Allow Kronos to consume volume when the stored series has it.",
    )
    parser.add_argument(
        "--train-only",
        action="store_true",
        help="Required: selection is train-only; validation is exam-only.",
    )
    parser.add_argument(
        "--no-costs",
        action="store_true",
        help="Required for v1. Search objective ignores trading costs.",
    )
    parser.add_argument(
        "--no-locked",
        action="store_true",
        help="Compatibility flag. Kronos v1 never opens locked data.",
    )
    parser.add_argument("--lookback", type=int, default=256)
    parser.add_argument("--forecast-step", type=int, default=5)
    parser.add_argument("--max-windows", type=int, default=400)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--sample-count", type=int, default=1)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--json", action="store_true")


def cmd_research_agent_sp500(args):
    """Run the bounded local SPY research agent."""
    from pathlib import Path

    from aurora.research.sp500_research_agent import (
        SP500ResearchAgentConfig,
        run_sp500_research_agent,
        sp500_agent_report_to_markdown,
    )

    try:
        report = run_sp500_research_agent(SP500ResearchAgentConfig(
            target_calmar=args.target_calmar,
            symbol=args.symbol,
            max_rounds=args.max_agent_rounds,
            candidates_per_round=args.candidates_per_round,
            max_search_hours=args.max_search_hours,
            output_dir=str(Path(args.output_dir)) if args.output_dir else None,
        ))
    except Exception as exc:
        return _runtime_error(f"sp500 research agent failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report.to_dict(), indent=2, default=str))
        return 0 if report.objective_met else 1

    print(sp500_agent_report_to_markdown(report))
    return 0 if report.objective_met else 1


def cmd_research_agent_loop(args):
    """Run the autonomous research loop."""
    from pathlib import Path

    from aurora.research.agent_loop.loop import run_agent_loop

    try:
        resume_run_dir = _agent_loop_run_dir(args) if (
            getattr(args, "resume_run_dir", None) or getattr(args, "resume_run_id", None)
        ) else None
        goal_path = args.goal
        if goal_path is None:
            if resume_run_dir is None:
                return _runtime_error("agent-loop requires --goal unless --resume-run-id or --resume-run-dir is used")
            goal_path = Path(resume_run_dir) / "goal.yaml"
        result = run_agent_loop(
            goal_path=goal_path,
            run_root=args.run_root,
            max_agent_steps=args.max_agent_steps,
            dry_run_codex=args.dry_run_codex or args.codex_provider == "dry-run",
            dry_run_worktree=not args.real_worktree,
            codex_provider=args.codex_provider,
            candidates_per_round=args.candidates_per_round,
            max_search_hours=args.max_search_hours,
            rounds_per_batch=args.rounds_per_batch,
            cpu_workers=args.cpu_workers,
            round_workers=args.round_workers,
            resume_run_dir=resume_run_dir,
        )
    except Exception as exc:
        return _runtime_error(f"agent-loop failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(result.to_dict(), indent=2, default=str))
    else:
        from aurora.research.agent_loop.reports import read_agent_report

        report = read_agent_report(result.state.run_dir)
        state = report["state"]
        print(f"run_id: {state['run_id']}")
        print(f"status: {state['status']}")
        print(f"run_dir: {state['run_dir']}")
        print(f"locked_opened: {state['locked_opened']}")
    return 0 if result.state.objective_met else 1


def cmd_research_agent_status(args):
    """Print autonomous loop state."""
    from aurora.research.agent_loop.state import load_agent_state

    try:
        state = load_agent_state(_agent_loop_run_dir(args))
    except Exception as exc:
        return _runtime_error(f"agent-status failed: {exc}")
    if getattr(args, "json", False):
        import json as _json

        payload = state.to_dict()
        payload["active_autosearch"] = _latest_autosearch_checkpoint(state.run_dir)
        print(_json.dumps(payload, indent=2, default=str))
    else:
        print(f"run_id: {state.run_id}")
        print(f"goal_id: {state.goal_id}")
        print(f"status: {state.status}")
        print(f"step: {state.step}")
        print(f"run_dir: {state.run_dir}")
        print(f"locked_opened: {state.locked_opened}")
        print(f"research_rounds: {state.research_rounds}")
        print(f"rounds_without_improvement: {state.rounds_without_improvement}")
        print(f"best_score: {state.best_score}")
        print(f"built_sources: {', '.join(state.built_sources) or 'none'}")
        print(f"blocked_sources: {', '.join(state.blocked_sources) or 'none'}")
        active = _latest_autosearch_checkpoint(state.run_dir)
        if active:
            print(f"active_autosearch_round: {active.get('round_index')}")
            print(f"active_autosearch_candidates: {active.get('candidates_evaluated')}")
            print(f"active_autosearch_candidates_per_second: {active.get('candidates_per_second')}")
    return 0


def cmd_research_agent_stop(args):
    """Request autonomous loop stop."""
    from aurora.research.agent_loop.state import request_agent_stop

    try:
        state = request_agent_stop(_agent_loop_run_dir(args))
    except Exception as exc:
        return _runtime_error(f"agent-stop failed: {exc}")
    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(state.to_dict(), indent=2, default=str))
    else:
        print("stop requested")
        print(f"run_id: {state.run_id}")
        print(f"status: {state.status}")
    return 0


def cmd_research_agent_report(args):
    """Print autonomous loop report."""
    from pathlib import Path

    from aurora.research.agent_loop.reports import read_agent_report

    try:
        run_dir = _agent_loop_run_dir(args)
        report = read_agent_report(run_dir)
    except Exception as exc:
        return _runtime_error(f"agent-report failed: {exc}")
    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(report, indent=2, default=str))
    else:
        md = Path(run_dir) / "reports" / "agent_report.md"
        if md.exists():
            print(md.read_text(encoding="utf-8"))
        else:
            state = report["state"]
            print(f"run_id: {state['run_id']}")
            print(f"status: {state['status']}")
    return 0


def cmd_research_agent_watchdog(args):
    """Inspect and optionally recover an autonomous loop run."""
    from pathlib import Path

    from aurora.research.agent_loop.watchdog import (
        recover_or_restart_agent_run,
        supervise_agent_run,
    )

    run_dir = _agent_loop_run_dir(args)
    run_kwargs = None
    if getattr(args, "restart", False):
        run_kwargs = {
            "run_root": args.run_root,
            "max_agent_steps": args.max_agent_steps,
            "dry_run_codex": args.dry_run_codex or args.codex_provider == "dry-run",
            "dry_run_worktree": not args.real_worktree,
            "codex_provider": args.codex_provider,
            "candidates_per_round": args.candidates_per_round,
            "max_search_hours": args.max_search_hours,
            "rounds_per_batch": args.rounds_per_batch,
            "cpu_workers": args.cpu_workers,
            "round_workers": args.round_workers,
            "repo_root": Path.cwd(),
        }
    try:
        if getattr(args, "watch", False):
            payload = supervise_agent_run(
                run_dir=run_dir,
                max_stale_seconds=float(args.max_stale_minutes) * 60.0,
                poll_seconds=float(args.poll_seconds),
                run_kwargs=run_kwargs,
            )
        else:
            payload = recover_or_restart_agent_run(
                run_dir=run_dir,
                max_stale_seconds=float(args.max_stale_minutes) * 60.0,
                restart=args.restart,
                run_kwargs=run_kwargs,
            )
    except Exception as exc:
        return _runtime_error(f"agent-watchdog failed: {exc}")

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps(payload, indent=2, default=str))
        return 0

    if payload.get("supervised"):
        state = payload.get("state", {})
        print("supervised: true")
        print(f"run_id: {state.get('run_id')}")
        print(f"status: {state.get('status')}")
        print(f"objective_met: {state.get('objective_met')}")
        print(f"locked_opened: {state.get('locked_opened')}")
        return 0

    inspection = payload["inspection"]
    print(f"run_id: {inspection['run_id']}")
    print(f"process_alive: {inspection['process_alive']}")
    print(f"locked_opened: {inspection['locked_opened']}")
    print(f"objective_met: {inspection['objective_met']}")
    print(f"state_status: {inspection['state_status']}")
    print(f"stale: {inspection['stale']}")
    print(f"needs_recovery: {inspection['needs_recovery']}")
    print(f"reason: {inspection['reason']}")
    if payload.get("report_written"):
        print("watchdog_report: written")
    print(f"restarted: {payload.get('restarted', False)}")
    return 0


def cmd_research_agent_open_locked(args):
    """Guarded final-only locked gate for autonomous loops."""
    from aurora.research.agent_loop.state import load_agent_state

    try:
        state = load_agent_state(_agent_loop_run_dir(args))
    except Exception as exc:
        return _runtime_error(f"agent-open-locked failed: {exc}")
    if not args.confirm_final:
        return _runtime_error("agent-open-locked requires --confirm-final")
    if not state.objective_met:
        return _runtime_error("cannot open locked before objective is met")
    return _runtime_error(
        "locked final evaluator is intentionally not automated in this MVP"
    )


def _latest_autosearch_checkpoint(run_dir):
    from pathlib import Path
    import json as _json

    root = Path(run_dir) / "autosearch"
    if not root.exists():
        return None
    checkpoints = sorted(
        root.glob("*/checkpoint.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not checkpoints:
        return None
    checkpoint = checkpoints[0]
    try:
        payload = _json.loads(checkpoint.read_text(encoding="utf-8"))
    except Exception:
        return {"path": str(checkpoint), "error": "unreadable_checkpoint"}
    payload["path"] = str(checkpoint)
    return payload


def _agent_loop_run_dir(args):
    from pathlib import Path

    explicit_run_dir = getattr(args, "run_dir", None) or getattr(args, "resume_run_dir", None)
    explicit_run_id = getattr(args, "run_id", None) or getattr(args, "resume_run_id", None)
    if explicit_run_dir:
        return Path(explicit_run_dir)
    if explicit_run_id:
        from aurora.core.runtime_paths import base_data_dir

        root = Path(getattr(args, "run_root", None) or base_data_dir() / "agent_loop")
        return root / explicit_run_id
    raise ValueError("provide --run-dir or --run-id")


def _research_protocol_ledger_path(args):
    from pathlib import Path

    if getattr(args, "ledger_path", None):
        return Path(args.ledger_path)
    from aurora.core.runtime_paths import base_data_dir

    return base_data_dir() / "research_protocol_ledger.jsonl"


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value).split(",") if part.strip())


def _parse_constraints(values) -> dict:
    out = {}
    for raw in values or []:
        key, sep, value = str(raw).partition("=")
        if not sep or not key.strip():
            raise ValueError(
                f"constraint {raw!r} must use key=value format"
            )
        out[key.strip()] = value.strip()
    return out


def cmd_research_protocol_show(args):
    """Print the unified mandatory research protocol."""
    from pathlib import Path

    doc = (
        Path(__file__).resolve().parent.parent
        / "docs"
        / "RESEARCH_OPERATING_PROTOCOL.md"
    )
    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps({
            "canonical_doc": str(doc),
            "mandatory": True,
            "summary": [
                "declare protocol before search",
                "select only from allowed phases",
                "locked phases are report-only",
                "exhaustive robustness run required before locked or promotion",
                "promotion order is selection -> robustness -> validation",
                "block new candidates after locked is opened",
                "ledger declaration required before validation",
            ],
        }, indent=2))
        return 0
    if doc.exists():
        print(doc.read_text(encoding="utf-8"))
    else:
        print("Aurora Research Operating Protocol is mandatory.")
        print(f"Expected doc path: {doc}")
    return 0


def cmd_research_protocol_init(args):
    """Declare the mandatory research protocol for one project."""
    from aurora.research.ledger import ResearchLedger
    from aurora.research.protocol_guard import (
        ResearchProtocolGuard,
        ResearchProtocolSpec,
    )

    try:
        spec = ResearchProtocolSpec(
            project_id=args.project_id,
            objective=args.objective,
            metric=args.metric,
            allowed_selection_phases=_parse_csv(args.selection_phases),
            locked_phases=_parse_csv(args.locked_phases),
            constraints=_parse_constraints(args.constraint),
            robustness_checks=_parse_csv(args.robustness_checks),
            max_trials=args.max_trials,
            selection_data_end=args.selection_data_end,
            locked_data_start=args.locked_data_start,
            locked_data_end=args.locked_data_end,
        )
    except Exception as exc:
        return _runtime_error(f"invalid research protocol: {exc}")

    ledger = ResearchLedger(_research_protocol_ledger_path(args))
    guard = ResearchProtocolGuard(spec, ledger)
    event = guard.declare(actor=args.actor)

    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps({
            "ledger_path": str(ledger.path),
            "event": event.to_dict(),
        }, indent=2, default=str))
    else:
        print("protocol declared")
        print(f"project_id: {spec.project_id}")
        print(f"ledger:     {ledger.path}")
        print(f"event:      {event.event_id}")
    return 0


def cmd_research_protocol_check(args):
    """Check whether a project has the mandatory protocol events."""
    from aurora.research.ledger import (
        LedgerEnforcementError,
        LedgerIntegrityError,
        ResearchLedger,
    )

    ledger = ResearchLedger(_research_protocol_ledger_path(args))
    try:
        ledger.verify_chain()
        if args.stage == "validation":
            ledger.assert_ready_for_validation(args.project_id)
        elif args.stage == "promotion":
            ledger.assert_ready_for_promotion(args.project_id)
        else:
            events = ledger.events(project_id=args.project_id)
            if not events:
                raise LedgerEnforcementError(
                    f"project {args.project_id!r} has no ledger events"
                )
    except (LedgerIntegrityError, LedgerEnforcementError) as exc:
        return _runtime_error(f"research protocol check failed: {exc}")

    events = ledger.events(project_id=args.project_id)
    if getattr(args, "json", False):
        import json as _json

        print(_json.dumps({
            "project_id": args.project_id,
            "stage": args.stage,
            "ledger_path": str(ledger.path),
            "ok": True,
            "events": [e.to_dict() for e in events],
        }, indent=2, default=str))
    else:
        print("protocol check: pass")
        print(f"project_id: {args.project_id}")
        print(f"stage:      {args.stage}")
        print(f"events:     {len(events)}")
        print(f"ledger:     {ledger.path}")
    return 0


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

    # ---- unified mandatory protocol --------------------------------------
    p_protocol = research_sub.add_parser(
        "protocol",
        help="Unified mandatory research operating protocol",
        description=(
            "Declare and verify the single mandatory protocol used before "
            "any Aurora research can be validated or promoted."
        ),
    )
    protocol_sub = p_protocol.add_subparsers(
        dest="protocol_cmd", required=True,
    )

    p_proto_show = protocol_sub.add_parser(
        "show", help="Print the canonical operating protocol",
    )
    p_proto_show.add_argument("--json", action="store_true")
    p_proto_show.set_defaults(func=cmd_research_protocol_show)

    p_proto_init = protocol_sub.add_parser(
        "init", help="Declare protocol for one research project",
    )
    p_proto_init.add_argument("--project-id", required=True)
    p_proto_init.add_argument("--objective", required=True)
    p_proto_init.add_argument("--metric", required=True)
    p_proto_init.add_argument(
        "--selection-phases",
        default="train,validation",
        help="Comma-separated phases allowed for candidate selection",
    )
    p_proto_init.add_argument(
        "--locked-phases",
        default="locked_test,forward",
        help="Comma-separated locked/report-only phases",
    )
    p_proto_init.add_argument("--selection-data-end", default=None)
    p_proto_init.add_argument("--locked-data-start", default=None)
    p_proto_init.add_argument("--locked-data-end", default=None)
    p_proto_init.add_argument("--max-trials", type=int, default=None)
    p_proto_init.add_argument(
        "--robustness-checks",
        default="reproducibility,lookahead,stress",
        help=(
            "Comma-separated mandatory robustness checks. At least three "
            "distinct checks are required."
        ),
    )
    p_proto_init.add_argument(
        "--constraint",
        action="append",
        default=[],
        help="Repeatable key=value constraint, e.g. asset=SPY",
    )
    p_proto_init.add_argument("--actor", default="operator")
    p_proto_init.add_argument("--ledger-path", default=None)
    p_proto_init.add_argument("--json", action="store_true")
    p_proto_init.set_defaults(func=cmd_research_protocol_init)

    p_proto_check = protocol_sub.add_parser(
        "check", help="Verify protocol ledger readiness",
    )
    p_proto_check.add_argument("--project-id", required=True)
    p_proto_check.add_argument(
        "--stage",
        choices=("declared", "validation", "promotion"),
        default="validation",
    )
    p_proto_check.add_argument("--ledger-path", default=None)
    p_proto_check.add_argument("--json", action="store_true")
    p_proto_check.set_defaults(func=cmd_research_protocol_check)

    p_rs_submit = research_sub.add_parser(
        "submit", help="Submit one StrategySpec (YAML or JSON) to the factory",
    )
    p_rs_submit.add_argument("spec_path",
                              help="Path to a single-spec YAML/JSON file")
    p_rs_submit.add_argument(
        "--config-path", default=None, dest="config_path",
        help="Optional path to a research_factory.yaml override",
    )
    p_rs_submit.add_argument(
        "--project-id", default=None,
        help="Research protocol project id (auto-generated if omitted).",
    )
    p_rs_submit.add_argument(
        "--protocol-ledger", default=None,
        help="Override research protocol ledger path.",
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
    p_rs_batch.add_argument(
        "--protocol-ledger", default=None,
        help="Override research protocol ledger path.",
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

    # ---- focused local research helpers ---------------------------------
    p_sp500_ls = research_sub.add_parser(
        "sp500-long-short",
        help="Search SPY/S&P 500 strategies that are always fully long or fully short",
        description=(
            "Runs a local-only candidate sweep on SPY. Every raw strategy "
            "signal is wrapped so final exposure is always exactly +1 or -1. "
            "Candidates are selected on train/validation data. The final test "
            "slice is locked report-only and cannot be used as a filter."
        ),
    )
    p_sp500_ls.add_argument("--symbol", default="SPY")
    p_sp500_ls.add_argument("--top-train", type=int, default=5000)
    p_sp500_ls.add_argument("--top-valid", type=int, default=10)
    p_sp500_ls.add_argument(
        "--min-train-calmar",
        type=float,
        default=None,
        help="Optional minimum train Calmar gate; does not inspect final test",
    )
    p_sp500_ls.add_argument(
        "--min-valid-calmar",
        type=float,
        default=None,
        help="Optional minimum validation Calmar gate; does not inspect final test",
    )
    p_sp500_ls.add_argument(
        "--allow-valid-underperform-long",
        action="store_true",
        help="Allow candidates that do not beat always-long SPY on validation",
    )
    p_sp500_ls.add_argument(
        "--min-valid-short-fraction",
        type=float,
        default=0.02,
        help="Minimum fraction of validation bars spent short (default 0.02)",
    )
    p_sp500_ls.add_argument(
        "--min-valid-trades",
        type=int,
        default=1,
        help="Minimum long/short flips on validation (default 1)",
    )
    p_sp500_ls.add_argument(
        "--output-dir",
        default=None,
        help="Directory for markdown/json report "
             "(default: $AU_DATA_DIR/research/sp500_long_short)",
    )
    p_sp500_ls.add_argument(
        "--open-locked-report",
        action="store_true",
        help="Explicitly open the final locked slice after selection",
    )
    p_sp500_ls.add_argument("--json", action="store_true")
    p_sp500_ls.set_defaults(func=cmd_research_sp500_long_short)

    p_sp500_nfci = research_sub.add_parser(
        "sp500-nfci-stress",
        help="Build the formal SPY long/short candidate report based on NFCI stress",
        description=(
            "Persists NFCI from FRED, evaluates the SPY always-long/short "
            "stress rule, prints lag-sensitivity checks, and treats the final "
            "test slice as report-only."
        ),
    )
    p_sp500_nfci.add_argument("--symbol", default="SPY")
    p_sp500_nfci.add_argument(
        "--output-dir",
        default=None,
        help="Directory for markdown/json report "
             "(default: $AU_DATA_DIR/research/sp500_nfci_stress)",
    )
    p_sp500_nfci.add_argument("--json", action="store_true")
    p_sp500_nfci.set_defaults(func=cmd_research_sp500_nfci_stress)

    p_sources = research_sub.add_parser(
        "discover-sources",
        help="Find candidate public data sources for future research",
        description=(
            "Auditable source discovery. This only ranks data sources and "
            "writes a report; it does not choose strategies or open locked data."
        ),
    )
    p_sources.add_argument(
        "--category",
        action="append",
        default=[],
        help="Filter category, repeatable: macro, rates, sentiment, "
             "positioning, factors, valuation, identity",
    )
    p_sources.add_argument(
        "--include-paid",
        action="store_true",
        help="Include non-free sources if they exist in the catalog",
    )
    p_sources.add_argument(
        "--sp500-only",
        action="store_true",
        help="Keep only sources likely useful for S&P 500 research",
    )
    p_sources.add_argument(
        "--only-new",
        action="store_true",
        help="Hide sources that already have Aurora connectors",
    )
    p_sources.add_argument(
        "--min-history-year",
        type=int,
        default=None,
        help="Reject sources whose known history starts after this year",
    )
    p_sources.add_argument(
        "--verify-urls",
        action="store_true",
        help="Try a light network check for each source URL",
    )
    p_sources.add_argument(
        "--output-dir",
        default=None,
        help="Directory for discovery JSON artifacts "
             "(default: $AU_DATA_DIR/research/source_discovery)",
    )
    p_sources.add_argument("--json", action="store_true")
    p_sources.set_defaults(func=cmd_research_discover_sources)

    p_autospy = research_sub.add_parser(
        "autosearch-sp500",
        help="Persistent train-only SPY autosearch loop",
        description=(
            "Runs a resumable SPY long/short autosearch. Selection is train-only, "
            "validation is exam-only, and locked is opened only with "
            "--open-locked-final after a candidate passes."
        ),
    )
    p_autospy.add_argument("--target-calmar", type=float, default=1.0)
    p_autospy.add_argument("--symbol", default="SPY")
    p_autospy.add_argument("--max-rounds", type=int, default=6)
    p_autospy.add_argument("--max-candidates-per-round", type=int, default=50_000)
    p_autospy.add_argument("--max-hours", type=float, default=8.0)
    p_autospy.add_argument("--checkpoint-every", type=int, default=5_000)
    p_autospy.add_argument(
        "--output-dir",
        default=None,
        help="Root directory for resumable run folders "
             "(default: $AU_DATA_DIR/research/sp500_autosearch)",
    )
    p_autospy.add_argument(
        "--resume",
        action="store_true",
        help="Resume the most recent checkpoint under --output-dir",
    )
    p_autospy.add_argument(
        "--open-locked-final",
        action="store_true",
        help="Open locked only after a candidate passes train robustness and validation",
    )
    p_autospy.add_argument("--json", action="store_true")
    p_autospy.set_defaults(func=cmd_research_autosearch_sp500)

    p_price_action = research_sub.add_parser(
        "price-action-ga",
        help="Train-only SPY price-action genetic search",
        description=(
            "Runs a GA over price-action-only SPY long/short rules. It consumes "
            "only adjusted daily OHLC, never uses validation for selection, and "
            "never opens locked data."
        ),
    )
    p_price_action.add_argument("--run-id", default="20260513T134704836569Z")
    p_price_action.add_argument("--target-calmar", type=float, default=1.0)
    p_price_action.add_argument(
        "--validation-target-calmar",
        type=float,
        default=None,
        help="If set, candidates that pass train are examined on validation and the run stops only when validation also passes this Calmar.",
    )
    p_price_action.add_argument("--symbol", default="SPY")
    p_price_action.add_argument("--workers", type=int, default=6)
    p_price_action.add_argument("--population", type=int, default=600)
    p_price_action.add_argument("--generations", type=int, default=80)
    p_price_action.add_argument("--seed", type=int, default=42)
    p_price_action.add_argument("--top-n", type=int, default=25)
    p_price_action.add_argument("--run-root", default=None)
    p_price_action.add_argument(
        "--no-costs",
        action="store_true",
        help="Required for v1. Search objective ignores trading costs.",
    )
    p_price_action.add_argument(
        "--train-only",
        action="store_true",
        help="Required for v1. Validation and locked are not used for selection.",
    )
    p_price_action.add_argument(
        "--keep-searching",
        action="store_true",
        help="Do not stop early after Calmar target is met.",
    )
    p_price_action.add_argument(
        "--no-resume-hall-of-fame",
        action="store_true",
        help="Start without seeding from the saved hall_of_fame.jsonl.",
    )
    p_price_action.add_argument(
        "--no-cache-evaluations",
        action="store_true",
        help="Re-evaluate duplicate genomes instead of using the in-run cache.",
    )
    p_price_action.add_argument("--json", action="store_true")
    p_price_action.set_defaults(func=cmd_research_price_action_ga)

    p_price_action_gp = research_sub.add_parser(
        "price-action-gp",
        help="Genetic programming search over SPY price-action trees",
        description=(
            "Runs GP over price-action-only OHLC trees. It consumes only "
            "adjusted daily open/high/low/close, keeps validation exam-only, "
            "and never opens locked data."
        ),
    )
    p_price_action_gp.add_argument("--run-id", required=True)
    p_price_action_gp.add_argument("--target-calmar", type=float, default=1.0)
    p_price_action_gp.add_argument("--validation-target-calmar", type=float, default=None)
    p_price_action_gp.add_argument("--symbol", default="SPY")
    p_price_action_gp.add_argument("--workers", type=int, default=6)
    p_price_action_gp.add_argument("--population", type=int, default=2000)
    p_price_action_gp.add_argument("--generations", type=int, default=200)
    p_price_action_gp.add_argument("--seed", type=int, default=42)
    p_price_action_gp.add_argument("--max-depth", type=int, default=5)
    p_price_action_gp.add_argument("--top-n", type=int, default=50)
    p_price_action_gp.add_argument("--run-root", default=None)
    p_price_action_gp.add_argument("--random-immigrant-fraction", type=float, default=0.35)
    p_price_action_gp.add_argument("--train-only", action="store_true")
    p_price_action_gp.add_argument("--no-costs", action="store_true")
    p_price_action_gp.add_argument("--keep-searching", action="store_true")
    p_price_action_gp.add_argument("--json", action="store_true")
    p_price_action_gp.set_defaults(func=cmd_research_price_action_gp)

    p_kronos = research_sub.add_parser(
        "kronos",
        help="Optional Kronos candlestick foundation-model tool",
        description=(
            "Install/register Kronos, generate rolling forecasts, or convert "
            "Kronos forecasts into train-selected long/short candidates. "
            "Locked data is never opened."
        ),
    )
    kronos_sub = p_kronos.add_subparsers(dest="kronos_cmd", required=True)

    p_kronos_install = kronos_sub.add_parser(
        "install",
        help="Clone/register the external Kronos tool under Aurora runtime storage",
    )
    p_kronos_install.add_argument("--model", default="Kronos-mini")
    p_kronos_install.add_argument(
        "--repo-url",
        default="https://github.com/shiyu-coder/Kronos",
    )
    p_kronos_install.add_argument("--tools-root", default=None)
    p_kronos_install.add_argument(
        "--skip-clone",
        action="store_true",
        help="Only write the manifest; useful when Kronos was cloned manually.",
    )
    p_kronos_install.add_argument("--force", action="store_true")
    p_kronos_install.add_argument("--json", action="store_true")
    p_kronos_install.set_defaults(func=cmd_research_kronos_install)

    p_kronos_forecast = kronos_sub.add_parser(
        "forecast",
        help="Generate Kronos rolling forecasts only",
    )
    _add_kronos_common_args(p_kronos_forecast)
    p_kronos_forecast.set_defaults(func=cmd_research_kronos_forecast)

    p_kronos_search = kronos_sub.add_parser(
        "search",
        help="Generate Kronos forecasts and evaluate long/short candidates",
    )
    _add_kronos_common_args(p_kronos_search)
    p_kronos_search.set_defaults(func=cmd_research_kronos_search)

    p_kronos_ingest_crypto_5m = kronos_sub.add_parser(
        "ingest-crypto-5m",
        help="Fetch Binance spot crypto 5m OHLCV into the TimeSeriesStore",
    )
    p_kronos_ingest_crypto_5m.add_argument("--run-id", default="kronos-btc-5m-base-direction-36m")
    p_kronos_ingest_crypto_5m.add_argument("--symbol", default="BTCUSDT")
    p_kronos_ingest_crypto_5m.add_argument("--library", default="crypto_5m")
    p_kronos_ingest_crypto_5m.add_argument("--interval", default="5m")
    p_kronos_ingest_crypto_5m.add_argument("--start", default="2023-05-01 00:00:00+00:00")
    p_kronos_ingest_crypto_5m.add_argument("--end", default="2026-04-30 23:55:00+00:00")
    p_kronos_ingest_crypto_5m.add_argument("--version", default="binance_5m_36m")
    p_kronos_ingest_crypto_5m.add_argument("--run-root", default=None)
    p_kronos_ingest_crypto_5m.add_argument("--replace", action="store_true")
    p_kronos_ingest_crypto_5m.add_argument("--json", action="store_true")
    p_kronos_ingest_crypto_5m.set_defaults(func=cmd_research_kronos_ingest_crypto_5m)

    p_kronos_direction = kronos_sub.add_parser(
        "direction-backtest",
        help="Backtest Kronos next 5m candle direction on crypto OHLCV",
    )
    p_kronos_direction.add_argument("--run-id", default="kronos-btc-5m-base-direction-36m")
    p_kronos_direction.add_argument("--symbol", default="BTCUSDT")
    p_kronos_direction.add_argument("--library", default="crypto_5m")
    p_kronos_direction.add_argument("--version", default="binance_5m_36m")
    p_kronos_direction.add_argument("--model", default="Kronos-base")
    p_kronos_direction.add_argument("--run-root", default=None)
    p_kronos_direction.add_argument("--allow-volume", action="store_true")
    p_kronos_direction.add_argument("--lookbacks", default="128,256,512")
    p_kronos_direction.add_argument("--temperatures", default="0.3,0.5,0.7,1.0")
    p_kronos_direction.add_argument("--top-ps", default="0.85,0.90,0.95")
    p_kronos_direction.add_argument("--sample-counts", default="1,4,8")
    p_kronos_direction.add_argument("--confidence-bps", default="0,2,5,10")
    p_kronos_direction.add_argument("--max-confidence-bps", default="1000000")
    p_kronos_direction.add_argument("--prediction-sides", default="both")
    p_kronos_direction.add_argument("--hour-windows", default="all")
    p_kronos_direction.add_argument("--train-fraction", type=float, default=0.60)
    p_kronos_direction.add_argument("--validation-fraction", type=float, default=0.20)
    p_kronos_direction.add_argument("--max-train-windows", type=int, default=0)
    p_kronos_direction.add_argument("--max-validation-windows", type=int, default=0)
    p_kronos_direction.add_argument("--min-train-predictions", type=int, default=30)
    p_kronos_direction.add_argument("--direction-rules", default="raw,inverted,adaptive_25,adaptive_50")
    p_kronos_direction.add_argument(
        "--selection-mode",
        choices=("stable", "recent"),
        default="stable",
        help="Use stable full-train selection or emphasize the most recent half of train.",
    )
    p_kronos_direction.add_argument("--device", default="auto")
    p_kronos_direction.add_argument("--json", action="store_true")
    p_kronos_direction.set_defaults(func=cmd_research_kronos_direction_backtest)

    p_crypto_direction_ml = research_sub.add_parser(
        "crypto-direction-ml",
        help="Predict next crypto 5m candle direction with optional LightGBM/XGBoost",
        description=(
            "Train-selects tabular ML candidates on crypto 5m OHLCV, examines "
            "validation, and keeps locked data closed by default."
        ),
    )
    p_crypto_direction_ml.add_argument("--run-id", required=True)
    p_crypto_direction_ml.add_argument("--symbol", default="BTCUSDT")
    p_crypto_direction_ml.add_argument("--library", default="crypto_5m")
    p_crypto_direction_ml.add_argument("--version", default="binance_5m_36m")
    p_crypto_direction_ml.add_argument("--models", default="lightgbm,xgboost")
    p_crypto_direction_ml.add_argument("--workers", type=int, default=6)
    p_crypto_direction_ml.add_argument("--target-accuracy", type=float, default=0.55)
    p_crypto_direction_ml.add_argument("--train-fraction", type=float, default=0.60)
    p_crypto_direction_ml.add_argument("--validation-fraction", type=float, default=0.20)
    p_crypto_direction_ml.add_argument("--seed", type=int, default=42)
    p_crypto_direction_ml.add_argument("--max-candidates", type=int, default=24)
    p_crypto_direction_ml.add_argument("--run-root", default=None)
    p_crypto_direction_ml.add_argument("--top-n", type=int, default=25)
    p_crypto_direction_ml.add_argument(
        "--no-locked",
        action="store_true",
        help="Required safety flag for v1. Locked data is not opened.",
    )
    p_crypto_direction_ml.add_argument("--json", action="store_true")
    p_crypto_direction_ml.set_defaults(func=cmd_research_crypto_direction_ml)

    p_crypto_direction_ml_regime = research_sub.add_parser(
        "crypto-direction-ml-regime",
        help="Predict next crypto 5m candle direction with regime specialists",
        description=(
            "Trains separate LightGBM/XGBoost specialists by hour, volume, "
            "range, or trend context. Every candle still receives one prediction. "
            "Locked data is kept closed."
        ),
    )
    p_crypto_direction_ml_regime.add_argument("--run-id", required=True)
    p_crypto_direction_ml_regime.add_argument("--symbol", default="BTCUSDT")
    p_crypto_direction_ml_regime.add_argument("--library", default="crypto_5m")
    p_crypto_direction_ml_regime.add_argument("--version", default="binance_5m_36m")
    p_crypto_direction_ml_regime.add_argument("--models", default="lightgbm,xgboost")
    p_crypto_direction_ml_regime.add_argument("--workers", type=int, default=6)
    p_crypto_direction_ml_regime.add_argument("--target-accuracy", type=float, default=0.55)
    p_crypto_direction_ml_regime.add_argument("--train-fraction", type=float, default=0.60)
    p_crypto_direction_ml_regime.add_argument("--validation-fraction", type=float, default=0.20)
    p_crypto_direction_ml_regime.add_argument("--seed", type=int, default=42)
    p_crypto_direction_ml_regime.add_argument("--max-candidates", type=int, default=120)
    p_crypto_direction_ml_regime.add_argument("--run-root", default=None)
    p_crypto_direction_ml_regime.add_argument("--top-n", type=int, default=25)
    p_crypto_direction_ml_regime.add_argument(
        "--partitions",
        default="hour_3,hour_6,volume_2,range_2,trend_2",
    )
    p_crypto_direction_ml_regime.add_argument(
        "--feature-sets",
        default="all,short_price,medium_price,volume_candle,no_calendar",
    )
    p_crypto_direction_ml_regime.add_argument("--min-bucket-rows", type=int, default=250)
    p_crypto_direction_ml_regime.add_argument(
        "--no-locked",
        action="store_true",
        help="Required safety flag for v1. Locked data is not opened.",
    )
    p_crypto_direction_ml_regime.add_argument("--json", action="store_true")
    p_crypto_direction_ml_regime.set_defaults(func=cmd_research_crypto_direction_ml_regime)

    p_crypto_direction_signal = research_sub.add_parser(
        "crypto-direction-signal-search",
        help="Find filtered crypto 5m direction signals instead of predicting every candle",
        description=(
            "Trains ML direction models, then searches train-only confidence, "
            "horizon, move-size, side, and hour filters. Validation is examined "
            "after train selection. Locked data is kept closed."
        ),
    )
    p_crypto_direction_signal.add_argument("--run-id", required=True)
    p_crypto_direction_signal.add_argument("--symbol", default="BTCUSDT")
    p_crypto_direction_signal.add_argument("--library", default="crypto_5m")
    p_crypto_direction_signal.add_argument("--version", default="binance_5m_36m")
    p_crypto_direction_signal.add_argument("--models", default="lightgbm,xgboost,logistic")
    p_crypto_direction_signal.add_argument("--workers", type=int, default=6)
    p_crypto_direction_signal.add_argument("--target-accuracy", type=float, default=0.55)
    p_crypto_direction_signal.add_argument("--train-fraction", type=float, default=0.60)
    p_crypto_direction_signal.add_argument("--validation-fraction", type=float, default=0.20)
    p_crypto_direction_signal.add_argument("--seed", type=int, default=42)
    p_crypto_direction_signal.add_argument("--max-candidates", type=int, default=5000)
    p_crypto_direction_signal.add_argument("--max-model-candidates", type=int, default=24)
    p_crypto_direction_signal.add_argument("--run-root", default=None)
    p_crypto_direction_signal.add_argument("--top-n", type=int, default=25)
    p_crypto_direction_signal.add_argument("--horizons", default="1,2,3,6,12")
    p_crypto_direction_signal.add_argument("--move-threshold-bps", default="0,2,5,10,15")
    p_crypto_direction_signal.add_argument(
        "--confidence-thresholds",
        default="0.50,0.52,0.53,0.54,0.55,0.57,0.60",
    )
    p_crypto_direction_signal.add_argument(
        "--hour-windows",
        default="all,utc_00_08,utc_08_16,utc_16_24",
    )
    p_crypto_direction_signal.add_argument("--sides", default="up,down,both")
    p_crypto_direction_signal.add_argument(
        "--feature-sets",
        default="all,short_price,medium_price,volume_candle,no_calendar",
    )
    p_crypto_direction_signal.add_argument("--min-train-signals", type=int, default=1000)
    p_crypto_direction_signal.add_argument("--min-validation-signals", type=int, default=300)
    p_crypto_direction_signal.add_argument(
        "--no-locked",
        action="store_true",
        help="Required safety flag for v1. Locked data is not opened.",
    )
    p_crypto_direction_signal.add_argument("--json", action="store_true")
    p_crypto_direction_signal.set_defaults(func=cmd_research_crypto_direction_signal_search)

    p_ml_search = research_sub.add_parser(
        "ml-search",
        help="Train-first ML search for long/short candidates",
        description=(
            "Runs ML routes on train, examines validation only after the train "
            "Calmar target is met, and never opens locked data."
        ),
    )
    p_ml_search.add_argument("--run-id", required=True)
    p_ml_search.add_argument("--symbol", default="SPY")
    p_ml_search.add_argument("--library", default="prices_daily")
    p_ml_search.add_argument("--target-calmar", type=float, default=1.0)
    p_ml_search.add_argument("--validation-target-calmar", type=float, default=1.0)
    p_ml_search.add_argument("--train-end", default="2013-10-18")
    p_ml_search.add_argument("--validation-start", default="2013-10-21")
    p_ml_search.add_argument("--validation-end", default="2020-01-28")
    p_ml_search.add_argument("--locked-start", default="2020-01-29")
    p_ml_search.add_argument("--workers", type=int, default=6)
    p_ml_search.add_argument("--max-candidates", type=int, default=5000)
    p_ml_search.add_argument("--batch-size", type=int, default=600)
    p_ml_search.add_argument("--seed", type=int, default=42)
    p_ml_search.add_argument(
        "--time-limit-seconds",
        type=float,
        default=None,
        help="Stop cleanly after the active batch once this runtime budget is reached.",
    )
    p_ml_search.add_argument(
        "--models",
        default="lightgbm,xgboost",
        help="Comma-separated model list: lightgbm,xgboost,logistic,forest,ridge,corr.",
    )
    p_ml_search.add_argument("--run-root", default=None)
    p_ml_search.add_argument("--top-n", type=int, default=25)
    p_ml_search.add_argument(
        "--target-objective-count",
        type=int,
        default=1,
        help="Number of diverse train+validation passing candidates to collect before stopping.",
    )
    p_ml_search.add_argument(
        "--min-feature-jaccard-distance",
        type=float,
        default=0.15,
        help="Minimum feature-set difference between accepted objective candidates.",
    )
    p_ml_search.add_argument(
        "--min-behavior-distance",
        type=float,
        default=0.15,
        help="Minimum behavior difference between accepted objective candidates.",
    )
    p_ml_search.add_argument(
        "--train-subperiod-count",
        type=int,
        default=4,
        help="Number of train subperiods used as a hard stability gate.",
    )
    p_ml_search.add_argument(
        "--validation-subperiod-count",
        type=int,
        default=None,
        help="Number of validation subperiods used as a hard stability gate. Defaults to train count.",
    )
    p_ml_search.add_argument(
        "--min-train-subperiod-calmar",
        type=float,
        default=0.0,
        help="Minimum Calmar required in every train subperiod for accepted candidates.",
    )
    p_ml_search.add_argument(
        "--min-validation-subperiod-calmar",
        type=float,
        default=None,
        help="Minimum Calmar required in every validation subperiod for accepted candidates.",
    )
    p_ml_search.add_argument(
        "--min-train-cagr",
        type=float,
        default=None,
        help="Minimum total train CAGR required for accepted candidates.",
    )
    p_ml_search.add_argument(
        "--min-validation-cagr",
        type=float,
        default=None,
        help="Minimum total validation CAGR required for accepted candidates.",
    )
    p_ml_search.add_argument(
        "--max-train-mdd",
        type=float,
        default=None,
        help="Maximum absolute train drawdown allowed, e.g. 0.30 for 30%%.",
    )
    p_ml_search.add_argument(
        "--max-validation-mdd",
        type=float,
        default=None,
        help="Maximum absolute validation drawdown allowed, e.g. 0.30 for 30%%.",
    )
    p_ml_search.add_argument(
        "--min-train-annual-return",
        type=float,
        default=None,
        help="Minimum return required in every calendar year of train for accepted candidates.",
    )
    p_ml_search.add_argument(
        "--min-validation-annual-return",
        type=float,
        default=None,
        help="Minimum return required in every calendar year of validation for accepted candidates.",
    )
    p_ml_search.add_argument(
        "--min-train-annual-calmar",
        type=float,
        default=None,
        help="Minimum Calmar required in every calendar year of train for accepted candidates.",
    )
    p_ml_search.add_argument(
        "--min-validation-annual-calmar",
        type=float,
        default=None,
        help="Minimum Calmar required in every calendar year of validation for accepted candidates.",
    )
    p_ml_search.add_argument(
        "--max-train-validation-calmar-ratio",
        type=float,
        default=None,
        help="Reject candidates whose train Calmar is too far above validation Calmar.",
    )
    p_ml_search.add_argument(
        "--min-validation-excess-pvalue",
        type=float,
        default=None,
        help="Maximum allowed p-value for validation excess return versus SPY.",
    )
    p_ml_search.add_argument(
        "--min-validation-bootstrap-calmar-p05",
        type=float,
        default=None,
        help="Minimum allowed 5th percentile validation Calmar from block bootstrap.",
    )
    p_ml_search.add_argument(
        "--min-validation-bootstrap-excess-calmar-p05",
        type=float,
        default=None,
        help="Minimum allowed 5th percentile validation excess Calmar from block bootstrap.",
    )
    p_ml_search.add_argument(
        "--max-validation-random-baseline-pvalue",
        type=float,
        default=None,
        help="Maximum allowed p-value versus random shuffled signals on validation.",
    )
    p_ml_search.add_argument(
        "--min-validation-deflated-sharpe",
        type=float,
        default=None,
        help="Minimum allowed deflated Sharpe probability on validation.",
    )
    p_ml_search.add_argument(
        "--max-validation-pbo",
        type=float,
        default=None,
        help="Maximum allowed probability of backtest overfitting proxy on validation.",
    )
    p_ml_search.add_argument(
        "--min-feature-ablation-validation-calmar",
        type=float,
        default=None,
        help="Minimum validation Calmar after removing the most important feature.",
    )
    p_ml_search.add_argument(
        "--min-validation-regime-calmar",
        type=float,
        default=None,
        help="Minimum validation Calmar required in simple up/down/crisis/quiet regimes.",
    )
    p_ml_search.add_argument(
        "--max-validation-trade-concentration",
        type=float,
        default=None,
        help="Maximum share of positive PnL allowed from the top five trades.",
    )
    p_ml_search.add_argument("--statistical-bootstrap-paths", type=int, default=300)
    p_ml_search.add_argument("--statistical-bootstrap-block", type=int, default=21)
    p_ml_search.add_argument("--statistical-random-shuffles", type=int, default=300)
    p_ml_search.add_argument("--statistical-pbo-splits", type=int, default=8)
    p_ml_search.add_argument(
        "--effective-dsr-trials",
        type=int,
        default=None,
        help="Effective number of trials used for deflated Sharpe instead of raw max-candidates.",
    )
    p_ml_search.add_argument(
        "--defer-robustness-until-basic-pass",
        action="store_true",
        help="Run expensive robustness checks only after train and validation basic gates pass.",
    )
    p_ml_search.add_argument(
        "--adaptive-family-search",
        action="store_true",
        help="Generate batches adaptively, favouring feature families that survive train gates.",
    )
    p_ml_search.add_argument(
        "--adaptive-quick-screen-candidates",
        type=int,
        default=0,
        help="Number of initial cheap-model candidates used to discover promising feature families.",
    )
    p_ml_search.add_argument(
        "--adaptive-family-min-weight",
        type=float,
        default=0.25,
        help="Minimum sampling weight for every feature family in adaptive mode.",
    )
    p_ml_search.add_argument(
        "--adaptive-family-reward",
        type=float,
        default=4.0,
        help="Reward multiplier for families whose candidates survive deeper gates.",
    )
    p_ml_search.add_argument(
        "--penalized-feature-pools",
        default="",
        help="Comma-separated feature pools to sample less often in adaptive mode.",
    )
    p_ml_search.add_argument(
        "--penalized-feature-pool-factor",
        type=float,
        default=0.25,
        help="Multiplier applied to penalized feature-pool sampling weights.",
    )
    p_ml_search.add_argument("--min-trades-per-year", type=float, default=0.5)
    p_ml_search.add_argument("--max-trades-per-year", type=float, default=None)
    p_ml_search.add_argument("--min-long-fraction", type=float, default=None)
    p_ml_search.add_argument("--max-long-fraction", type=float, default=None)
    p_ml_search.add_argument("--max-features-per-candidate", type=int, default=None)
    p_ml_search.add_argument(
        "--reject-same-feature-family",
        action="store_true",
        help="Reject accepted objective candidates that use the same broad feature family mix.",
    )
    p_ml_search.add_argument(
        "--no-costs",
        action="store_true",
        help="Required for v1. Search objective ignores trading costs.",
    )
    p_ml_search.add_argument(
        "--no-locked",
        action="store_true",
        help="Required for v1. Locked data is never loaded.",
    )
    p_ml_search.add_argument(
        "--include-kronos",
        action="store_true",
        help="Run Kronos as a secondary challenger if classic ML does not finish the objective first.",
    )
    p_ml_search.add_argument(
        "--no-classic-ml",
        action="store_true",
        help="Disable the classic ML route.",
    )
    p_ml_search.add_argument(
        "--include-sequence-models",
        action="store_true",
        help="Reserved compatibility flag for LSTM/Transformer routes.",
    )
    p_ml_search.add_argument(
        "--include-pending-features",
        action="store_true",
        help="Use the materialized pending feature panel for this search.",
    )
    p_ml_search.add_argument(
        "--pending-feature-library",
        default="features_pending_daily",
        help="TimeSeriesStore library containing materialized pending features.",
    )
    p_ml_search.add_argument(
        "--pending-feature-version",
        default="pending_features_v1",
        help="Version of the materialized pending feature panel.",
    )
    p_ml_search.add_argument("--json", action="store_true")
    p_ml_search.set_defaults(func=cmd_research_ml_search)

    p_route_tournament = research_sub.add_parser(
        "sp500-route-tournament",
        help="Run the 9-route all-feature SP500 research tournament",
        description=(
            "Runs nine train-first strategy-search routes sequentially. Every "
            "route uses all available features, no costs, and locked stays closed."
        ),
    )
    p_route_tournament.add_argument("--run-id", required=True)
    p_route_tournament.add_argument("--symbol", default="SPY")
    p_route_tournament.add_argument("--library", default="prices_daily")
    p_route_tournament.add_argument("--workers", type=int, default=6)
    p_route_tournament.add_argument("--minutes-per-route", type=float, default=60.0)
    p_route_tournament.add_argument("--feature-mode", default="all", choices=("all",))
    p_route_tournament.add_argument("--run-root", default=None)
    p_route_tournament.add_argument("--max-candidates-per-route", type=int, default=2_000_000)
    p_route_tournament.add_argument("--batch-size", type=int, default=1200)
    p_route_tournament.add_argument("--seed", type=int, default=42)
    p_route_tournament.add_argument("--target-calmar", type=float, default=1.25)
    p_route_tournament.add_argument("--validation-target-calmar", type=float, default=1.25)
    p_route_tournament.add_argument("--train-end", default="2013-10-18")
    p_route_tournament.add_argument("--validation-start", default="2013-10-21")
    p_route_tournament.add_argument("--validation-end", default="2019-12-31")
    p_route_tournament.add_argument("--locked-start", default="2020-01-01")
    p_route_tournament.add_argument(
        "--route",
        action="append",
        default=None,
        help="Run only this tournament route. Can be passed more than once.",
    )
    p_route_tournament.add_argument("--literature-max-queries", type=int, default=4)
    p_route_tournament.add_argument("--literature-per-query", type=int, default=8)
    p_route_tournament.add_argument("--literature-max-papers-to-enrich", type=int, default=8)
    p_route_tournament.add_argument(
        "--literature-extra-ideas-path",
        default=None,
        help="Optional JSON/JSONL file with AI-read literature ideas to merge into the paper route.",
    )
    p_route_tournament.add_argument(
        "--literature-use-ai",
        action="store_true",
        help="Use optional extra AI extraction on ESTUDIOS summaries. Off by default.",
    )
    p_route_tournament.add_argument(
        "--no-literature-evidence",
        action="store_true",
        help=(
            "Disable ESTUDIOS evidence for the paper route. The route still runs, "
            "but without literature-derived train feature priors."
        ),
    )
    p_route_tournament.add_argument(
        "--pending-feature-library",
        default="features_pending_daily",
        help="TimeSeriesStore library containing materialized pending features.",
    )
    p_route_tournament.add_argument(
        "--pending-feature-version",
        default="pending_features_v2_free_sources",
        help="Version of the materialized pending feature panel.",
    )
    p_route_tournament.add_argument("--no-costs", action="store_true")
    p_route_tournament.add_argument("--no-locked", action="store_true")
    p_route_tournament.add_argument("--json", action="store_true")
    p_route_tournament.set_defaults(func=cmd_research_sp500_route_tournament)

    p_literature_build = research_sub.add_parser(
        "sp500-literature-build",
        help="Build a SQLite corpus of SP500 literature ideas",
        description=(
            "Searches ESTUDIOS for SP500/equity timing papers, enriches legal PDFs "
            "when available, extracts structured strategy ideas, and writes a SQLite ledger. "
            "It does not run strategy backtests and locked stays closed."
        ),
    )
    p_literature_build.add_argument("--run-id", required=True)
    p_literature_build.add_argument("--symbol", default="SPY")
    p_literature_build.add_argument("--max-studies", type=int, default=200)
    p_literature_build.add_argument(
        "--pdf-mode",
        default="full-if-available",
        choices=("full-if-available",),
    )
    p_literature_build.add_argument("--output", default="sqlite", choices=("sqlite",))
    p_literature_build.add_argument("--run-root", default=None)
    p_literature_build.add_argument("--per-query", type=int, default=20)
    p_literature_build.add_argument("--timeout-seconds", type=int, default=180)
    p_literature_build.add_argument("--ai-timeout-seconds", type=int, default=300)
    p_literature_build.add_argument(
        "--no-locked",
        action="store_true",
        help="Required. Locked data is never opened by this literature build.",
    )
    p_literature_build.add_argument("--json", action="store_true")
    p_literature_build.set_defaults(func=cmd_research_sp500_literature_build)

    p_literature_corpus = research_sub.add_parser(
        "literature-corpus-build",
        help="Build a broad SQLite corpus of literature strategy ideas",
        description=(
            "Searches ESTUDIOS/OpenAlex with a broad finance query bank, paginates "
            "results, deduplicates all studies, enriches legal PDFs when available, "
            "extracts strategy ideas, and writes review artifacts. It never runs "
            "backtests and locked stays closed."
        ),
    )
    p_literature_corpus.add_argument("--run-id", required=True)
    p_literature_corpus.add_argument("--run-root", default=None)
    p_literature_corpus.add_argument("--per-page", type=int, default=200)
    p_literature_corpus.add_argument("--pages-per-query", type=int, default=5)
    p_literature_corpus.add_argument("--sorts", default="relevance,citations,date")
    p_literature_corpus.add_argument(
        "--max-studies-to-enrich",
        type=int,
        default=0,
        help="0 means enrich every deduplicated study found.",
    )
    p_literature_corpus.add_argument("--timeout-seconds", type=int, default=180)
    p_literature_corpus.add_argument("--ai-timeout-seconds", type=int, default=300)
    p_literature_corpus.add_argument(
        "--no-locked",
        action="store_true",
        help="Required. Locked data is never opened by this literature build.",
    )
    p_literature_corpus.add_argument("--json", action="store_true")
    p_literature_corpus.set_defaults(func=cmd_research_literature_corpus_build)

    p_rl_league = research_sub.add_parser(
        "rl-trader-league",
        help="Train-first RL league of independent long/short traders",
        description=(
            "Trains many independent RL traders on train only, examines validation "
            "only after train gates pass, and never opens locked data."
        ),
    )
    p_rl_league.add_argument("--run-id", required=True)
    p_rl_league.add_argument("--symbol", default="SPY")
    p_rl_league.add_argument("--library", default="prices_daily")
    p_rl_league.add_argument("--target-count", type=int, default=50)
    p_rl_league.add_argument("--target-calmar", type=float, default=1.0)
    p_rl_league.add_argument("--validation-target-calmar", type=float, default=1.0)
    p_rl_league.add_argument("--workers", type=int, default=6)
    p_rl_league.add_argument("--max-traders", type=int, default=5000)
    p_rl_league.add_argument("--training-steps", type=int, default=10000)
    p_rl_league.add_argument("--seed", type=int, default=42)
    p_rl_league.add_argument("--run-root", default=None)
    p_rl_league.add_argument("--top-n", type=int, default=25)
    p_rl_league.add_argument("--train-subperiod-count", type=int, default=4)
    p_rl_league.add_argument("--min-train-subperiod-calmar", type=float, default=1.5)
    p_rl_league.add_argument("--min-train-annual-return", type=float, default=0.05)
    p_rl_league.add_argument("--min-behavior-distance", type=float, default=0.15)
    p_rl_league.add_argument(
        "--no-costs",
        action="store_true",
        help="Required for v1. Search objective ignores trading costs.",
    )
    p_rl_league.add_argument(
        "--no-locked",
        action="store_true",
        help="Required for v1. Locked data is never loaded.",
    )
    p_rl_league.add_argument("--json", action="store_true")
    p_rl_league.set_defaults(func=cmd_research_rl_trader_league)

    p_agent = research_sub.add_parser(
        "agent-sp500",
        help="Bounded local agent for SPY strategy research",
        description=(
            "Runs a controlled loop: autosearch first, then source discovery "
            "if the objective is not met. It never opens locked data and "
            "does not create connectors automatically."
        ),
    )
    p_agent.add_argument("--target-calmar", type=float, default=1.0)
    p_agent.add_argument("--symbol", default="SPY")
    p_agent.add_argument("--max-agent-rounds", type=int, default=3)
    p_agent.add_argument("--candidates-per-round", type=int, default=50_000)
    p_agent.add_argument("--max-search-hours", type=float, default=2.0)
    p_agent.add_argument(
        "--output-dir",
        default=None,
        help="Directory for agent reports "
             "(default: $AU_DATA_DIR/research/sp500_research_agent)",
    )
    p_agent.add_argument("--json", action="store_true")
    p_agent.set_defaults(func=cmd_research_agent_sp500)

    p_agent_loop = research_sub.add_parser(
        "agent-loop",
        help="Autonomous Aurora research loop from a goal YAML",
        description=(
            "Runs the safe autonomous loop. By default it continues until "
            "the goal is met or an explicit stop request is received. "
            "It uses a dry-run Codex planner unless --codex-provider "
            "codex-cli is selected, creates an isolated worktree, and never "
            "opens locked data."
        ),
    )
    p_agent_loop.add_argument(
        "--goal",
        default=None,
        help="Goal YAML. Required for a new run; optional when resuming.",
    )
    p_agent_loop.add_argument("--run-root", default=None)
    p_agent_loop.add_argument("--resume-run-dir", default=None)
    p_agent_loop.add_argument("--resume-run-id", default=None)
    p_agent_loop.add_argument(
        "--max-agent-steps",
        type=int,
        default=None,
        help="Debug/test cap only. Omit for goal-only stop policy.",
    )
    p_agent_loop.add_argument("--candidates-per-round", type=int, default=50_000)
    p_agent_loop.add_argument("--max-search-hours", type=float, default=2.0)
    p_agent_loop.add_argument("--rounds-per-batch", type=int, default=3)
    p_agent_loop.add_argument("--cpu-workers", type=int, default=3)
    p_agent_loop.add_argument(
        "--round-workers",
        type=int,
        default=1,
        help="Feature combinations to run at the same time inside each batch.",
    )
    p_agent_loop.add_argument(
        "--codex-provider",
        choices=("dry-run", "codex-cli"),
        default="dry-run",
    )
    p_agent_loop.add_argument("--dry-run-codex", action="store_true")
    p_agent_loop.add_argument(
        "--real-worktree",
        action="store_true",
        help="Create a real git worktree instead of a simulated test directory",
    )
    p_agent_loop.add_argument("--json", action="store_true")
    p_agent_loop.set_defaults(func=cmd_research_agent_loop)

    p_agent_status = research_sub.add_parser(
        "agent-status",
        help="Read autonomous research loop state",
    )
    p_agent_status.add_argument("--run-dir", default=None)
    p_agent_status.add_argument("--run-id", default=None)
    p_agent_status.add_argument("--run-root", default=None)
    p_agent_status.add_argument("--json", action="store_true")
    p_agent_status.set_defaults(func=cmd_research_agent_status)

    p_agent_stop = research_sub.add_parser(
        "agent-stop",
        help="Request stop for an autonomous research loop",
    )
    p_agent_stop.add_argument("--run-dir", default=None)
    p_agent_stop.add_argument("--run-id", default=None)
    p_agent_stop.add_argument("--run-root", default=None)
    p_agent_stop.add_argument("--json", action="store_true")
    p_agent_stop.set_defaults(func=cmd_research_agent_stop)

    p_agent_report = research_sub.add_parser(
        "agent-report",
        help="Print autonomous research loop report",
    )
    p_agent_report.add_argument("--run-dir", default=None)
    p_agent_report.add_argument("--run-id", default=None)
    p_agent_report.add_argument("--run-root", default=None)
    p_agent_report.add_argument("--json", action="store_true")
    p_agent_report.set_defaults(func=cmd_research_agent_report)

    p_agent_watchdog = research_sub.add_parser(
        "agent-watchdog",
        help="Detect dead autonomous loop runs and optionally resume them",
    )
    p_agent_watchdog.add_argument("--run-dir", default=None)
    p_agent_watchdog.add_argument("--run-id", default=None)
    p_agent_watchdog.add_argument("--run-root", default=None)
    p_agent_watchdog.add_argument("--max-stale-minutes", type=float, default=10.0)
    p_agent_watchdog.add_argument("--restart", action="store_true")
    p_agent_watchdog.add_argument(
        "--watch",
        action="store_true",
        help="Keep supervising and restarting until terminal state.",
    )
    p_agent_watchdog.add_argument("--poll-seconds", type=float, default=60.0)
    p_agent_watchdog.add_argument(
        "--max-agent-steps",
        type=int,
        default=None,
        help="Optional step cap when --restart is used.",
    )
    p_agent_watchdog.add_argument("--candidates-per-round", type=int, default=50_000)
    p_agent_watchdog.add_argument("--max-search-hours", type=float, default=2.0)
    p_agent_watchdog.add_argument("--rounds-per-batch", type=int, default=3)
    p_agent_watchdog.add_argument("--cpu-workers", type=int, default=3)
    p_agent_watchdog.add_argument(
        "--round-workers",
        type=int,
        default=1,
        help="Feature combinations to run at the same time inside each batch.",
    )
    p_agent_watchdog.add_argument(
        "--codex-provider",
        choices=("dry-run", "codex-cli"),
        default="dry-run",
    )
    p_agent_watchdog.add_argument("--dry-run-codex", action="store_true")
    p_agent_watchdog.add_argument("--real-worktree", action="store_true")
    p_agent_watchdog.add_argument("--json", action="store_true")
    p_agent_watchdog.set_defaults(func=cmd_research_agent_watchdog)

    p_agent_open_locked = research_sub.add_parser(
        "agent-open-locked",
        help="Final-only locked gate for an autonomous research loop",
    )
    p_agent_open_locked.add_argument("--run-dir", default=None)
    p_agent_open_locked.add_argument("--run-id", default=None)
    p_agent_open_locked.add_argument("--run-root", default=None)
    p_agent_open_locked.add_argument("--confirm-final", action="store_true")
    p_agent_open_locked.add_argument("--json", action="store_true")
    p_agent_open_locked.set_defaults(func=cmd_research_agent_open_locked)

    return research_sub
