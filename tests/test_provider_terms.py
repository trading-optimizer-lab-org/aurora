"""Tests for R178 provider terms registry."""
from __future__ import annotations

import json
from datetime import date

import pytest

from aurora.data_contracts.provider_terms import (
    ProviderTerms,
    ProviderTermsBlocked,
    ProviderTermsRegistry,
    UsageLabel,
    default_registry,
    explain_usages,
    render_provider_detail,
    render_table,
)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def _make_terms(**overrides) -> ProviderTerms:
    base = dict(
        provider="acme",
        source_url="https://example.com",
        licence_url="https://example.com/terms",
        licence_summary="acme",
        cost_tier="free",
        reviewed_at=date(2026, 5, 10),
        allowed_usage=frozenset({UsageLabel.PERSONAL_RESEARCH}),
    )
    base.update(overrides)
    return ProviderTerms(**base)


def test_provider_terms_requires_non_empty_provider():
    with pytest.raises(ValueError):
        _make_terms(provider="")


def test_provider_terms_rejects_unknown_cost_tier():
    with pytest.raises(ValueError):
        _make_terms(cost_tier="bogus")


def test_provider_terms_rejects_invalid_reviewed_at():
    with pytest.raises(TypeError):
        _make_terms(reviewed_at="2026-05-10")  # str, not date


def test_provider_terms_coerces_iterable_to_frozenset():
    terms = _make_terms(allowed_usage={UsageLabel.SMOKE_TEST})
    assert isinstance(terms.allowed_usage, frozenset)


def test_provider_terms_rejects_non_usage_label_member():
    with pytest.raises(TypeError):
        _make_terms(allowed_usage=frozenset({"smoke_test"}))


def test_permits_returns_true_for_allowed():
    terms = _make_terms()
    assert terms.permits(UsageLabel.PERSONAL_RESEARCH) is True


def test_permits_returns_false_for_disallowed():
    terms = _make_terms()
    assert terms.permits(UsageLabel.LIVE_TRADING) is False


def test_explain_lists_personal_use_only_reason():
    terms = _make_terms(personal_use_only=True)
    msg = terms.explain(UsageLabel.LIVE_TRADING)
    assert "personal-use-only" in msg


def test_explain_lists_redistribution_reason():
    terms = _make_terms(redistribution_allowed=False)
    msg = terms.explain(UsageLabel.REDISTRIBUTION)
    assert "redistribution not allowed" in msg


def test_explain_falls_back_to_not_in_allowed_usage():
    terms = _make_terms()
    msg = terms.explain(UsageLabel.PAPER_TRADING)
    assert "not in allowed_usage" in msg


def test_explain_for_allowed_says_permitted():
    terms = _make_terms()
    msg = terms.explain(UsageLabel.PERSONAL_RESEARCH)
    assert "permitted" in msg


def test_to_dict_round_trip_keys():
    terms = _make_terms()
    payload = terms.to_dict()
    assert payload["provider"] == "acme"
    assert payload["allowed_usage"] == ["personal_research"]
    assert payload["reviewed_at"] == "2026-05-10"


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


def test_registry_register_and_get():
    reg = ProviderTermsRegistry()
    t = _make_terms()
    reg.register(t)
    assert reg.get("acme") is t
    assert "acme" in reg
    assert len(reg) == 1


def test_registry_rejects_duplicate_unless_replace():
    reg = ProviderTermsRegistry()
    reg.register(_make_terms())
    with pytest.raises(ValueError):
        reg.register(_make_terms())
    reg.register(_make_terms(licence_summary="updated"), replace=True)
    assert reg.require("acme").licence_summary == "updated"


def test_require_raises_for_unknown_provider():
    reg = ProviderTermsRegistry()
    with pytest.raises(KeyError):
        reg.require("missing")


def test_assert_allowed_passes_for_permitted_usage():
    reg = ProviderTermsRegistry()
    reg.register(_make_terms())
    reg.assert_allowed("acme", UsageLabel.PERSONAL_RESEARCH)


def test_assert_allowed_blocks_disallowed_usage():
    reg = ProviderTermsRegistry()
    reg.register(_make_terms())
    with pytest.raises(ProviderTermsBlocked):
        reg.assert_allowed("acme", UsageLabel.LIVE_TRADING)


def test_assert_allowed_blocks_unknown_provider():
    reg = ProviderTermsRegistry()
    with pytest.raises(ProviderTermsBlocked):
        reg.assert_allowed("acme", UsageLabel.PERSONAL_RESEARCH)


def test_is_allowed_boolean_form():
    reg = ProviderTermsRegistry()
    reg.register(_make_terms())
    assert reg.is_allowed("acme", UsageLabel.PERSONAL_RESEARCH) is True
    assert reg.is_allowed("acme", UsageLabel.LIVE_TRADING) is False
    assert reg.is_allowed("missing", UsageLabel.PERSONAL_RESEARCH) is False


def test_providers_sorted():
    reg = ProviderTermsRegistry()
    reg.register(_make_terms(provider="zeta"))
    reg.register(_make_terms(provider="alpha"))
    assert reg.providers() == ["alpha", "zeta"]


# ---------------------------------------------------------------------------
# Seed registry tests
# ---------------------------------------------------------------------------


def test_default_registry_contains_known_providers():
    reg = default_registry(reviewed=date(2026, 5, 10))
    expected = {
        "yahoo",
        "snapshot",
        "csv",
        "synthetic",
        "ccxt",
        "dukascopy",
        "marketdata_app",
        "sec_edgar",
        "dbnomics",
        "ecb",
    }
    assert expected.issubset(set(reg.providers()))


def test_yahoo_is_personal_use_only():
    reg = default_registry(reviewed=date(2026, 5, 10))
    yahoo = reg.require("yahoo")
    assert yahoo.personal_use_only is True
    assert yahoo.permits(UsageLabel.LIVE_TRADING) is False
    assert yahoo.permits(UsageLabel.REDISTRIBUTION) is False
    assert yahoo.permits(UsageLabel.PERSONAL_RESEARCH) is True


def test_dbnomics_requires_attribution_and_is_non_redistributable():
    reg = default_registry(reviewed=date(2026, 5, 10))
    db = reg.require("dbnomics")
    assert db.requires_attribution is True
    assert db.redistribution_allowed is False


def test_synthetic_blocks_live_trading():
    reg = default_registry(reviewed=date(2026, 5, 10))
    assert reg.is_allowed("synthetic", UsageLabel.LIVE_TRADING) is False


def test_sec_edgar_allows_redistribution():
    reg = default_registry(reviewed=date(2026, 5, 10))
    sec = reg.require("sec_edgar")
    assert sec.redistribution_allowed is True
    assert sec.permits(UsageLabel.REDISTRIBUTION) is True


def test_marketdata_app_personal_use_blocks_live():
    reg = default_registry(reviewed=date(2026, 5, 10))
    with pytest.raises(ProviderTermsBlocked) as exc:
        reg.assert_allowed("marketdata_app", UsageLabel.LIVE_TRADING)
    assert "personal-use-only" in str(exc.value) or "blocked" in str(exc.value)


# ---------------------------------------------------------------------------
# Renderers + helpers
# ---------------------------------------------------------------------------


def test_render_table_includes_header_and_provider():
    reg = ProviderTermsRegistry()
    reg.register(_make_terms())
    out = render_table(reg)
    assert "PROVIDER" in out
    assert "acme" in out


def test_render_provider_detail_lists_required_fields():
    reg = ProviderTermsRegistry()
    reg.register(_make_terms())
    out = render_provider_detail(reg, "acme")
    for label in (
        "provider", "cost_tier", "licence_url", "allowed_usage",
        "personal_use_only", "redistribution_allowed",
    ):
        assert label in out


def test_explain_usages_returns_one_message_per_usage():
    reg = ProviderTermsRegistry()
    reg.register(_make_terms())
    out = explain_usages(
        "acme", [UsageLabel.PERSONAL_RESEARCH, UsageLabel.LIVE_TRADING], reg,
    )
    assert "personal_research" in out
    assert "live_trading" in out


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_provider_terms_cli_table(capsys):
    from aurora.cli.cmd_data import cmd_data_provider_terms

    class _Args:
        provider = None
        check_usage = None
        json = False

    rc = cmd_data_provider_terms(_Args())
    captured = capsys.readouterr()
    assert rc == 0
    assert "PROVIDER" in captured.out
    assert "yahoo" in captured.out


def test_provider_terms_cli_check_usage_yahoo_blocks_live(capsys):
    from aurora.cli.cmd_data import cmd_data_provider_terms

    class _Args:
        provider = None
        check_usage = "live_trading"
        json = False

    rc = cmd_data_provider_terms(_Args())
    captured = capsys.readouterr()
    assert rc == 0
    assert "BLOCK" in captured.out
    assert "yahoo" in captured.out


def test_provider_terms_cli_json_output(capsys):
    from aurora.cli.cmd_data import cmd_data_provider_terms

    class _Args:
        provider = "yahoo"
        check_usage = None
        json = True

    rc = cmd_data_provider_terms(_Args())
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert "yahoo" in payload
    assert payload["yahoo"]["personal_use_only"] is True
