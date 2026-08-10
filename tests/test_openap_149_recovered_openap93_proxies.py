from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import pytest

from aurora.research.openap_181.acquisition_149 import (
    build_acquisition_matrix,
    load_target_routes,
)
from aurora.research.openap_181.recovered_openap93_proxies import (
    BETAVIX_RECOVERY_SOURCE,
    COMPEQUISS_FORMULA_ID,
    COMPEQUISS_RECOVERY_SOURCE,
    EQUITY_DURATION_FORMULA_ID,
    EQUITY_DURATION_RECOVERY_SOURCE,
    MARKET_FORMULA_IDS,
    MARKET_RECOVERY_SOURCES,
    OSCORE_FORMULA_ID,
    OSCORE_RECOVERY_SOURCE,
    OPENAP93_RECOVERY_RUN_URL,
    RIO_RECOVERY_SOURCE,
    YAHOO_MARKET_FORMULA_IDS,
    YAHOO_MARKET_RECOVERY_SOURCES,
    load_verified_openap93_comp_equ_iss,
    load_verified_openap93_proxy_batch,
)


ROOT = Path(__file__).resolve().parents[1]
ROUTE_MATRIX = (
    ROOT / "docs" / "OPENAP_181_CURRENT_FREE_SOURCE_REAUDIT_2026-08-09.csv"
)
SOURCE_RUN_ID = 31333714423
SOURCE_HEAD_SHA = "34464d5327598282aa2af1523422105dfd5dd184"
OPENAP_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"


def _row(
    security_id: str,
    ticker: str,
    cik: int,
    *,
    value: float | None,
    current_usable: bool,
) -> dict[str, object]:
    return {
        "security_id": security_id,
        "ticker": ticker,
        "cik": cik,
        "signal": "CompEquIss",
        "formation_at": "2026-08-09",
        "period_end": "2026-02-28",
        "filed_at": "2026-08-07 00:00:00",
        "available_at": "2026-08-07 00:00:00",
        "retrieved_at": "2026-08-09T22:37:41.271512+00:00",
        "value": value,
        "fidelity_class": "reconstructed" if current_usable else "unavailable",
        "current_usable": current_usable,
        "source_id": "sec_edgar|yahoo_public",
        "source_url": (
            "https://www.sec.gov/files/company_tickers_exchange.json|"
            "https://query1.finance.yahoo.com/v8/finance/chart/AAA"
        ),
        "coverage_flag": "current_usable" if current_usable else "missing",
        "formula_id": COMPEQUISS_FORMULA_ID,
        "openap_script": "Signals/pyCode/Predictors/CompEquIss.py",
        "natural_frequency": "annual",
        "staleness_days": 2.0,
        "is_current_for_natural_frequency": current_usable,
        "observation_count": 85,
        "reason_if_missing": "" if current_usable else "missing_causal_multiyear_inputs",
        "caveat": (
            "Primary-share price times SEC issuer shares replaces CRSP company "
            "market equity"
        ),
    }


def _equity_duration_row(
    security_id: str,
    ticker: str,
    cik: int,
    *,
    value: float | None,
    current_usable: bool,
) -> dict[str, object]:
    return {
        **_row(
            security_id,
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        ),
        "signal": "EquityDuration",
        "formula_id": EQUITY_DURATION_FORMULA_ID,
        "openap_script": "Signals/pyCode/Predictors/EquityDuration.py",
        "observation_count": 5,
        "caveat": (
            "SEC annual equity/income/revenue and Yahoo fiscal-period price "
            "replace Compustat/CRSP"
        ),
    }


def _beta_vix_row(
    security_id: str,
    ticker: str,
    cik: int,
    *,
    value: float | None,
    current_usable: bool,
) -> dict[str, object]:
    return {
        **_row(
            security_id,
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        ),
        "signal": "betaVIX",
        "period_end": "2026-07-31",
        "filed_at": "2026-07-31 00:00:00",
        "available_at": "2026-07-31 00:00:00",
        "source_id": "yahoo_public|kenneth_french|cboe_public",
        "formula_id": "openap_beta_vix_20d_min15_market_control",
        "openap_script": "Signals/pyCode/Predictors/ZZ2_betaVIX.py",
        "natural_frequency": "monthly",
        "observation_count": 20,
        "caveat": "",
    }


def _oscore_row(
    security_id: str,
    ticker: str,
    cik: int,
    *,
    value: float | None,
    current_usable: bool,
) -> dict[str, object]:
    return {
        **_row(
            security_id,
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        ),
        "signal": "OScore",
        "period_end": "2025-12-31",
        "filed_at": "2026-02-01 12:00:00",
        "available_at": "2026-02-01 12:00:00",
        "source_id": "sec_edgar|fred_public_csv",
        "formula_id": OSCORE_FORMULA_ID,
        "openap_script": "Signals/pyCode/Predictors/OScore.py",
        "natural_frequency": "annual",
        "observation_count": 4,
        "caveat": (
            "Operating cash flow is the documented OpenAP fallback for "
            "funds from operations"
        ),
    }


MARKET_OPENAP_SCRIPTS = {
    "PriceDelayRsq": (
        "Signals/pyCode/Predictors/"
        "ZZ2_PriceDelaySlope_PriceDelayRsq_PriceDelayTstat.py"
    ),
    "CoskewACX": "Signals/pyCode/Predictors/CoskewACX.py",
    "Coskewness": "Signals/pyCode/Predictors/Coskewness.py",
    "ResidualMomentum": (
        "Signals/pyCode/Predictors/"
        "ZZ1_ResidualMomentum6m_ResidualMomentum.py"
    ),
}
MARKET_FREQUENCIES = {
    "PriceDelayRsq": "annual",
    "CoskewACX": "monthly",
    "Coskewness": "monthly",
    "ResidualMomentum": "monthly",
}
MARKET_OBSERVATION_COUNTS = {
    "PriceDelayRsq": 251,
    "CoskewACX": 252,
    "Coskewness": 60,
    "ResidualMomentum": 83,
}


def _market_row(
    signal: str,
    security_id: str,
    ticker: str,
    cik: int,
    *,
    value: float | None,
    current_usable: bool,
) -> dict[str, object]:
    return {
        **_row(
            security_id,
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        ),
        "signal": signal,
        "period_end": "2026-06-30",
        "filed_at": "2026-06-30 00:00:00",
        "available_at": "2026-06-30 00:00:00",
        "source_id": "yahoo_public|kenneth_french",
        "formula_id": MARKET_FORMULA_IDS[signal],
        "openap_script": MARKET_OPENAP_SCRIPTS[signal],
        "natural_frequency": MARKET_FREQUENCIES[signal],
        "observation_count": MARKET_OBSERVATION_COUNTS[signal],
        "caveat": "",
    }


YAHOO_MARKET_OPENAP_SCRIPTS = {
    "BetaTailRisk": "Signals/pyCode/Predictors/BetaTailRisk.py",
    "DivYieldST": "Signals/pyCode/Predictors/DivYieldST.py",
    "MomVol": "Signals/pyCode/Predictors/MomVol.py",
    "MomRev": "Signals/pyCode/Predictors/MomRev.py",
}
YAHOO_MARKET_CAVEATS = {
    "BetaTailRisk": "",
    "DivYieldST": (
        "Yahoo cash distributions replace CRSP distributions; payment "
        "frequency is inferred from observed ex-date spacing"
    ),
    "MomVol": "",
    "MomRev": "",
}
YAHOO_MARKET_OBSERVATION_COUNTS = {
    "BetaTailRisk": 83,
    "DivYieldST": 84,
    "MomVol": 84,
    "MomRev": 84,
}


def _yahoo_market_row(
    signal: str,
    security_id: str,
    ticker: str,
    cik: int,
    *,
    value: float | None,
    current_usable: bool,
) -> dict[str, object]:
    return {
        **_row(
            security_id,
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        ),
        "signal": signal,
        "period_end": "2026-07-31",
        "filed_at": "2026-08-07 00:00:00",
        "available_at": "2026-08-07 00:00:00",
        "source_id": "yahoo_public",
        "formula_id": YAHOO_MARKET_FORMULA_IDS[signal],
        "openap_script": YAHOO_MARKET_OPENAP_SCRIPTS[signal],
        "natural_frequency": "monthly",
        "observation_count": YAHOO_MARKET_OBSERVATION_COUNTS[signal],
        "caveat": YAHOO_MARKET_CAVEATS[signal],
    }


RIO_FORMULA_IDS = {
    "RIO_MB": "openap_residual_institutional_ownership_lag6_high_mb",
    "RIO_Turnover": (
        "openap_residual_institutional_ownership_lag6_high_turnover"
    ),
    "RIO_Volatility": (
        "openap_residual_institutional_ownership_lag6_high_volatility"
    ),
}
RIO_CAVEATS = {
    "RIO_MB": (
        "SEC 13F, SEC shares/book equity and Yahoo prices reconstruct the "
        "published residual-ownership formula"
    ),
    "RIO_Turnover": (
        "SEC 13F and current monthly Yahoo turnover replace Thomson/CRSP inputs"
    ),
    "RIO_Volatility": (
        "SEC 13F and 12-month Yahoo return volatility replace Thomson/CRSP inputs"
    ),
}


def _rio_row(
    signal: str,
    security_id: str,
    ticker: str,
    cik: int,
    *,
    value: float | None,
    current_usable: bool,
) -> dict[str, object]:
    return {
        **_row(
            security_id,
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        ),
        "signal": signal,
        "filed_at": "2026-08-09 00:00:00",
        "available_at": "2026-08-09 00:00:00",
        "source_id": "sec_13f|openfigi_public|sec_edgar|yahoo_public",
        "formula_id": RIO_FORMULA_IDS[signal],
        "openap_script": (
            "Signals/pyCode/Predictors/"
            "ZZ1_RIO_MB_RIO_Disp_RIO_Turnover_RIO_Volatility.py"
        ),
        "natural_frequency": "quarterly",
        "observation_count": 12,
        "caveat": RIO_CAVEATS[signal],
    }


def _write_artifact(root: Path) -> tuple[Path, Path, Path, Path]:
    root.mkdir()
    recovered_signals = [
        "CompEquIss",
        "EquityDuration",
        "betaVIX",
        "RIO_MB",
        "RIO_Turnover",
        "RIO_Volatility",
        "OScore",
        *MARKET_FORMULA_IDS,
        *YAHOO_MARKET_FORMULA_IDS,
    ]
    selected_signals = recovered_signals + [
        f"SyntheticSignal{index:02d}" for index in range(78)
    ]
    comp_rows = [
        _row("US-SEC-0000000001-AAA", "AAA", 1, value=0.25, current_usable=True),
        _row("US-SEC-0000000002-BBB", "BBB", 2, value=-0.10, current_usable=True),
        _row("US-SEC-0000000003-CCC", "CCC", 3, value=None, current_usable=False),
    ]
    equity_duration_rows = [
        _equity_duration_row(
            "US-SEC-0000000001-AAA",
            "AAA",
            1,
            value=16.0,
            current_usable=True,
        ),
        _equity_duration_row(
            "US-SEC-0000000002-BBB",
            "BBB",
            2,
            value=18.0,
            current_usable=True,
        ),
        {
            **_equity_duration_row(
                "US-SEC-0000000003-CCC",
                "CCC",
                3,
                value=None,
                current_usable=False,
            ),
            "period_end": "2026-08-08",
        },
    ]
    beta_vix_rows = [
        _beta_vix_row(
            "US-SEC-0000000001-AAA",
            "AAA",
            1,
            value=-0.01,
            current_usable=True,
        ),
        _beta_vix_row(
            "US-SEC-0000000002-BBB",
            "BBB",
            2,
            value=0.02,
            current_usable=True,
        ),
        _beta_vix_row(
            "US-SEC-0000000003-CCC",
            "CCC",
            3,
            value=None,
            current_usable=False,
        ),
    ]
    rio_rows = [
        _rio_row(
            signal,
            f"US-SEC-{cik:010d}-{ticker}",
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        )
        for signal in RIO_FORMULA_IDS
        for cik, ticker, value, current_usable in (
            (1, "AAA", 5.0, True),
            (2, "BBB", 3.0, True),
            (3, "CCC", None, False),
        )
    ]
    oscore_rows = [
        _oscore_row(
            "US-SEC-0000000001-AAA",
            "AAA",
            1,
            value=0.0,
            current_usable=True,
        ),
        _oscore_row(
            "US-SEC-0000000002-BBB",
            "BBB",
            2,
            value=1.0,
            current_usable=True,
        ),
        _oscore_row(
            "US-SEC-0000000003-CCC",
            "CCC",
            3,
            value=None,
            current_usable=False,
        ),
    ]
    market_rows = [
        _market_row(
            signal,
            f"US-SEC-{cik:010d}-{ticker}",
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        )
        for signal in MARKET_FORMULA_IDS
        for cik, ticker, value, current_usable in (
            (1, "AAA", -0.05, True),
            (2, "BBB", 0.25, True),
            (3, "CCC", None, False),
        )
    ]
    yahoo_market_rows = [
        _yahoo_market_row(
            signal,
            f"US-SEC-{cik:010d}-{ticker}",
            ticker,
            cik,
            value=value,
            current_usable=current_usable,
        )
        for signal in YAHOO_MARKET_FORMULA_IDS
        for cik, ticker, value, current_usable in (
            (1, "AAA", 1.0, True),
            (2, "BBB", 0.0 if signal == "MomRev" else 2.0, True),
            (3, "CCC", None, False),
        )
    ]
    filler_rows = [
        {
            **_row(
                f"US-SEC-{index + 10:010d}-ZZZ",
                "ZZZ",
                index + 10,
                value=None,
                current_usable=False,
            ),
            "signal": signal,
            "formula_id": f"synthetic_{index}",
            "openap_script": f"Signals/pyCode/Predictors/{signal}.py",
        }
        for index, signal in enumerate(selected_signals[len(recovered_signals) :])
    ]
    signals_path = root / "signals_93_current.csv"
    pd.DataFrame(
        comp_rows
        + equity_duration_rows
        + beta_vix_rows
        + rio_rows
        + oscore_rows
        + market_rows
        + yahoo_market_rows
        + filler_rows
    ).to_csv(
        signals_path,
        index=False,
    )

    coverage_rows = [
        {
            "signal": "CompEquIss",
            "status": "current_usable",
            "fidelity_class": "reconstructed",
            "current_usable": True,
            "exact_formula": True,
            "primary_source": "sec_edgar",
            "fallback_source": "yahoo_public",
            "source_domains": "query1.finance.yahoo.com|sec.gov",
            "latest_period_end": "2026-02-28",
            "latest_available_at": "2026-08-07 00:00:00",
            "natural_frequency": "annual",
            "universe_count": 3,
            "applicable_count": 3,
            "non_null_count": 2,
            "current_usable_count": 2,
            "not_applicable_count": 0,
            "missing_count": 1,
            "coverage_pct": 200 / 3,
            "license": "Public endpoint; terms must be reviewed|US government public data",
            "terms_status": "authorized_public_rate_limited|terms_review_required",
            "scraping_required": False,
            "reason_if_missing": "missing_causal_multiyear_inputs",
            "openap_script": "Signals/pyCode/Predictors/CompEquIss.py",
            "implementation_file": "research/openap_93/advanced_accounting_pipeline.py",
        }
    ]
    coverage_rows.append(
        {
            "signal": "EquityDuration",
            "status": "current_usable",
            "fidelity_class": "reconstructed",
            "current_usable": True,
            "exact_formula": True,
            "primary_source": "sec_edgar",
            "fallback_source": "yahoo_public",
            "source_domains": "query1.finance.yahoo.com|sec.gov",
            "latest_period_end": "2026-02-28",
            "latest_available_at": "2026-08-07 00:00:00",
            "natural_frequency": "annual",
            "universe_count": 3,
            "applicable_count": 3,
            "non_null_count": 2,
            "current_usable_count": 2,
            "not_applicable_count": 0,
            "missing_count": 1,
            "coverage_pct": 200 / 3,
            "license": (
                "Public endpoint; terms must be reviewed|US government public data"
            ),
            "terms_status": (
                "authorized_public_rate_limited|terms_review_required"
            ),
            "scraping_required": False,
            "reason_if_missing": "missing_causal_multiyear_inputs",
            "openap_script": "Signals/pyCode/Predictors/EquityDuration.py",
            "implementation_file": (
                "research/openap_93/advanced_accounting_pipeline.py"
            ),
        }
    )
    for signal in MARKET_FORMULA_IDS:
        coverage_rows.append(
            {
                "signal": signal,
                "status": "current_usable",
                "fidelity_class": "reconstructed",
                "current_usable": True,
                "exact_formula": True,
                "primary_source": "kenneth_french",
                "fallback_source": "yahoo_public",
                "source_domains": (
                    "mba.tuck.dartmouth.edu|query1.finance.yahoo.com"
                ),
                "latest_period_end": "2026-06-30",
                "latest_available_at": "2026-06-30 00:00:00",
                "natural_frequency": MARKET_FREQUENCIES[signal],
                "universe_count": 3,
                "applicable_count": 3,
                "non_null_count": 2,
                "current_usable_count": 2,
                "not_applicable_count": 0,
                "missing_count": 1,
                "coverage_pct": 200 / 3,
                "license": (
                    "Academic public download|Public endpoint; terms must be "
                    "reviewed"
                ),
                "terms_status": "authorized_public|terms_review_required",
                "scraping_required": False,
                "reason_if_missing": "insufficient_history_or_inputs",
                "openap_script": MARKET_OPENAP_SCRIPTS[signal],
                "implementation_file": "research/openap_93/market_pipeline.py",
            }
        )
    for signal in YAHOO_MARKET_FORMULA_IDS:
        coverage_rows.append(
            {
                "signal": signal,
                "status": "current_usable",
                "fidelity_class": "reconstructed",
                "current_usable": True,
                "exact_formula": True,
                "primary_source": "yahoo_public",
                "fallback_source": "",
                "source_domains": "query1.finance.yahoo.com",
                "latest_period_end": "2026-07-31",
                "latest_available_at": "2026-08-07 00:00:00",
                "natural_frequency": "monthly",
                "universe_count": 3,
                "applicable_count": 3,
                "non_null_count": 2,
                "current_usable_count": 2,
                "not_applicable_count": 0,
                "missing_count": 1,
                "coverage_pct": 200 / 3,
                "license": "Public endpoint; terms must be reviewed",
                "terms_status": "terms_review_required",
                "scraping_required": False,
                "reason_if_missing": "insufficient_history_or_inputs",
                "openap_script": YAHOO_MARKET_OPENAP_SCRIPTS[signal],
                "implementation_file": "research/openap_93/market_pipeline.py",
            }
        )
    coverage_rows.append(
        {
            "signal": "betaVIX",
            "status": "current_usable",
            "fidelity_class": "reconstructed",
            "current_usable": True,
            "exact_formula": True,
            "primary_source": "cboe_public",
            "fallback_source": "kenneth_french|yahoo_public",
            "source_domains": (
                "cdn.cboe.com|mba.tuck.dartmouth.edu|query1.finance.yahoo.com"
            ),
            "latest_period_end": "2026-07-31",
            "latest_available_at": "2026-07-31 00:00:00",
            "natural_frequency": "monthly",
            "universe_count": 3,
            "applicable_count": 3,
            "non_null_count": 2,
            "current_usable_count": 2,
            "not_applicable_count": 0,
            "missing_count": 1,
            "coverage_pct": 200 / 3,
            "license": (
                "Academic public download|Cboe website terms|Public endpoint; "
                "terms must be reviewed"
            ),
            "terms_status": (
                "authorized_public|public_download_terms_review|"
                "terms_review_required"
            ),
            "scraping_required": False,
            "reason_if_missing": "missing_market_inputs",
            "openap_script": "Signals/pyCode/Predictors/ZZ2_betaVIX.py",
            "implementation_file": "research/openap_93/market_pipeline.py",
        }
    )
    for signal in RIO_FORMULA_IDS:
        coverage_rows.append(
            {
                "signal": signal,
                "status": "current_usable",
                "fidelity_class": "reconstructed",
                "current_usable": True,
                "exact_formula": True,
                "primary_source": "openfigi_public",
                "fallback_source": "sec_13f|sec_edgar|yahoo_public",
                "source_domains": (
                    "api.openfigi.com|query1.finance.yahoo.com|sec.gov"
                ),
                "latest_period_end": "2026-07-31",
                "latest_available_at": "2026-08-09 00:00:00",
                "natural_frequency": "quarterly",
                "universe_count": 3,
                "applicable_count": 2,
                "non_null_count": 2,
                "current_usable_count": 2,
                "not_applicable_count": 1,
                "missing_count": 0,
                "coverage_pct": 100.0,
                "license": (
                    "OpenFIGI public API terms|Public endpoint; terms must be "
                    "reviewed|US government public data"
                ),
                "terms_status": (
                    "authorized_public_rate_limited|terms_review_required"
                ),
                "scraping_required": False,
                "reason_if_missing": "not_applicable:official_nyse_amex_size_filter",
                "openap_script": (
                    "Signals/pyCode/Predictors/"
                    "ZZ1_RIO_MB_RIO_Disp_RIO_Turnover_RIO_Volatility.py"
                ),
                "implementation_file": (
                    "research/openap_93/institutional_pipeline.py"
                ),
            }
        )
    coverage_rows.append(
        {
            "signal": "OScore",
            "status": "current_usable",
            "fidelity_class": "reconstructed",
            "current_usable": True,
            "exact_formula": True,
            "primary_source": "fred_public_csv",
            "fallback_source": "sec_edgar",
            "source_domains": "fred.stlouisfed.org|sec.gov",
            "latest_period_end": "2025-12-31",
            "latest_available_at": "2026-02-01 12:00:00",
            "natural_frequency": "annual",
            "universe_count": 3,
            "applicable_count": 3,
            "non_null_count": 2,
            "current_usable_count": 2,
            "not_applicable_count": 0,
            "missing_count": 1,
            "coverage_pct": 200 / 3,
            "license": (
                "Federal Reserve public series; per-series rights apply|"
                "US government public data"
            ),
            "terms_status": (
                "authorized_public|authorized_public_rate_limited"
            ),
            "scraping_required": False,
            "reason_if_missing": "missing_point_in_time_sec_inputs",
            "openap_script": "Signals/pyCode/Predictors/OScore.py",
            "implementation_file": "research/openap_93/accounting_pipeline.py",
        }
    )
    coverage_rows.extend(
        {
            "signal": signal,
            "status": "unavailable",
            "fidelity_class": "unavailable",
            "current_usable": False,
            "exact_formula": False,
            "primary_source": "",
            "fallback_source": "",
            "source_domains": "",
            "latest_period_end": "",
            "latest_available_at": "",
            "natural_frequency": "annual",
            "universe_count": 1,
            "applicable_count": 1,
            "non_null_count": 0,
            "current_usable_count": 0,
            "not_applicable_count": 0,
            "missing_count": 1,
            "coverage_pct": 0,
            "license": "",
            "terms_status": "",
            "scraping_required": False,
            "reason_if_missing": "synthetic",
            "openap_script": f"Signals/pyCode/Predictors/{signal}.py",
            "implementation_file": "synthetic.py",
        }
        for signal in selected_signals[len(recovered_signals) :]
    )
    coverage_path = root / "coverage_93.csv"
    pd.DataFrame(coverage_rows).to_csv(coverage_path, index=False)

    source_manifest_path = root / "source_run_manifest.json"
    source_manifest = {
        "formation_at": "2026-08-09T00:00:00",
        "retrieved_at": "2026-08-09T22:37:41.271512+00:00",
        "input_signals": 93,
        "universe_count": 3,
        "rows": (
            len(comp_rows)
            + len(equity_duration_rows)
            + len(beta_vix_rows)
            + len(rio_rows)
            + len(oscore_rows)
            + len(market_rows)
            + len(yahoo_market_rows)
            + len(filler_rows)
        ),
        "openap_commit": OPENAP_COMMIT,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "cost_eur": 0,
        "api_keys_required": False,
        "manual_actions_required": False,
        "selected_signals": selected_signals,
        "current_usable_signal_count": 15,
        "output_hashes": {
            "coverage_93.csv": sha256(coverage_path.read_bytes()).hexdigest(),
            "signals_93_current.csv": sha256(signals_path.read_bytes()).hexdigest(),
        },
    }
    source_manifest_path.write_text(
        json.dumps(source_manifest, sort_keys=True), encoding="utf-8"
    )

    recovery_manifest_path = root / "openap_93_artifact_recovery_manifest.json"
    recovery_manifest = {
        "bytes_fetched": 13720277,
        "cost_eur": 0,
        "current_usable_signal_count": 15,
        "full_artifact_downloaded": False,
        "input_signals": 93,
        "locked_opened": False,
        "range_requests": 12,
        "source_artifact_id": 9045608652,
        "source_artifact_name": "openap-93-max-free-failed-output-31333714423",
        "source_artifact_size_bytes": 2741147673,
        "source_head_sha": SOURCE_HEAD_SHA,
        "source_run_id": SOURCE_RUN_ID,
        "source_run_url": (
            "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"
            f"{SOURCE_RUN_ID}"
        ),
        "strict_score_eligible": False,
        "validation_used_for_selection": False,
        "recovered_hashes": {
            "coverage_93.csv": sha256(coverage_path.read_bytes()).hexdigest(),
            "run_manifest.json": sha256(source_manifest_path.read_bytes()).hexdigest(),
            "signals_93_current.csv": sha256(signals_path.read_bytes()).hexdigest(),
        },
    }
    recovery_manifest_path.write_text(
        json.dumps(recovery_manifest, sort_keys=True), encoding="utf-8"
    )
    return signals_path, coverage_path, source_manifest_path, recovery_manifest_path


def _rewrite_json(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _rehash_artifact(
    signals_path: Path,
    coverage_path: Path,
    source_path: Path,
    recovery_path: Path,
) -> None:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["output_hashes"].update(
        {
            "signals_93_current.csv": sha256(signals_path.read_bytes()).hexdigest(),
            "coverage_93.csv": sha256(coverage_path.read_bytes()).hexdigest(),
        }
    )
    source_path.write_text(json.dumps(source, sort_keys=True), encoding="utf-8")
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    recovery["recovered_hashes"].update(
        {
            "signals_93_current.csv": sha256(signals_path.read_bytes()).hexdigest(),
            "coverage_93.csv": sha256(coverage_path.read_bytes()).hexdigest(),
            "run_manifest.json": sha256(source_path.read_bytes()).hexdigest(),
        }
    )
    recovery_path.write_text(
        json.dumps(recovery, sort_keys=True),
        encoding="utf-8",
    )


def test_verified_openap93_recovery_accepts_only_current_comp_equ_iss(
    tmp_path: Path,
) -> None:
    paths = _write_artifact(tmp_path / "artifact")

    values, evidence_paths, evidence = load_verified_openap93_comp_equ_iss(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )

    assert len(values) == 2
    assert set(values["ticker"]) == {"AAA", "BBB"}
    assert values["current_usable"].all()
    assert not values["strict_score_eligible"].any()
    assert values["fidelity_class"].eq("reconstructed").all()
    assert values["source_id"].eq(COMPEQUISS_RECOVERY_SOURCE).all()
    assert values["formula_id"].eq(COMPEQUISS_FORMULA_ID).all()
    assert values["caveat"].str.contains("historical CRSP identity not verified").all()
    assert set(evidence_paths) == set(paths)
    assert evidence["source_run_id"] == SOURCE_RUN_ID
    assert evidence["current_value_rows"] == 2
    assert evidence["strict_score_increment"] == 0


def test_verified_openap93_proxy_batch_accepts_fifteen_narrow_signals(
    tmp_path: Path,
) -> None:
    _write_artifact(tmp_path / "artifact")

    values, _, evidence = load_verified_openap93_proxy_batch(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )

    assert values.groupby("signal").size().to_dict() == {
        "CompEquIss": 2,
        "EquityDuration": 2,
        "RIO_MB": 2,
        "RIO_Turnover": 2,
        "RIO_Volatility": 2,
        "OScore": 2,
        "PriceDelayRsq": 2,
        "CoskewACX": 2,
        "Coskewness": 2,
        "ResidualMomentum": 2,
        "BetaTailRisk": 2,
        "DivYieldST": 2,
        "MomVol": 2,
        "MomRev": 2,
        "betaVIX": 2,
    }
    duration = values.loc[values["signal"].eq("EquityDuration")]
    assert duration["source_id"].eq(EQUITY_DURATION_RECOVERY_SOURCE).all()
    assert duration["formula_id"].eq(EQUITY_DURATION_FORMULA_ID).all()
    assert duration["fidelity_class"].eq("reconstructed").all()
    assert duration["caveat"].str.contains(
        "historical Compustat/CRSP identity not verified"
    ).all()
    assert not duration["strict_score_eligible"].any()
    assert evidence["signals"]["EquityDuration"]["current_value_rows"] == 2
    beta_vix = values.loc[values["signal"].eq("betaVIX")]
    assert beta_vix["source_id"].eq(BETAVIX_RECOVERY_SOURCE).all()
    assert beta_vix["formula_id"].eq(
        "openap_beta_vix_20d_min15_market_control"
    ).all()
    assert beta_vix["caveat"].str.startswith("recovered from hash-bound").all()
    for signal, formula_id in RIO_FORMULA_IDS.items():
        rio = values.loc[values["signal"].eq(signal)]
        assert rio["source_id"].eq(RIO_RECOVERY_SOURCE).all()
        assert rio["formula_id"].eq(formula_id).all()
        assert rio["value"].between(1, 5).all()
        assert evidence["signals"][signal]["current_value_rows"] == 2
    oscore = values.loc[values["signal"].eq("OScore")]
    assert oscore["source_id"].eq(OSCORE_RECOVERY_SOURCE).all()
    assert oscore["formula_id"].eq(OSCORE_FORMULA_ID).all()
    assert set(oscore["value"]) == {0.0, 1.0}
    assert evidence["signals"]["OScore"]["current_value_rows"] == 2
    for signal, recovery_source in MARKET_RECOVERY_SOURCES.items():
        market = values.loc[values["signal"].eq(signal)]
        assert market["source_id"].eq(recovery_source).all()
        assert market["formula_id"].eq(MARKET_FORMULA_IDS[signal]).all()
        assert evidence["signals"][signal]["current_value_rows"] == 2
    for signal, recovery_source in YAHOO_MARKET_RECOVERY_SOURCES.items():
        market = values.loc[values["signal"].eq(signal)]
        assert market["source_id"].eq(recovery_source).all()
        assert market["formula_id"].eq(YAHOO_MARKET_FORMULA_IDS[signal]).all()
        assert evidence["signals"][signal]["current_value_rows"] == 2
    assert evidence["strict_score_increment"] == 0


@pytest.mark.parametrize(
    "mutation",
    ["formula", "source", "caveat", "observations", "coverage_count"],
)
def test_verified_equity_duration_recovery_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    signals_path, coverage_path, source_path, recovery_path = _write_artifact(
        tmp_path / "artifact"
    )
    if mutation == "coverage_count":
        coverage = pd.read_csv(coverage_path)
        coverage.loc[
            coverage["signal"].eq("EquityDuration"),
            "current_usable_count",
        ] = 3
        coverage.to_csv(coverage_path, index=False)
    else:
        values = pd.read_csv(signals_path)
        row = values.index[
            values["signal"].eq("EquityDuration")
            & values["current_usable"].astype(str).str.lower().eq("true")
        ][0]
        if mutation == "formula":
            values.loc[row, "formula_id"] = "wrong_formula"
        elif mutation == "source":
            values.loc[row, "source_id"] = "sec_edgar"
        elif mutation == "caveat":
            values.loc[row, "caveat"] = "weaker undocumented proxy"
        else:
            values.loc[row, "observation_count"] = 1
        values.to_csv(signals_path, index=False)
    _rehash_artifact(signals_path, coverage_path, source_path, recovery_path)

    with pytest.raises(ValueError):
        load_verified_openap93_proxy_batch(
            tmp_path / "artifact",
            evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
        )


@pytest.mark.parametrize(
    ("signal", "mutation"),
    [
        ("betaVIX", "formula"),
        ("betaVIX", "observations"),
        ("betaVIX", "source"),
        ("RIO_MB", "formula"),
        ("RIO_Turnover", "frequency"),
        ("RIO_Volatility", "quintile"),
        ("RIO_Volatility", "coverage_count"),
        ("OScore", "formula"),
        ("OScore", "observations"),
        ("OScore", "source"),
        ("OScore", "binary"),
        ("OScore", "coverage_count"),
        ("PriceDelayRsq", "formula"),
        ("PriceDelayRsq", "observations"),
        ("CoskewACX", "observations"),
        ("Coskewness", "frequency"),
        ("ResidualMomentum", "source"),
        ("ResidualMomentum", "coverage_count"),
        ("BetaTailRisk", "observations"),
        ("BetaTailRisk", "coverage_count"),
        ("DivYieldST", "category"),
        ("DivYieldST", "caveat"),
        ("MomVol", "decile10"),
        ("MomRev", "binary"),
        ("MomRev", "source"),
    ],
)
def test_verified_market_and_rio_recoveries_fail_closed(
    tmp_path: Path,
    signal: str,
    mutation: str,
) -> None:
    signals_path, coverage_path, source_path, recovery_path = _write_artifact(
        tmp_path / "artifact"
    )
    if mutation == "coverage_count":
        coverage = pd.read_csv(coverage_path)
        coverage.loc[
            coverage["signal"].eq(signal),
            "current_usable_count",
        ] = 1
        coverage.to_csv(coverage_path, index=False)
    else:
        values = pd.read_csv(signals_path)
        row = values.index[
            values["signal"].eq(signal)
            & values["current_usable"].astype(str).str.lower().eq("true")
        ][0]
        if mutation == "formula":
            values.loc[row, "formula_id"] = "wrong_formula"
        elif mutation == "observations":
            if signal in {"CoskewACX", "PriceDelayRsq"}:
                values.loc[row, "observation_count"] = 199
            elif signal == "BetaTailRisk":
                values.loc[row, "observation_count"] = 71
            elif signal == "OScore":
                values.loc[row, "observation_count"] = 3
            else:
                values.loc[row, "observation_count"] = 14
        elif mutation == "source":
            values.loc[row, "source_id"] = "cboe_public"
        elif mutation == "frequency":
            values.loc[row, "natural_frequency"] = "daily"
        elif mutation == "binary":
            values.loc[row, "value"] = 0.5
        elif mutation == "category":
            values.loc[row, "value"] = 4.0
        elif mutation == "decile10":
            values.loc[row, "value"] = 11.0
        elif mutation == "caveat":
            values.loc[row, "caveat"] = "wrong caveat"
        else:
            values.loc[row, "value"] = 2.5
        values.to_csv(signals_path, index=False)
    _rehash_artifact(signals_path, coverage_path, source_path, recovery_path)

    with pytest.raises(ValueError):
        load_verified_openap93_proxy_batch(
            tmp_path / "artifact",
            evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "recovery_hash",
        "source_hash",
        "formula",
        "source",
        "duplicate_identity",
        "lookahead",
        "coverage_count",
        "artifact_identity",
        "strict_manifest",
        "source_safety",
    ],
)
def test_verified_openap93_recovery_fails_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    signals_path, coverage_path, source_path, recovery_path = _write_artifact(
        tmp_path / "artifact"
    )
    if mutation == "recovery_hash":
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].__setitem__(
                "signals_93_current.csv", "0" * 64
            ),
        )
    elif mutation == "source_hash":
        _rewrite_json(
            source_path,
            lambda payload: payload["output_hashes"].__setitem__(
                "signals_93_current.csv", "0" * 64
            ),
        )
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].__setitem__(
                "run_manifest.json", sha256(source_path.read_bytes()).hexdigest()
            ),
        )
    elif mutation in {"formula", "source", "duplicate_identity", "lookahead"}:
        frame = pd.read_csv(signals_path)
        comp = frame.index[frame["signal"].eq("CompEquIss")]
        if mutation == "formula":
            frame.loc[comp[0], "formula_id"] = "wrong_formula"
        elif mutation == "source":
            frame.loc[comp[0], "source_id"] = "yahoo_public"
        elif mutation == "duplicate_identity":
            frame.loc[comp[1], "security_id"] = frame.loc[comp[0], "security_id"]
        else:
            frame.loc[comp[0], "available_at"] = "2026-08-10 00:00:00"
        frame.to_csv(signals_path, index=False)
        digest = sha256(signals_path.read_bytes()).hexdigest()
        _rewrite_json(
            source_path,
            lambda payload: payload["output_hashes"].__setitem__(
                "signals_93_current.csv", digest
            ),
        )
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].update(
                {
                    "signals_93_current.csv": digest,
                    "run_manifest.json": sha256(source_path.read_bytes()).hexdigest(),
                }
            ),
        )
    elif mutation == "coverage_count":
        frame = pd.read_csv(coverage_path)
        frame.loc[frame["signal"].eq("CompEquIss"), "current_usable_count"] = 3
        frame.to_csv(coverage_path, index=False)
        digest = sha256(coverage_path.read_bytes()).hexdigest()
        _rewrite_json(
            source_path,
            lambda payload: payload["output_hashes"].__setitem__(
                "coverage_93.csv", digest
            ),
        )
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].update(
                {
                    "coverage_93.csv": digest,
                    "run_manifest.json": sha256(source_path.read_bytes()).hexdigest(),
                }
            ),
        )
    elif mutation == "artifact_identity":
        _rewrite_json(
            recovery_path,
            lambda payload: payload.__setitem__(
                "source_artifact_size_bytes", 2741147672
            ),
        )
    elif mutation == "strict_manifest":
        _rewrite_json(
            recovery_path,
            lambda payload: payload.__setitem__("strict_score_eligible", True),
        )
    else:
        _rewrite_json(
            source_path,
            lambda payload: payload.__setitem__("locked_opened", True),
        )
        _rewrite_json(
            recovery_path,
            lambda payload: payload["recovered_hashes"].__setitem__(
                "run_manifest.json", sha256(source_path.read_bytes()).hexdigest()
            ),
        )

    with pytest.raises(ValueError):
        load_verified_openap93_comp_equ_iss(
            tmp_path / "artifact",
            evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
        )


def test_comp_equ_iss_recovery_route_is_narrow_and_non_strict(tmp_path: Path) -> None:
    _write_artifact(tmp_path / "artifact")
    values, _, _ = load_verified_openap93_comp_equ_iss(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )
    routes = load_target_routes(ROUTE_MATRIX)
    route = routes.loc[routes["signal"].eq("CompEquIss")].iloc[0]
    assert COMPEQUISS_RECOVERY_SOURCE in route["primary_free_sources"].split("|")
    assert "yahoo_public" not in route["primary_free_sources"].split("|")

    matrix, approved = build_acquisition_matrix(
        routes,
        values,
        formula_inventory=pd.DataFrame(
            [
                {
                    "signal": "CompEquIss",
                    "formula_sha256": (
                        "d87a14114fbd43039f32c71bec6c42d017fedaf0130f8f1d58cc227f899b808b"
                    ),
                }
            ]
        ),
    )
    comp = matrix.loc[matrix["signal"].eq("CompEquIss")].iloc[0]
    assert comp["status"] == "current_signal_computed"
    assert comp["current_value_count"] == 2
    assert comp["fidelity"] == "reconstructed"
    assert not bool(comp["strict_score_eligible"])
    assert set(approved["signal"]) == {"CompEquIss"}


def test_equity_duration_recovery_route_is_narrow_and_non_strict(
    tmp_path: Path,
) -> None:
    _write_artifact(tmp_path / "artifact")
    values, _, _ = load_verified_openap93_proxy_batch(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )
    routes = load_target_routes(ROUTE_MATRIX)
    route = routes.loc[routes["signal"].eq("EquityDuration")].iloc[0]
    assert EQUITY_DURATION_RECOVERY_SOURCE in route["primary_free_sources"].split(
        "|"
    )
    assert "yahoo_public" not in route["primary_free_sources"].split("|")

    matrix, approved = build_acquisition_matrix(
        routes,
        values,
        formula_inventory=pd.DataFrame(
            [
                {
                    "signal": "CompEquIss",
                    "formula_sha256": (
                        "d87a14114fbd43039f32c71bec6c42d017fedaf0130f8f1d58cc227f899b808b"
                    ),
                },
                {
                    "signal": "EquityDuration",
                    "formula_sha256": (
                        "3e4adc868044a3de5b420a8555f816557a8d02dfa3112a09f114bff4593a9997"
                    ),
                },
            ]
        ),
    )
    duration = matrix.loc[matrix["signal"].eq("EquityDuration")].iloc[0]
    assert duration["status"] == "current_signal_computed"
    assert duration["current_value_count"] == 2
    assert duration["coverage"] == pytest.approx(2 / 3)
    assert duration["fidelity"] == "reconstructed"
    assert not bool(duration["strict_score_eligible"])
    assert set(approved["signal"]) == {"CompEquIss", "EquityDuration"}


def test_beta_vix_and_rio_recovery_routes_are_narrow_and_non_strict(
    tmp_path: Path,
) -> None:
    _write_artifact(tmp_path / "artifact")
    values, _, _ = load_verified_openap93_proxy_batch(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )
    signals = {"betaVIX", *RIO_FORMULA_IDS}
    values = values.loc[values["signal"].isin(signals)].copy()
    routes = load_target_routes(ROUTE_MATRIX)
    expected_sources = {
        "betaVIX": BETAVIX_RECOVERY_SOURCE,
        **{signal: RIO_RECOVERY_SOURCE for signal in RIO_FORMULA_IDS},
    }
    for signal, source in expected_sources.items():
        route = routes.loc[routes["signal"].eq(signal)].iloc[0]
        assert source in route["primary_free_sources"].split("|")
        assert "yahoo_public" not in route["primary_free_sources"].split("|")

    formula_hashes = {
        "betaVIX": "1e850d7fde9a46a064c8c281bcc4243655b533cc89d4b7675e80378819e27e41",
        **{
            signal: "34a01df935551f7c8f19f5521084a658f5bc401d65c54c3fcabb7746438a6afa"
            for signal in RIO_FORMULA_IDS
        },
    }
    matrix, approved = build_acquisition_matrix(
        routes,
        values,
        formula_inventory=pd.DataFrame(
            [
                {"signal": signal, "formula_sha256": formula_hash}
                for signal, formula_hash in formula_hashes.items()
            ]
        ),
    )
    for signal in signals:
        evidence = matrix.loc[matrix["signal"].eq(signal)].iloc[0]
        assert evidence["status"] == "current_signal_computed"
        assert evidence["current_value_count"] == 2
        assert evidence["fidelity"] == "reconstructed"
        assert not bool(evidence["strict_score_eligible"])
    assert set(approved["signal"]) == signals


def test_oscore_recovery_route_is_narrow_causal_and_non_strict(
    tmp_path: Path,
) -> None:
    _write_artifact(tmp_path / "artifact")
    values, _, evidence = load_verified_openap93_proxy_batch(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )
    values = values.loc[values["signal"].eq("OScore")].copy()
    routes = load_target_routes(ROUTE_MATRIX)
    route = routes.loc[routes["signal"].eq("OScore")].iloc[0]
    assert OSCORE_RECOVERY_SOURCE in route["primary_free_sources"].split("|")
    assert "yahoo_public" not in route["primary_free_sources"].split("|")

    matrix, approved = build_acquisition_matrix(
        routes,
        values,
        formula_inventory=pd.DataFrame(
            [
                {
                    "signal": "OScore",
                    "formula_sha256": (
                        "ab970ee501bd7ab86a0a0d10b44f20c126195cf3201a1e2ed023ef90accd59d1"
                    ),
                }
            ]
        ),
    )

    oscore = matrix.loc[matrix["signal"].eq("OScore")].iloc[0]
    assert oscore["status"] == "current_signal_computed"
    assert oscore["current_value_count"] == 2
    assert oscore["coverage"] == pytest.approx(2 / 3)
    assert oscore["fidelity"] == "reconstructed"
    assert not bool(oscore["strict_score_eligible"])
    assert set(approved["signal"]) == {"OScore"}
    assert evidence["signals"]["OScore"]["strict_score_eligible"] is False


def test_market_recovery_routes_are_narrow_causal_and_non_strict(
    tmp_path: Path,
) -> None:
    _write_artifact(tmp_path / "artifact")
    values, _, evidence = load_verified_openap93_proxy_batch(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )
    values = values.loc[values["signal"].isin(MARKET_FORMULA_IDS)].copy()
    routes = load_target_routes(ROUTE_MATRIX)
    for signal, recovery_source in MARKET_RECOVERY_SOURCES.items():
        route = routes.loc[routes["signal"].eq(signal)].iloc[0]
        assert recovery_source in route["primary_free_sources"].split("|")

    formula_hashes = {
        "CoskewACX": (
            "81cff4979e62361a896a5b61b61a9778b7abf67c14a51bb2ef3bfebc7b273998"
        ),
        "Coskewness": (
            "1deefcb70f9a3fbb9fec2816de5035f159e57790c0f23354e1047465f1082979"
        ),
        "PriceDelayRsq": (
            "a003da84b08f46f78598f076c50959128016cb402a9235b4dabeb0341ac08fef"
        ),
        "ResidualMomentum": (
            "1f1c9a114c36ee325bc2f679933ad5b1760ccac0816ec437246eb986c31f3143"
        ),
    }
    matrix, approved = build_acquisition_matrix(
        routes,
        values,
        formula_inventory=pd.DataFrame(
            [
                {"signal": signal, "formula_sha256": formula_hash}
                for signal, formula_hash in formula_hashes.items()
            ]
        ),
    )

    selected = matrix.loc[matrix["signal"].isin(MARKET_FORMULA_IDS)]
    assert set(selected["status"]) == {"current_signal_computed"}
    assert set(selected["fidelity"]) == {"reconstructed"}
    assert not selected["strict_score_eligible"].astype(bool).any()
    assert set(approved["signal"]) == set(MARKET_FORMULA_IDS)
    assert all(
        evidence["signals"][signal]["strict_score_eligible"] is False
        for signal in MARKET_FORMULA_IDS
    )


def test_yahoo_market_recovery_routes_are_narrow_and_non_strict(
    tmp_path: Path,
) -> None:
    _write_artifact(tmp_path / "artifact")
    values, _, evidence = load_verified_openap93_proxy_batch(
        tmp_path / "artifact",
        evidence_run_url=OPENAP93_RECOVERY_RUN_URL,
    )
    values = values.loc[
        values["signal"].isin(YAHOO_MARKET_FORMULA_IDS)
    ].copy()
    routes = load_target_routes(ROUTE_MATRIX)
    for signal, recovery_source in YAHOO_MARKET_RECOVERY_SOURCES.items():
        route = routes.loc[routes["signal"].eq(signal)].iloc[0]
        assert recovery_source in route["primary_free_sources"].split("|")

    formula_hashes = {
        "BetaTailRisk": (
            "05a6814113c1e2d7e7513c5831fe73fa9e891c441ab549cbbbd61e418b6c959b"
        ),
        "DivYieldST": (
            "d3831b7da4bfc36433dabcec9545aac8a436e0890d5523ccbf24174479fab2d0"
        ),
        "MomVol": (
            "b80ab3e5495590470e7c865bc55b3dee06d009d4bf1ea2e3b23dfa3073967b27"
        ),
        "MomRev": (
            "c161588a8b984f4832a43c66cb32af555743b5dc068227239123f706be43df60"
        ),
    }
    matrix, approved = build_acquisition_matrix(
        routes,
        values,
        formula_inventory=pd.DataFrame(
            [
                {"signal": signal, "formula_sha256": formula_hash}
                for signal, formula_hash in formula_hashes.items()
            ]
        ),
    )

    selected = matrix.loc[matrix["signal"].isin(YAHOO_MARKET_FORMULA_IDS)]
    assert set(selected["status"]) == {"current_signal_computed"}
    assert set(selected["fidelity"]) == {"reconstructed"}
    assert not selected["strict_score_eligible"].astype(bool).any()
    assert set(approved["signal"]) == set(YAHOO_MARKET_FORMULA_IDS)
    assert all(
        evidence["signals"][signal]["strict_score_eligible"] is False
        for signal in YAHOO_MARKET_FORMULA_IDS
    )
