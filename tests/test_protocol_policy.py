"""Tests for :mod:`quantforge.core.protocol_policy` and its wire-in points.

Covers:
  * ``default()`` builds the canonical policy.
  * YAML round-trip is lossless and hash-stable.
  * Hash determinism + tamper detection.
  * Frozen instance contract.
  * Wire-ins: data_tiers, validation/pipeline, cli/forge, snapshots, ga.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.core import protocol_policy as pp_mod
from aurora.core.protocol_policy import (
    ProtocolPolicy,
    TierConfig,
    CeremonyConfig,
    RiskLimits,
    CostModelConfig,
    StressConfig,
    DCAConfig,
    ObjectiveConfig,
    GAConfigPolicy,
    PROTOCOL_VERSION,
    get_active_policy,
    set_active_policy,
)


@pytest.fixture(autouse=True)
def _reset_active_policy_cache():
    """Each test starts with the global cached policy cleared."""
    set_active_policy(None)
    yield
    set_active_policy(None)


# ---------------------------------------------------------------------------
# Core dataclass behaviour
# ---------------------------------------------------------------------------


def test_default_policy_loads():
    """``ProtocolPolicy.default()`` materializes the production policy."""
    pol = ProtocolPolicy.default()
    assert pol.version == PROTOCOL_VERSION
    # The five protocol tiers must all be present.
    assert set(pol.tiers.keys()) == {
        "IS_TRAIN", "IS_VALID", "OOS_DEV", "OOS_LOCKED", "FORWARD",
    }
    # The four canonical ceremonies.
    assert set(pol.oos_ceremonies.keys()) == {
        "explicit_unlock_snapshot",
        "explicit_unlock_oos_locked",
        "explicit_unlock_forward",
        "explicit_unlock_full_tier",
    }
    # Nine mandatory gates after P1.B auditor gate addition.
    assert len(pol.mandatory_gates) == 9
    assert "walk_forward" in pol.mandatory_gates
    assert "deflated_sharpe" in pol.mandatory_gates
    assert "auditor_gate" in pol.mandatory_gates
    # Hash is non-empty + 64 chars (sha256 hex).
    assert len(pol.policy_hash) == 64
    assert all(c in "0123456789abcdef" for c in pol.policy_hash)


def test_yaml_roundtrip(tmp_path):
    """Serializing then loading produces the same hash."""
    pol = ProtocolPolicy.default()
    yaml_path = tmp_path / "policy.yaml"
    pol.to_yaml(str(yaml_path))
    pol_back = ProtocolPolicy.from_yaml(str(yaml_path))
    assert pol_back.policy_hash == pol.policy_hash
    assert pol_back.version == pol.version
    assert pol_back.tiers["IS_TRAIN"].end == pol.tiers["IS_TRAIN"].end
    assert pol_back.mandatory_gates == pol.mandatory_gates


def test_policy_hash_stable():
    """Two builds of ``default()`` produce the same hash."""
    h1 = ProtocolPolicy.default().policy_hash
    h2 = ProtocolPolicy.default().policy_hash
    assert h1 == h2
    # Recomputing on the in-memory instance also matches.
    pol = ProtocolPolicy.default()
    assert pol.compute_hash() == pol.policy_hash


def test_policy_hash_changes_on_mutation():
    """A modified policy produces a different hash."""
    base = ProtocolPolicy.default()
    # Use ``replace`` because the dataclass is frozen.
    new_tiers = dict(base.tiers)
    new_tiers["IS_TRAIN"] = TierConfig(
        start="2000-01-01", end="2010-12-31",
        purpose="Mutated for test", requires_ceremony=None,
    )
    mutated = dataclasses.replace(base, tiers=new_tiers, policy_hash="")
    # Recompute the digest after the mutation.
    mutated = dataclasses.replace(
        mutated, policy_hash=mutated.compute_hash()
    )
    assert mutated.policy_hash != base.policy_hash
    # The mutation only affects the tier dict, not unrelated structures.
    assert mutated.mandatory_gates == base.mandatory_gates


def test_policy_is_frozen():
    """Direct mutation raises ``FrozenInstanceError``."""
    pol = ProtocolPolicy.default()
    with pytest.raises(dataclasses.FrozenInstanceError):
        pol.version = "0.0.0"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        pol.tiers["IS_TRAIN"].start = "1900-01-01"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Wire-ins: data_tiers / validation / cli / snapshots / ga
# ---------------------------------------------------------------------------


def test_data_tiers_uses_policy():
    """Custom policy dates propagate to ``core.data_tiers`` constants."""
    from aurora.core import data_tiers as dt
    base = ProtocolPolicy.default()
    new_tiers = dict(base.tiers)
    new_tiers["IS_TRAIN"] = TierConfig(
        start="1995-01-01", end="2005-12-31",
        purpose="Mutated for test", requires_ceremony=None,
    )
    custom = dataclasses.replace(base, tiers=new_tiers, policy_hash="")
    custom = dataclasses.replace(custom, policy_hash=custom.compute_hash())
    set_active_policy(custom)
    try:
        dt.reload_tier_constants_from_policy()
        assert dt.IS_TRAIN_END == pd.Timestamp("2005-12-31")
        assert dt._TIER_END_DATES["IS_TRAIN"] == pd.Timestamp("2005-12-31")
    finally:
        # Restore the canonical defaults so other tests are unaffected.
        set_active_policy(None)
        dt.reload_tier_constants_from_policy()
    # Sanity: the global cache is back on the production policy.
    assert dt.IS_TRAIN_END == pd.Timestamp("2010-12-31")


def test_validation_pipeline_uses_policy():
    """``get_mandatory_gates`` reflects ``policy.mandatory_gates``."""
    from aurora.validation import pipeline as vpipeline
    base = ProtocolPolicy.default()
    custom = dataclasses.replace(base,
                                  mandatory_gates=["walk_forward", "spp"],
                                  policy_hash="")
    custom = dataclasses.replace(custom, policy_hash=custom.compute_hash())
    set_active_policy(custom)
    try:
        assert vpipeline.get_mandatory_gates() == ["walk_forward", "spp"]
    finally:
        set_active_policy(None)
    # And the default returns the nine production gates (P1.B added auditor_gate).
    assert len(vpipeline.get_mandatory_gates()) == 9


def test_cli_validate_tier_choices_match_policy():
    """`forge validate --tier` choices come from ``policy.tiers``."""
    # Build the parser with the production policy and inspect the
    # --tier choices on the validate subparser.
    from aurora.cli import forge as forge_mod
    parser = forge_mod.build_parser()
    sub_actions = [a for a in parser._actions
                   if isinstance(a, type(parser._subparsers._actions[1]
                                         if hasattr(parser, "_subparsers")
                                         else parser._actions[-1]))]
    # Pull the validate subparser via choices map.
    subs = next(a for a in parser._actions
                if a.__class__.__name__ == "_SubParsersAction")
    p_val = subs.choices["validate"]
    tier_action = next(
        a for a in p_val._actions
        if "--tier" in a.option_strings
    )
    expected = [
        t for t in forge_mod._policy_tier_choices()
        if t in ("oos_dev", "oos_locked", "forward")
    ]
    assert sorted(tier_action.choices) == sorted(expected)


def test_cli_ceremony_env_flag_matches_policy():
    """``_policy_ceremony_env_flag`` round-trips ``policy.oos_ceremonies``."""
    from aurora.cli import forge as forge_mod
    base = ProtocolPolicy.default()
    custom_cer = dict(base.oos_ceremonies)
    custom_cer["explicit_unlock_oos_locked"] = CeremonyConfig(
        env_flag="custom_locked_phase",
        requires_oos_guard=True,
        requires_signed_authorization=True,
        purpose_pattern="custom",
    )
    custom = dataclasses.replace(base, oos_ceremonies=custom_cer,
                                  policy_hash="")
    custom = dataclasses.replace(custom, policy_hash=custom.compute_hash())
    set_active_policy(custom)
    try:
        assert (forge_mod._policy_ceremony_env_flag(
                    "explicit_unlock_oos_locked")
                == "custom_locked_phase")
        # Default ceremonies still resolve under custom policy.
        assert (forge_mod._policy_ceremony_env_flag(
                    "explicit_unlock_snapshot")
                == "explicit_unlock_snapshot")
    finally:
        set_active_policy(None)


def test_snapshot_records_policy_hash(tmp_path):
    """Freezing a snapshot writes the active policy hash into its row."""
    from aurora.core.snapshots import SnapshotStore
    store = SnapshotStore(str(tmp_path))
    idx = pd.date_range("2020-01-01", periods=30, freq="D")
    series = pd.Series(np.linspace(100, 130, 30), index=idx)
    snap = store.freeze(series, "TEST", provenance="unit-test")
    active_hash = get_active_policy().policy_hash
    assert snap.policy_hash == active_hash
    # And reading it back through ``load`` preserves it.
    _, snap2 = store.load(snap.sha256)
    assert snap2.policy_hash == active_hash


def test_policy_verify_detects_tampering(tmp_path):
    """Mutating the YAML's declared hash makes ``forge policy verify`` fail."""
    pol = ProtocolPolicy.default()
    yaml_path = tmp_path / "policy.yaml"
    pol.to_yaml(str(yaml_path))

    # Tamper: replace the declared hash with a different valid-looking
    # sha256 hex string so the YAML body no longer matches its declared
    # digest. Using "deadbeef" repeated rather than zeros so YAML keeps
    # the value as a string (a bare 64-zero token is parsed back as 0).
    text = yaml_path.read_text(encoding="utf-8")
    tampered_text = text.replace(pol.policy_hash, "deadbeef" * 8)
    yaml_path.write_text(tampered_text, encoding="utf-8")

    # Invoke the CLI so the test exercises the same surface a user hits.
    proc = subprocess.run(
        [sys.executable, "-m", "aurora.cli.forge",
         "policy", "verify", "--path", str(yaml_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "FAIL" in proc.stdout


def test_ga_uses_policy_defaults():
    """``GAConfig`` defaults come from the active policy."""
    from aurora.ga.runner import GAConfig, _ga_defaults_from_policy
    g = GAConfig()
    pol = ProtocolPolicy.default()
    assert g.population == pol.ga_config.population
    assert g.generations == pol.ga_config.generations
    assert g.seed == pol.ga_config.seed
    assert g.backend == pol.ga_config.backend
    # And the helper itself returns matching values.
    d = _ga_defaults_from_policy()
    assert d["population"] == pol.ga_config.population


# ---------------------------------------------------------------------------
# Extra coverage
# ---------------------------------------------------------------------------


def test_load_falls_back_to_default_when_yaml_missing(tmp_path):
    """``ProtocolPolicy.load`` returns ``default()`` when the file is absent."""
    missing = tmp_path / "does_not_exist.yaml"
    pol = ProtocolPolicy.load(str(missing))
    assert pol.policy_hash == ProtocolPolicy.default().policy_hash


def test_canonical_dict_does_not_carry_hash():
    """The hash field is excluded from the digest payload."""
    pol = ProtocolPolicy.default()
    canonical = pol._canonical_dict()
    assert "policy_hash" not in canonical
    payload = json.dumps(canonical, sort_keys=True,
                         separators=(",", ":"),
                         ensure_ascii=True, default=str)
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert pol.policy_hash == expected


def test_from_dict_recomputes_hash_when_missing():
    """``from_dict`` always rehashes; the embedded hash field is ignored."""
    pol = ProtocolPolicy.default()
    d = pol.to_dict()
    d["policy_hash"] = "deadbeef" * 8  # garbage
    rebuilt = ProtocolPolicy.from_dict(d)
    assert rebuilt.policy_hash == pol.policy_hash
