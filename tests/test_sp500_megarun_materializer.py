from __future__ import annotations

import pandas as pd

from aurora.infra.sp500_megarun.materializer import (
    _request_headers,
    _expand_resource,
    coverage_spans_research_window,
    discover_official_data_links,
    parquet_safe_frame,
)


def test_sec_download_headers_identify_the_research_client() -> None:
    headers = _request_headers("https://www.sec.gov/Archives/edgar/full-index/2020/QTR4/master.idx")

    assert "@" in headers["User-Agent"]
    assert headers["Accept-Encoding"] == "gzip, deflate"
    assert _request_headers("https://example.test/data.csv")["User-Agent"].startswith(
        "Aurora-SP500"
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


def test_weekly_or_monthly_sources_may_start_after_calendar_boundary() -> None:
    assert coverage_spans_research_window(
        minimum_date="1998-01-06",
        maximum_date="2010-12-28",
        search_start="1998-01-01",
        evaluation_end="2010-12-31",
    )


def test_resource_expansion_builds_year_quarter_cross_product() -> None:
    rows = _expand_resource(
        {
            "id": "sec",
            "url_template": "https://example.test/{year}/QTR{quarter}/master.idx",
            "years": [2019, 2020],
            "quarters": [1, 4],
            "format": "idx",
        }
    )

    assert [row[0] for row in rows] == ["sec:2019:Q1", "sec:2019:Q4", "sec:2020:Q1", "sec:2020:Q4"]
