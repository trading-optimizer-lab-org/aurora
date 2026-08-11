from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable

import pandas as pd
import pytest

from aurora.research.openap_181.verified_current_batches import (
    CURRENT_BATCH_CONTRACTS,
    FORMULA_INVENTORY_SHA256,
    CurrentBatchContract,
    load_verified_current_batch,
)


ROOT = Path(__file__).resolve().parents[1]
RUN_URL_PREFIX = "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/"


def _row(
    *,
    security_id: str = "US-SEC-0000000001-AAA",
    value: float | None = 0.25,
    current_usable: bool = True,
) -> dict[str, object]:
    return {
        "security_id": security_id,
        "ticker": "AAA",
        "cik": "0000000001",
        "signal": "Cash",
        "formation_at": "2026-08-09T00:00:00Z",
        "period_end": "2025-12-31",
        "filed_at": "2026-02-01T12:00:00Z",
        "available_at": "2026-02-01T12:00:00Z",
        "retrieved_at": "2026-08-10T12:00:00Z",
        "value": value,
        "fidelity_class": "reconstructed" if current_usable else "unavailable",
        "current_usable": current_usable,
        "source_id": "sec_edgar",
        "source_url": (
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"
        ),
        "formula_id": "openap_cash_fixture",
        "formula_sha256": "a" * 64,
        "observation_count": 2 if current_usable else 0,
        "reason_if_missing": "" if current_usable else "missing_inputs",
        "caveat": "SEC reconstruction",
        "strict_score_eligible": False,
    }


def _write_fixture(
    root: Path,
    *,
    mutate_rows: Callable[[list[dict[str, object]]], None] | None = None,
    manifest_updates: dict[str, object] | None = None,
    allow_missing_current_usable: bool = False,
    allow_missing_strict_score_eligible: bool = False,
) -> tuple[CurrentBatchContract, Path, Path]:
    root.mkdir()
    rows = [
        _row(),
        _row(
            security_id="US-SEC-0000000002-BBB",
            value=None,
            current_usable=False,
        ),
    ]
    if mutate_rows is not None:
        mutate_rows(rows)
    expected_usable_rows = 1
    if allow_missing_current_usable:
        rows[1].update(
            {
                "value": -0.10,
                "fidelity_class": "reconstructed",
                "observation_count": 2,
                "reason_if_missing": "",
            }
        )
        expected_usable_rows = 2
    frame = pd.DataFrame(rows)
    if allow_missing_current_usable:
        frame = frame.drop(columns=["current_usable"])
    if allow_missing_strict_score_eligible:
        frame = frame.drop(columns=["strict_score_eligible"])
    csv_path = root / "fixture_current.csv"
    frame.to_csv(csv_path, index=False)

    manifest = {
        "current_value_rows": len(frame),
        "current_usable_rows": expected_usable_rows,
        "signals_calculated": ["Cash"],
        "formation_at": "2026-08-09T02:00:00+02:00",
        "formula_inventory_sha256": FORMULA_INVENTORY_SHA256,
        "strict_score_eligible": False,
        "locked_opened": False,
        "forward_opened": False,
        "validation_used_for_selection": False,
        "cost_eur": 0,
    }
    if manifest_updates:
        manifest.update(manifest_updates)
    manifest_path = root / "fixture_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract = CurrentBatchContract(
        batch_id="fixture",
        run_id=42,
        csv_filename=csv_path.name,
        manifest_filename=manifest_path.name,
        csv_sha256=sha256(csv_path.read_bytes()).hexdigest(),
        expected_signals=("Cash",),
        expected_rows=len(frame),
        expected_usable_rows=expected_usable_rows,
        expected_sources=(("Cash", "sec_edgar"),),
        expected_formula_ids=(("Cash", "openap_cash_fixture"),),
        expected_formula_sha256=(("Cash", "a" * 64),),
        manifest_row_count_key="current_value_rows",
        manifest_usable_count_key="current_usable_rows",
        manifest_signal_list_key="signals_calculated",
        required_false_manifest_fields=(
            "strict_score_eligible",
            "locked_opened",
            "forward_opened",
            "validation_used_for_selection",
        ),
        required_zero_manifest_fields=("cost_eur",),
        allow_missing_current_usable=allow_missing_current_usable,
        allow_missing_strict_score_eligible=(
            allow_missing_strict_score_eligible
        ),
    )
    return contract, csv_path, manifest_path


def _load(root: Path, contract: CurrentBatchContract):
    return load_verified_current_batch(
        root,
        contract=contract,
        evidence_run_url=f"{RUN_URL_PREFIX}{contract.run_id}",
        expected_formula_inventory_sha256=FORMULA_INVENTORY_SHA256,
    )


def test_verified_loader_accepts_hash_bound_non_strict_batch(
    tmp_path: Path,
) -> None:
    contract, csv_path, manifest_path = _write_fixture(tmp_path / "artifact")

    frame, paths, evidence = _load(tmp_path / "artifact", contract)

    assert len(frame) == 2
    assert frame["current_usable"].tolist() == [True, False]
    assert not frame["strict_score_eligible"].astype(bool).any()
    assert paths == [csv_path, manifest_path]
    assert evidence == {
        "batch_id": "fixture",
        "run_id": 42,
        "run_url": f"{RUN_URL_PREFIX}42",
        "csv_sha256": contract.csv_sha256,
        "manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
        "formula_inventory_sha256": FORMULA_INVENTORY_SHA256,
        "formula_inventory_manifest_bound": True,
        "signals": ["Cash"],
        "rows": 2,
        "current_usable_rows": 1,
        "strict_score_increment": 0,
        "normalized_missing_current_usable": False,
        "normalized_missing_strict_score_eligible": False,
    }


def test_verified_loader_normalizes_only_contract_declared_legacy_gates(
    tmp_path: Path,
) -> None:
    contract, _, _ = _write_fixture(
        tmp_path / "legacy",
        allow_missing_current_usable=True,
        allow_missing_strict_score_eligible=True,
    )
    frame, _, evidence = _load(tmp_path / "legacy", contract)

    assert frame["current_usable"].tolist() == [True, True]
    assert frame["strict_score_eligible"].tolist() == [False, False]
    assert evidence["normalized_missing_current_usable"] is True
    assert evidence["normalized_missing_strict_score_eligible"] is True


def test_verified_loader_binds_manifest_output_formula_and_record_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "manifest_bound"
    contract, csv_path, manifest_path = _write_fixture(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "output_sha256": {
                csv_path.name: sha256(csv_path.read_bytes()).hexdigest()
            },
            "formula_sha256": {"Cash": "a" * 64},
            "records": [
                {
                    "security_id": "US-SEC-0000000001-AAA",
                    "current_signal_computed": True,
                    "strict_score_eligible": False,
                },
                {
                    "security_id": "US-SEC-0000000002-BBB",
                    "current_signal_computed": True,
                    "strict_score_eligible": False,
                },
            ],
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract = replace(
        contract,
        manifest_output_hashes_key="output_sha256",
        manifest_formula_sha256_key="formula_sha256",
        manifest_records_key="records",
    )

    frame, paths, evidence = _load(root, contract)

    assert len(frame) == 2
    assert paths == [csv_path, manifest_path]
    assert evidence["manifest_sha256"] == sha256(
        manifest_path.read_bytes()
    ).hexdigest()


def test_verified_loader_rejects_wrong_run_and_csv_tampering(
    tmp_path: Path,
) -> None:
    contract, csv_path, _ = _write_fixture(tmp_path / "artifact")

    with pytest.raises(ValueError, match="run URL"):
        load_verified_current_batch(
            tmp_path / "artifact",
            contract=contract,
            evidence_run_url=f"{RUN_URL_PREFIX}43",
            expected_formula_inventory_sha256=FORMULA_INVENTORY_SHA256,
        )

    csv_path.write_bytes(csv_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="CSV SHA-256"):
        _load(tmp_path / "artifact", contract)


@pytest.mark.parametrize(
    ("mutate_rows", "manifest_updates", "message"),
    [
        (
            lambda rows: rows[1].update(
                {
                    "security_id": rows[0]["security_id"],
                    "formation_at": rows[0]["formation_at"],
                }
            ),
            None,
            "duplicate identity",
        ),
        (
            lambda rows: rows[0].update(
                {"available_at": "2026-08-10T00:00:00Z"}
            ),
            None,
            "lookahead",
        ),
        (
            lambda rows: rows[0].update({"value": None}),
            None,
            "usable values",
        ),
        (
            lambda rows: rows[0].update({"strict_score_eligible": True}),
            None,
            "strict",
        ),
        (
            lambda rows: rows[0].update({"source_id": "unapproved_source"}),
            None,
            "source",
        ),
        (
            lambda rows: rows[0].update({"formula_id": "changed_formula"}),
            None,
            "formula",
        ),
        (
            None,
            {"current_value_rows": 3},
            "manifest row count",
        ),
        (
            None,
            {"locked_opened": True},
            "safety",
        ),
    ],
)
def test_verified_loader_fails_closed_on_semantic_or_manifest_violation(
    tmp_path: Path,
    mutate_rows: Callable[[list[dict[str, object]]], None] | None,
    manifest_updates: dict[str, object] | None,
    message: str,
) -> None:
    contract, _, _ = _write_fixture(
        tmp_path / message.replace(" ", "_"),
        mutate_rows=mutate_rows,
        manifest_updates=manifest_updates,
    )

    with pytest.raises(ValueError, match=message):
        _load(tmp_path / message.replace(" ", "_"), contract)


def test_verified_loader_rejects_formula_inventory_mismatch(
    tmp_path: Path,
) -> None:
    contract, _, _ = _write_fixture(tmp_path / "artifact")

    with pytest.raises(ValueError, match="formula inventory"):
        load_verified_current_batch(
            tmp_path / "artifact",
            contract=contract,
            evidence_run_url=f"{RUN_URL_PREFIX}{contract.run_id}",
            expected_formula_inventory_sha256="b" * 64,
        )


def test_production_contracts_pin_the_six_executed_free_batches() -> None:
    assert set(CURRENT_BATCH_CONTRACTS) == {
        "sec_companyfacts",
        "finra_short_interest",
        "realestate",
        "exchange_switch",
        "field_ritter_ipo",
        "spinoff",
    }
    expected = {
        "sec_companyfacts": (
            31490896342,
            "03cac84d7f999a211402f27a3db0bef41902af42a78c85b4ef29ac6056e96212",
            95935,
            95935,
        ),
        "finra_short_interest": (
            31384007094,
            "f179e3274709b78902f38e4a5cd06a55502860f8862f757c8bb7eaa7ce99c545",
            2989,
            2989,
        ),
        "realestate": (
            31384049772,
            "bb9dc9d9525c2371b783dbdb095c79af93f25dda56f6efdac13a1e867e1d5b0a",
            7,
            7,
        ),
        "exchange_switch": (
            31389285731,
            "aff9d7ca77951d870169caae10fb4984805e09771b1fecf6a4573969d7b8beea",
            7659,
            2869,
        ),
        "field_ritter_ipo": (
            31395454942,
            "f78ed07e45376b57918c9fb5f6d7239fdacf5e09bd396a1092d7d763a7faf53e",
            13149,
            1401,
        ),
        "spinoff": (
            31393646423,
            "c1ccf515d0866e54988f3823a578bd98d93b027ffbdc14d9000d5692cba16717",
            5156,
            8,
        ),
    }
    actual = {
        key: (
            contract.run_id,
            contract.csv_sha256,
            contract.expected_rows,
            contract.expected_usable_rows,
        )
        for key, contract in CURRENT_BATCH_CONTRACTS.items()
    }
    assert actual == expected
    assert CURRENT_BATCH_CONTRACTS["sec_companyfacts"].expected_signals == (
        "Accruals",
        "BookLeverage",
        "Cash",
        "ChAssetTurnover",
        "ChInvIA",
        "ChTax",
        "CompositeDebtIssuance",
        "ConvDebt",
        "DebtIssuance",
        "DelCOA",
        "DelCOL",
        "DelDRC",
        "DelEqu",
        "DelFINL",
        "DelLTI",
        "DelNetFin",
        "DivOmit",
        "DivSeason",
        "EarningsConsistency",
        "EarningsSurprise",
        "FirmAge",
        "GP",
        "GrSaleToGrInv",
        "GrSaleToGrOverhead",
        "Herf",
        "HerfAsset",
        "HerfBE",
        "InvGrowth",
        "Investment",
        "NOA",
        "NetDebtFinance",
        "NetEquityFinance",
        "OPLeverage",
        "OperProf",
        "OperProfRD",
        "RDAbility",
        "RDcap",
        "RevenueSurprise",
        "ShareIss1Y",
        "ShareIss5Y",
        "ShareRepurchase",
        "SurpriseRD",
        "Tax",
        "TotalAccruals",
        "XFIN",
        "roaq",
        "sinAlgo",
        "tang",
    )


def test_consolidator_uses_verified_loaders_for_all_six_batches() -> None:
    source = (
        ROOT / "scripts" / "run_openap_149_consolidate.py"
    ).read_text(encoding="utf-8")

    for loader in (
        "load_verified_sec_companyfacts_batch",
        "load_verified_finra_short_interest_batch",
        "load_verified_realestate_batch",
        "load_verified_exchange_switch_batch",
        "load_verified_field_ritter_ipo_batch",
        "load_verified_spinoff_batch",
    ):
        assert loader in source
    for variable in (
        "sec_path",
        "finra_path",
        "realestate_path",
        "exchange_switch_path",
        "field_ritter_path",
        "spinoff_path",
    ):
        assert f"pd.read_csv({variable}" not in source


def test_consolidation_workflow_runs_the_verified_batch_contract() -> None:
    source = (
        ROOT / ".github" / "workflows" / "openap-149-consolidate.yml"
    ).read_text(encoding="utf-8")

    assert "research/openap_181/verified_current_batches.py" in source
    assert source.count("tests/test_openap_149_verified_current_batches.py") == 2
