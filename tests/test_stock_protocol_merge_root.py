"""Regression tests for the data-root duplication that produced two symbols."""
from pathlib import Path

from scripts.merge_free_us_daily_shards import qf_data_root_from_argument


def test_expanded_dataset_root_is_normalised_to_qf_data_root(tmp_path: Path):
    dataset_root = tmp_path / "prices" / "free_us_daily"
    assert qf_data_root_from_argument(dataset_root) == tmp_path


def test_plain_qf_data_root_is_left_unchanged(tmp_path: Path):
    assert qf_data_root_from_argument(tmp_path) == tmp_path
