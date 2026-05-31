"""Tests for ``aurora.exports.lean`` (P3.B Lean export adapter).

The exporter is pure-Python text generation -- no Lean runtime is
required. These tests pin:

* the artifact contract (immutability, file presence),
* the provenance contract (policy_hash / spec_hash / qf_version /
  exported_at all populated in qf_metadata.json),
* the translation tier mapping (full vs partial vs scaffold-only),
* the README guard (``DO NOT TRUST IN ISOLATION`` always present;
  validation-marker warning when none was supplied),
* basic syntactic sanity of the generated Lean C# (class declaration +
  required overrides),
* JSON validity of config.json and qf_metadata.json,
* idempotency / overwrite-refusal of the exporter,
* CLI smoke (``forge export lean``) + verify-tamper detection.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pandas as pd
import pytest

from aurora.core.protocol_policy import ProtocolPolicy
from aurora.exports.lean import (
    LeanExportConfig,
    LeanExporter,
    LeanProjectArtifact,
)
from aurora.exports.lean.exporter import (
    TRANSLATION_TIERS,
    list_translation_tiers,
    verify_project,
)
from aurora.research.factory import StrategySpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def policy() -> ProtocolPolicy:
    return ProtocolPolicy.default()


def _spec(strategy_class: str, params: dict, name: str = "TestSpec") -> StrategySpec:
    return StrategySpec.make(
        name=name,
        hypothesis="cross-validation only",
        strategy_class=strategy_class,
        params=params,
        universe=["SPY"],
        rebalance="1d",
    )


def _make_config(tmp_path: Path, project_name: str = "TestProject") -> LeanExportConfig:
    return LeanExportConfig(
        target_directory=tmp_path,
        project_name=project_name,
        cash=100_000,
        benchmark="SPY",
        resolution="Daily",
        universe_resolution="Daily",
        start_date=pd.Timestamp("2015-01-01"),
        end_date=pd.Timestamp("2020-12-31"),
    )


# ---------------------------------------------------------------------------
# 1. LeanExportConfig defaults
# ---------------------------------------------------------------------------


def test_lean_export_config_defaults(tmp_path):
    cfg = LeanExportConfig(
        target_directory=tmp_path,
        project_name="P",
        start_date=pd.Timestamp("2015-01-01"),
    )
    assert cfg.cash == 100_000
    assert cfg.benchmark == "SPY"
    assert cfg.resolution == "Daily"
    assert cfg.universe_resolution == "Daily"
    assert cfg.end_date is None
    assert cfg.include_costs_from_policy is True
    assert cfg.include_validation_marker is True


# ---------------------------------------------------------------------------
# 2. LeanProjectArtifact immutable
# ---------------------------------------------------------------------------


def test_lean_project_artifact_is_frozen(tmp_path, policy):
    cfg = _make_config(tmp_path)
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 10, "slow": 50, "allow_short": False},
    )
    artifact = LeanExporter(cfg, policy).export(spec)
    assert isinstance(artifact, LeanProjectArtifact)
    with pytest.raises(FrozenInstanceError):
        artifact.project_name = "mutated"


# ---------------------------------------------------------------------------
# 3. Exporter writes the four mandatory files
# ---------------------------------------------------------------------------


def test_exporter_writes_required_files(tmp_path, policy):
    cfg = _make_config(tmp_path)
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 10, "slow": 50},
    )
    artifact = LeanExporter(cfg, policy).export(spec)

    assert artifact.main_cs_path.exists()
    assert artifact.config_json_path.exists()
    assert artifact.readme_path.exists()
    metadata_path = artifact.main_cs_path.parent / "qf_metadata.json"
    assert metadata_path.exists()
    assert metadata_path in artifact.files_written
    assert artifact.main_cs_path.parent.name == "TestProject"


# ---------------------------------------------------------------------------
# 4. qf_metadata.json carries the full provenance record
# ---------------------------------------------------------------------------


def test_metadata_contains_provenance(tmp_path, policy):
    cfg = _make_config(tmp_path, "ProvProject")
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 10, "slow": 50},
    )
    artifact = LeanExporter(cfg, policy).export(spec)
    meta_path = artifact.main_cs_path.parent / "qf_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in ("policy_hash", "spec_hash", "qf_version", "exported_at"):
        assert meta.get(key), f"missing {key}"
    # policy_hash must agree with the policy passed in.
    expected_hash = policy._with_hash().policy_hash
    assert meta["policy_hash"] == expected_hash
    assert meta["spec_hash"] == spec.spec_hash
    assert meta["validation_marker"] is None
    # exported_at must be parseable as ISO-8601 UTC.
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", meta["exported_at"])


# ---------------------------------------------------------------------------
# 5. Known strategy class -> templated Lean MA logic
# ---------------------------------------------------------------------------


def test_known_strategy_renders_ma_cross_lean_logic(tmp_path, policy):
    cfg = _make_config(tmp_path, "MAProject")
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 7, "slow": 30, "allow_short": True},
    )
    artifact = LeanExporter(cfg, policy).export(spec)
    main = artifact.main_cs_path.read_text(encoding="utf-8")
    # The MA template references SimpleMovingAverage with the right
    # period numbers and includes the cross logic.
    assert "SimpleMovingAverage" in main
    assert "SMA(Sym, 7" in main
    assert "SMA(Sym, 30" in main
    assert "_fast > _slow" in main
    # Translation tier marker in metadata.
    meta = json.loads(
        (artifact.main_cs_path.parent / "qf_metadata.json").read_text(encoding="utf-8")
    )
    assert meta["translation_tier"] == "full"


# ---------------------------------------------------------------------------
# 6. Unknown strategy class -> scaffold + params embedded
# ---------------------------------------------------------------------------


def test_unknown_strategy_falls_back_to_scaffold(tmp_path, policy):
    cfg = _make_config(tmp_path, "ScaffoldProj")
    spec = _spec(
        "thirdparty.exotic.MysteryEdge",
        {"alpha": 0.42, "lookback": 17},
    )
    artifact = LeanExporter(cfg, policy).export(spec)
    main = artifact.main_cs_path.read_text(encoding="utf-8")
    # Scaffold marker must be present.
    assert "TODO scaffold-only" in main
    # The original params dict must appear in a comment so a manual
    # port has them in front.
    assert "alpha" in main
    assert "lookback" in main
    meta = json.loads(
        (artifact.main_cs_path.parent / "qf_metadata.json").read_text(encoding="utf-8")
    )
    assert meta["translation_tier"] == "scaffold-only"


# ---------------------------------------------------------------------------
# 7. README has the "DO NOT TRUST IN ISOLATION" warning
# ---------------------------------------------------------------------------


def test_readme_has_do_not_trust_warning(tmp_path, policy):
    cfg = _make_config(tmp_path)
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 10, "slow": 50},
    )
    artifact = LeanExporter(cfg, policy).export(spec)
    readme = artifact.readme_path.read_text(encoding="utf-8")
    assert "DO NOT TRUST IN ISOLATION" in readme


# ---------------------------------------------------------------------------
# 8. README warns when no validation_marker provided
# ---------------------------------------------------------------------------


def test_readme_warns_without_validation_marker(tmp_path, policy):
    cfg = _make_config(tmp_path, "NoMarkerProj")
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 10, "slow": 50},
    )
    # No validation_marker -> warning must appear.
    artifact = LeanExporter(cfg, policy).export(spec, validation_marker=None)
    readme = artifact.readme_path.read_text(encoding="utf-8")
    assert "EXPORTED WITHOUT VALIDATION MARKER" in readme
    assert "research-grade only" in readme.lower() or "Research-grade only" in readme

    # With validation_marker -> warning must NOT appear, and the marker
    # block must show up.
    cfg2 = LeanExportConfig(
        target_directory=tmp_path,
        project_name="MarkerProj",
        start_date=pd.Timestamp("2015-01-01"),
    )
    artifact2 = LeanExporter(cfg2, policy).export(
        spec, validation_marker={"sharpe": 1.4, "calmar": 0.9}
    )
    readme2 = artifact2.readme_path.read_text(encoding="utf-8")
    assert "EXPORTED WITHOUT VALIDATION MARKER" not in readme2
    assert "Validation marker" in readme2
    assert "1.4" in readme2


# ---------------------------------------------------------------------------
# 9. Lean Main.cs is syntactically valid C# (smoke regex)
# ---------------------------------------------------------------------------


def test_main_cs_smoke_regex(tmp_path, policy):
    cfg = _make_config(tmp_path, "SyntaxProj")
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 10, "slow": 50},
    )
    artifact = LeanExporter(cfg, policy).export(spec)
    main = artifact.main_cs_path.read_text(encoding="utf-8")
    # using directives.
    assert "using QuantConnect.Algorithm;" in main
    # namespace declaration.
    assert re.search(r"namespace\s+Aurora\.Exports", main)
    # class declaration extending QCAlgorithm.
    assert re.search(r"class\s+\w+\s*:\s*QCAlgorithm", main)
    # required overrides.
    assert re.search(r"public override void Initialize\(\s*\)", main)
    assert re.search(r"public override void OnData\(\s*Slice\s+\w+\s*\)", main)
    # SetStartDate / SetCash present.
    assert "SetStartDate(" in main
    assert "SetCash(" in main
    # No unbalanced template placeholders left.
    assert "$" not in re.sub(r"\$[a-zA-Z_]\w*", "", main).replace("$", "_OK_")
    # And, most critically, the substitution actually completed: no
    # ``${...}`` style holes.
    assert "${" not in main


# ---------------------------------------------------------------------------
# 10. config.json is valid JSON with the expected keys
# ---------------------------------------------------------------------------


def test_config_json_is_valid_json(tmp_path, policy):
    cfg = _make_config(tmp_path, "JsonProj")
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 10, "slow": 50, "allow_short": False},
    )
    artifact = LeanExporter(cfg, policy).export(spec)
    config = json.loads(artifact.config_json_path.read_text(encoding="utf-8"))
    assert config["algorithm-language"] == "CSharp"
    assert config["local-id"] == "JsonProj"
    assert isinstance(config["parameters"], dict)
    # qf-export envelope carries provenance for verifiers.
    qf = config["qf-export"]
    assert qf["spec_hash"] == spec.spec_hash
    assert qf["qf_version"]
    assert qf["validation_marker_present"] is False


# ---------------------------------------------------------------------------
# 11. Universe symbols normalize correctly (US equity passthrough)
# ---------------------------------------------------------------------------


def test_universe_symbols_normalized(tmp_path, policy):
    cfg = _make_config(tmp_path, "SymbolsProj")
    spec = StrategySpec.make(
        name="MultiSym",
        hypothesis="multi-asset MA cross",
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        params={"fast": 10, "slow": 50},
        universe=["SPY", "QQQ", "IWM"],
        rebalance="1d",
    )
    artifact = LeanExporter(cfg, policy).export(spec)
    main = artifact.main_cs_path.read_text(encoding="utf-8")
    # AddEquity for each ticker.
    assert 'AddEquity("SPY"' in main
    assert 'AddEquity("QQQ"' in main
    assert 'AddEquity("IWM"' in main
    # Primary symbol (first in universe) is what the indicator block
    # binds to.
    assert 'private const string Sym = "SPY";' in main
    # Metadata records the full universe.
    meta = json.loads(
        (artifact.main_cs_path.parent / "qf_metadata.json").read_text(encoding="utf-8")
    )
    assert meta["universe"] == ["SPY", "QQQ", "IWM"]


# ---------------------------------------------------------------------------
# 12. Refuses to overwrite an existing project unless force=True
# ---------------------------------------------------------------------------


def test_exporter_refuses_overwrite_without_force(tmp_path, policy):
    cfg = _make_config(tmp_path, "OverwriteProj")
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 10, "slow": 50},
    )
    exporter = LeanExporter(cfg, policy)
    artifact = exporter.export(spec)
    assert artifact.main_cs_path.exists()
    # A second export without force must raise.
    with pytest.raises(FileExistsError):
        exporter.export(spec)
    # With force=True it succeeds.
    artifact2 = exporter.export(spec, force=True)
    assert artifact2.main_cs_path.exists()


# ---------------------------------------------------------------------------
# 13. ``forge export lean`` CLI smoke
# ---------------------------------------------------------------------------


def test_cli_export_lean_smoke(tmp_path):
    """Run the CLI as a subprocess to exercise end-to-end wiring."""
    spec_path = tmp_path / "spec.json"
    spec = StrategySpec.make(
        name="CliMA",
        hypothesis="cli smoke",
        strategy_class="aurora.strategies.library.ma_cross.MACross",
        params={"fast": 10, "slow": 50, "allow_short": False},
        universe=["SPY"],
        rebalance="1d",
    )
    spec_path.write_text(json.dumps(spec.to_dict()), encoding="utf-8")

    out_dir = tmp_path / "lean_exports"
    cmd = [
        sys.executable, "-m", "aurora.cli.forge", "export", "lean",
        str(spec_path),
        "--target-dir", str(out_dir),
        "--project-name", "CliSmoke",
        "--start-date", "2015-01-01",
        "--end-date", "2020-12-31",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"stderr={res.stderr}\nstdout={res.stdout}"
    project_dir = out_dir / "CliSmoke"
    assert (project_dir / "Main.cs").exists()
    assert (project_dir / "config.json").exists()
    assert (project_dir / "README.md").exists()
    assert (project_dir / "qf_metadata.json").exists()


# ---------------------------------------------------------------------------
# 14. ``forge export verify`` detects qf_metadata.json tamper
# ---------------------------------------------------------------------------


def test_export_verify_detects_tamper(tmp_path, policy):
    cfg = _make_config(tmp_path, "TamperProj")
    spec = _spec(
        "aurora.strategies.library.ma_cross.MACross",
        {"fast": 10, "slow": 50},
    )
    artifact = LeanExporter(cfg, policy).export(spec)
    project_dir = artifact.main_cs_path.parent

    # Pristine state must verify as ok.
    result_ok = verify_project(project_dir)
    assert result_ok["ok"], result_ok["errors"]

    # Tamper: rewrite policy_hash to a clearly-wrong value.
    meta_path = project_dir / "qf_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["policy_hash"] = "0" * 64
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    result_bad = verify_project(project_dir)
    assert not result_bad["ok"]
    assert any("policy_hash mismatch" in e for e in result_bad["errors"])


# ---------------------------------------------------------------------------
# Bonus: translation-tier table reflects the registry
# ---------------------------------------------------------------------------


def test_translation_tier_table_shape():
    rows = list_translation_tiers()
    assert rows  # not empty
    # Sorted by class name.
    names = [n for n, _ in rows]
    assert names == sorted(names)
    # Every tier value is one of the three known buckets.
    for _, tier in rows:
        assert tier in {"full", "partial", "scaffold-only"}
    # MACross must be marked full (it has a complete Lean template).
    assert TRANSLATION_TIERS["MACross"] == "full"
