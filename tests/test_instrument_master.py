"""Tests for R159 instrument master + identity resolver."""
from __future__ import annotations

from datetime import date

import pytest

from aurora.data_contracts.instrument_master import (
    AmbiguousIdentityError,
    IdentityResolver,
    InstrumentProvenance,
    InstrumentRecord,
    expand_provider_aliases,
    normalise_symbol,
    seed_resolver,
)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def _record(canonical="ACME", aliases=()) -> InstrumentRecord:
    return InstrumentRecord(
        canonical_symbol=canonical,
        asset_class="equity",
        exchange="NYSE",
        country="US",
        currency="USD",
        aliases=frozenset(aliases),
        provenance=InstrumentProvenance(
            source="seed", retrieved_at=date(2026, 5, 10),
        ),
    )


def test_record_requires_canonical_symbol():
    with pytest.raises(ValueError):
        InstrumentRecord(
            canonical_symbol="",
            asset_class="equity",
            exchange="NYSE",
            country="US",
            currency="USD",
        )


def test_record_rejects_unknown_asset_class():
    with pytest.raises(ValueError):
        InstrumentRecord(
            canonical_symbol="X",
            asset_class="bogus",
            exchange="NYSE",
            country="US",
            currency="USD",
        )


def test_record_coerces_iterable_aliases_to_frozenset():
    rec = _record(aliases=["X-A", "X.A"])
    assert isinstance(rec.aliases, frozenset)


def test_record_matches_canonical_and_aliases():
    rec = _record(aliases=["A1"])
    assert rec.matches("ACME") is True
    assert rec.matches("A1") is True
    assert rec.matches("OTHER") is False


def test_record_to_dict_serialises_dates_as_iso():
    rec = InstrumentRecord(
        canonical_symbol="X",
        asset_class="equity",
        exchange="NYSE",
        country="US",
        currency="USD",
        listing_start=date(2020, 1, 2),
        provenance=InstrumentProvenance(
            source="seed", retrieved_at=date(2026, 5, 10),
        ),
    )
    payload = rec.to_dict()
    assert payload["listing_start"] == "2020-01-02"
    assert payload["provenance"]["retrieved_at"] == "2026-05-10"


def test_provenance_rejects_non_date_retrieved_at():
    with pytest.raises(TypeError):
        InstrumentProvenance(source="x", retrieved_at="2026-05-10")  # type: ignore[arg-type]


def test_provenance_rejects_unknown_confidence():
    with pytest.raises(ValueError):
        InstrumentProvenance(
            source="x", retrieved_at=date(2026, 5, 10), confidence="bogus",
        )


# ---------------------------------------------------------------------------
# Resolver tests
# ---------------------------------------------------------------------------


def test_resolver_register_and_resolve_canonical():
    r = IdentityResolver()
    r.register(_record("ACME"))
    assert r.resolve("ACME").canonical_symbol == "ACME"
    assert "ACME" in r


def test_resolver_resolves_alias():
    r = IdentityResolver()
    r.register(_record("BRK.B", aliases=["BRK-B"]))
    rec = r.resolve("BRK-B")
    assert rec.canonical_symbol == "BRK.B"


def test_resolver_unknown_symbol_raises_keyerror():
    r = IdentityResolver()
    with pytest.raises(KeyError):
        r.resolve("MISSING")


def test_resolver_ambiguous_alias_raises():
    r = IdentityResolver()
    r.register(_record("ACMEA", aliases=["A.SHARED"]))
    r.register(_record("ACMEB", aliases=["A.SHARED"]))
    with pytest.raises(AmbiguousIdentityError):
        r.resolve("A.SHARED")


def test_resolver_ambiguous_does_not_lose_canonical_lookup():
    r = IdentityResolver()
    r.register(_record("ACMEA", aliases=["SHARED"]))
    r.register(_record("ACMEB", aliases=["SHARED"]))
    # Canonical lookup remains valid even though the alias is ambiguous.
    assert r.resolve("ACMEA").canonical_symbol == "ACMEA"


def test_resolver_register_replace_overwrites():
    r = IdentityResolver()
    r.register(_record("ACME"))
    with pytest.raises(ValueError):
        r.register(_record("ACME"))
    r.register(
        InstrumentRecord(
            canonical_symbol="ACME",
            asset_class="etf",
            exchange="ARCA",
            country="US",
            currency="USD",
        ),
        replace=True,
    )
    assert r.resolve("ACME").asset_class == "etf"


def test_resolver_is_resolved_returns_bool():
    r = IdentityResolver()
    r.register(_record("ACME", aliases=["AC"]))
    assert r.is_resolved("AC") is True
    assert r.is_resolved("ZZZ") is False


def test_resolver_coverage_report_classifies():
    r = IdentityResolver()
    r.register(_record("ACME", aliases=["AC"]))
    r.register(_record("XA", aliases=["DUP"]))
    r.register(_record("XB", aliases=["DUP"]))
    out = r.coverage_report(["ACME", "AC", "MISSING", "DUP"])
    assert out["resolved"] == ["AC", "ACME"]
    assert out["unresolved"] == ["MISSING"]
    assert out["ambiguous"] == ["DUP"]


def test_resolver_aliases_of_returns_frozenset():
    r = IdentityResolver()
    r.register(_record("ACME", aliases=["A1", "A2"]))
    out = r.aliases_of("ACME")
    assert out == frozenset({"A1", "A2"})


def test_resolver_all_records_sorted_by_canonical():
    r = IdentityResolver()
    r.register(_record("BBB"))
    r.register(_record("AAA"))
    out = [rec.canonical_symbol for rec in r.all_records()]
    assert out == ["AAA", "BBB"]


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


def test_normalise_symbol_folds_separators():
    assert normalise_symbol("brk-b") == "BRK.B"
    assert normalise_symbol("brk/b") == "BRK.B"
    assert normalise_symbol(" aapl ") == "AAPL"
    assert normalise_symbol("") == ""


def test_expand_provider_aliases_only_for_share_classes():
    out = expand_provider_aliases("BRK.B")
    assert out == frozenset({"BRK-B", "BRK/B"})
    assert expand_provider_aliases("AAPL") == frozenset()


# ---------------------------------------------------------------------------
# Seed resolver tests
# ---------------------------------------------------------------------------


def test_seed_resolver_resolves_brk_b_aliases():
    r = seed_resolver(retrieved_at=date(2026, 5, 10))
    rec = r.resolve("BRK-B")
    assert rec.canonical_symbol == "BRK.B"
    assert rec.cik == "1067983"


def test_seed_resolver_includes_eurusd_aliases():
    r = seed_resolver(retrieved_at=date(2026, 5, 10))
    assert r.is_resolved("EUR/USD") is True
    assert r.is_resolved("EUR-USD") is True


def test_seed_resolver_attaches_provenance():
    r = seed_resolver(retrieved_at=date(2026, 5, 10))
    rec = r.resolve("SPY")
    assert rec.provenance is not None
    assert rec.provenance.retrieved_at == date(2026, 5, 10)
    assert rec.provenance.confidence == "high"
