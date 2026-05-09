"""Tests for StrategyNFT local registry."""
from __future__ import annotations

import json

from aurora.experimental.strategy_nft import StrategyNFT


def test_mint_creates_metadata_record(tmp_path):
    nft = StrategyNFT(registry_path=tmp_path / "reg.json")
    md = nft.mint(
        name="momo_v1",
        strategy_code="def signal(p): return 0",
        params={"lookback": 20},
        git_ref="abc123",
    )
    assert md["name"] == "momo_v1"
    assert len(md["token_id"]) == 64  # sha256 hex
    attrs = {a["trait_type"]: a["value"] for a in md["attributes"]}
    assert attrs["git_ref"] == "abc123"
    assert attrs["param_count"] == 1


def test_mint_is_idempotent(tmp_path):
    nft = StrategyNFT(registry_path=tmp_path / "reg.json")
    md1 = nft.mint("s", "code", {"a": 1})
    md2 = nft.mint("s", "code", {"a": 1})
    assert md1["token_id"] == md2["token_id"]
    assert len(nft.list_tokens()) == 1


def test_mint_different_params_produces_different_tokens(tmp_path):
    nft = StrategyNFT(registry_path=tmp_path / "reg.json")
    a = nft.mint("s", "code", {"x": 1})
    b = nft.mint("s", "code", {"x": 2})
    assert a["token_id"] != b["token_id"]
    assert len(nft.list_tokens()) == 2


def test_get_returns_none_for_unknown_token(tmp_path):
    nft = StrategyNFT(registry_path=tmp_path / "reg.json")
    nft.mint("s", "code", {})
    assert nft.get("0" * 64) is None


def test_registry_persists_across_instances(tmp_path):
    p = tmp_path / "reg.json"
    nft1 = StrategyNFT(registry_path=p)
    md = nft1.mint("s", "code", {"a": 1})
    nft2 = StrategyNFT(registry_path=p)
    assert nft2.get(md["token_id"]) is not None
    # Sanity: the file is valid JSON.
    json.loads(p.read_text(encoding="utf-8"))
