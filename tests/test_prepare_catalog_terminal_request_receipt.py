from __future__ import annotations

from pathlib import Path

import pytest

from scripts.prepare_catalog_terminal_request_receipt import _json


def test_terminal_receipt_json_rejects_duplicates_and_nonfinite(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"value":1,"value":2}', encoding="utf-8")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"value":NaN}', encoding="utf-8")

    with pytest.raises(ValueError, match="CATALOG_REQUEST_RECEIPT_JSON_DUPLICATE"):
        _json(duplicate, runner_temp=tmp_path)
    with pytest.raises(ValueError, match="CATALOG_REQUEST_RECEIPT_JSON_NONFINITE"):
        _json(nonfinite, runner_temp=tmp_path)


def test_terminal_receipt_json_must_stay_inside_runner_temp(tmp_path: Path) -> None:
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="CATALOG_REQUEST_RECEIPT_INPUT_INVALID"):
        _json(outside, runner_temp=runner_temp)
