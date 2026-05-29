"""Build a SP500 literature corpus for later strategy testing.

This module deliberately does not run strategy backtests. It searches papers,
enriches the selected corpus with legal PDFs/summaries when available, extracts
structured strategy ideas, and writes a SQLite ledger for later Aurora runs.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from aurora.core.runtime_paths import base_data_dir
from aurora.research.agent_loop.estudios_bridge import (
    ESTUDIOS_PYTHON_ENV,
    ESTUDIOS_ROOT_ENV,
    EstudiosAvailability,
    _estudios_python,
    _estudios_root,
    _run_paper_ai,
    estudios_availability,
)


Runner = Callable[[list[str], Path, int], str]
AIExtractor = Callable[[str, int], str]


SP500_LITERATURE_QUERIES: tuple[str, ...] = (
    "SP500 market timing",
    "Equity market timing",
    "Tactical asset allocation",
    "Volatility timing",
    "VIX and equity returns",
    "Credit spreads and stock returns",
    "Yield curve and equity returns",
    "Momentum and reversal",
    "Macro predictors stock market",
    "Regime switching equity",
    "Financial conditions and stock returns",
    "Cross-asset risk appetite",
    "Sector rotation SP500",
    "Anomaly decay factor timing",
    "Machine learning empirical asset pricing",
)


@dataclass(frozen=True)
class SP500LiteratureBuildConfig:
    run_id: str
    symbol: str = "SPY"
    max_studies: int = 200
    pdf_mode: str = "full-if-available"
    output: str = "sqlite"
    run_root: str | None = None
    no_locked: bool = True
    per_query: int = 20
    timeout_seconds: int = 180
    ai_timeout_seconds: int = 300


@dataclass(frozen=True)
class SP500LiteratureBuildReport:
    run_id: str
    status: str
    locked_opened: bool
    estudios_available: bool
    estudios_root: str
    estudios_python: str
    availability_reason: str
    output_dir: str
    sqlite_path: str
    status_path: str
    markdown_report_path: str
    studies_found: int
    studies_selected: int
    pdf_available_count: int
    ai_extractions_count: int
    strategy_ideas_count: int
    failures_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_sp500_literature_build(
    config: SP500LiteratureBuildConfig,
    *,
    runner: Runner | None = None,
    ai_extractor: AIExtractor | None = None,
) -> SP500LiteratureBuildReport:
    if not config.no_locked:
        raise ValueError("sp500-literature-build requires --no-locked")
    if config.output != "sqlite":
        raise ValueError("sp500-literature-build v1 only supports --output sqlite")
    if config.pdf_mode != "full-if-available":
        raise ValueError("sp500-literature-build v1 only supports --pdf-mode full-if-available")
    if config.max_studies < 1:
        raise ValueError("max_studies must be >= 1")

    root = _estudios_root()
    python_bin = _estudios_python(root)
    availability = estudios_availability(
        root=root,
        python_bin=python_bin,
        verify_command=runner is None,
    )
    if runner is None:
        if not availability.available:
            raise RuntimeError(
                "ESTUDIOS unavailable for sp500-literature-build: "
                f"{availability.reason}. Set {ESTUDIOS_ROOT_ENV} and/or {ESTUDIOS_PYTHON_ENV}."
            )
    run = runner or _run_estudios
    output_dir = _output_dir(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = output_dir / "literature.sqlite"
    status_path = output_dir / "status.json"
    progress_path = output_dir / "progress.jsonl"
    failed_path = output_dir / "failed_papers.jsonl"
    queries_path = output_dir / "search_queries.json"
    report_path = output_dir / "literature_report.md"

    _write_json(queries_path, list(SP500_LITERATURE_QUERIES))
    _write_status(
        status_path,
        config,
        output_dir,
        availability=availability,
        status="running",
        studies_found=0,
        studies_selected=0,
        pdf_available_count=0,
        ai_extractions_count=0,
        strategy_ideas_count=0,
        failures_count=0,
    )
    _init_db(sqlite_path)

    found: dict[str, dict[str, Any]] = {}
    seen_keys: set[str] = set()
    failures = 0
    for query in SP500_LITERATURE_QUERIES:
        _append_jsonl(progress_path, {"event": "search_started", "query": query, "locked_opened": False})
        cmd = [
            str(python_bin),
            "-m",
            "estudios",
            "search",
            query,
            "--json",
            "--per-page",
            str(int(config.per_query)),
        ]
        try:
            payload = _extract_json_object(run(cmd, root, int(config.timeout_seconds)))
            studies = payload.get("studies", [])
            if not isinstance(studies, list):
                raise ValueError("invalid studies payload")
        except Exception as exc:
            failures += 1
            _record_failure(sqlite_path, failed_path, "search", query, str(exc))
            continue
        with sqlite3.connect(sqlite_path) as con:
            for study in studies:
                if not isinstance(study, dict):
                    continue
                keys = _dedupe_keys(study)
                if not keys or seen_keys.intersection(keys):
                    continue
                key = keys[0]
                found[key] = study
                seen_keys.update(keys)
                _insert_search_result(con, query, study, key)
        _append_jsonl(
            progress_path,
            {"event": "search_completed", "query": query, "studies_total": len(found), "locked_opened": False},
        )

    ranked = sorted(found.values(), key=_study_score, reverse=True)
    selected = ranked[: int(config.max_studies)]
    with sqlite3.connect(sqlite_path) as con:
        for index, study in enumerate(ranked, start=1):
            _insert_study(con, study, selected=index <= len(selected), rank=index)

    pdf_available_count = 0
    ai_extractions_count = 0
    strategy_ideas_count = 0
    for index, study in enumerate(selected, start=1):
        study_id = _study_id(study)
        _append_jsonl(
            progress_path,
            {
                "event": "study_enrichment_started",
                "study_id": study_id,
                "index": index,
                "total": len(selected),
                "locked_opened": False,
            },
        )
        try:
            text_info = _enrich_text(
                study,
                python_bin=python_bin,
                root=root,
                output_dir=output_dir,
                runner=run,
                timeout_seconds=int(config.timeout_seconds),
            )
            if text_info["pdf_available"]:
                pdf_available_count += 1
            extraction = _extract_strategy_card(
                study,
                text=str(text_info.get("text", "")),
                ai_extractor=ai_extractor,
                timeout_seconds=int(config.ai_timeout_seconds),
            )
            if extraction:
                ai_extractions_count += 1
            ideas = _ideas_from_extraction(study, extraction)
            strategy_ideas_count += len(ideas)
            with sqlite3.connect(sqlite_path) as con:
                _insert_paper_text(con, study_id, text_info)
                _insert_ai_extraction(con, study_id, extraction)
                for idea in ideas:
                    _insert_strategy_idea(con, idea, study_id)
        except Exception as exc:
            failures += 1
            _record_failure(sqlite_path, failed_path, "enrich", study_id, str(exc))
            continue
        _write_status(
            status_path,
            config,
            output_dir,
            availability=availability,
            status="running",
            studies_found=len(found),
            studies_selected=len(selected),
            pdf_available_count=pdf_available_count,
            ai_extractions_count=ai_extractions_count,
            strategy_ideas_count=strategy_ideas_count,
            failures_count=failures,
        )

    report = SP500LiteratureBuildReport(
        run_id=config.run_id,
        status="completed",
        locked_opened=False,
        estudios_available=availability.available,
        estudios_root=availability.root,
        estudios_python=availability.python,
        availability_reason=availability.reason,
        output_dir=str(output_dir),
        sqlite_path=str(sqlite_path),
        status_path=str(status_path),
        markdown_report_path=str(report_path),
        studies_found=len(found),
        studies_selected=len(selected),
        pdf_available_count=pdf_available_count,
        ai_extractions_count=ai_extractions_count,
        strategy_ideas_count=strategy_ideas_count,
        failures_count=failures,
    )
    _write_report(report_path, report, sqlite_path)
    _write_json(status_path, report.to_dict() | {"locked_opened": False})
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


def _output_dir(config: SP500LiteratureBuildConfig) -> Path:
    if config.run_root:
        return Path(config.run_root) / config.run_id / "literature_pipeline"
    return base_data_dir() / "agent_loop" / config.run_id / "literature_pipeline"


def _init_db(path: Path) -> None:
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            create table if not exists studies (
                study_id text primary key,
                dedupe_key text not null,
                title text not null,
                year integer,
                doi text,
                venue text,
                abstract text,
                citations_count integer,
                is_open_access integer not null,
                score real not null,
                selected integer not null,
                rank integer not null,
                raw_json text not null
            );
            create table if not exists search_results (
                query text not null,
                study_id text not null,
                dedupe_key text not null,
                title text not null,
                raw_json text not null
            );
            create table if not exists paper_texts (
                study_id text primary key,
                pdf_attempted integer not null,
                pdf_available integer not null,
                pdf_output text,
                summary_path text,
                text_chars integer not null,
                text_excerpt text not null
            );
            create table if not exists ai_extractions (
                study_id text primary key,
                usable_for_strategy integer not null,
                confidence real not null,
                strategy_family text not null,
                hypothesis text not null,
                signal_logic_plain text not null,
                expected_holding_period text not null,
                test_priority text not null,
                overfitting_risks_json text not null,
                required_features_json text not null,
                raw_json text not null,
                ai_error text
            );
            create table if not exists strategy_ideas (
                idea_id text primary key,
                strategy_family text not null,
                hypothesis text not null,
                signal_logic_plain text not null,
                expected_holding_period text not null,
                test_priority text not null,
                confidence real not null,
                complexity text not null,
                overfitting_risk text not null
            );
            create table if not exists idea_sources (
                idea_id text not null,
                study_id text not null,
                primary key (idea_id, study_id)
            );
            create table if not exists feature_mappings (
                idea_id text not null,
                source_feature text not null,
                aurora_feature text not null
            );
            create table if not exists failures (
                stage text not null,
                subject text not null,
                error text not null,
                created_at_utc text not null
            );
            """
        )


def _insert_search_result(con: sqlite3.Connection, query: str, study: dict[str, Any], key: str) -> None:
    con.execute(
        "insert into search_results(query, study_id, dedupe_key, title, raw_json) values (?, ?, ?, ?, ?)",
        (query, _study_id(study), key, _title(study), json.dumps(study, ensure_ascii=False, default=str)),
    )


def _insert_study(con: sqlite3.Connection, study: dict[str, Any], *, selected: bool, rank: int) -> None:
    study_id = _study_id(study)
    con.execute(
        """
        insert or replace into studies(
            study_id, dedupe_key, title, year, doi, venue, abstract, citations_count,
            is_open_access, score, selected, rank, raw_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            study_id,
            _dedupe_key(study),
            _title(study),
            _int_or_none(study.get("year")),
            _str_or_none(study.get("doi")),
            _venue(study),
            str(study.get("abstract", "")),
            _int_or_none(study.get("citations_count")),
            1 if bool(study.get("is_oa", study.get("is_open_access", False))) else 0,
            _study_score(study),
            1 if selected else 0,
            int(rank),
            json.dumps(study, ensure_ascii=False, default=str),
        ),
    )


def _enrich_text(
    study: dict[str, Any],
    *,
    python_bin: Path,
    root: Path,
    output_dir: Path,
    runner: Runner,
    timeout_seconds: int,
) -> dict[str, Any]:
    study_id = _study_id(study)
    safe_id = _safe_filename(study_id)
    pdf_attempted = True
    pdf_available = False
    pdf_output = ""
    try:
        runner([str(python_bin), "-m", "estudios", "save", study_id], root, timeout_seconds)
    except Exception:
        pass
    try:
        pdf_output = runner([str(python_bin), "-m", "estudios", "pdf", study_id], root, timeout_seconds)
        pdf_available = "no disponible" not in pdf_output.lower()
    except Exception as exc:
        pdf_output = str(exc)
        pdf_available = False
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
    except Exception:
        text = _metadata_text(study)
    if not text.strip():
        text = _metadata_text(study)
    return {
        "pdf_attempted": pdf_attempted,
        "pdf_available": pdf_available,
        "pdf_output": pdf_output[-2000:],
        "summary_path": str(summary_path) if summary_path.exists() else None,
        "text": text[:250_000],
    }


def _insert_paper_text(con: sqlite3.Connection, study_id: str, text_info: dict[str, Any]) -> None:
    text = str(text_info.get("text", ""))
    con.execute(
        """
        insert or replace into paper_texts(
            study_id, pdf_attempted, pdf_available, pdf_output, summary_path, text_chars, text_excerpt
        ) values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            study_id,
            1 if text_info.get("pdf_attempted") else 0,
            1 if text_info.get("pdf_available") else 0,
            str(text_info.get("pdf_output") or ""),
            text_info.get("summary_path"),
            len(text),
            text[:20_000],
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
        fallback = _heuristic_extraction(study, text)
        return _normalise_extraction(fallback, study, ai_error=str(exc))


def _external_ai_configured() -> bool:
    return bool(
        os.environ.get("AURORA_PAPER_AI_COMMAND", "").strip()
        or os.environ.get("AURORA_PAPER_AI_PROVIDER", "").strip()
        or os.environ.get("AURORA_CODEX_BIN", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )


def _insert_ai_extraction(con: sqlite3.Connection, study_id: str, extraction: dict[str, Any]) -> None:
    con.execute(
        """
        insert or replace into ai_extractions(
            study_id, usable_for_strategy, confidence, strategy_family, hypothesis,
            signal_logic_plain, expected_holding_period, test_priority,
            overfitting_risks_json, required_features_json, raw_json, ai_error
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            study_id,
            1 if extraction["usable_for_strategy"] else 0,
            float(extraction["confidence"]),
            extraction["strategy_family"],
            extraction["hypothesis"],
            extraction["signal_logic_plain"],
            extraction["expected_holding_period"],
            extraction["test_priority"],
            json.dumps(extraction["overfitting_risks"], ensure_ascii=False),
            json.dumps(extraction["required_features"], ensure_ascii=False),
            json.dumps(extraction, ensure_ascii=False, default=str),
            extraction.get("ai_error"),
        ),
    )


def _ideas_from_extraction(study: dict[str, Any], extraction: dict[str, Any]) -> list[dict[str, Any]]:
    if not extraction.get("usable_for_strategy"):
        return []
    family = str(extraction["strategy_family"])
    idea_id = f"lit_{_safe_filename(_study_id(study)).lower()}_{_safe_filename(family).lower()}"[:120]
    return [
        {
            "idea_id": idea_id,
            "study_id": _study_id(study),
            "strategy_family": family,
            "hypothesis": extraction["hypothesis"],
            "signal_logic_plain": extraction["signal_logic_plain"],
            "expected_holding_period": extraction["expected_holding_period"],
            "test_priority": extraction["test_priority"],
            "confidence": float(extraction["confidence"]),
            "complexity": _complexity(extraction),
            "overfitting_risk": _overfitting_risk_label(extraction),
            "features": list(extraction["required_features"]),
        }
    ]


def _insert_strategy_idea(con: sqlite3.Connection, idea: dict[str, Any], study_id: str) -> None:
    con.execute(
        """
        insert or replace into strategy_ideas(
            idea_id, strategy_family, hypothesis, signal_logic_plain,
            expected_holding_period, test_priority, confidence, complexity, overfitting_risk
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            idea["idea_id"],
            idea["strategy_family"],
            idea["hypothesis"],
            idea["signal_logic_plain"],
            idea["expected_holding_period"],
            idea["test_priority"],
            float(idea["confidence"]),
            idea["complexity"],
            idea["overfitting_risk"],
        ),
    )
    con.execute(
        "insert or ignore into idea_sources(idea_id, study_id) values (?, ?)",
        (idea["idea_id"], study_id),
    )
    for source_feature in idea.get("features", []):
        for aurora_feature in _map_feature(str(source_feature)):
            con.execute(
                "insert into feature_mappings(idea_id, source_feature, aurora_feature) values (?, ?, ?)",
                (idea["idea_id"], str(source_feature), aurora_feature),
            )


def _record_failure(db_path: Path, failed_path: Path, stage: str, subject: str, error: str) -> None:
    payload = {
        "stage": stage,
        "subject": subject,
        "error": error,
        "created_at_utc": _now(),
    }
    _append_jsonl(failed_path, payload)
    with sqlite3.connect(db_path) as con:
        con.execute(
            "insert into failures(stage, subject, error, created_at_utc) values (?, ?, ?, ?)",
            (stage, subject, error, payload["created_at_utc"]),
        )


def _write_report(path: Path, report: SP500LiteratureBuildReport, db_path: Path) -> None:
    top_ideas: list[tuple[str, str, float]] = []
    with sqlite3.connect(db_path) as con:
        for row in con.execute(
            "select idea_id, strategy_family, confidence from strategy_ideas "
            "order by test_priority='high' desc, confidence desc limit 15"
        ):
            top_ideas.append((str(row[0]), str(row[1]), float(row[2])))
    lines = [
        "# SP500 Literature Corpus",
        "",
        f"Run ID: `{report.run_id}`",
        f"Locked abierto: {str(report.locked_opened).lower()}",
        f"ESTUDIOS disponible: {str(report.estudios_available).lower()}",
        f"ESTUDIOS root: `{report.estudios_root}`",
        f"ESTUDIOS python: `{report.estudios_python}`",
        f"Disponibilidad motivo: `{report.availability_reason}`",
        f"Estudios encontrados: {report.studies_found}",
        f"Estudios seleccionados: {report.studies_selected}",
        f"PDFs disponibles: {report.pdf_available_count}",
        f"Extracciones IA/estructuradas: {report.ai_extractions_count}",
        f"Ideas generadas: {report.strategy_ideas_count}",
        f"Fallos registrados: {report.failures_count}",
        "",
        "## Mejores Ideas",
    ]
    if top_ideas:
        lines.extend(["", "| Idea | Familia | Confianza |", "|---|---:|---:|"])
        lines.extend(f"| `{idea}` | {family} | {confidence:.2f} |" for idea, family, confidence in top_ideas)
    else:
        lines.append("")
        lines.append("No hay ideas utilizables todavía.")
    lines.extend([
        "",
        "## Siguiente Paso",
        "Usar `literature.sqlite` como cola para probar ideas en train y validacion, manteniendo locked cerrado.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_status(
    path: Path,
    config: SP500LiteratureBuildConfig,
    output_dir: Path,
    *,
    availability: EstudiosAvailability,
    status: str,
    studies_found: int,
    studies_selected: int,
    pdf_available_count: int,
    ai_extractions_count: int,
    strategy_ideas_count: int,
    failures_count: int,
) -> None:
    _write_json(
        path,
        {
            "run_id": config.run_id,
            "symbol": config.symbol,
            "status": status,
            "locked_opened": False,
            "estudios_available": availability.available,
            "estudios_root": availability.root,
            "estudios_python": availability.python,
            "availability_reason": availability.reason,
            "max_studies": config.max_studies,
            "pdf_mode": config.pdf_mode,
            "output": config.output,
            "output_dir": str(output_dir),
            "studies_found": studies_found,
            "studies_selected": studies_selected,
            "pdf_available_count": pdf_available_count,
            "ai_extractions_count": ai_extractions_count,
            "strategy_ideas_count": strategy_ideas_count,
            "failures_count": failures_count,
            "updated_at_utc": _now(),
        },
    )


def _study_score(study: dict[str, Any]) -> float:
    text = _metadata_text(study).lower()
    relevance = sum(
        1.0
        for token in (
            "s&p",
            "sp500",
            "stock",
            "equity",
            "market timing",
            "volatility",
            "vix",
            "credit",
            "yield",
            "momentum",
            "regime",
            "asset pricing",
            "factor",
        )
        if token in text
    )
    citations = math.log1p(max(0, _int_or_none(study.get("citations_count")) or 0))
    year = _int_or_none(study.get("year")) or 0
    recency = max(0.0, min(3.0, (year - 1990) / 12.0)) if year else 0.0
    pdf_bonus = 1.0 if bool(study.get("is_oa", study.get("is_open_access", False))) else 0.0
    generic_penalty = 3.0 if "survey" in text and relevance < 3 else 0.0
    return relevance * 3.0 + citations + recency + pdf_bonus - generic_penalty


def _normalise_extraction(payload: dict[str, Any], study: dict[str, Any], *, ai_error: str | None) -> dict[str, Any]:
    text = _metadata_text(study)
    features = payload.get("required_features", payload.get("features", []))
    if not isinstance(features, list):
        features = []
    risks = payload.get("overfitting_risks", [])
    if not isinstance(risks, list):
        risks = [str(risks)]
    confidence = _float_or(payload.get("confidence"), 0.45)
    usable = bool(payload.get("usable_for_strategy", confidence >= 0.45))
    family = str(payload.get("strategy_family") or _family_from_text(text)).strip() or "trend_stress_combo"
    hypothesis = str(payload.get("hypothesis") or _hypothesis_from_text(text)).strip()
    signal = str(payload.get("signal_logic_plain") or _signal_logic_from_features(features)).strip()
    return {
        "study_id": _study_id(study),
        "title": _title(study),
        "usable_for_strategy": usable,
        "confidence": max(0.0, min(1.0, confidence)),
        "strategy_family": family[:80],
        "hypothesis": hypothesis[:1000],
        "required_features": [str(feature).strip() for feature in features if str(feature).strip()][:20],
        "signal_logic_plain": signal[:1000],
        "expected_holding_period": str(payload.get("expected_holding_period") or "daily_to_monthly")[:80],
        "overfitting_risks": [str(risk)[:300] for risk in risks[:10]],
        "test_priority": _priority(payload.get("test_priority"), confidence),
        "ai_error": ai_error,
    }


def _heuristic_extraction(study: dict[str, Any], text: str) -> dict[str, Any]:
    full_text = f"{_metadata_text(study)} {text}".lower()
    features = _features_from_text(full_text)
    confidence = 0.65 if len(features) >= 3 else 0.45
    return {
        "usable_for_strategy": bool(features),
        "confidence": confidence,
        "strategy_family": _family_from_text(full_text),
        "hypothesis": _hypothesis_from_text(full_text),
        "required_features": features,
        "signal_logic_plain": _signal_logic_from_features(features),
        "expected_holding_period": "daily_to_monthly",
        "overfitting_risks": ["multiple testing", "threshold mining", "publication bias"],
        "test_priority": "high" if confidence >= 0.6 else "medium",
    }


def _features_from_text(text: str) -> list[str]:
    checks = [
        ("vix", "vix"),
        ("volatility", "realized_volatility"),
        ("credit", "credit_spread"),
        ("spread", "credit_spread"),
        ("yield", "yield_curve"),
        ("curve", "yield_curve"),
        ("momentum", "spy_momentum"),
        ("trend", "spy_momentum"),
        ("sector", "sector_rotation"),
        ("quality", "quality_factor"),
        ("value", "value_factor"),
        ("liquidity", "liquidity"),
        ("regime", "market_regime"),
        ("inflation", "inflation"),
        ("macro", "macro_cycle"),
    ]
    features: list[str] = []
    for token, feature in checks:
        if token in text:
            features.append(feature)
    return list(dict.fromkeys(features)) or ["spy_momentum", "market_regime"]


def _map_feature(feature: str) -> list[str]:
    text = feature.lower()
    mapping = {
        "vix": ["pending_yf_vix_level", "pending_yf_vix_ret_5"],
        "vol": ["roll_std_20", "pending_vol_garman_klass_20"],
        "credit": ["cs_spread", "pending_yf_hyg_ret_5"],
        "spread": ["cs_spread"],
        "yield": ["yc_10y_2y", "pending_yf_tnx_ret_5"],
        "curve": ["yc_10y_2y"],
        "momentum": ["ret_lag_21", "ret_lag_63"],
        "trend": ["roll_mean_20", "roll_mean_60"],
        "sector": ["pending_yf_xlu_ret_21", "pending_yf_xle_ret_21"],
        "quality": ["pending_quality_proxy"],
        "value": ["pending_value_proxy"],
        "liquidity": ["pending_dollar_volume", "pending_relative_volume_20"],
        "regime": ["roll_std_60", "pending_yf_vix_z_63"],
        "inflation": ["pending_free_bls_cpi_u_z_63"],
        "macro": ["pending_free_fred_nfci_z_21"],
    }
    out: list[str] = []
    for token, features in mapping.items():
        if token in text:
            out.extend(features)
    return list(dict.fromkeys(out)) or ["ret_lag_21"]


def _family_from_text(text: str) -> str:
    if "vix" in text or "volatility" in text:
        return "volatility_vix"
    if "credit" in text or "spread" in text:
        return "credit_stress"
    if "yield" in text or "curve" in text or "rate" in text:
        return "yield_curve_macro"
    if "sector" in text:
        return "sector_rotation"
    if "machine learning" in text or "asset pricing" in text:
        return "ml_factor_anomalies"
    return "trend_stress_combo"


def _hypothesis_from_text(text: str) -> str:
    if "credit" in text:
        return "Use credit stress as a causal SP500 risk-on/risk-off filter."
    if "vix" in text or "volatility" in text:
        return "Use volatility regime changes to reduce exposure during weak SP500 periods."
    if "yield" in text or "curve" in text:
        return "Use yield-curve and rate pressure as macro timing inputs for SP500."
    if "momentum" in text or "trend" in text:
        return "Use SP500 trend persistence and reversal pressure as timing signals."
    return "Test a literature-backed causal SP500 market timing signal."


def _signal_logic_from_features(features: list[Any]) -> str:
    joined = " ".join(str(feature).lower() for feature in features)
    if "credit" in joined or "vix" in joined or "vol" in joined:
        return "Prefer long exposure when stress is falling and SP500 trend is healthy; reduce or short when stress rises."
    if "yield" in joined or "macro" in joined:
        return "Prefer long exposure when macro pressure is improving; reduce or short when curve or macro stress worsens."
    return "Convert the literature signal into a causal daily long/short rule and apply it next session."


def _priority(value: Any, confidence: float) -> str:
    text = str(value or "").lower()
    if text in {"high", "medium", "low"}:
        return text
    if confidence >= 0.7:
        return "high"
    if confidence >= 0.45:
        return "medium"
    return "low"


def _complexity(extraction: dict[str, Any]) -> str:
    count = len(extraction.get("required_features", []))
    if count <= 3:
        return "low"
    if count <= 6:
        return "medium"
    return "high"


def _overfitting_risk_label(extraction: dict[str, Any]) -> str:
    risk_count = len(extraction.get("overfitting_risks", []))
    confidence = float(extraction.get("confidence", 0.0))
    if risk_count >= 3 or confidence < 0.45:
        return "high"
    if risk_count >= 1:
        return "medium"
    return "low"


def _ai_prompt(study: dict[str, Any], text: str) -> str:
    return (
        "Devuelve SOLO JSON valido. Lee este estudio para Aurora/SP500 y extrae una ficha. "
        "No uses locked, futuro, ni datos no causales. Campos obligatorios: "
        "usable_for_strategy, confidence, strategy_family, hypothesis, required_features, "
        "signal_logic_plain, expected_holding_period, overfitting_risks, test_priority. "
        f"METADATOS={json.dumps(_study_brief(study), ensure_ascii=False, default=str)}\n"
        f"TEXTO={text[:120000]}"
    )


def _study_brief(study: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _study_id(study),
        "title": _title(study),
        "year": study.get("year"),
        "doi": study.get("doi"),
        "abstract": str(study.get("abstract", ""))[:4000],
    }


def _metadata_text(study: dict[str, Any]) -> str:
    parts = [
        _title(study),
        str(study.get("abstract", "")),
        str(study.get("summary", "")),
        _venue(study),
    ]
    for key in ("concepts", "keywords"):
        value = study.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
    return " ".join(parts)


def _dedupe_key(study: dict[str, Any]) -> str:
    keys = _dedupe_keys(study)
    return keys[0] if keys else ""


def _dedupe_keys(study: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for key in ("id", "openalex_id"):
        value = study.get(key)
        if isinstance(value, str) and value.strip():
            keys.append(f"openalex:{value.strip().lower()}")
    doi = _str_or_none(study.get("doi"))
    if doi:
        keys.append(f"doi:{doi.lower()}")
    title = re.sub(r"\s+", " ", _title(study).lower()).strip()
    year = _int_or_none(study.get("year")) or ""
    if title:
        keys.append(f"title:{title}:{year}")
    return list(dict.fromkeys(keys))


def _study_id(study: dict[str, Any]) -> str:
    for key in ("id", "openalex_id", "doi"):
        value = study.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:160]
    return _safe_filename(_title(study))[:160]


def _title(study: dict[str, Any]) -> str:
    return str(study.get("title", "")).strip()[:1000]


def _venue(study: dict[str, Any]) -> str:
    for key in ("venue", "journal", "source"):
        value = study.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[:140].strip("_") or "paper"


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
    "SP500_LITERATURE_QUERIES",
    "SP500LiteratureBuildConfig",
    "SP500LiteratureBuildReport",
    "run_sp500_literature_build",
]
