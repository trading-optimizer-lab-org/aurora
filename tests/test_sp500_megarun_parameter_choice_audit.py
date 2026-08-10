from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from aurora.infra.sp500_megarun.parameter_choice_audit import (
    audit_frozen_parameter_choices,
)


def test_parameter_choice_audit_is_not_ready_when_choices_are_inactive() -> None:
    contract = SimpleNamespace(
        sha256="frozen-contract",
        lanes=[
            SimpleNamespace(
                lane_id="F001",
                parameter_space={"window": [5, 20]},
            )
        ],
    )
    identical = pd.DataFrame(
        {
            "date": pd.to_datetime(["1998-01-02", "1999-01-04"]),
            "observed_at": pd.to_datetime(["1998-01-01", "1999-01-03"]),
            "available_at": pd.to_datetime(["1998-01-02", "1999-01-04"]),
            "value": [1.0, 2.0],
        }
    )

    report = audit_frozen_parameter_choices(
        contract,
        lane_ids=["F001"],
        evaluator=lambda _lane_id, _configuration: identical,
        expected_years=[1998, 1999],
    )

    assert report["ready"] is False
    assert report["inactive_choice_groups"] == [
        {
            "lane_id": "F001",
            "parameter": "window",
            "choices": [5, 20],
            "output_sha256": report["records"][0]["output_sha256"],
        }
    ]


def test_warmup_only_differences_do_not_make_a_choice_active() -> None:
    contract = SimpleNamespace(
        sha256="frozen-contract",
        lanes=[
            SimpleNamespace(
                lane_id="F001",
                parameter_space={"window": [5, 20]},
            )
        ],
    )

    def evaluator(_lane_id: str, configuration: dict[str, object]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["1997-12-31", "1998-01-02", "1999-01-04"]),
                "observed_at": pd.to_datetime(["1997-12-30", "1998-01-01", "1999-01-03"]),
                "available_at": pd.to_datetime(["1997-12-31", "1998-01-02", "1999-01-04"]),
                "value": [float(configuration["window"]), 1.0, 2.0],
            }
        )

    report = audit_frozen_parameter_choices(
        contract,
        lane_ids=["F001"],
        evaluator=evaluator,
        expected_years=[1998, 1999],
    )

    assert report["ready"] is False
    assert report["inactive_choice_groups"][0]["choices"] == [5, 20]
