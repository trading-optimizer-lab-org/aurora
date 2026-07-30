from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs/adr/0003-gtbi-v7-identity.md"


def test_gtbi_v7_identity_adr_freezes_required_identity() -> None:
    text = ADR.read_text(encoding="utf-8")
    required = {
        "product=GTBI V7 Performance Engine",
        "reference_engine=GTBI Fast Strict V6",
        "clean_portfolio_in_scope=false",
        "scientific_change_allowed=false",
        "full_run_authorized=false",
        "train_end=2010-12-31",
        "validation_start=2011-01-01",
        "validation_end=2020-12-31",
        "historical_exclusion_start=2021-01-01",
        "locked_start=2021-01-01",
        "execution_environment=GitHub Actions",
        "g1a_status=blocked",
    }
    for value in required:
        assert value in text


def test_gtbi_v7_identity_adr_does_not_claim_formal_approval() -> None:
    text = ADR.read_text(encoding="utf-8")
    assert "Status: `PROPOSED_BLOCKED_BY_G0`" in text
    assert "it does not complete it" in text
    assert "full_run_authorized=true" not in text
