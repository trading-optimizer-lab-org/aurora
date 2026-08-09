"""Freeze the exact Open Asset Pricing formula source for each predictor.

The official repository is pinned to a commit.  Matching is deliberately
conservative: a predictor is only linked when its name is present in the file
name or in an explicit output/save call inside the source file.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable, Iterable, Mapping
import ast
import gzip
import json
import os
import re
import time
import urllib.request
import zlib

import pandas as pd

from aurora.research.openap_93.http import public_headers


OPENAP_REPOSITORY = "OpenSourceAP/CrossSection"
OPENAP_FORMULA_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"
PREDICTOR_PREFIXES = (
    "Signals/pyCode/Predictors/",
    "Signals/Code/Predictors/",
    "Signals/LegacyStataCode/Predictors/",
)
PREDICTOR_PREFIX_PRIORITY = {
    # OpenSourceAP documents pyCode as the current stock-level construction
    # pipeline.  The Stata tree is retained for legacy replication only.
    "Signals/pyCode/Predictors/": 3,
    "Signals/Code/Predictors/": 2,
    "Signals/LegacyStataCode/Predictors/": 1,
}
SOURCE_SUFFIXES = (".py", ".do", ".r", ".R")


class FormulaInventoryError(RuntimeError):
    """Raised when the pinned official source cannot be inventoried safely."""


@dataclass(frozen=True)
class FormulaMatch:
    signal: str
    status: str
    path: str
    match_method: str
    candidate_count: int
    commit: str
    source_url: str
    sha256: str


def _raw_url(path: str) -> str:
    return (
        f"https://raw.githubusercontent.com/{OPENAP_REPOSITORY}/"
        f"{OPENAP_FORMULA_COMMIT}/{path}"
    )


def _tree_url() -> str:
    return (
        f"https://api.github.com/repos/{OPENAP_REPOSITORY}/git/trees/"
        f"{OPENAP_FORMULA_COMMIT}?recursive=1"
    )


def _request_headers(url: str) -> dict[str, str]:
    headers = public_headers()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    return headers


def _fetch_bytes(url: str, *, attempts: int = 4, timeout: int = 60) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=_request_headers(url))
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                encoding = str(response.headers.get("Content-Encoding", "")).lower()
                if "gzip" in encoding or body[:2] == b"\x1f\x8b":
                    return gzip.decompress(body)
                if "deflate" in encoding:
                    return zlib.decompress(body)
                return body
        except Exception as exc:  # pragma: no cover - exercised in GitHub
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise FormulaInventoryError(f"Unable to fetch {url}: {last_error}")


def fetch_predictor_sources(
    *, fetch: Callable[[str], bytes] = _fetch_bytes
) -> dict[str, bytes]:
    """Download all predictor source files from the pinned official commit."""

    payload = json.loads(fetch(_tree_url()).decode("utf-8"))
    if payload.get("truncated"):
        raise FormulaInventoryError("Pinned OpenAP tree response is truncated")
    paths = sorted(
        item["path"]
        for item in payload.get("tree", [])
        if item.get("type") == "blob"
        and item.get("path", "").startswith(PREDICTOR_PREFIXES)
        and item.get("path", "").endswith(SOURCE_SUFFIXES)
    )
    if len(paths) < 150:
        raise FormulaInventoryError(
            f"Expected a substantial official predictor tree; found {len(paths)} files"
        )
    return {path: fetch(_raw_url(path)) for path in paths}


def _explicit_outputs(text: str) -> set[str]:
    patterns = (
        r"save_predictor\s*\([^\n]*?[\"']([A-Za-z0-9_]+)[\"']\s*\)",
        r"to_csv\s*\([^\n]*?[\"'][^\"']*/([A-Za-z0-9_]+)\.csv[\"']",
        r"save\s+[^\n]*?/([A-Za-z0-9_]+)\.csv",
        r"export\s+delimited\s+[^\n]*?/([A-Za-z0-9_]+)\.csv",
    )
    outputs: set[str] = set()
    for pattern in patterns:
        outputs.update(re.findall(pattern, text, flags=re.IGNORECASE))
    outputs.update(_literal_loop_outputs(text))
    return outputs


def _literal_loop_outputs(text: str) -> set[str]:
    """Recover literal output collections consumed by save_predictor loops."""

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    literal_lists: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        value = node.value
        if not isinstance(target, ast.Name) or not isinstance(
            value, (ast.List, ast.Tuple, ast.Set)
        ):
            continue
        values = {
            item.value
            for item in value.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        if values and len(values) == len(value.elts):
            literal_lists[target.id] = values

    outputs: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not isinstance(node.target, ast.Name) or not isinstance(node.iter, ast.Name):
            continue
        candidates = literal_lists.get(node.iter.id)
        if not candidates:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            function_name = (
                child.func.id
                if isinstance(child.func, ast.Name)
                else child.func.attr
                if isinstance(child.func, ast.Attribute)
                else ""
            )
            if function_name != "save_predictor":
                continue
            if any(
                isinstance(argument, ast.Name) and argument.id == node.target.id
                for argument in child.args
            ):
                outputs.update(candidates)
                break
    return outputs


def _filename_tokens(path: str) -> set[str]:
    stem = Path(path).stem
    return {token for token in re.split(r"[^A-Za-z0-9]+", stem) if token}


def _source_priority(path: str) -> int:
    for prefix, priority in PREDICTOR_PREFIX_PRIORITY.items():
        if path.startswith(prefix):
            return priority
    return 0


def build_formula_inventory(
    signals: Iterable[str], sources: Mapping[str, bytes]
) -> pd.DataFrame:
    """Map signals to official source files, reporting ambiguity fail-closed."""

    decoded = {
        path: blob.decode("utf-8", errors="replace") for path, blob in sources.items()
    }
    outputs = {path: _explicit_outputs(text) for path, text in decoded.items()}
    rows: list[dict[str, object]] = []
    for signal in sorted(set(signals)):
        scored: list[tuple[int, str, str]] = []
        for path, text in decoded.items():
            stem = Path(path).stem
            if stem == signal:
                scored.append((100, path, "exact_filename"))
            elif signal in outputs[path]:
                scored.append((95, path, "explicit_output"))
            elif signal in _filename_tokens(path):
                scored.append((90, path, "filename_token"))
            elif re.search(rf"(?<![A-Za-z0-9_]){re.escape(signal)}(?![A-Za-z0-9_])", text):
                scored.append((40, path, "source_reference_only"))
        eligible = [item for item in scored if item[0] >= 90]
        if not eligible:
            match = FormulaMatch(
                signal, "unresolved", "", "", 0, OPENAP_FORMULA_COMMIT, "", ""
            )
        else:
            best_priority = max(_source_priority(item[1]) for item in eligible)
            priority_matches = [
                item for item in eligible if _source_priority(item[1]) == best_priority
            ]
            best_score = max(item[0] for item in priority_matches)
            best = sorted(
                item for item in priority_matches if item[0] == best_score
            )
            if len(best) != 1:
                match = FormulaMatch(
                    signal,
                    "ambiguous",
                    "|".join(item[1] for item in best),
                    best[0][2],
                    len(best),
                    OPENAP_FORMULA_COMMIT,
                    "",
                    "",
                )
            else:
                _, path, method = best[0]
                blob = sources[path]
                match = FormulaMatch(
                    signal,
                    "resolved",
                    path,
                    method,
                    len(eligible),
                    OPENAP_FORMULA_COMMIT,
                    _raw_url(path),
                    sha256(blob).hexdigest(),
                )
        rows.append(match.__dict__)
    return pd.DataFrame(rows).sort_values("signal").reset_index(drop=True)


def write_formula_bundle(
    inventory: pd.DataFrame,
    sources: Mapping[str, bytes],
    output_dir: str | Path,
) -> dict[str, object]:
    output = Path(output_dir)
    source_root = output / "official_sources"
    source_root.mkdir(parents=True, exist_ok=True)
    for path in sorted(set(inventory.loc[inventory["status"].eq("resolved"), "path"])):
        target = source_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sources[path])
    inventory.to_csv(output / "openap_181_formula_inventory.csv", index=False)
    counts = inventory["status"].value_counts().to_dict()
    summary = {
        "repository": OPENAP_REPOSITORY,
        "commit": OPENAP_FORMULA_COMMIT,
        "signals": int(len(inventory)),
        "resolved": int(counts.get("resolved", 0)),
        "ambiguous": int(counts.get("ambiguous", 0)),
        "unresolved": int(counts.get("unresolved", 0)),
        "all_formulas_resolved": bool(inventory["status"].eq("resolved").all()),
    }
    (output / "openap_181_formula_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    return summary


__all__ = [
    "FormulaInventoryError",
    "OPENAP_FORMULA_COMMIT",
    "OPENAP_REPOSITORY",
    "build_formula_inventory",
    "fetch_predictor_sources",
    "write_formula_bundle",
]
