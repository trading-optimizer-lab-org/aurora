"""Bridge from the ESTUDIOS literature project into Aurora idea queues."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from aurora.research.agent_loop.ideas import StrategyIdea


Runner = Callable[[list[str], Path, int], str]
AIExtractor = Callable[[str, int], str]

ESTUDIOS_ROOT_ENV = "AURORA_ESTUDIOS_ROOT"
ESTUDIOS_PYTHON_ENV = "AURORA_ESTUDIOS_PYTHON"
DEFAULT_ESTUDIOS_ROOT = Path(r"C:\Users\HP\ESTUDIOS")


@dataclass(frozen=True)
class EstudiosAvailability:
    available: bool
    root: str
    python: str
    reason: str = ""
    env_root_set: bool = False
    env_python_set: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LiteraturePaperArtifact:
    study_id: str
    title: str
    year: int | None
    doi: str | None
    source: str
    is_open_access: bool
    citations_count: int | None
    saved: bool
    pdf_attempted: bool
    pdf_available: bool
    pdf_output: str | None = None
    summary_prompt_path: str | None = None
    summary_excerpt: str = ""
    ai_used: bool = False
    ai_insight_path: str | None = None
    ai_error: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LiteratureIdeaReport:
    queries: tuple[str, ...]
    studies_seen: int
    ideas: tuple[StrategyIdea, ...]
    paper_artifacts: tuple[LiteraturePaperArtifact, ...] = ()
    errors: tuple[str, ...] = ()
    estudios_available: bool = True
    estudios_root: str = ""
    estudios_python: str = ""
    availability_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "queries": self.queries,
            "studies_seen": self.studies_seen,
            "ideas": [idea.to_dict() for idea in self.ideas],
            "paper_artifacts": [artifact.to_dict() for artifact in self.paper_artifacts],
            "errors": self.errors,
            "estudios_available": self.estudios_available,
            "estudios_root": self.estudios_root,
            "estudios_python": self.estudios_python,
            "availability_reason": self.availability_reason,
        }


DEFAULT_ESTUDIOS_QUERIES = (
    "S&P 500 market timing volatility credit spreads",
    "equity market timing VIX credit spread momentum",
    "stock market regime switching volatility trend following",
    "S&P 500 tactical asset allocation macro indicators",
)

EXTENDED_ESTUDIOS_QUERIES = DEFAULT_ESTUDIOS_QUERIES + (
    "equity index crash prediction macro financial conditions",
    "stock market drawdown prediction volatility term structure",
    "market timing unemployment claims treasury yield curve",
    "S&P 500 regime detection defensive sectors credit risk",
    "asset allocation trend following moving average drawdown",
    "equity risk premium timing inflation rates volatility",
    "financial stress index stock returns prediction",
    "risk on risk off equity market timing indicators",
    "VIX term structure S&P 500 returns timing",
    "credit spread momentum stock market returns",
    "business cycle indicators equity market timing",
    "tactical equity allocation macroeconomic variables",
)


def discover_literature_strategy_ideas(
    *,
    queries: Iterable[str] = DEFAULT_ESTUDIOS_QUERIES,
    per_query: int = 5,
    query_offset: int = 0,
    max_queries: int | None = None,
    timeout_seconds: int = 120,
    output_dir: str | Path | None = None,
    enrich_papers: bool = False,
    download_pdfs: bool = True,
    summarize_papers: bool = True,
    max_papers_to_enrich: int = 8,
    use_ai: bool = False,
    ai_extractor: AIExtractor | None = None,
    ai_timeout_seconds: int = 300,
    runner: Runner | None = None,
    required: bool = False,
) -> LiteratureIdeaReport:
    """Search ESTUDIOS and convert paper evidence into safe strategy ideas."""

    root = _estudios_root()
    python_bin = _estudios_python(root)
    run = runner or _run_estudios
    artifact_dir = Path(output_dir) if output_dir is not None else None
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
    ideas: list[StrategyIdea] = []
    artifacts: list[LiteraturePaperArtifact] = []
    ai_ideas: list[StrategyIdea] = []
    errors: list[str] = []
    studies_seen = 0
    used_ids: set[str] = set()
    enriched_ids: set[str] = set()
    query_tuple = _select_queries(
        tuple(queries),
        query_offset=query_offset,
        max_queries=max_queries,
    )
    availability = estudios_availability(
        root=root,
        python_bin=python_bin,
        verify_command=runner is None,
    )
    if runner is None and not availability.available:
        message = (
            f"ESTUDIOS unavailable ({availability.reason}); "
            f"set {ESTUDIOS_ROOT_ENV} and/or {ESTUDIOS_PYTHON_ENV}"
        )
        if required:
            raise RuntimeError(message)
        return LiteratureIdeaReport(
            queries=query_tuple,
            studies_seen=0,
            ideas=tuple(),
            paper_artifacts=tuple(),
            errors=(message,),
            estudios_available=False,
            estudios_root=availability.root,
            estudios_python=availability.python,
            availability_reason=availability.reason,
        )

    for query in query_tuple:
        cmd = [
            str(python_bin),
            "-m",
            "estudios",
            "search",
            query,
            "--json",
            "--per-page",
            str(int(per_query)),
        ]
        try:
            raw = run(cmd, root, int(timeout_seconds))
            payload = _extract_json_object(raw)
        except Exception as exc:
            errors.append(f"{query}: {exc}")
            continue
        studies = payload.get("studies", [])
        if not isinstance(studies, list):
            errors.append(f"{query}: invalid studies payload")
            continue
        studies_seen += len(studies)
        for study in studies:
            if not isinstance(study, dict):
                continue
            if not _is_market_strategy_study(study):
                continue
            artifact_text = ""
            if (
                enrich_papers
                and artifact_dir is not None
                and len(enriched_ids) < max(0, int(max_papers_to_enrich))
            ):
                source_id = _study_source(study)
                if source_id not in enriched_ids:
                    artifact, extracted_ai_ideas = _enrich_study_with_estudios(
                        study,
                        python_bin=python_bin,
                        root=root,
                        output_dir=artifact_dir,
                        timeout_seconds=timeout_seconds,
                        run=run,
                        download_pdf=download_pdfs,
                        summarize=summarize_papers,
                        use_ai=use_ai,
                        ai_extractor=ai_extractor,
                        ai_timeout_seconds=ai_timeout_seconds,
                    )
                    artifacts.append(artifact)
                    ai_ideas.extend(extracted_ai_ideas)
                    enriched_ids.add(source_id)
                    artifact_text = artifact.summary_excerpt
                    if artifact.error:
                        errors.append(f"{source_id}: {artifact.error}")
                    if artifact.ai_error:
                        errors.append(f"{source_id}: {artifact.ai_error}")
            idea = _study_to_idea(study, artifact_text=artifact_text)
            if idea.idea_id in used_ids:
                continue
            ideas.append(idea)
            used_ids.add(idea.idea_id)
        for idea in ai_ideas:
            if idea.idea_id in used_ids:
                continue
            ideas.append(idea)
            used_ids.add(idea.idea_id)

    return LiteratureIdeaReport(
        queries=query_tuple,
        studies_seen=studies_seen,
        ideas=tuple(ideas),
        paper_artifacts=tuple(artifacts),
        errors=tuple(errors),
        estudios_available=availability.available,
        estudios_root=availability.root,
        estudios_python=availability.python,
        availability_reason=availability.reason,
    )


def _select_queries(
    queries: tuple[str, ...],
    *,
    query_offset: int,
    max_queries: int | None,
) -> tuple[str, ...]:
    pool = EXTENDED_ESTUDIOS_QUERIES if queries == DEFAULT_ESTUDIOS_QUERIES else queries
    if not pool:
        return ()
    n = len(pool)
    start = int(query_offset) % n
    rotated = pool[start:] + pool[:start]
    limit = len(rotated) if max_queries is None else max(1, int(max_queries))
    return rotated[:limit]


def _estudios_root() -> Path:
    return Path(os.environ.get(ESTUDIOS_ROOT_ENV, str(DEFAULT_ESTUDIOS_ROOT)))


def _estudios_python(root: Path) -> Path:
    override = os.environ.get(ESTUDIOS_PYTHON_ENV)
    if override:
        return Path(override)
    candidate = root / ".venv" / "Scripts" / "python.exe"
    return candidate if candidate.exists() else Path("python")


def estudios_availability(
    *,
    root: Path | None = None,
    python_bin: Path | None = None,
    verify_command: bool = True,
    timeout_seconds: int = 10,
) -> EstudiosAvailability:
    resolved_root = root or _estudios_root()
    resolved_python = python_bin or _estudios_python(resolved_root)
    env_root_set = bool(os.environ.get(ESTUDIOS_ROOT_ENV, "").strip())
    env_python_set = bool(os.environ.get(ESTUDIOS_PYTHON_ENV, "").strip())
    if not resolved_root.exists():
        return EstudiosAvailability(
            available=False,
            root=str(resolved_root),
            python=str(resolved_python),
            reason="root_not_found",
            env_root_set=env_root_set,
            env_python_set=env_python_set,
        )
    if resolved_python != Path("python") and not resolved_python.exists():
        return EstudiosAvailability(
            available=False,
            root=str(resolved_root),
            python=str(resolved_python),
            reason="python_not_found",
            env_root_set=env_root_set,
            env_python_set=env_python_set,
        )
    if verify_command:
        try:
            subprocess.run(
                [str(resolved_python), "-m", "estudios", "--version"],
                cwd=resolved_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, int(timeout_seconds)),
            )
        except FileNotFoundError:
            return EstudiosAvailability(
                available=False,
                root=str(resolved_root),
                python=str(resolved_python),
                reason="python_not_found",
                env_root_set=env_root_set,
                env_python_set=env_python_set,
            )
        except subprocess.TimeoutExpired:
            return EstudiosAvailability(
                available=False,
                root=str(resolved_root),
                python=str(resolved_python),
                reason="version_check_timeout",
                env_root_set=env_root_set,
                env_python_set=env_python_set,
            )
        except subprocess.CalledProcessError:
            return EstudiosAvailability(
                available=False,
                root=str(resolved_root),
                python=str(resolved_python),
                reason="estudios_module_not_available",
                env_root_set=env_root_set,
                env_python_set=env_python_set,
            )
    return EstudiosAvailability(
        available=True,
        root=str(resolved_root),
        python=str(resolved_python),
        reason="",
        env_root_set=env_root_set,
        env_python_set=env_python_set,
    )


def _run_estudios(cmd: list[str], cwd: Path, timeout_seconds: int) -> str:
    try:
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
    except FileNotFoundError as exc:
        raise RuntimeError("ESTUDIOS python executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ESTUDIOS search timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"ESTUDIOS search failed: {detail[:500]}") from exc
    return proc.stdout or ""


def _extract_json_object(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("ESTUDIOS did not return output")
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
    raise ValueError("ESTUDIOS did not return a JSON object")


def _enrich_study_with_estudios(
    study: dict[str, Any],
    *,
    python_bin: Path,
    root: Path,
    output_dir: Path,
    timeout_seconds: int,
    run: Runner,
    download_pdf: bool,
    summarize: bool,
    use_ai: bool,
    ai_extractor: AIExtractor | None,
    ai_timeout_seconds: int,
) -> tuple[LiteraturePaperArtifact, list[StrategyIdea]]:
    study_id = _study_source(study)
    safe_id = _safe_filename(study_id)
    saved = False
    pdf_attempted = False
    pdf_available = False
    pdf_output: str | None = None
    summary_path: Path | None = None
    summary_excerpt = ""
    ai_used = False
    ai_insight_path: Path | None = None
    ai_error: str | None = None
    ai_ideas: list[StrategyIdea] = []
    errors: list[str] = []

    try:
        run([str(python_bin), "-m", "estudios", "save", study_id], root, timeout_seconds)
        saved = True
    except Exception as exc:
        errors.append(f"save failed: {exc}")

    if download_pdf:
        pdf_attempted = True
        try:
            pdf_output = run([str(python_bin), "-m", "estudios", "pdf", study_id], root, timeout_seconds)
            pdf_available = True
        except Exception as exc:
            errors.append(f"pdf unavailable: {exc}")

    if summarize:
        summary_path = output_dir / f"{safe_id}_critical_prompt.txt"
        try:
            run(
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
                summary_excerpt = summary_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )[:20_000]
        except Exception as exc:
            errors.append(f"summarize failed: {exc}")

    if use_ai and summary_excerpt:
        ai_insight_path = output_dir / f"{safe_id}_ai_insight.json"
        try:
            raw_ai = (ai_extractor or _run_paper_ai)(
                _paper_ai_prompt(study, summary_excerpt),
                int(ai_timeout_seconds),
            )
            ai_payload = _extract_json_object(raw_ai)
            ai_ideas = _ideas_from_ai_payload(ai_payload, study)
            insight_payload = {
                "study_id": study_id,
                "source": f"estudios:{study_id}",
                "raw": ai_payload,
                "ideas": [idea.to_dict() for idea in ai_ideas],
            }
            ai_insight_path.write_text(
                json.dumps(insight_payload, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            ai_used = bool(ai_ideas)
            if not ai_ideas:
                ai_error = "AI extraction returned no safe ideas"
        except Exception as exc:
            ai_error = f"AI extraction failed: {exc}"

    artifact = LiteraturePaperArtifact(
        study_id=study_id,
        title=str(study.get("title", ""))[:500],
        year=_int_or_none(study.get("year")),
        doi=_str_or_none(study.get("doi")),
        source=f"estudios:{study_id}",
        is_open_access=bool(study.get("is_oa", False)),
        citations_count=_int_or_none(study.get("citations_count")),
        saved=saved,
        pdf_attempted=pdf_attempted,
        pdf_available=pdf_available,
        pdf_output=pdf_output[-1000:] if pdf_output else None,
        summary_prompt_path=str(summary_path) if summary_path else None,
        summary_excerpt=summary_excerpt[:2000],
        ai_used=ai_used,
        ai_insight_path=str(ai_insight_path) if ai_insight_path and ai_insight_path.exists() else None,
        ai_error=ai_error,
        error="; ".join(errors) if errors else None,
    )
    (output_dir / f"{safe_id}_artifact.json").write_text(
        json.dumps(artifact.to_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return artifact, ai_ideas


def _paper_ai_prompt(study: dict[str, Any], summary_excerpt: str) -> str:
    return (
        "Eres un investigador cuantitativo. Devuelve SOLO JSON valido. "
        "Extrae ideas de trading para SPY/SP500 desde este paper. "
        "No uses locked, futuro, live trading ni datos no causales. "
        "Schema: {\"ideas\":[{\"idea_id\":\"safe_id\","
        "\"features\":[\"feature causal\"],"
        "\"rule_family\":\"drawdown_volatility|trend_stress_combo|"
        "defensive_ratio_blend|yield_curve_macro|vix_term_structure|"
        "breadth_proxy_regime|sector_rotation_momentum|crash_asymmetry|"
        "mean_reversion_stress\","
        "\"hypothesis\":\"hipotesis concreta\"}],"
        "\"claims\":[\"...\"],\"warnings\":[\"...\"]}. "
        f"Paper: {json.dumps(_study_brief(study), ensure_ascii=False, default=str)}. "
        f"Texto preparado por ESTUDIOS: {summary_excerpt[:12000]}"
    )


def _run_paper_ai(prompt: str, timeout_seconds: int) -> str:
    command = os.environ.get("AURORA_PAPER_AI_COMMAND", "").strip()
    if command:
        prompt_path = Path(os.environ.get("TEMP", ".")) / "aurora_paper_ai_prompt.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        cmd = command.format(prompt_file=str(prompt_path), timeout=int(timeout_seconds))
        proc = subprocess.run(
            cmd,
            shell=True,  # nosec B602 - explicit operator-supplied command hook
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        return proc.stdout

    provider = os.environ.get("AURORA_PAPER_AI_PROVIDER", "codex-cli").strip().lower()
    if provider == "openai":
        return _run_openai_paper_ai(prompt, timeout_seconds)
    if provider == "github_models":
        return _run_github_models_paper_ai(prompt, timeout_seconds)
    if provider != "codex-cli":
        raise RuntimeError(f"unsupported paper AI provider: {provider}")
    codex_bin = os.environ.get("AURORA_CODEX_BIN", "codex")
    proc = subprocess.run(
        [codex_bin, "--search", "exec", prompt],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )
    return proc.stdout


def _run_github_models_paper_ai(prompt: str, timeout_seconds: int) -> str:
    token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GITHUB_MODELS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required for AURORA_PAPER_AI_PROVIDER=github_models")
    model = os.environ.get("AURORA_PAPER_AI_MODEL", "").strip()
    if not model:
        raise RuntimeError("AURORA_PAPER_AI_MODEL is required for GitHub Models paper AI")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Return only valid JSON. Do not include markdown fences.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    request = urllib.request.Request(
        "https://models.github.ai/inference/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=int(timeout_seconds)) as response:
        raw = response.read().decode("utf-8")
    data = _extract_json_object(raw)
    choices = data.get("choices", [])
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str) and content.strip():
            return content
    raise RuntimeError("GitHub Models response did not contain output text")


def _run_openai_paper_ai(prompt: str, timeout_seconds: int) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for AURORA_PAPER_AI_PROVIDER=openai")
    model = os.environ.get("AURORA_PAPER_AI_MODEL", "").strip()
    if not model:
        raise RuntimeError("AURORA_PAPER_AI_MODEL is required for OpenAI paper AI")
    payload = {
        "model": model,
        "input": prompt,
        "text": {"format": {"type": "json_object"}},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=int(timeout_seconds)) as response:
        raw = response.read().decode("utf-8")
    data = _extract_json_object(raw)
    text = _openai_response_text(data)
    if not text:
        raise RuntimeError("OpenAI response did not contain output text")
    return text


def _openai_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return str(data["output_text"])
    parts: list[str] = []
    output = data.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(str(part["text"]))
    return "\n".join(parts).strip()


def _ideas_from_ai_payload(payload: dict[str, Any], study: dict[str, Any]) -> list[StrategyIdea]:
    raw_ideas = payload.get("ideas", [])
    if not isinstance(raw_ideas, list):
        return []
    out: list[StrategyIdea] = []
    source = f"estudios_ai:{_study_source(study)}"
    for item in raw_ideas:
        if not isinstance(item, dict):
            continue
        try:
            idea = _safe_ai_idea(item, source=source)
        except ValueError:
            continue
        out.append(idea)
    return out[:20]


def _safe_ai_idea(item: dict[str, Any], *, source: str) -> StrategyIdea:
    idea_id = _safe_filename(str(item.get("idea_id", ""))).lower()
    if not idea_id:
        raise ValueError("idea_id required")
    features = tuple(
        str(feature).strip()
        for feature in item.get("features", ())
        if str(feature).strip()
    )
    if not features:
        raise ValueError("features required")
    rule_family = str(item.get("rule_family", "trend_stress_combo")).strip()
    hypothesis = str(item.get("hypothesis", "")).strip()
    safe_text = " ".join((idea_id, " ".join(features), rule_family, hypothesis)).lower()
    if any(token in safe_text for token in ("locked", "future", "lookahead", "live trading")):
        raise ValueError("unsafe AI idea")
    allowed_families = {
        "drawdown_volatility",
        "trend_stress_combo",
        "defensive_ratio_blend",
        "yield_curve_macro",
        "vix_term_structure",
        "breadth_proxy_regime",
        "sector_rotation_momentum",
        "crash_asymmetry",
        "mean_reversion_stress",
    }
    if rule_family not in allowed_families:
        rule_family = _family_from_features(list(features), safe_text)
    return StrategyIdea(
        idea_id=idea_id[:80],
        features=features[:10],
        rule_family=rule_family,
        hypothesis=hypothesis[:500] or "AI-extracted literature hypothesis using causal signals.",
        allowed_data=("train only",),
        forbidden=("locked", "future data"),
        source=source,
    )


def _study_brief(study: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _study_source(study),
        "title": study.get("title"),
        "year": study.get("year"),
        "doi": study.get("doi"),
        "abstract": str(study.get("abstract", ""))[:4000],
        "concepts": study.get("concepts", [])[:20]
        if isinstance(study.get("concepts"), list)
        else [],
    }


def _study_to_idea(study: dict[str, Any], *, artifact_text: str = "") -> StrategyIdea:
    text = _study_text(study)
    enriched_text = f"{text} {artifact_text.lower()}"
    digest = hashlib.sha1(
        text.encode("utf-8", errors="ignore"), usedforsecurity=False
    ).hexdigest()[:12]
    features = _features_from_text(enriched_text)
    family = _family_from_features(features, enriched_text)
    source = f"estudios:{_study_source(study)}"
    return StrategyIdea(
        idea_id=f"study_{digest}",
        features=tuple(features),
        rule_family=family,
        hypothesis=_hypothesis_from_text(enriched_text, source=source),
        allowed_data=("train only",),
        forbidden=("locked", "future data"),
        source=source,
    )


def _study_text(study: dict[str, Any]) -> str:
    parts = [
        str(study.get("title", "")),
        str(study.get("abstract", "")),
        str(study.get("summary", "")),
    ]
    concepts = study.get("concepts", [])
    if isinstance(concepts, list):
        parts.extend(str(item) for item in concepts)
    keywords = study.get("keywords", [])
    if isinstance(keywords, list):
        parts.extend(str(item) for item in keywords)
    return " ".join(parts).lower()


def _is_market_strategy_study(study: dict[str, Any]) -> bool:
    text = _study_text(study)
    market_terms = (
        "s&p",
        "sp500",
        "s&p 500",
        "equity",
        "stock",
        "asset pricing",
        "market timing",
        "portfolio",
        "trading",
        "investment",
        "financial market",
        "capital market",
        "risk premium",
        "volatility",
        "liquidity",
        "credit spread",
        "yield curve",
        "monetary policy",
        "business cycle",
        "factor model",
    )
    exclusion_terms = (
        "pesticide",
        "agriculture",
        "crop",
        "soil",
        "clinical",
        "patient",
        "biology",
        "chemistry",
    )
    if any(term in text for term in exclusion_terms) and not any(
        term in text for term in market_terms
    ):
        return False
    return any(term in text for term in market_terms)


def _features_from_text(text: str) -> list[str]:
    features: list[str] = []
    if any(token in text for token in ("vix", "volatility", "variance", "risk")):
        features.extend(["VIX regime", "SPY realized volatility"])
    if any(token in text for token in ("credit", "spread", "financial condition", "stress")):
        features.extend(["credit stress", "HYG LQD ratio"])
    if any(token in text for token in ("momentum", "trend", "moving average", "time series")):
        features.extend(["SPY momentum", "SPY moving average"])
    if any(token in text for token in ("yield", "rate", "term structure", "treasury", "curve")):
        features.extend(["rates slope", "Treasury yield"])
    if any(token in text for token in ("sector", "defensive", "cyclical", "industry")):
        features.extend(["defensive sector ratio", "cyclical sector ratio"])
    if any(token in text for token in ("drawdown", "crash", "bear market", "tail")):
        features.extend(["SPY drawdown", "stress filter"])
    if any(token in text for token in ("breadth", "advance decline", "equal weight")):
        features.extend(["equal weight breadth", "small cap breadth"])
    if any(token in text for token in ("term spread", "default spread", "credit spread")):
        features.extend(["term spread", "default spread"])
    if any(token in text for token in ("inflation", "unemployment", "industrial production", "business cycle")):
        features.extend(["macro cycle", "inflation pressure"])
    if any(token in text for token in ("liquidity", "funding liquidity", "market liquidity")):
        features.extend(["liquidity pressure", "financial conditions"])
    if any(token in text for token in ("sentiment", "news", "analyst", "survey")):
        features.extend(["sentiment proxy", "risk appetite"])
    if not features:
        features.extend(["SPY momentum", "market regime"])
    return list(dict.fromkeys(features))[:10]


def _family_from_features(features: list[str], text: str) -> str:
    joined = " ".join(features).lower()
    if "drawdown" in joined or "volatility" in joined or "vix" in joined:
        return "drawdown_volatility"
    if "credit" in joined or "stress" in joined or "rate" in joined:
        return "trend_stress_combo"
    if "sector" in joined or "defensive" in text:
        return "defensive_ratio_blend"
    if "breadth" in joined:
        return "breadth_proxy_regime"
    if "macro" in joined or "inflation" in joined or "yield" in joined:
        return "yield_curve_macro"
    return "trend_stress_combo"


def _hypothesis_from_text(text: str, *, source: str) -> str:
    if "machine learning" in text or "nonlinear" in text:
        return f"Literature idea from {source}: allow nonlinear interactions between market timing signals."
    if "credit" in text or "spread" in text:
        return f"Literature idea from {source}: use credit and stress signals to time SPY risk-on/risk-off."
    if "vix" in text or "volatility" in text:
        return f"Literature idea from {source}: use volatility regime shifts to avoid weak SPY periods."
    if "business cycle" in text or "inflation" in text:
        return f"Literature idea from {source}: use macro-cycle pressure as a SPY timing filter."
    return f"Literature inspired market timing hypothesis from {source} using causal signals."


def _study_source(study: dict[str, Any]) -> str:
    for key in ("id", "openalex_id", "doi"):
        value = study.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return "metadata"


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[:120].strip("_") or "paper"


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "DEFAULT_ESTUDIOS_QUERIES",
    "DEFAULT_ESTUDIOS_ROOT",
    "ESTUDIOS_PYTHON_ENV",
    "ESTUDIOS_ROOT_ENV",
    "EXTENDED_ESTUDIOS_QUERIES",
    "EstudiosAvailability",
    "LiteraturePaperArtifact",
    "LiteratureIdeaReport",
    "discover_literature_strategy_ideas",
    "estudios_availability",
]
