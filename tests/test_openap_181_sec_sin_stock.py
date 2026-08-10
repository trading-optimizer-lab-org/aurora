from __future__ import annotations

from pathlib import Path

import pandas as pd

from aurora.research.openap_181.sec_sin_stock import (
    SINALGO_FORMULA_SHA256,
    calculate_sec_sinalgo_current,
)


FORMATION_AT = "2026-08-09T23:59:59Z"
RETRIEVED_AT = "2026-08-10T10:00:00Z"
ROOT = Path(__file__).resolve().parents[1]


def _status() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for cik, symbol in ((1, "TOB"), (2, "GAME"), (3, "BEER")):
        rows.extend(
            [
                {
                    "cik": cik,
                    "symbol": symbol,
                    "surface": "companyfacts",
                    "status": "ok",
                },
                {
                    "cik": cik,
                    "symbol": symbol,
                    "surface": "submissions",
                    "status": "ok",
                },
            ]
        )
    return pd.DataFrame(rows)


def _submissions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cik": 1,
                "accession_number": "0000000001-25-000001",
                "accepted_at": "2025-02-01T12:00:00Z",
                "sic": 2000,
            },
            {
                "cik": 1,
                "accession_number": "0000000001-26-000001",
                "accepted_at": "2026-05-01T12:00:00Z",
                "sic": 2111,
            },
            {
                "cik": 2,
                "accession_number": "0000000002-26-000001",
                "accepted_at": "2026-05-01T12:00:00Z",
                "sic": 7990,
            },
            {
                "cik": 3,
                "accession_number": "0000000003-26-000001",
                "accepted_at": "2026-09-01T12:00:00Z",
                "sic": 2082,
            },
        ]
    )


def test_sec_sinalgo_emits_only_positive_current_tobacco_or_beer_sic() -> None:
    result = calculate_sec_sinalgo_current(
        _submissions(),
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).set_index("ticker")

    assert result.loc["TOB", "value"] == 1.0
    assert result.loc["TOB", "current_usable"]
    assert result.loc["TOB", "fidelity_class"] == "reconstructed"
    assert result.loc["TOB", "formula_sha256"] == SINALGO_FORMULA_SHA256
    assert pd.isna(result.loc["GAME", "value"])
    assert not result.loc["GAME", "current_usable"]
    assert pd.isna(result.loc["BEER", "value"])
    assert not result.loc["BEER", "current_usable"]


def test_sec_sinalgo_rejects_conflicting_latest_sic() -> None:
    submissions = pd.concat(
        [
            _submissions(),
            pd.DataFrame(
                [
                    {
                        "cik": 1,
                        "accession_number": "0000000001-26-000002",
                        "accepted_at": "2026-05-01T12:00:00Z",
                        "sic": 2082,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    result = calculate_sec_sinalgo_current(
        submissions,
        _status(),
        formation_at=FORMATION_AT,
        retrieved_at=RETRIEVED_AT,
    ).set_index("ticker")

    assert pd.isna(result.loc["TOB", "value"])
    assert not result.loc["TOB", "current_usable"]


def test_sec_sinalgo_is_connected_to_guarded_sec_batch() -> None:
    runner = (ROOT / "scripts" / "run_openap_149_sec_companyfacts.py").read_text(
        encoding="utf-8"
    )
    workflow = (
        ROOT / ".github" / "workflows" / "openap-149-sec-companyfacts.yml"
    ).read_text(encoding="utf-8")

    assert "calculate_sec_sinalgo_current" in runner
    assert "tests/test_openap_181_sec_sin_stock.py" in workflow
    assert "require_github_actions_or_explicit_local_permission" in runner
