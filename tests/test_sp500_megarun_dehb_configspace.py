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
        ("F079", 2),
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
        ("F113", 14),
        ("F115", 4),
        ("F116", 4),
        ("F117", 8),
        ("F118", 2),
        ("F120", 3),
        ("F121", 21),
        ("F123", 10),
        ("F124", 4),
        ("F125", 19),
        ("F127", 15),
        ("F128", 26),
        ("F130", 24),
        ("F132", 9),
        ("F133", 8),
        ("F135", 18),
        ("F136", 3),
        ("F137", 9),
        ("F139", 12),
        ("F140", 12),
        ("F141", 15),
        ("F142", 13),
        ("F143", 3),
        ("F144", 20),
        ("F145", 8),
        ("F148", 4),
        ("F149", 8),
        ("F150", 13),
        ("F161", 14),
        ("F162", 6),
        ("F165", 9),
        ("F169", 16),
        ("F170", 14),
        ("F171", 8),
        ("F172", 9),
        ("F173", 4),
        ("F174", 13),
        ("F176", 13),
        ("F177", 6),
        ("F178", 3),
        ("F179", 3),
        ("F180", 12),
        ("F181", 14),
        ("F182", 26),
        ("F183", 9),
        ("F184", 30),
        ("F185", 47),
        ("F186", 18),
        ("F187", 26),
        ("F188", 41),
        ("F190", 9),
        ("F191", 12),
        ("F192", 12),
        ("F193", 48),
        ("F194", 12),
        ("F195", 36),
        ("F196", 60),
        ("F197", 42),
        ("F198", 36),
        ("F199", 36),
        ("F200", 12),
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


def test_f148_invalid_receptive_fields_are_forbidden_as_exact_triplets(
    feature_contract,
) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace

    row = build_lane_configspace(
        feature_contract,
        "F148",
        seed=51,
        configspace_module=FAKE_CONFIGSPACE,
    )

    forbidden = {
        tuple((clause.hyperparameter.name, clause.value) for clause in conjunction.clauses)
        for conjunction in row.configspace.forbidden_clauses
    }
    assert forbidden == {
        (("sequence", 10), ("kernel", 3), ("dilation", 8)),
        (("sequence", 10), ("kernel", 5), ("dilation", 4)),
        (("sequence", 10), ("kernel", 5), ("dilation", 8)),
        (("sequence", 20), ("kernel", 5), ("dilation", 8)),
    }


def test_f169_effective_selection_count_clones_are_forbidden_as_triplets(
    feature_contract,
) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace

    lane = next(item for item in feature_contract.lanes if item.lane_id == "F169")
    assert lane.parameter_space["selection_fraction"] == (0.1, 0.25, 0.33, 0.5)
    row = build_lane_configspace(
        feature_contract,
        "F169",
        seed=51,
        configspace_module=FAKE_CONFIGSPACE,
    )

    triplets = {
        tuple((clause.hyperparameter.name, clause.value) for clause in conjunction.clauses)
        for conjunction in row.configspace.forbidden_clauses
        if len(conjunction.clauses) == 3
    }
    assert triplets == {
        (("aggregation", aggregation), ("universe", universe), ("selection_fraction", fraction))
        for aggregation in ("mean", "median")
        for universe, fraction in (
            ("regions_only", 0.25),
            ("regions_only", 0.33),
            ("developed_ex_us_plus_regions", 0.25),
            ("developed_ex_us_plus_regions", 0.5),
            ("all_available", 0.33),
        )
    }


def test_f173_tail_fractions_have_three_distinct_nine_currency_counts(
    feature_contract,
) -> None:
    lane = next(item for item in feature_contract.lanes if item.lane_id == "F173")

    assert lane.parameter_space["selection_fraction"] == (0.2, 0.25, 0.5)


def test_f172_does_not_forbid_independent_window_pairs(feature_contract) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace

    row = build_lane_configspace(
        feature_contract,
        "F172",
        seed=51,
        configspace_module=FAKE_CONFIGSPACE,
    )
    forbidden_names = {
        tuple(clause.hyperparameter.name for clause in conjunction.clauses)
        for conjunction in row.configspace.forbidden_clauses
    }

    assert ("window", "long_window") not in forbidden_names


def test_f180_long_window_rules_are_scoped_to_the_statistics_that_use_it(
    feature_contract,
) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace

    row = build_lane_configspace(
        feature_contract,
        "F180",
        seed=51,
        configspace_module=FAKE_CONFIGSPACE,
    )
    forbidden = {
        tuple((clause.hyperparameter.name, clause.value) for clause in conjunction.clauses)
        for conjunction in row.configspace.forbidden_clauses
    }

    assert forbidden == {
        (("statistic", statistic), ("long_window", long_window))
        for statistic in ("correlation", "beta")
        for long_window in (252, 504, 756)
    } | {
        (("statistic", statistic), ("window", window), ("long_window", long_window))
        for statistic in ("decoupling", "sign_change")
        for window, long_window in ((126, 126), (252, 126), (252, 252))
    }


@pytest.mark.parametrize(
    ("lane_id", "scoped_statistic", "excluded_statistics", "expected_triplets"),
    [
        ("F184", "baa_aaa", ("credit_stress_composite",), 24),
        ("F185", "quality_spread", ("spread_volume_composite",), 32),
        ("F188", "total_growth", ("consumer_credit_stress",), 32),
        (
            "F193",
            "nonresidential_investment",
            ("housing_investment_composite", "revision_composite"),
            30,
        ),
        ("F195", "payroll_first", ("labor_composite",), 30),
        (
            "F196",
            "industrial_production",
            ("production_capacity_composite", "revision_composite"),
            36,
        ),
        ("F197", "output_nowcast", ("macro_outlook_composite",), 36),
        (
            "F198",
            "ngdp_iqr",
            ("macro_disagreement", "disagreement_breadth"),
            30,
        ),
        (
            "F199",
            "forecast_revision",
            ("rolling_bias", "rolling_absolute_error"),
            30,
        ),
    ],
)
def test_internal_composites_keep_their_window_while_raw_simple_statistics_do_not(
    feature_contract,
    lane_id: str,
    scoped_statistic: str,
    excluded_statistics: tuple[str, ...],
    expected_triplets: int,
) -> None:
    from aurora.infra.sp500_megarun.dehb_configspace import build_lane_configspace

    row = build_lane_configspace(
        feature_contract,
        lane_id,
        seed=51,
        configspace_module=FAKE_CONFIGSPACE,
    )
    triplets = {
        tuple((clause.hyperparameter.name, clause.value) for clause in conjunction.clauses)
        for conjunction in row.configspace.forbidden_clauses
        if len(conjunction.clauses) == 3
    }

    assert len(triplets) == expected_triplets
    assert any(("statistic", scoped_statistic) in item for item in triplets)
    assert all(
        ("statistic", excluded_statistic) not in item
        for item in triplets
        for excluded_statistic in excluded_statistics
    )


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
