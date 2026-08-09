"""Pinned source probe and fail-closed evidence for OpenAP patent signals."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping
import base64
import json
import os
import re
import time
import urllib.request
import zipfile

import pandas as pd


KPSS_REPOSITORY = (
    "KPSS2017/Technological-Innovation-Resource-Allocation-and-Growth-Extended-Data"
)
KPSS_COMMIT = "2ee29097f7ca05fc0e56905e82474ad426c387b9"
KPSS_ARCHIVES = {
    "KPSS_2024.zip": {
        "sha256": "60215d8db687b0c40060de1649cf0f14364cbac2cbdd16b5cb3dee2dcdb85f27",
        "size": 57199194,
    },
    "Match_patent_permco_permno_2024.zip": {
        "sha256": "4686ee4383bfc8bf43b7721766f28e04e331ea02bbffe4dd1358d5c02b5e675a",
        "size": 16776297,
    },
    "Match_patent_cpc_2024.zip": {
        "sha256": "a43de8ee5d43b3c0840f11540d0468febccad0d378dc372b4aee803aefce4257",
        "size": 74407853,
    },
}
OPENAP_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"
OPENAP_FORMULA_SOURCES = {
    "CitationsRD": {
        "path": "Signals/pyCode/Predictors/CitationsRD.py",
        "sha256": "5bb1160828898b763362fbee42785fc88257a5c84bf26132df58f472b45de9cf",
    },
    "PatentsRD": {
        "path": "Signals/pyCode/Predictors/PatentsRD.py",
        "sha256": "3f352968a0fe03dd6892065bfbda89023ebb12e32e195d10f34acb7a86828d72",
    },
    "PatentDataProcessed": {
        "path": "Signals/pyCode/DataDownloads/PatentCitations.py",
        "sha256": "1fcabbbb4d7cc3e64fd28ecc56ea07ac4855c8a2b7f627103385a1580f1465aa",
    },
}

_PATENT_COLUMNS = frozenset(
    {
        "patent_num",
        "permno",
        "issue_date",
        "filing_date",
        "xi_nominal",
        "xi_real",
        "cites",
    }
)
_MATCH_COLUMNS = frozenset({"patent_num", "permco", "permno"})
_CPC_COLUMNS = frozenset({"patent_num", "cpc"})
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def parse_lfs_pointer(text: str) -> dict[str, Any]:
    """Parse a Git LFS pointer and reject anything outside the pinned contract."""

    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    if not lines or lines[0] != "version https://git-lfs.github.com/spec/v1":
        raise ValueError("Invalid Git LFS pointer version")
    digest = next(
        (line.removeprefix("oid sha256:") for line in lines if line.startswith("oid sha256:")),
        "",
    )
    size_text = next(
        (line.removeprefix("size ") for line in lines if line.startswith("size ")),
        "",
    )
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not size_text.isdigit():
        raise ValueError("Invalid Git LFS pointer integrity fields")
    return {"sha256": digest, "size": int(size_text)}


def _nonblank_values(series: pd.Series) -> set[str]:
    values = series.dropna().astype(str).str.strip()
    return set(values.loc[values.ne("")])


def summarize_kpss_patent_chunks(
    chunks: Iterable[pd.DataFrame],
) -> dict[str, Any]:
    """Measure the public patent panel without treating it as signal coverage."""

    rows = 0
    patents: set[str] = set()
    permnos: set[str] = set()
    missing_permno = 0
    missing_filing_date = 0
    missing_cites = 0
    first_issue: pd.Timestamp | None = None
    last_issue: pd.Timestamp | None = None
    observed = False
    for chunk in chunks:
        observed = True
        missing = _PATENT_COLUMNS - set(chunk.columns)
        if missing:
            raise ValueError(f"KPSS patent panel is missing columns: {sorted(missing)}")
        rows += len(chunk)
        patents.update(_nonblank_values(chunk["patent_num"]))
        permnos.update(_nonblank_values(chunk["permno"]))
        missing_permno += int(chunk["permno"].isna().sum())
        missing_filing_date += int(chunk["filing_date"].isna().sum())
        missing_cites += int(chunk["cites"].isna().sum())
        issue = pd.to_datetime(chunk["issue_date"], errors="coerce", format="mixed")
        if issue.notna().any():
            chunk_first = issue.min()
            chunk_last = issue.max()
            first_issue = chunk_first if first_issue is None else min(first_issue, chunk_first)
            last_issue = chunk_last if last_issue is None else max(last_issue, chunk_last)
    if not observed or rows == 0:
        raise ValueError("KPSS patent panel contains no rows")
    return {
        "rows": rows,
        "unique_patents": len(patents),
        "unique_permnos": len(permnos),
        "missing_permno": missing_permno,
        "missing_filing_date": missing_filing_date,
        "missing_cites": missing_cites,
        "first_issue_date": first_issue.date().isoformat() if first_issue is not None else "",
        "last_issue_date": last_issue.date().isoformat() if last_issue is not None else "",
        "signal_coverage_measured": False,
    }


def _summarize_identifier_chunks(
    chunks: Iterable[pd.DataFrame], required: frozenset[str]
) -> dict[str, Any]:
    rows = 0
    distinct: dict[str, set[str]] = {column: set() for column in required}
    observed = False
    for chunk in chunks:
        observed = True
        missing = required - set(chunk.columns)
        if missing:
            raise ValueError(f"KPSS identifier table is missing columns: {sorted(missing)}")
        rows += len(chunk)
        for column in required:
            distinct[column].update(_nonblank_values(chunk[column]))
    if not observed or rows == 0:
        raise ValueError("KPSS identifier table contains no rows")
    return {
        "rows": rows,
        **{f"unique_{column}": len(values) for column, values in distinct.items()},
    }


def _headers(*, api: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": "Aurora-OpenAP-181-patent-probe/1.0",
        "Accept": "application/vnd.github+json" if api else "application/octet-stream",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token and api:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    return headers


def _fetch_bytes(url: str, *, api: bool = False, attempts: int = 4) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=_headers(api=api))
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read()
        except Exception as exc:  # pragma: no cover - exercised in GitHub Actions
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


def _fetch_json(url: str) -> dict[str, Any]:
    return json.loads(_fetch_bytes(url, api=True).decode("utf-8"))


def _download_verified(
    url: str,
    target: Path,
    expected: Mapping[str, Any],
    *,
    attempts: int = 4,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            digest = sha256()
            size = 0
            request = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(request, timeout=300) as response, target.open(
                "wb"
            ) as output:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    digest.update(block)
                    size += len(block)
            if size != int(expected["size"]) or digest.hexdigest() != expected["sha256"]:
                raise ValueError(
                    f"Downloaded archive failed integrity verification: {target.name}"
                )
            return
        except Exception as exc:  # pragma: no cover - exercised in GitHub Actions
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to download verified archive {target.name}: {last_error}")


def _csv_chunks(archive: Path, *, chunksize: int = 200_000) -> Iterable[pd.DataFrame]:
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"Expected one CSV in {archive.name}; found {members}")
        with bundle.open(members[0]) as source:
            yield from pd.read_csv(source, chunksize=chunksize, low_memory=False)


def _formula_requirements() -> pd.DataFrame:
    rows = [
        {
            "signal": "CitationsRD",
            "formula_commit": OPENAP_COMMIT,
            "formula_sha256": OPENAP_FORMULA_SOURCES["CitationsRD"]["sha256"],
            "patent_input_required": "ncitscale",
            "kpss_field": "cites",
            "patent_input_exact": False,
            "reason": (
                "OpenAP ncitscale uses individual citations within five years and "
                "year-subcategory scaling; KPSS publishes a total forward-citation count "
                "updated through 2024."
            ),
            "other_exact_inputs": (
                "xrd,gvkey,permno,time_avail_m,mve_c,sicCRSP,exchcd,ceq"
            ),
        },
        {
            "signal": "PatentsRD",
            "formula_commit": OPENAP_COMMIT,
            "formula_sha256": OPENAP_FORMULA_SOURCES["PatentsRD"]["sha256"],
            "patent_input_required": "npat",
            "kpss_field": "patent_num grouped by permno and issue year",
            "patent_input_exact": False,
            "reason": (
                "KPSS supplies a plausible count and PERMNO bridge, but OpenAP builds npat "
                "through the NBER dynamic assignee-to-GVKEY mapping; stock-level equivalence "
                "has not been measured."
            ),
            "other_exact_inputs": (
                "xrd,gvkey,permno,time_avail_m,mve_c,sicCRSP,exchcd,ceq"
            ),
        },
    ]
    return pd.DataFrame(rows)


def build_patent_batch_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Record precisely what the patent probe proves without promoting either signal."""

    required_true = (
        "archives_verified",
        "schema_verified",
        "readme_use_with_citation",
    )
    valid = (
        probe.get("source_commit") == KPSS_COMMIT
        and all(probe.get(field) is True for field in required_true)
        and probe.get("raw_redistribution_authorized") is False
        and str(evidence_run_url).startswith("https://")
        and bool(str(evidence_artifact).strip())
        and bool(_COMMIT_RE.fullmatch(str(implementation_commit)))
    )
    if probe.get("formula_sources_verified") is False:
        valid = False
    if not valid:
        raise ValueError("Invalid or incomplete patent probe evidence")
    blockers = {
        "CitationsRD": (
            "patent_source_partial:kpss_total_forward_cites_do_not_reproduce_"
            "openap_five_year_subcategory_scaled_ncitscale;exact_xrd_and_"
            "gvkey_permno_stock_spine_unavailable"
        ),
        "PatentsRD": (
            "patent_source_partial:kpss_patent_counts_and_permno_bridge_available_"
            "but_exact_xrd_gvkey_spine_and_stock_level_fidelity_unverified"
        ),
    }
    rows = []
    for signal, blocker in blockers.items():
        rows.append(
            {
                "signal": signal,
                "formula_implemented": True,
                "data_pipeline_implemented": False,
                "point_in_time_verified": False,
                "identity_verified": False,
                "coverage_measured": False,
                "fidelity_measured": False,
                "coverage_result": "not_measured",
                "fidelity_result": "not_measured",
                "strict_gate_result": "blocked",
                "blocking_reason": blocker,
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
        )
    return pd.DataFrame(rows)


def run_patent_source_probe(
    *,
    output_dir: Path,
    download_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, Any]:
    """Run the bounded public-source probe and write non-redistributive evidence."""

    output_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    api_root = f"https://api.github.com/repos/{KPSS_REPOSITORY}"
    repository = _fetch_json(api_root)
    commit = _fetch_json(f"{api_root}/commits/{KPSS_COMMIT}")
    if commit.get("sha") != KPSS_COMMIT:
        raise ValueError("Pinned KPSS commit is unavailable")
    readme_url = (
        f"https://raw.githubusercontent.com/{KPSS_REPOSITORY}/{KPSS_COMMIT}/README.md"
    )
    readme = _fetch_bytes(readme_url).decode("utf-8")
    readme_lower = readme.lower()
    use_with_citation = "if you use these data sets, please cite" in readme_lower
    clone_documented = "git clone this repository" in readme_lower
    if not use_with_citation or not clone_documented:
        raise ValueError("KPSS README no longer documents use with citation and cloning")

    pointer_rows: list[dict[str, Any]] = []
    for name, expected in KPSS_ARCHIVES.items():
        content = _fetch_json(f"{api_root}/contents/{name}?ref={KPSS_COMMIT}")
        pointer = parse_lfs_pointer(
            base64.b64decode(str(content["content"]).replace("\n", "")).decode("utf-8")
        )
        if pointer != expected:
            raise ValueError(f"KPSS LFS pointer drift detected for {name}")
        target = download_dir / name
        media_url = (
            f"https://media.githubusercontent.com/media/{KPSS_REPOSITORY}/"
            f"{KPSS_COMMIT}/{name}"
        )
        _download_verified(media_url, target, expected)
        pointer_rows.append({"archive": name, **pointer, "download_verified": True})

    formula_verified = True
    for source in OPENAP_FORMULA_SOURCES.values():
        url = (
            "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
            f"{OPENAP_COMMIT}/{source['path']}"
        )
        formula_verified &= sha256(_fetch_bytes(url)).hexdigest() == source["sha256"]
    if not formula_verified:
        raise ValueError("Pinned OpenAP patent formula source hash mismatch")

    patent_metrics = summarize_kpss_patent_chunks(
        _csv_chunks(download_dir / "KPSS_2024.zip")
    )
    match_metrics = _summarize_identifier_chunks(
        _csv_chunks(download_dir / "Match_patent_permco_permno_2024.zip"),
        _MATCH_COLUMNS,
    )
    cpc_metrics = _summarize_identifier_chunks(
        _csv_chunks(download_dir / "Match_patent_cpc_2024.zip"),
        _CPC_COLUMNS,
    )
    summary = {
        "source_repository": KPSS_REPOSITORY,
        "source_commit": KPSS_COMMIT,
        "source_url": f"https://github.com/{KPSS_REPOSITORY}/tree/{KPSS_COMMIT}",
        "archives_verified": True,
        "schema_verified": True,
        "formula_sources_verified": True,
        "readme_use_with_citation": use_with_citation,
        "readme_clone_documented": clone_documented,
        "formal_license_detected": bool(repository.get("license")),
        "raw_redistribution_authorized": False,
        "raw_archives_in_artifact": False,
        "patent_panel": patent_metrics,
        "permco_permno_match": match_metrics,
        "cpc_match": cpc_metrics,
        "strict_approved": 0,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    evidence = build_patent_batch_evidence(
        summary,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    pd.DataFrame(pointer_rows).to_csv(
        output_dir / "kpss_archive_integrity.csv", index=False
    )
    pd.DataFrame([patent_metrics]).to_csv(
        output_dir / "kpss_patent_source_metrics.csv", index=False
    )
    _formula_requirements().to_csv(
        output_dir / "patent_formula_requirements.csv", index=False
    )
    evidence.to_csv(output_dir / "patent_batch_evidence.csv", index=False)
    (output_dir / "patent_source_probe.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    report = "\n".join(
        (
            "# OpenAP 181 Patent Source Probe",
            "",
            f"- KPSS commit: `{KPSS_COMMIT}`",
            f"- OpenAP formula commit: `{OPENAP_COMMIT}`",
            f"- Raw archives uploaded: `{str(False).lower()}`",
            f"- Formal license detected: `{str(summary['formal_license_detected']).lower()}`",
            "- Permission basis: README explicitly invites use with citation and documents Git cloning.",
            "- Raw redistribution: not authorized by an explicit license; omitted from artifact.",
            "- CitationsRD: blocked because KPSS total forward cites are not OpenAP `ncitscale`, and exact `xrd`/identity inputs remain unavailable.",
            "- PatentsRD: patent counts and PERMNO bridge are plausible components, but exact `xrd`, GVKEY spine, coverage and fidelity remain unverified.",
            "- New strict approvals: `0`.",
            "",
        )
    )
    (output_dir / "PATENT_SOURCE_PROBE_REPORT.md").write_text(report, encoding="utf-8")
    return summary


__all__ = [
    "KPSS_ARCHIVES",
    "KPSS_COMMIT",
    "KPSS_REPOSITORY",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_SOURCES",
    "build_patent_batch_evidence",
    "parse_lfs_pointer",
    "run_patent_source_probe",
    "summarize_kpss_patent_chunks",
]
