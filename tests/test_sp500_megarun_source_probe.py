from __future__ import annotations

from pathlib import Path

import pytest

from aurora.core.execution_policy import LocalRunBlocked
from aurora.infra.sp500_megarun.data_contract import (
    load_and_validate_contract,
    load_and_validate_source_plan,
)
from aurora.infra.sp500_megarun.source_probe import expand_source_urls, probe_sources


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_free_data_120.json"
SOURCE_PLAN_PATH = REPO_ROOT / "config" / "sp500_megarun_free_sources.json"


def test_expand_source_urls_expands_series_and_year_templates_without_post_2010_dates() -> None:
    resources = (
        {
            "id": "series",
            "url_template": "https://example.test/{series_id}",
            "series_ids": ["ONE", "TWO"],
            "format": "csv",
        },
        {
            "id": "years",
            "url_template": "https://example.test/{year}.zip",
            "years": [2009, 2010],
            "format": "zip_csv",
        },
    )

    expanded = expand_source_urls(resources, secrets={})

    assert [item.url for item in expanded] == [
        "https://example.test/ONE",
        "https://example.test/TWO",
        "https://example.test/2009.zip",
        "https://example.test/2010.zip",
    ]
    assert all("2011" not in item.url for item in expanded)


def test_source_probe_is_blocked_locally_even_with_valid_contract(tmp_path: Path) -> None:
    contract = load_and_validate_contract(CONTRACT_PATH)
    source_plan = load_and_validate_source_plan(SOURCE_PLAN_PATH, contract)

    with pytest.raises(LocalRunBlocked):
        probe_sources(source_plan, output_path=tmp_path / "report.json", environ={})
