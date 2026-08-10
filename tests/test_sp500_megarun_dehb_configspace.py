from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_contract import load_and_validate_feature_contract


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_free_data_240.json"
FEATURE_CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_feature_contract_240.json"


class _FakeCategoricalHyperparameter:
    def __init__(
        self,
        name: str,
        *,
        choices: tuple[object, ...],
        default_value: object,
    ) -> None:
        self.name = name
        self.choices = tuple(choices)
        self.default_value = default_value


class _FakeForbiddenEqualsClause:
    def __init__(self, hyperparameter: _FakeCategoricalHyperparameter, value: object) -> None:
        self.hyperparameter = hyperparameter
        self.value = value


class _FakeForbiddenAndConjunction:
    def __init__(self, *clauses: _FakeForbiddenEqualsClause) -> None:
        self.clauses = clauses


class _FakeConfigurationSpace:
    def __init__(self, *, seed: int) -> None:
        self.seed = seed
        self.hyperparameters: list[_FakeCategoricalHyperparameter] = []
        self.forbidden_clauses: list[_FakeForbiddenAndConjunction] = []

    def add(self, items: list[object]) -> None:
        for item in items:
            if isinstance(item, _FakeCategoricalHyperparameter):
                self.hyperparameters.append(item)
            elif isinstance(item, _FakeForbiddenAndConjunction):
                self.forbidden_clauses.append(item)
            else:
                raise TypeError(f"unsupported fake ConfigSpace item: {item!r}")

    def __getitem__(self, name: str) -> _FakeCategoricalHyperparameter:
        return next(item for item in self.hyperparameters if item.name == name)


FAKE_CONFIGSPACE = SimpleNamespace(
    ConfigurationSpace=_FakeConfigurationSpace,
    CategoricalHyperparameter=_FakeCategoricalHyperparameter,
    ForbiddenEqualsClause=_FakeForbiddenEqualsClause,
    ForbiddenAndConjunction=_FakeForbiddenAndConjunction,
)


@pytest.fixture(scope="module")
def feature_contract():
    data_contract = load_and_validate_contract(DATA_CONTRACT_PATH)
    return load_and_validate_feature_contract(FEATURE_CONTRACT_PATH, data_contract)


def test_builds_all_240_exact_discrete_configspaces(feature_contract) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_all_lane_configspaces

    spaces = build_all_lane_configspaces(
        feature_contract,
        base_seed=7300,
        configspace_module=FAKE_CONFIGSPACE,
    )

    assert [row.lane_id for row in spaces] == [f"F{index:03d}" for index in range(1, 241)]
    assert all(row.seed == 7300 + index for index, row in enumerate(spaces))
    assert all(row.canonical_sha256 == feature_contract.lanes[index].canonical_sha256 for index, row in enumerate(spaces))
    assert all(row.dimensions for row in spaces)
    for row, lane in zip(spaces, feature_contract.lanes, strict=True):
        fake_space = row.configspace
        assert [item.name for item in fake_space.hyperparameters] == list(
            lane.parameter_space
        )
        assert {
            item.name: item.choices for item in fake_space.hyperparameters
        } == lane.parameter_space
        assert all(
            item.default_value == item.choices[0]
            for item in fake_space.hyperparameters
        )


def test_single_lane_space_rejects_unknown_or_non_executable_lane(feature_contract) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import (
        DehbConfigSpaceError,
        build_lane_configspace,
    )

    with pytest.raises(DehbConfigSpaceError, match="UNKNOWN_LANE:F999"):
        build_lane_configspace(
            feature_contract,
            "F999",
            seed=1,
            configspace_module=FAKE_CONFIGSPACE,
        )

    blocked_lane = feature_contract.lanes[0].__class__(
        **{
            **feature_contract.lanes[0].__dict__,
            "implementation_status": "blueprint_only",
        }
    )
    blocked_contract = feature_contract.__class__(
        **{
            **feature_contract.__dict__,
            "lanes": (blocked_lane, *feature_contract.lanes[1:]),
        }
    )
    with pytest.raises(DehbConfigSpaceError, match="LANE_NOT_EXECUTABLE:F001"):
        build_lane_configspace(
            blocked_contract,
            "F001",
            seed=1,
            configspace_module=FAKE_CONFIGSPACE,
        )


@pytest.mark.parametrize(
    ("lane_id", "left", "right", "expected_count"),
    [
        ("F002", "fast", "slow", 3),
        ("F120", "embargo", "horizon", 3),
        ("F172", "window", "long_window", 3),
        ("F180", "window", "long_window", 3),
    ],
)
def test_relationally_invalid_pairs_are_physically_forbidden(
    feature_contract,
    lane_id: str,
    left: str,
    right: str,
    expected_count: int,
) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace

    row = build_lane_configspace(
        feature_contract,
        lane_id,
        seed=19,
        configspace_module=FAKE_CONFIGSPACE,
    )

    assert row.forbidden_configuration_count == expected_count
    pairs = {
        tuple((clause.hyperparameter.name, clause.value) for clause in conjunction.clauses)
        for conjunction in row.configspace.forbidden_clauses
    }
    assert all(
        {name for name, _value in pair} == {left, right}
        for pair in pairs
    )


def test_empty_window_normalization_combinations_are_forbidden(feature_contract) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace

    row = build_lane_configspace(
        feature_contract,
        "F023",
        seed=23,
        configspace_module=FAKE_CONFIGSPACE,
    )

    assert row.forbidden_configuration_count == 2
    assert len(row.configspace.forbidden_clauses) == 2


def test_empirical_tail_choices_with_same_effective_rank_are_forbidden(
    feature_contract,
) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace

    row = build_lane_configspace(
        feature_contract,
        "F022",
        seed=22,
        configspace_module=FAKE_CONFIGSPACE,
    )

    assert row.forbidden_configuration_count == 3
    forbidden = {
        tuple((clause.hyperparameter.name, clause.value) for clause in conjunction.clauses)
        for conjunction in row.configspace.forbidden_clauses
    }
    assert (("window", 20), ("tail", 0.025)) in forbidden
    assert (("window", 20), ("tail", 0.05)) in forbidden
    assert (("window", 40), ("tail", 0.025)) in forbidden


@pytest.mark.parametrize(
    ("lane_id", "expected_count"),
    [
        ("F051", 4),
        ("F055", 1),
        ("F057", 5),
        ("F058", 6),
        ("F059", 2),
        ("F060", 20),
        ("F069", 2),
        ("F074", 6),
        ("F079", 6),
        ("F082", 6),
        ("F083", 6),
        ("F084", 7),
        ("F085", 5),
        ("F086", 7),
        ("F087", 21),
        ("F088", 16),
        ("F089", 3),
        ("F091", 7),
        ("F093", 14),
        ("F095", 9),
        ("F097", 4),
        ("F098", 3),
        ("F099", 11),
        ("F100", 9),
        ("F101", 6),
        ("F102", 9),
        ("F103", 9),
        ("F104", 3),
        ("F105", 3),
        ("F106", 12),
        ("F108", 2),
        ("F110", 9),
    ],
)
def test_conditionally_inactive_model_parameters_are_forbidden(
    feature_contract,
    lane_id: str,
    expected_count: int,
) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace

    row = build_lane_configspace(
        feature_contract,
        lane_id,
        seed=51,
        configspace_module=FAKE_CONFIGSPACE,
    )

    assert row.forbidden_configuration_count == expected_count
    assert len(row.configspace.forbidden_clauses) == expected_count


def test_manifest_freezes_fidelities_versions_boundaries_and_exact_choices(
    feature_contract,
) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_dehb_space_manifest

    versions = {"DEHB": "0.1.2", "ConfigSpace": "1.2.2", "python": "3.11.9"}
    first = build_dehb_space_manifest(feature_contract, runtime_versions=versions)
    second = build_dehb_space_manifest(feature_contract, runtime_versions=versions)

    assert first == second
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["feature_contract_sha256"] == feature_contract.sha256
    assert first["search_end"] == "2010-12-31"
    assert first["validation_opened"] is False
    assert first["locked_opened"] is False
    assert first["fidelities"] == [1, 3, 9, 27]
    assert first["eta"] == 3
    assert first["lane_count"] == 240
    assert first["lanes"][0]["lane_id"] == "F001"
    assert first["lanes"][0]["parameter_space"] == {
        name: list(values)
        for name, values in feature_contract.lanes[0].parameter_space.items()
    }
    assert json.loads(json.dumps(first, sort_keys=True)) == first


def test_crosses_are_frozen_separately_without_implicit_cartesian_product(
    feature_contract,
) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_cross_manifest
    from aurora.infra.sp500_megarun.feature_contract import is_cross_allowed

    manifest = build_cross_manifest(feature_contract)

    assert manifest["cross_rule_count"] == len(feature_contract.cross_rules)
    assert manifest["implicit_crosses_in_lane_spaces"] is False
    assert all(row["max_features"] <= 5 for row in manifest["rules"])
    assert all(row["compositions"] for row in manifest["rules"])
    assert any(
        "F001" in row["left_lanes"] and "F019" in row["right_lanes"]
        for row in manifest["rules"]
    )
    assert is_cross_allowed(feature_contract, "F001", "F019") is True
    assert is_cross_allowed(feature_contract, "F001", "F239") is False


def test_manifest_fails_closed_if_validation_or_locked_is_open(feature_contract) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import (
        DehbConfigSpaceError,
        build_dehb_space_manifest,
    )

    versions = {"DEHB": "0.1.2", "ConfigSpace": "1.2.2", "python": "3.11.9"}
    opened = feature_contract.__class__(
        **{**feature_contract.__dict__, "validation_opened": True}
    )
    with pytest.raises(DehbConfigSpaceError, match="VALIDATION_MUST_REMAIN_CLOSED"):
        build_dehb_space_manifest(opened, runtime_versions=versions)

    opened = feature_contract.__class__(
        **{**feature_contract.__dict__, "locked_opened": True}
    )
    with pytest.raises(DehbConfigSpaceError, match="LOCKED_MUST_REMAIN_CLOSED"):
        build_dehb_space_manifest(opened, runtime_versions=versions)


def test_dependency_import_failure_has_an_actionable_error(feature_contract, monkeypatch) -> None:
    import aurora.infra.sp500_megarun.dehb_configspace as api

    def _missing(_: str):
        raise ModuleNotFoundError("ConfigSpace")

    monkeypatch.setattr(api.importlib, "import_module", _missing)

    with pytest.raises(api.DehbConfigSpaceError, match="CONFIGSPACE_DEPENDENCY_MISSING"):
        api.build_lane_configspace(feature_contract, "F001", seed=1)
