"""Build a broad literature corpus of strategy ideas for Aurora.

This pipeline searches ESTUDIOS/OpenAlex, stores every returned study in a
reproducible SQLite ledger, enriches studies when legal text is available, and
extracts strategy ideas. It deliberately does not run backtests or open locked
data.
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import subprocess
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aurora.core.runtime_paths import base_data_dir
from aurora.research.agent_loop.estudios_bridge import (
    ESTUDIOS_PYTHON_ENV,
    ESTUDIOS_ROOT_ENV,
    _estudios_python,
    _estudios_root,
    _run_paper_ai,
    estudios_availability,
)


Runner = Callable[[list[str], Path, int], str]
AIExtractor = Callable[[str, int], str]

LITERATURE_QUERY_BANK: dict[str, tuple[str, ...]] = {
    "market_timing": (
        "equity market timing",
        "stock market timing",
        "market timing predictability returns",
    ),
    "tactical_asset_allocation": (
        "tactical asset allocation equity bonds commodities",
        "dynamic asset allocation macro signals",
        "risk on risk off tactical allocation",
    ),
    "trend_following": (
        "trend following equity index",
        "time series momentum equities",
        "moving average trading rule stock returns",
    ),
    "momentum": (
        "momentum stock market returns",
        "cross sectional momentum asset pricing",
        "equity momentum anomaly timing",
    ),
    "reversal": (
        "short term reversal stock returns",
        "long term reversal equity returns",
        "mean reversion stock market strategy",
    ),
    "volatility_timing": (
        "volatility timing equity returns",
        "realized volatility stock market predictability",
        "volatility managed portfolios",
    ),
    "vix": (
        "VIX equity returns predictability",
        "VIX term structure stock market returns",
        "implied volatility market timing",
    ),
    "credit_spreads": (
        "credit spreads stock market returns",
        "corporate bond spreads equity returns",
        "default spread market timing",
    ),
    "yield_curve": (
        "yield curve stock returns predictability",
        "term spread equity premium",
        "interest rate curve market timing",
    ),
    "macro_predictors": (
        "macroeconomic predictors stock returns",
        "business cycle stock market predictability",
        "economic indicators equity returns",
    ),
    "inflation": (
        "inflation stock returns predictability",
        "inflation regimes equity returns",
        "CPI inflation equity premium",
    ),
    "rates": (
        "interest rates stock returns predictability",
        "federal funds rate equity returns",
        "real rates equity market timing",
    ),
    "unemployment": (
        "unemployment stock market returns",
        "jobless claims equity returns",
        "labor market indicators stock returns",
    ),
    "liquidity": (
        "liquidity stock market returns",
        "financial liquidity equity returns",
        "money supply stock market predictability",
    ),
    "dollar": (
        "dollar returns equity market timing",
        "exchange rates stock market returns",
        "US dollar risk appetite equity returns",
    ),
    "commodities": (
        "commodity returns stock market predictability",
        "oil prices stock returns",
        "commodity markets tactical asset allocation",
    ),
    "gold": (
        "gold stock market hedge timing",
        "gold returns equity risk regimes",
        "gold safe haven stock market",
    ),
    "bonds": (
        "bond returns equity market timing",
        "stocks bonds tactical allocation",
        "treasury returns stock market regimes",
    ),
    "sector_rotation": (
        "sector rotation stock market strategy",
        "industry momentum sector rotation",
        "business cycle sector allocation",
    ),
    "factor_timing": (
        "factor timing asset pricing",
        "style timing value momentum quality",
        "predicting factor returns",
    ),
    "regime_switching": (
        "regime switching equity returns",
        "hidden Markov stock market regimes",
        "market regime detection asset allocation",
    ),
    "crisis_prediction": (
        "financial crisis prediction stock market",
        "stock market crash prediction indicators",
        "drawdown prediction equity market",
    ),
    "machine_learning_asset_pricing": (
        "machine learning empirical asset pricing",
        "machine learning stock return prediction",
        "AI asset pricing anomalies",
    ),
}

SUPPORTED_AURORA_FEATURE_TOKENS: dict[str, str] = {
    "vix": "vix",
    "volatility": "realized_volatility",
    "realized vol": "realized_volatility",
    "credit": "credit_spread",
    "spread": "credit_spread",
    "yield curve": "yield_curve",
    "term spread": "yield_curve",
    "interest rate": "rates",
    "fed funds": "rates",
    "momentum": "momentum",
    "trend": "trend",
    "moving average": "trend",
    "inflation": "inflation",
    "cpi": "inflation",
    "unemployment": "unemployment",
    "jobless": "unemployment",
    "liquidity": "liquidity",
    "money supply": "liquidity",
    "dollar": "dollar",
    "commodity": "commodities",
    "oil": "commodities",
    "gold": "gold",
    "bond": "bonds",
    "treasury": "bonds",
    "sector": "sector_rotation",
    "factor": "factor_timing",
    "regime": "regime",
}


@dataclass(frozen=True)
class LiteratureCorpusBuildConfig:
    run_id: str
    run_root: str | None = None
    per_page: int = 200
    pages_per_query: int = 5
    sorts: tuple[str, ...] = ("relevance", "citations", "date")
    max_studies_to_enrich: int = 0
    timeout_seconds: int = 180
    ai_timeout_seconds: int = 300
    no_locked: bool = True
    backtest_enabled: bool = False


@dataclass(frozen=True)
class LiteratureCorpusBuildReport:
    run_id: str
    status: str
    locked_opened: bool
    backtest_enabled: bool
    output_dir: str
    sqlite_path: str
    studies_found: int
    studies_enriched: int
    ideas_total: int
    ideas_ready_to_test: int
    ideas_pending_data: int
    failures_count: int
    estudios_available: bool
    estudios_root: str
    estudios_python: str
    availability_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_literature_corpus_build(
    config: LiteratureCorpusBuildConfig,
    *,
    runner: Runner | None = None,
    ai_extractor: AIExtractor | None = None,
) -> LiteratureCorpusBuildReport:
    if not config.no_locked:
        raise ValueError("literature-corpus-build requires --no-locked")
    if config.backtest_enabled:
        raise ValueError("literature-corpus-build does not run backtests")
    if config.per_page < 1:
        raise ValueError("per_page must be >= 1")
    if config.pages_per_query < 1:
        raise ValueError("pages_per_query must be >= 1")

    root = _estudios_root()
    python_bin = _estudios_python(root)
    availability = estudios_availability(root=root, python_bin=python_bin, verify_command=runner is None)
    run = runner or _run_estudios
    use_estudios = runner is not None or availability.available
    output_dir = _output_dir(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = output_dir / "literature_corpus.sqlite"
    status_path = output_dir / "status.json"
    progress_path = output_dir / "progress.jsonl"
    failures_path = output_dir / "study_failures.jsonl"

    _init_db(sqlite_path)
    _write_json(output_dir / "query_bank.json", LITERATURE_QUERY_BANK)
    _write_json(status_path, {"run_id": config.run_id, "status": "running", "locked_opened": False})
    _log_progress("corpus_started", run_id=config.run_id, pages_per_query=config.pages_per_query)

    canonical_by_key: dict[str, str] = {}
    studies_by_id: dict[str, dict[str, Any]] = {}
    failures = 0

    with sqlite3.connect(sqlite_path) as con:
        for family, queries in LITERATURE_QUERY_BANK.items():
            for query in queries:
                for sort in config.sorts:
                    for page in range(1, int(config.pages_per_query) + 1):
                        query_key = _query_key(family, query, sort, page)
                        started_at = _now()
                        _append_jsonl(
                            progress_path,
                            {
                                "event": "search_started",
                                "family": family,
                                "query": query,
                                "sort": sort,
                                "page": page,
                                "locked_opened": False,
                            },
                        )
                        try:
                            if use_estudios:
                                cmd = [
                                    str(python_bin),
                                    "-m",
                                    "estudios",
                                    "search",
                                    query,
                                    "--json",
                                    "--per-page",
                                    str(min(int(config.per_page), 200)),
                                    "--page",
                                    str(page),
                                    "--sort",
                                    sort,
                                ]
                                payload = _extract_json_object(run(cmd, root, int(config.timeout_seconds)))
                            else:
                                payload = _direct_openalex_search(
                                    query=query,
                                    sort=sort,
                                    page=page,
                                    per_page=min(int(config.per_page), 200),
                                    timeout_seconds=int(config.timeout_seconds),
                                )
                            studies = payload.get("studies", [])
                            if not isinstance(studies, list):
                                raise ValueError("invalid studies payload")
                            total = _int_or_none(payload.get("total"))
                            _insert_search_query(
                                con,
                                query_key=query_key,
                                family=family,
                                query=query,
                                sort=sort,
                                page=page,
                                per_page=min(int(config.per_page), 200),
                                total_reported=total,
                                returned_count=len(studies),
                                status="ok",
                                error="",
                                started_at=started_at,
                            )
                        except Exception as exc:
                            failures += 1
                            _insert_search_query(
                                con,
                                query_key=query_key,
                                family=family,
                                query=query,
                                sort=sort,
                                page=page,
                                per_page=min(int(config.per_page), 200),
                                total_reported=None,
                                returned_count=0,
                                status="failed",
                                error=str(exc),
                                started_at=started_at,
                            )
                            _record_failure(con, failures_path, "search", query_key, str(exc))
                            continue

                        for position, study in enumerate(studies, start=1):
                            if not isinstance(study, dict):
                                continue
                            raw_id = _study_id(study)
                            _insert_raw_search_result(con, query_key, raw_id, position, study)
                            canonical_id = _canonical_study_id(study, canonical_by_key)
                            if canonical_id not in studies_by_id:
                                studies_by_id[canonical_id] = study | {
                                    "_canonical_study_id": canonical_id,
                                    "_status": "found",
                                }
                                _insert_study(con, canonical_id, studies_by_id[canonical_id], status="found")
                            _insert_study_source(con, canonical_id, query_key, position)
                        _append_jsonl(
                            progress_path,
                            {
                                "event": "search_completed",
                                "family": family,
                                "query": query,
                                "sort": sort,
                                "page": page,
                                "returned_count": len(studies),
                                "unique_studies": len(studies_by_id),
                                "locked_opened": False,
                            },
                        )
                        _log_progress(
                            "search_completed",
                            family=family,
                            sort=sort,
                            page=page,
                            returned_count=len(studies),
                            unique_studies=len(studies_by_id),
                        )

    ranked = sorted(studies_by_id.items(), key=lambda item: _study_score(item[1]), reverse=True)
    if config.max_studies_to_enrich > 0:
        ranked = ranked[: int(config.max_studies_to_enrich)]
    _log_progress("search_phase_completed", unique_studies=len(studies_by_id), studies_to_enrich=len(ranked))

    enriched = 0
    ideas_total = 0
    ideas_ready = 0
    ideas_pending = 0
    with sqlite3.connect(sqlite_path) as con:
        for index, (canonical_id, study) in enumerate(ranked, start=1):
            try:
                text_info = _enrich_text(
                    study,
                    python_bin=python_bin,
                    root=root,
                    output_dir=output_dir,
                    runner=run,
                    timeout_seconds=int(config.timeout_seconds),
                    use_estudios=use_estudios,
                )
                _insert_paper_text(con, canonical_id, text_info)
                extraction = _extract_strategy_card(
                    study,
                    text=str(text_info.get("text", "")),
                    ai_extractor=ai_extractor,
                    timeout_seconds=int(config.ai_timeout_seconds),
                )
                _insert_ai_extraction(con, canonical_id, extraction)
                ideas = _ideas_from_extraction(canonical_id, study, extraction)
                status = "not_strategy"
                if ideas:
                    status = "ready_to_test" if any(i["aurora_supported"] for i in ideas) else "pending_data"
                _update_study_status(con, canonical_id, status)
                enriched += 1
                for idea in ideas:
                    ideas_total += 1
                    if idea["aurora_supported"]:
                        ideas_ready += 1
                    else:
                        ideas_pending += 1
                    _insert_strategy_idea(con, idea, canonical_id)
                    if not idea["aurora_supported"]:
                        _insert_unsupported_data(con, idea)
            except Exception as exc:
                failures += 1
                _update_study_status(con, canonical_id, "failed")
                _record_failure(con, failures_path, "enrich", canonical_id, str(exc))
            _write_json(
                status_path,
                {
                    "run_id": config.run_id,
                    "status": "running",
                    "locked_opened": False,
                    "studies_found": len(studies_by_id),
                    "studies_enriched": enriched,
                    "current_index": index,
                },
            )
            if index == 1 or index % 250 == 0 or index == len(ranked):
                _log_progress(
                    "enrich_progress",
                    current_index=index,
                    studies_to_enrich=len(ranked),
                    studies_enriched=enriched,
                    ideas_total=ideas_total,
                    ideas_ready_to_test=ideas_ready,
                    ideas_pending_data=ideas_pending,
                    failures_count=failures,
                )

    _export_artifacts(sqlite_path, output_dir)
    report = LiteratureCorpusBuildReport(
        run_id=config.run_id,
        status="completed",
        locked_opened=False,
        backtest_enabled=False,
        output_dir=str(output_dir),
        sqlite_path=str(sqlite_path),
        studies_found=len(studies_by_id),
        studies_enriched=enriched,
        ideas_total=ideas_total,
        ideas_ready_to_test=ideas_ready,
        ideas_pending_data=ideas_pending,
        failures_count=failures,
        estudios_available=availability.available,
        estudios_root=availability.root,
        estudios_python=availability.python,
        availability_reason=availability.reason,
    )
    _write_json(status_path, report.to_dict())
    _log_progress("corpus_completed", **report.to_dict())
    return report


def _run_estudios(cmd: list[str], cwd: Path, timeout_seconds: int) -> str:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    return proc.stdout or ""


def _direct_openalex_search(
    *,
    query: str,
    sort: str,
    page: int,
    per_page: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    sort_map = {
        "relevance": "relevance_score:desc",
        "citations": "cited_by_count:desc",
        "date": "publication_date:desc",
        "recency": "publication_date:desc",
    }
    params = {
        "search": query,
        "per-page": str(min(max(int(per_page), 1), 200)),
        "page": str(max(int(page), 1)),
        "sort": sort_map.get(sort, "relevance_score:desc"),
        "filter": "is_retracted:false",
    }
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Aurora literature corpus builder (mailto:not-configured)",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    studies = [_openalex_work_to_study(work) for work in payload.get("results", []) if isinstance(work, dict)]
    return {
        "studies": studies,
        "total": int((payload.get("meta") or {}).get("count") or len(studies)),
        "source": "openalex_direct",
    }


def _openalex_work_to_study(work: dict[str, Any]) -> dict[str, Any]:
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    open_access = work.get("open_access") or {}
    concepts = [
        str(item.get("display_name"))
        for item in work.get("concepts", [])
        if isinstance(item, dict) and item.get("display_name")
    ]
    authors = []
    for item in work.get("authorships", []) or []:
        if not isinstance(item, dict):
            continue
        author = item.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append({"name": name, "openalex_id": author.get("id")})
    return {
        "id": _short_id(work.get("id")),
        "openalex_id": _short_id(work.get("id")),
        "doi": work.get("doi"),
        "title": work.get("title") or work.get("display_name") or "",
        "authors": authors,
        "year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "venue": source.get("display_name") or "",
        "type": work.get("type"),
        "language": work.get("language"),
        "abstract": _abstract_from_openalex(work.get("abstract_inverted_index")),
        "citations_count": work.get("cited_by_count") or 0,
        "is_oa": bool(open_access.get("is_oa")),
        "oa_url": open_access.get("oa_url"),
        "concepts": concepts,
        "keywords": concepts,
        "raw_openalex": work,
    }


def _output_dir(config: LiteratureCorpusBuildConfig) -> Path:
    if config.run_root:
        return Path(config.run_root) / config.run_id / "literature_idea_discovery"
    return base_data_dir() / "agent_loop" / config.run_id / "literature_idea_discovery"


def _init_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            create table if not exists search_queries (
                query_key text primary key,
                family text not null,
                query text not null,
                sort text not null,
                page integer not null,
                per_page integer not null,
                total_reported integer,
                returned_count integer not null,
                status text not null,
                error text not null,
                started_at_utc text not null,
                finished_at_utc text not null
            );
            create table if not exists raw_search_results (
                query_key text not null,
                raw_study_id text not null,
                position integer not null,
                raw_json text not null,
                primary key (query_key, raw_study_id, position)
            );
            create table if not exists studies (
                study_id text primary key,
                openalex_id text,
                doi text,
                title text not null,
                year integer,
                authors_json text not null,
                venue text,
                study_type text,
                language text,
                abstract text,
                citations_count integer,
                is_open_access integer not null,
                oa_url text,
                concepts_json text not null,
                keywords_json text not null,
                raw_json text not null,
                dedupe_key text not null,
                status text not null,
                score real not null
            );
            create table if not exists study_sources (
                study_id text not null,
                query_key text not null,
                position integer not null,
                primary key (study_id, query_key)
            );
            create table if not exists paper_texts (
                study_id text primary key,
                pdf_attempted integer not null,
                pdf_available integer not null,
                pdf_output text,
                summary_path text,
                text_chars integer not null,
                text_excerpt text not null,
                error text not null
            );
            create table if not exists ai_extractions (
                study_id text primary key,
                usable_for_strategy integer not null,
                confidence real not null,
                strategy_family text not null,
                hypothesis text not null,
                signal_logic_plain text not null,
                tradable_assets_json text not null,
                required_features_json text not null,
                expected_holding_period text not null,
                overfitting_risks_json text not null,
                reason_to_test text not null,
                raw_json text not null,
                ai_error text
            );
            create table if not exists strategy_ideas (
                idea_id text primary key,
                strategy_family text not null,
                hypothesis text not null,
                rule_plain text not null,
                tradable_assets_json text not null,
                required_features_json text not null,
                periodicity text not null,
                aurora_supported integer not null,
                data_status text not null,
                confidence real not null,
                reason_to_test text not null,
                status text not null,
                locked_opened integer not null
            );
            create table if not exists idea_sources (
                idea_id text not null,
                study_id text not null,
                primary key (idea_id, study_id)
            );
            create table if not exists unsupported_data (
                idea_id text primary key,
                missing_features_json text not null,
                reason text not null
            );
            create table if not exists failures (
                stage text not null,
                subject text not null,
                error text not null,
                created_at_utc text not null
            );
            """
        )


def _insert_search_query(
    con: sqlite3.Connection,
    *,
    query_key: str,
    family: str,
    query: str,
    sort: str,
    page: int,
    per_page: int,
    total_reported: int | None,
    returned_count: int,
    status: str,
    error: str,
    started_at: str,
) -> None:
    con.execute(
        """
        insert or replace into search_queries(
            query_key, family, query, sort, page, per_page, total_reported,
            returned_count, status, error, started_at_utc, finished_at_utc
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (query_key, family, query, sort, page, per_page, total_reported, returned_count, status, error, started_at, _now()),
    )


def _insert_raw_search_result(
    con: sqlite3.Connection,
    query_key: str,
    raw_study_id: str,
    position: int,
    study: dict[str, Any],
) -> None:
    con.execute(
        """
        insert or ignore into raw_search_results(query_key, raw_study_id, position, raw_json)
        values (?, ?, ?, ?)
        """,
        (query_key, raw_study_id, int(position), json.dumps(study, ensure_ascii=False, default=str)),
    )


def _insert_study(con: sqlite3.Connection, study_id: str, study: dict[str, Any], *, status: str) -> None:
    con.execute(
        """
        insert or replace into studies(
            study_id, openalex_id, doi, title, year, authors_json, venue, study_type,
            language, abstract, citations_count, is_open_access, oa_url, concepts_json,
            keywords_json, raw_json, dedupe_key, status, score
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            study_id,
            _str_or_none(study.get("openalex_id") or study.get("id")),
            _normalise_doi(study.get("doi")),
            _title(study),
            _int_or_none(study.get("year")),
            json.dumps(study.get("authors", []), ensure_ascii=False, default=str),
            _venue(study),
            _str_or_none(study.get("type")),
            _str_or_none(study.get("language")),
            str(study.get("abstract", "")),
            _int_or_none(study.get("citations_count")),
            1 if bool(study.get("is_oa", study.get("is_open_access", False))) else 0,
            _str_or_none(study.get("oa_url")),
            json.dumps(study.get("concepts", []), ensure_ascii=False, default=str),
            json.dumps(study.get("keywords", []), ensure_ascii=False, default=str),
            json.dumps(study, ensure_ascii=False, default=str),
            _dedupe_keys(study)[0],
            status,
            _study_score(study),
        ),
    )


def _insert_study_source(con: sqlite3.Connection, study_id: str, query_key: str, position: int) -> None:
    con.execute(
        "insert or ignore into study_sources(study_id, query_key, position) values (?, ?, ?)",
        (study_id, query_key, int(position)),
    )


def _update_study_status(con: sqlite3.Connection, study_id: str, status: str) -> None:
    con.execute("update studies set status=? where study_id=?", (status, study_id))


def _enrich_text(
    study: dict[str, Any],
    *,
    python_bin: Path,
    root: Path,
    output_dir: Path,
    runner: Runner,
    timeout_seconds: int,
    use_estudios: bool,
) -> dict[str, Any]:
    if not use_estudios:
        text = _metadata_text(study)
        return {
            "pdf_attempted": False,
            "pdf_available": False,
            "pdf_output": "ESTUDIOS unavailable; used OpenAlex metadata only.",
            "summary_path": "",
            "text": text[:250_000],
            "error": "",
        }
    study_id = _study_id(study)
    safe_id = _safe_filename(study_id)
    pdf_output = ""
    pdf_available = False
    error = ""
    try:
        runner([str(python_bin), "-m", "estudios", "save", study_id], root, timeout_seconds)
    except Exception:
        pass
    try:
        pdf_output = runner([str(python_bin), "-m", "estudios", "pdf", study_id], root, timeout_seconds)
        pdf_available = "no disponible" not in pdf_output.lower()
    except Exception as exc:
        pdf_output = str(exc)
        error = str(exc)
    summary_path = output_dir / f"{safe_id}_full_or_abstract.txt"
    text = ""
    try:
        runner(
            [
                str(python_bin),
                "-m",
                "estudios",
                "summarize",
                study_id,
                "--mode",
                "critical",
                "--file",
                str(summary_path),
            ],
            root,
            timeout_seconds,
        )
        if summary_path.exists():
            text = summary_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        error = error or str(exc)
        text = _metadata_text(study)
    if not text.strip():
        text = _metadata_text(study)
    return {
        "pdf_attempted": True,
        "pdf_available": pdf_available,
        "pdf_output": pdf_output[-2000:],
        "summary_path": str(summary_path) if summary_path.exists() else "",
        "text": text[:250_000],
        "error": error[:2000],
    }


def _insert_paper_text(con: sqlite3.Connection, study_id: str, text_info: dict[str, Any]) -> None:
    text = str(text_info.get("text", ""))
    con.execute(
        """
        insert or replace into paper_texts(
            study_id, pdf_attempted, pdf_available, pdf_output, summary_path,
            text_chars, text_excerpt, error
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            study_id,
            1 if text_info.get("pdf_attempted") else 0,
            1 if text_info.get("pdf_available") else 0,
            str(text_info.get("pdf_output") or ""),
            str(text_info.get("summary_path") or ""),
            len(text),
            text[:20_000],
            str(text_info.get("error") or ""),
        ),
    )


def _extract_strategy_card(
    study: dict[str, Any],
    *,
    text: str,
    ai_extractor: AIExtractor | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    prompt = _ai_prompt(study, text)
    if ai_extractor is None and not _external_ai_configured():
        return _normalise_extraction(_heuristic_extraction(study, text), study, ai_error=None)
    try:
        raw = (ai_extractor or _run_paper_ai)(prompt, timeout_seconds)
        payload = _extract_json_object(raw)
        return _normalise_extraction(payload, study, ai_error=None)
    except Exception as exc:
        return _normalise_extraction(_heuristic_extraction(study, text), study, ai_error=str(exc))


def _insert_ai_extraction(con: sqlite3.Connection, study_id: str, extraction: dict[str, Any]) -> None:
    con.execute(
        """
        insert or replace into ai_extractions(
            study_id, usable_for_strategy, confidence, strategy_family, hypothesis,
            signal_logic_plain, tradable_assets_json, required_features_json,
            expected_holding_period, overfitting_risks_json, reason_to_test, raw_json, ai_error
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            study_id,
            1 if extraction["usable_for_strategy"] else 0,
            float(extraction["confidence"]),
            extraction["strategy_family"],
            extraction["hypothesis"],
            extraction["signal_logic_plain"],
            json.dumps(extraction["tradable_assets"], ensure_ascii=False),
            json.dumps(extraction["required_features"], ensure_ascii=False),
            extraction["expected_holding_period"],
            json.dumps(extraction["overfitting_risks"], ensure_ascii=False),
            extraction["reason_to_test"],
            json.dumps(extraction, ensure_ascii=False, default=str),
            extraction.get("ai_error"),
        ),
    )


def _ideas_from_extraction(
    canonical_id: str,
    study: dict[str, Any],
    extraction: dict[str, Any],
) -> list[dict[str, Any]]:
    if not extraction.get("usable_for_strategy"):
        return []
    features = [str(item) for item in extraction["required_features"]]
    supported, missing = _feature_support(features)
    family = str(extraction["strategy_family"])
    idea_id = f"lit_{_safe_filename(canonical_id).lower()}_{_safe_filename(family).lower()}"[:140]
    status = "ready_to_test" if supported else "pending_data"
    return [
        {
            "idea_id": idea_id,
            "strategy_family": family,
            "hypothesis": extraction["hypothesis"],
            "rule_plain": extraction["signal_logic_plain"],
            "tradable_assets": extraction["tradable_assets"],
            "required_features": features,
            "periodicity": extraction["expected_holding_period"],
            "aurora_supported": supported,
            "data_status": status,
            "confidence": float(extraction["confidence"]),
            "reason_to_test": extraction["reason_to_test"],
            "status": status,
            "missing_features": missing,
            "study_title": _title(study),
        }
    ]


def _insert_strategy_idea(con: sqlite3.Connection, idea: dict[str, Any], study_id: str) -> None:
    con.execute(
        """
        insert or replace into strategy_ideas(
            idea_id, strategy_family, hypothesis, rule_plain, tradable_assets_json,
            required_features_json, periodicity, aurora_supported, data_status,
            confidence, reason_to_test, status, locked_opened
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            idea["idea_id"],
            idea["strategy_family"],
            idea["hypothesis"],
            idea["rule_plain"],
            json.dumps(idea["tradable_assets"], ensure_ascii=False),
            json.dumps(idea["required_features"], ensure_ascii=False),
            idea["periodicity"],
            1 if idea["aurora_supported"] else 0,
            idea["data_status"],
            float(idea["confidence"]),
            idea["reason_to_test"],
            idea["status"],
            0,
        ),
    )
    con.execute(
        "insert or ignore into idea_sources(idea_id, study_id) values (?, ?)",
        (idea["idea_id"], study_id),
    )


def _insert_unsupported_data(con: sqlite3.Connection, idea: dict[str, Any]) -> None:
    con.execute(
        "insert or replace into unsupported_data(idea_id, missing_features_json, reason) values (?, ?, ?)",
        (
            idea["idea_id"],
            json.dumps(idea["missing_features"], ensure_ascii=False),
            "Required data is not currently mapped to Aurora-supported public features.",
        ),
    )


def _record_failure(
    con: sqlite3.Connection,
    failures_path: Path,
    stage: str,
    subject: str,
    error: str,
) -> None:
    payload = {"stage": stage, "subject": subject, "error": error, "created_at_utc": _now()}
    con.execute(
        "insert into failures(stage, subject, error, created_at_utc) values (?, ?, ?, ?)",
        (payload["stage"], payload["subject"], payload["error"], payload["created_at_utc"]),
    )
    _append_jsonl(failures_path, payload)


def _export_artifacts(sqlite_path: Path, output_dir: Path) -> None:
    exports = {
        "studies_all.csv": "select * from studies order by score desc",
        "studies_enriched.csv": (
            "select s.*, p.pdf_available, p.text_chars from studies s "
            "join paper_texts p on s.study_id=p.study_id order by s.score desc"
        ),
        "strategy_ideas_all.csv": "select * from strategy_ideas order by confidence desc",
        "ideas_ready_to_test.csv": (
            "select * from strategy_ideas where aurora_supported=1 order by confidence desc"
        ),
        "ideas_pending_data.csv": (
            "select * from strategy_ideas where aurora_supported=0 order by confidence desc"
        ),
        "failures_report.csv": "select * from failures order by created_at_utc",
        "query_coverage.csv": "select * from search_queries order by family, query, sort, page",
    }
    with sqlite3.connect(sqlite_path) as con:
        for filename, query in exports.items():
            _write_csv(output_dir / filename, con.execute(query))
        coverage = {
            "locked_opened": False,
            "backtest_enabled": False,
            "queries": con.execute("select count(*) from search_queries").fetchone()[0],
            "studies": con.execute("select count(*) from studies").fetchone()[0],
            "enriched": con.execute("select count(*) from paper_texts").fetchone()[0],
            "ideas_total": con.execute("select count(*) from strategy_ideas").fetchone()[0],
            "ideas_ready_to_test": con.execute(
                "select count(*) from strategy_ideas where aurora_supported=1"
            ).fetchone()[0],
            "ideas_pending_data": con.execute(
                "select count(*) from strategy_ideas where aurora_supported=0"
            ).fetchone()[0],
            "failures": con.execute("select count(*) from failures").fetchone()[0],
        }
        _write_json(output_dir / "coverage_report.json", coverage)


def _write_csv(path: Path, cursor: sqlite3.Cursor) -> None:
    rows = cursor.fetchall()
    headers = [desc[0] for desc in cursor.description or []]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _canonical_study_id(study: dict[str, Any], canonical_by_key: dict[str, str]) -> str:
    keys = _dedupe_keys(study)
    for key in keys:
        if key in canonical_by_key:
            canonical = canonical_by_key[key]
            for alias in keys:
                canonical_by_key.setdefault(alias, canonical)
            return canonical
    canonical = _study_id(study)
    for key in keys:
        canonical_by_key[key] = canonical
    return canonical


def _dedupe_keys(study: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    openalex = _str_or_none(study.get("openalex_id") or study.get("id"))
    if openalex:
        keys.append(f"openalex:{openalex.lower().rstrip('/')}")
    doi = _normalise_doi(study.get("doi"))
    if doi:
        keys.append(f"doi:{doi}")
    title = _normalise_title(_title(study))
    year = _int_or_none(study.get("year"))
    author = _first_author(study)
    if title:
        keys.append(f"title:{title}")
    if title and year:
        keys.append(f"title_year:{title}:{year}")
    if title and author:
        keys.append(f"title_author:{title}:{author}")
    return list(dict.fromkeys(keys)) or [f"fallback:{_study_id(study).lower()}"]


def _normalise_extraction(payload: dict[str, Any], study: dict[str, Any], *, ai_error: str | None) -> dict[str, Any]:
    text = _metadata_text(study)
    features = payload.get("required_features", payload.get("features", []))
    if not isinstance(features, list):
        features = []
    assets = payload.get("tradable_assets", payload.get("assets", []))
    if not isinstance(assets, list):
        assets = []
    risks = payload.get("overfitting_risks", [])
    if not isinstance(risks, list):
        risks = [str(risks)]
    confidence = max(0.0, min(1.0, _float_or(payload.get("confidence"), 0.45)))
    family = str(payload.get("strategy_family") or _family_from_text(text)).strip() or "market_timing"
    hypothesis = str(payload.get("hypothesis") or _hypothesis_from_text(text)).strip()
    signal = str(payload.get("signal_logic_plain") or _signal_logic_from_features(features)).strip()
    return {
        "study_id": _study_id(study),
        "title": _title(study),
        "usable_for_strategy": bool(payload.get("usable_for_strategy", confidence >= 0.45)),
        "confidence": confidence,
        "strategy_family": family[:100],
        "hypothesis": hypothesis[:1200],
        "required_features": [str(feature).strip() for feature in features if str(feature).strip()][:30],
        "tradable_assets": [str(asset).strip().upper() for asset in assets if str(asset).strip()][:30]
        or _assets_from_text(text),
        "signal_logic_plain": signal[:1200],
        "expected_holding_period": str(payload.get("expected_holding_period") or "daily_to_monthly")[:100],
        "overfitting_risks": [str(risk)[:300] for risk in risks[:12]],
        "reason_to_test": str(payload.get("reason_to_test") or payload.get("test_priority") or "literature_supported")[:500],
        "ai_error": ai_error,
    }


def _heuristic_extraction(study: dict[str, Any], text: str) -> dict[str, Any]:
    full_text = f"{_metadata_text(study)} {text}".lower()
    features = _features_from_text(full_text)
    return {
        "usable_for_strategy": bool(features),
        "confidence": 0.65 if len(features) >= 3 else 0.45,
        "strategy_family": _family_from_text(full_text),
        "hypothesis": _hypothesis_from_text(full_text),
        "required_features": features,
        "tradable_assets": _assets_from_text(full_text),
        "signal_logic_plain": _signal_logic_from_features(features),
        "expected_holding_period": "daily_to_monthly",
        "overfitting_risks": ["publication bias", "multiple testing", "data availability mismatch"],
        "reason_to_test": "mentions tradable market timing inputs in public literature",
    }


def _feature_support(features: list[str]) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for feature in features:
        text = feature.lower()
        if not any(token in text for token in SUPPORTED_AURORA_FEATURE_TOKENS):
            missing.append(feature)
    return not missing, missing


def _features_from_text(text: str) -> list[str]:
    found = [feature for token, feature in SUPPORTED_AURORA_FEATURE_TOKENS.items() if token in text]
    return list(dict.fromkeys(found))


def _assets_from_text(text: str) -> list[str]:
    checks = ("SPY", "QQQ", "IWM", "TLT", "IEF", "HYG", "LQD", "GLD", "SLV", "UUP", "DBC")
    upper = text.upper()
    found = [asset for asset in checks if asset in upper]
    if not found and any(token in text.lower() for token in ("stock", "equity", "market")):
        found.append("SPY")
    return found


def _family_from_text(text: str) -> str:
    lowered = text.lower()
    for family in LITERATURE_QUERY_BANK:
        if family.replace("_", " ") in lowered:
            return family
    if "vix" in lowered or "volatility" in lowered:
        return "volatility_timing"
    if "credit" in lowered or "spread" in lowered:
        return "credit_spreads"
    if "yield" in lowered or "curve" in lowered:
        return "yield_curve"
    if "sector" in lowered:
        return "sector_rotation"
    if "machine learning" in lowered:
        return "machine_learning_asset_pricing"
    return "market_timing"


def _hypothesis_from_text(text: str) -> str:
    lowered = text.lower()
    if "credit" in lowered:
        return "Credit stress may identify equity risk-on/risk-off regimes."
    if "vix" in lowered or "volatility" in lowered:
        return "Volatility regimes may improve market exposure decisions."
    if "yield" in lowered or "curve" in lowered:
        return "Yield-curve signals may forecast broad asset return regimes."
    if "momentum" in lowered or "trend" in lowered:
        return "Trend and momentum signals may identify persistent return regimes."
    return "Literature-backed signal may generate a testable trading rule."


def _signal_logic_from_features(features: list[Any]) -> str:
    joined = " ".join(str(feature).lower() for feature in features)
    if "credit" in joined or "vix" in joined or "vol" in joined:
        return "Increase risky exposure when stress improves; reduce risky exposure when stress worsens."
    if "yield" in joined or "macro" in joined or "inflation" in joined:
        return "Use macro regime improvement or deterioration to alter market exposure."
    return "Convert the documented signal into a causal rule using only data known before the trade."


def _ai_prompt(study: dict[str, Any], text: str) -> str:
    return (
        "Devuelve SOLO JSON valido. Extrae ideas de estrategia rentable de este estudio para Aurora. "
        "No propongas backtest, no uses validacion, no uses locked, no uses futuro. "
        "Campos obligatorios: usable_for_strategy, confidence, strategy_family, hypothesis, "
        "signal_logic_plain, tradable_assets, required_features, expected_holding_period, "
        "overfitting_risks, reason_to_test. Si faltan datos para probarlo, deja la idea clara igualmente. "
        f"METADATOS={json.dumps(_study_brief(study), ensure_ascii=False, default=str)}\n"
        f"TEXTO={text[:120000]}"
    )


def _external_ai_configured() -> bool:
    if os.environ.get("AURORA_PAPER_AI_COMMAND", "").strip():
        return True
    provider = os.environ.get("AURORA_PAPER_AI_PROVIDER", "").strip().lower()
    if provider == "openai":
        return bool(
            os.environ.get("OPENAI_API_KEY", "").strip()
            and os.environ.get("AURORA_PAPER_AI_MODEL", "").strip()
        )
    return bool(os.environ.get("AURORA_CODEX_BIN", "").strip())


def _study_score(study: dict[str, Any]) -> float:
    text = _metadata_text(study).lower()
    relevance = sum(1.0 for token in SUPPORTED_AURORA_FEATURE_TOKENS if token in text)
    citations = max(0, _int_or_none(study.get("citations_count")) or 0) ** 0.5
    year = _int_or_none(study.get("year")) or 0
    recency = max(0.0, min(4.0, (year - 1980) / 12.0)) if year else 0.0
    oa_bonus = 1.0 if bool(study.get("is_oa", study.get("is_open_access", False))) else 0.0
    return relevance * 3.0 + citations + recency + oa_bonus


def _metadata_text(study: dict[str, Any]) -> str:
    parts = [_title(study), str(study.get("abstract", "")), _venue(study)]
    for key in ("concepts", "keywords"):
        value = study.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(parts)


def _study_brief(study: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _study_id(study),
        "title": _title(study),
        "year": study.get("year"),
        "doi": study.get("doi"),
        "venue": _venue(study),
        "abstract": str(study.get("abstract", ""))[:4000],
    }


def _query_key(family: str, query: str, sort: str, page: int) -> str:
    return f"{family}:{sort}:{page}:{_safe_filename(query).lower()}"


def _short_id(value: Any) -> str | None:
    text = _str_or_none(value)
    if not text:
        return None
    return text.rstrip("/").rsplit("/", 1)[-1]


def _abstract_from_openalex(inverted: Any) -> str:
    if not isinstance(inverted, dict):
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            try:
                positions[int(index)] = str(word)
            except (TypeError, ValueError):
                continue
    return " ".join(positions[index] for index in sorted(positions))


def _study_id(study: dict[str, Any]) -> str:
    for key in ("openalex_id", "id", "doi"):
        value = _str_or_none(study.get(key))
        if value:
            return value[:180]
    return _safe_filename(_title(study))[:180]


def _title(study: dict[str, Any]) -> str:
    return str(study.get("title", "")).strip()[:1000] or "(untitled)"


def _venue(study: dict[str, Any]) -> str:
    for key in ("venue", "journal", "source"):
        value = _str_or_none(study.get(key))
        if value:
            return value[:500]
    return ""


def _first_author(study: dict[str, Any]) -> str:
    authors = study.get("authors", [])
    if isinstance(authors, list) and authors:
        first = authors[0]
        if isinstance(first, dict):
            return _normalise_title(str(first.get("name", "")))
        return _normalise_title(str(first))
    return ""


def _extract_json_object(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("empty JSON output")
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for idx, char in enumerate(raw):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(raw[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("no JSON object found")


def _normalise_doi(value: Any) -> str | None:
    text = _str_or_none(value)
    if not text:
        return None
    text = text.lower().replace("https://doi.org/", "").replace("http://doi.org/", "")
    return text.strip()


def _normalise_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[:140].strip("_") or "item"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _log_progress(event: str, **payload: Any) -> None:
    print(json.dumps({"event": event, **payload}, ensure_ascii=False, default=str), flush=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "LITERATURE_QUERY_BANK",
    "LiteratureCorpusBuildConfig",
    "LiteratureCorpusBuildReport",
    "run_literature_corpus_build",
]
