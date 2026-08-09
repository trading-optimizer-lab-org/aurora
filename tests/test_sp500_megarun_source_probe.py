from __future__ import annotations

from datetime import date
from pathlib import Path
from threading import Barrier, Lock
import time

import pytest

from aurora.core.execution_policy import LocalRunBlocked
from aurora.infra.sp500_megarun.data_contract import (
    SourcePlanItem,
    load_and_validate_contract,
    load_and_validate_source_plan,
)
from aurora.infra.sp500_megarun.source_probe import (
    ExpandedSource,
    expand_source_urls,
    probe_expanded_sources,
    probe_sources,
)


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
        {
            "id": "vintages",
            "url_template": "https://example.test/{series_id}?vintage_date={vintage_dates}",
            "series_ids": ["PIT"],
            "vintage_schedule": {
                "start": "1998-01-31",
                "end": "1998-03-31",
                "frequency": "month_end",
            },
            "format": "csv",
        },
    )

    expanded = expand_source_urls(resources, secrets={})

    assert [item.url for item in expanded] == [
        "https://example.test/ONE",
        "https://example.test/TWO",
        "https://example.test/2009.zip",
        "https://example.test/2010.zip",
        "https://example.test/PIT?vintage_date=1998-01-31%2C1998-02-28%2C1998-03-31",
    ]
    assert all("2011" not in item.url for item in expanded)


def test_source_probe_is_blocked_locally_even_with_valid_contract(tmp_path: Path) -> None:
    contract = load_and_validate_contract(CONTRACT_PATH)
    source_plan = load_and_validate_source_plan(SOURCE_PLAN_PATH, contract)

    with pytest.raises(LocalRunBlocked):
        probe_sources(source_plan, output_path=tmp_path / "report.json", environ={})


def test_probe_expanded_sources_uses_bounded_parallel_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    rendezvous = Barrier(2, timeout=2)

    class FakeResponse:
        ok = True
        status_code = 200
        content = b"date,value\n2000-01-01,1\n"

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        assert kwargs["timeout"] == (15, 45)
        rendezvous.wait()
        return FakeResponse()

    monkeypatch.setattr("aurora.infra.sp500_megarun.source_probe.requests.get", fake_get)
    sources = (
        ExpandedSource("one", "https://example.test/one.csv", "csv"),
        ExpandedSource("two", "https://example.test/two.csv", "csv"),
    )

    rows = probe_expanded_sources(sources, max_workers=2)

    assert [row["resource_id"] for row in rows] == ["one", "two"]
    assert all(row["shape_valid"] is True for row in rows)


def test_probe_sources_uses_one_global_queue_across_datasets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rendezvous = Barrier(2, timeout=2)

    class FakeResponse:
        ok = True
        status_code = 200
        content = b"date,value\n2000-01-01,1\n"

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        rendezvous.wait()
        return FakeResponse()

    monkeypatch.setattr("aurora.infra.sp500_megarun.source_probe.requests.get", fake_get)
    source_plan = {
        dataset_id: SourcePlanItem(
            dataset_id=dataset_id,
            execution="github_actions_only",
            acquisition_kind="direct",
            adapter="academic_table",
            maximum_observation_date=date(2010, 12, 31),
            resources=({"id": dataset_id, "url": f"https://example.test/{dataset_id}.csv", "format": "csv"},),
        )
        for dataset_id in ("D_ONE", "D_TWO")
    }

    report = probe_sources(
        source_plan,
        output_path=tmp_path / "report.json",
        environ={"GITHUB_ACTIONS": "true"},
    )

    assert report["ready"] is True


def test_probe_expanded_sources_limits_parallelism_per_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = Lock()
    active = 0
    maximum_active = 0

    class FakeResponse:
        ok = True
        status_code = 200
        content = b"date,value\n2000-01-01,1\n"

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.1)
        with lock:
            active -= 1
        return FakeResponse()

    monkeypatch.setattr("aurora.infra.sp500_megarun.source_probe.requests.get", fake_get)
    sources = tuple(
        ExpandedSource(str(index), f"https://one.example/{index}.csv", "csv")
        for index in range(4)
    )

    probe_expanded_sources(sources, max_workers=4, per_host_workers=2)

    assert maximum_active == 2


def test_prefix_probe_streams_only_a_bounded_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        ok = True
        status_code = 206
        headers = {"Content-Length": "1000000"}

        def iter_content(self, chunk_size: int) -> object:
            assert chunk_size == 65536
            yield b"PK\x03\x04sample"

        def close(self) -> None:
            return None

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        assert kwargs["stream"] is True
        return FakeResponse()

    monkeypatch.setattr("aurora.infra.sp500_megarun.source_probe.requests.get", fake_get)
    source = ExpandedSource(
        "large_zip",
        "https://large.example/data.zip",
        "zip_xml",
        probe_mode="prefix",
    )

    row = probe_expanded_sources((source,), max_workers=1)[0]

    assert row["shape_valid"] is True
    assert row["byte_count"] == 10
    assert row["declared_byte_count"] == 1000000
