"""v38 checks: the grid and the books' items from the per-member cache."""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def V():
    from test_v24 import _script
    return _script("run_v38", "run_v38_under_test")


def test_grid(V) -> None:
    assert len(V.BOOKS) == len(set(V.BOOKS)) == 216 and len(V.JOBS) == 24
    assert sorted(b for k in range(V.CHUNKS) for b in V.BOOKS[k::V.CHUNKS]) == sorted(V.BOOKS)


def test_cache_and_items(V, monkeypatch) -> None:
    calls = []

    def fake(rows, level, size, ladder, **costs):
        calls.append((rows[0]["fam"] if rows else None, size))
        return [{"fam": rows[0]["fam"], "size": size}] if rows else []
    monkeypatch.setattr(V.R35, "book_items", fake)
    rows = [{"fam": m} for m in V.MEMBER_SIZES]
    b = (0.3, 0.5, 0.1, 0.0, "half")
    cache = V.member_cache(rows, 5000.0, [b])
    assert sorted(calls) == sorted([("B:v19:DS1", 0.3), ("B:v20:RU", 0.5), ("B:v20:NS", 0.1)])
    its = V.book_its(cache, b)
    assert [(it["fam"], it["size"]) for it in its] == [("B:v19:DS1", 0.3), ("B:v20:RU", 0.5), ("B:v20:NS", 0.1)]
    assert V.book_name(b) == "DS1 30% RU 50% NS 10% ON1 0% HOT half"
