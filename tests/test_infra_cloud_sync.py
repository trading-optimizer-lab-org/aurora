"""Tests for aurora.infra.cloud_sync.CloudSync (mock mode)."""
from __future__ import annotations

import os

import pytest

from aurora.infra.cloud_sync import CloudConfig, CloudSync


@pytest.fixture
def sync(tmp_path):
    cfg = CloudConfig(provider="s3", bucket="test", prefix="qf",
                      mock_root=str(tmp_path / "mock"))
    return CloudSync(cfg)


def test_invalid_provider_raises():
    with pytest.raises(ValueError):
        CloudSync(CloudConfig(provider="bogus"))


def test_upload_download_round_trip(sync, tmp_path):
    src = tmp_path / "input.txt"
    src.write_text("hello", encoding="utf-8")
    uri = sync.upload(str(src), "snapshots/v1.txt")
    assert uri.startswith("s3://test/qf/snapshots/v1.txt")
    dst = tmp_path / "output.txt"
    sync.download("snapshots/v1.txt", str(dst))
    assert dst.read_text(encoding="utf-8") == "hello"


def test_list_keys_after_upload(sync, tmp_path):
    src = tmp_path / "a.parquet"
    src.write_bytes(b"binary")
    sync.upload(str(src), "data/2024/SPY.parquet")
    keys = sync.list_keys("data/")
    assert "qf/data/2024/SPY.parquet" in keys


def test_delete_returns_true_then_false(sync, tmp_path):
    src = tmp_path / "x.txt"
    src.write_text("x", encoding="utf-8")
    sync.upload(str(src), "x.txt")
    assert sync.delete("x.txt") is True
    assert sync.delete("x.txt") is False


def test_upload_missing_file_raises(sync):
    with pytest.raises(FileNotFoundError):
        sync.upload("nonexistent.dat", "remote.dat")


def test_download_missing_key_raises(sync, tmp_path):
    with pytest.raises(FileNotFoundError):
        sync.download("missing.dat", str(tmp_path / "out.dat"))


def test_sync_strategy_snapshot(sync, tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "a.txt").write_text("a", encoding="utf-8")
    (snap / "b.txt").write_text("b", encoding="utf-8")
    uris = sync.sync_strategy_snapshot(str(snap), version="v1.0")
    assert len(uris) == 2
    assert all("versions/v1.0/" in u for u in uris)


def test_uri_scheme_per_provider(tmp_path):
    for provider, scheme in (("s3", "s3://"), ("gcs", "gs://"), ("azure", "azure://")):
        cfg = CloudConfig(provider=provider, bucket="b",
                          mock_root=str(tmp_path / provider))
        cs = CloudSync(cfg)
        src = tmp_path / f"{provider}.txt"
        src.write_text("x", encoding="utf-8")
        uri = cs.upload(str(src), "k.txt")
        assert uri.startswith(scheme)
