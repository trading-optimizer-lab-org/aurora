from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from scripts.run_paper_cboe_sentiment_sharpe2 import (
    LOCKED_START,
    Candidate,
    build_dataset,
    build_positions,
    encode_params,
    read_jsonl_frames,
    write_jsonl_frame,
)


def test_cboe_sentiment_dataset_uses_shifted_features_without_locked() -> None:
    idx = pd.bdate_range("2020-12-20", "2021-01-05")
    close = pd.DataFrame({"SPY": np.linspace(100, 110, len(idx)), "^VIX": np.linspace(20, 30, len(idx))}, index=idx)
    cboe = pd.DataFrame(
        {
            "cboe_total_pc": np.linspace(0.7, 1.3, len(idx)),
            "cboe_index_pc": np.linspace(1.0, 1.5, len(idx)),
            "cboe_equity_pc": np.linspace(0.5, 0.8, len(idx)),
        },
        index=idx,
    )
    fred = pd.DataFrame({"fred_nfci": np.linspace(-1, 1, len(idx))}, index=idx)
    data = build_dataset(close, cboe, fred)
    assert data.index.max() < LOCKED_START
    checked = data.index[1]
    assert data.loc[checked, "cboe_total_pc"] == cboe["cboe_total_pc"].shift(1).reindex(data.index).loc[checked]
    assert data.loc[checked, "vix_level"] == close["^VIX"].shift(1).reindex(data.index).loc[checked]


def test_positions_use_only_existing_features_and_spy_asset() -> None:
    idx = pd.bdate_range("2010-01-01", periods=6)
    data = pd.DataFrame(
        {
            "cboe_total_pc_z_21d": [-2, -1, 0, 1, 2, 3],
            "target_return_next_day": [0.01] * 6,
        },
        index=idx,
    )
    candidate = Candidate(
        "put_call_extreme",
        {"pc_feature": "cboe_total_pc_z_21d", "pc_threshold": 1.0, "direction": 1, "outside_position": 0.0},
    )
    positions = build_positions(candidate, data)
    assert positions.tolist() == [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]


def test_params_encoding_is_csv_safe() -> None:
    encoded = encode_params({"pc_feature": "cboe_total_pc_z_21d", "pc_threshold": 1.25, "direction": -1})
    assert "," not in encoded
    assert '"' not in encoded
    assert "\n" not in encoded


def test_jsonl_shard_roundtrip_handles_commas_and_quotes(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "candidate_id": "x",
                "source_rule_summary": 'comma, quote "ok"',
                "locked_opened": False,
                "validation_used_for_selection": False,
            }
        ]
    )
    path = tmp_path / "top_candidates.jsonl"
    write_jsonl_frame(frame, path)
    loaded = read_jsonl_frames([path])
    assert loaded.loc[0, "source_rule_summary"] == 'comma, quote "ok"'
    assert loaded.loc[0, "locked_opened"] is False or loaded.loc[0, "locked_opened"] == np.False_


def test_cboe_sentiment_workflow_requests_360_parallel_jobs() -> None:
    workflow = Path(".github/workflows/paper-cboe-sentiment-sharpe2-360jobs.yml").read_text(encoding="utf-8")
    assert "range(180)" in workflow
    assert "range(180, 360)" in workflow
    assert workflow.count("max-parallel: 180") == 2
    assert "paper-cboe-sentiment-sharpe2-360jobs-results" in workflow
    script = Path("scripts/run_paper_cboe_sentiment_sharpe2.py").read_text(encoding="utf-8")
    assert '"locked_opened": False' in script
    assert '"validation_used_for_selection": False' in script
    assert '"uses_individual_stocks": False' in script
