"""Audit redundancy among Open Asset Pricing monthly predictor portfolios."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _detect_date_column(frame: pd.DataFrame) -> str:
    preferred = {"date", "eom", "month", "yyyymm", "yearmonth"}
    for column in frame.columns:
        if _key(column) in preferred:
            return str(column)
    return str(frame.columns[0])


def _parse_dates(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    yyyymm = text.str.fullmatch(r"\d{6}")
    parsed = pd.to_datetime(text, errors="coerce")
    parsed.loc[yyyymm] = pd.to_datetime(
        text.loc[yyyymm] + "01", format="%Y%m%d", errors="coerce"
    )
    return parsed


def _token_similarity(left: str, right: str) -> float:
    tokens_left = set(re.findall(r"[a-z]+|\d+", left.lower()))
    tokens_right = set(re.findall(r"[a-z]+|\d+", right.lower()))
    if not tokens_left or not tokens_right:
        return 0.0
    return len(tokens_left & tokens_right) / len(tokens_left | tokens_right)


def _components(nodes: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    graph: dict[str, set[str]] = {node: set() for node in nodes}
    for left, right in edges:
        graph[left].add(right)
        graph[right].add(left)
    seen: set[str] = set()
    result: list[list[str]] = []
    for node in nodes:
        if node in seen or not graph[node]:
            continue
        stack = [node]
        component: list[str] = []
        seen.add(node)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour in graph[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        result.append(sorted(component))
    return sorted(result, key=lambda values: (-len(values), values))


def analyze(
    returns_path: Path,
    summary_path: Path,
    output_dir: Path,
    correlation_threshold: float,
    extreme_threshold: float,
    min_overlap: int,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = pd.read_excel(summary_path, sheet_name="short")
    predictors = metadata.loc[metadata["Cat.Signal"].eq("Predictor")].copy()
    selected = predictors.loc[
        predictors["tstat"].gt(1.96)
        & (predictors["T.Stat"].isna() | predictors["T.Stat"].ge(1.96))
    ].copy()
    if len(selected) != 185:
        raise RuntimeError(f"Expected 185 selected predictors, found {len(selected)}")

    raw = pd.read_csv(returns_path, low_memory=False)
    date_column = _detect_date_column(raw)
    raw[date_column] = _parse_dates(raw[date_column])
    raw = raw.loc[raw[date_column].notna()].set_index(date_column).sort_index()

    available = {_key(column): str(column) for column in raw.columns}
    selected_names = selected["signalname"].astype(str).tolist()
    missing = [name for name in selected_names if _key(name) not in available]
    if missing:
        raise RuntimeError(f"Missing return columns for {len(missing)} predictors: {missing}")

    rename = {available[_key(name)]: name for name in selected_names}
    returns = raw[list(rename)].rename(columns=rename).apply(pd.to_numeric, errors="coerce")
    correlation = returns.corr(min_periods=min_overlap)
    overlap = returns.notna().astype("int16").T.dot(returns.notna().astype("int16"))

    meta = selected.set_index("signalname").to_dict(orient="index")
    pairs: list[dict[str, object]] = []
    for i, left in enumerate(selected_names):
        for right in selected_names[i + 1 :]:
            corr = correlation.at[left, right]
            n_overlap = int(overlap.at[left, right])
            if pd.isna(corr) or n_overlap < min_overlap:
                continue
            left_meta = meta[left]
            right_meta = meta[right]
            same_data = left_meta.get("Cat.Data") == right_meta.get("Cat.Data")
            same_economic = left_meta.get("Cat.Economic") == right_meta.get("Cat.Economic")
            name_similarity = _token_similarity(left, right)
            economically_similar = bool(same_economic or (same_data and name_similarity > 0))
            pairs.append(
                {
                    "signal_a": left,
                    "signal_b": right,
                    "correlation": float(corr),
                    "abs_correlation": abs(float(corr)),
                    "overlap_months": n_overlap,
                    "same_data_family": bool(same_data),
                    "same_economic_family": bool(same_economic),
                    "name_token_similarity": name_similarity,
                    "economically_similar": economically_similar,
                    "data_family_a": left_meta.get("Cat.Data"),
                    "data_family_b": right_meta.get("Cat.Data"),
                    "economic_family_a": left_meta.get("Cat.Economic"),
                    "economic_family_b": right_meta.get("Cat.Economic"),
                    "description_a": left_meta.get("LongDescription"),
                    "description_b": right_meta.get("LongDescription"),
                }
            )

    pair_frame = pd.DataFrame(pairs).sort_values(
        ["abs_correlation", "overlap_months"], ascending=[False, False]
    )
    high = pair_frame.loc[pair_frame["abs_correlation"].ge(correlation_threshold)].copy()
    extreme = pair_frame.loc[pair_frame["abs_correlation"].ge(extreme_threshold)].copy()
    near_duplicates = high.loc[
        high["correlation"].gt(0) & high["economically_similar"]
    ].copy()
    inverse = high.loc[high["correlation"].lt(0)].copy()

    positive_edges = [
        (row.signal_a, row.signal_b)
        for row in high.itertuples()
        if row.correlation >= correlation_threshold
    ]
    clusters = _components(selected_names, positive_edges)
    cluster_rows = [
        {
            "cluster_id": index + 1,
            "cluster_size": len(component),
            "signals": " | ".join(component),
        }
        for index, component in enumerate(clusters)
    ]

    pair_frame.to_csv(output_dir / "all_pairwise_correlations.csv", index=False)
    high.to_csv(output_dir / "high_correlation_pairs.csv", index=False)
    extreme.to_csv(output_dir / "extreme_correlation_pairs.csv", index=False)
    near_duplicates.to_csv(output_dir / "economically_similar_high_corr_pairs.csv", index=False)
    inverse.to_csv(output_dir / "high_inverse_correlation_pairs.csv", index=False)
    pd.DataFrame(cluster_rows).to_csv(output_dir / "correlation_clusters.csv", index=False)
    selected.to_csv(output_dir / "selected_185_predictors.csv", index=False)

    summary = {
        "selected_predictors": len(selected_names),
        "pairwise_comparisons": len(pair_frame),
        "min_overlap_months": min_overlap,
        "high_correlation_threshold": correlation_threshold,
        "extreme_correlation_threshold": extreme_threshold,
        "high_correlation_pairs": len(high),
        "extreme_correlation_pairs": len(extreme),
        "economically_similar_high_corr_pairs": len(near_duplicates),
        "high_inverse_correlation_pairs": len(inverse),
        "positive_correlation_clusters": len(clusters),
        "max_cluster_size": max((len(component) for component in clusters), default=1),
        "date_start": returns.index.min().date().isoformat(),
        "date_end": returns.index.max().date().isoformat(),
        "source": "Open Asset Pricing official monthly long-short portfolios",
    }
    (output_dir / "correlation_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--returns", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--correlation-threshold", type=float, default=0.80)
    parser.add_argument("--extreme-threshold", type=float, default=0.90)
    parser.add_argument("--min-overlap", type=int, default=60)
    args = parser.parse_args()
    summary = analyze(
        args.returns,
        args.summary,
        args.output_dir,
        args.correlation_threshold,
        args.extreme_threshold,
        args.min_overlap,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
