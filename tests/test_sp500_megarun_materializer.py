from __future__ import annotations

import pandas as pd

from aurora.infra.sp500_megarun.materializer import (
    discover_official_data_links,
    parquet_safe_frame,
)


def test_official_data_link_discovery_resolves_relative_links_and_deduplicates() -> None:
    html = b"""
    <a href="/files/history.xlsx">Download</a>
    <a href="https://www.finra.org/files/history.xlsx?download=1">Again</a>
    <a href="javascript:alert(1)">Ignore</a>
    <a href="https://evil.example/data.xlsx">Wrong host</a>
    """

    links = discover_official_data_links(
        html,
        base_url="https://www.finra.org/page",
        allowed_hosts={"www.finra.org"},
    )

    assert links == (
        "https://www.finra.org/files/history.xlsx",
        "https://www.finra.org/files/history.xlsx?download=1",
    )


def test_official_data_link_discovery_accepts_zip_csv_and_xls_only() -> None:
    html = b"""
    <a href="data.csv">CSV</a><a href="book.xls">XLS</a>
    <a href="archive.zip">ZIP</a><a href="manual.pdf">PDF</a>
    """

    links = discover_official_data_links(
        html,
        base_url="https://www.philadelphiafed.org/data/index.html",
        allowed_hosts={"www.philadelphiafed.org"},
    )

    assert links == (
        "https://www.philadelphiafed.org/data/archive.zip",
        "https://www.philadelphiafed.org/data/book.xls",
        "https://www.philadelphiafed.org/data/data.csv",
    )


def test_parquet_safe_frame_stabilizes_mixed_object_columns() -> None:
    frame = pd.DataFrame({"mixed": [1.5, "18.13", None], "number": [1.0, 2.0, 3.0]})

    safe = parquet_safe_frame(frame)

    assert str(safe["mixed"].dtype) == "string"
    assert str(safe["number"].dtype) == "float64"
