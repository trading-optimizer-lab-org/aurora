from __future__ import annotations

import pandas as pd
import pytest

from aurora.research.openap_93.historical_proxy_validation import FIVE_PROXY_SIGNALS
from scripts.merge_openap_five_proxy_reconstructions import merge_reconstructions


def _write_shard(root, signal: str, index: int) -> None:
    shard = root / signal
    shard.mkdir(parents=True)
    pd.DataFrame(
        {
            "signal": [signal],
            "variant_id": [f"variant-{signal}"],
            "symbol": [f"S{index}"],
            "formation_month": [pd.Timestamp("2020-01-01")],
            "proxy_value": [float(index)],
        }
    ).to_parquet(shard / "proxy_reconstruction_panel.parquet", index=False)
    pd.DataFrame(
        {
            "symbol": [f"S{index}"],
            "completed_month": ["2020-01-01"],
            "month_return": [0.01],
        }
    ).to_csv(shard / "proxy_realized_monthly.csv", index=False)


def test_merge_requires_all_five_signal_shards(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    for index, signal in enumerate(FIVE_PROXY_SIGNALS[:-1]):
        _write_shard(tmp_path / "input", signal, index)

    with pytest.raises(RuntimeError, match="Expected 5 reconstruction panels"):
        merge_reconstructions(
            input_dir=tmp_path / "input", output_dir=tmp_path / "output"
        )


def test_merge_combines_exactly_one_shard_per_signal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    for index, signal in enumerate(FIVE_PROXY_SIGNALS):
        _write_shard(tmp_path / "input", signal, index)

    summary = merge_reconstructions(
        input_dir=tmp_path / "input", output_dir=tmp_path / "output"
    )

    panel = pd.read_parquet(tmp_path / "output" / "proxy_reconstruction_panel.parquet")
    assert set(panel["signal"]) == set(FIVE_PROXY_SIGNALS)
    assert summary["reconstruction_shards_found"] == 5
    assert summary["partial"] is False
    assert summary["locked_opened"] is False
