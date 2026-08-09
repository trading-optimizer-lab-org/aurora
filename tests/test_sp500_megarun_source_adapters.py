from __future__ import annotations

from io import BytesIO
import zipfile

import pandas as pd

from aurora.infra.sp500_megarun.source_adapters import normalize_resource_payload


def _zip_bytes(name: str, payload: bytes) -> bytes:
    target = BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, payload)
    return target.getvalue()


def test_federal_reserve_zip_xml_is_normalized_and_bounded() -> None:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <message:CompactData xmlns:message="urn:test" xmlns:frb="urn:frb">
      <frb:Series SERIES_NAME="Treasury 10Y" SERIES_ID="H15_T10Y">
        <frb:Obs TIME_PERIOD="2010-12-30" OBS_VALUE="3.36" />
        <frb:Obs TIME_PERIOD="2011-01-03" OBS_VALUE="3.30" />
      </frb:Series>
    </message:CompactData>
    """

    frame = normalize_resource_payload(
        "federal_reserve_ddp_zip_xml",
        _zip_bytes("H15_data.xml", xml),
        format_name="zip_xml",
        resource_id="h15",
        maximum_observation_date="2010-12-31",
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2010-12-30"]
    assert frame["value"].tolist() == [3.36]
    assert frame["series_id"].tolist() == ["H15_T10Y"]


def test_french_zip_skips_description_and_finds_daily_table() -> None:
    raw = b"""This file was created by CMPT_ME_BEME_RETS using the 202407 CRSP database.\n\n,Mkt-RF,SMB,HML,RF\n19980102,1.20,0.10,-0.20,0.02\n19980105,-0.30,0.04,0.11,0.02\n\n Annual Factors: January-December \n"""

    frame = normalize_resource_payload(
        "french_zip_csv",
        _zip_bytes("factors.csv", raw),
        format_name="zip_csv",
        resource_id="ff3_daily",
        maximum_observation_date="2010-12-31",
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["1998-01-02", "1998-01-05"]
    assert frame["Mkt-RF"].tolist() == [1.2, -0.3]


def test_csv_normalizer_rejects_rows_after_the_evaluation_boundary() -> None:
    payload = b"date,value\n2010-12-31,1\n2011-01-03,2\n"

    frame = normalize_resource_payload(
        "cboe_history_csv",
        payload,
        format_name="csv",
        resource_id="vix",
        maximum_observation_date="2010-12-31",
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2010-12-31"]
    assert frame["resource_id"].unique().tolist() == ["vix"]


def test_numeric_yyyymm_dates_are_normalized_without_future_leakage() -> None:
    payload = b"month,value\n199801,10\n201012,20\n201101,30\n"

    frame = normalize_resource_payload(
        "academic_table",
        payload,
        format_name="csv",
        resource_id="monthly",
        maximum_observation_date="2010-12-31",
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["1998-01-01", "2010-12-01"]


def test_normalized_resource_has_a_stable_content_hash_input() -> None:
    payload = b"date,value\n1998-01-02,1.5\n"

    first = normalize_resource_payload(
        "cboe_history_csv",
        payload,
        format_name="csv",
        resource_id="stable",
        maximum_observation_date="2010-12-31",
    )
    second = normalize_resource_payload(
        "cboe_history_csv",
        payload,
        format_name="csv",
        resource_id="stable",
        maximum_observation_date="2010-12-31",
    )

    pd.testing.assert_frame_equal(first, second)
