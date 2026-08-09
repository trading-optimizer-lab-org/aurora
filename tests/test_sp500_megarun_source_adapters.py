from __future__ import annotations

from io import BytesIO
import json
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


def test_quarter_and_decimal_month_dates_are_normalized() -> None:
    quarterly = normalize_resource_payload(
        "academic_table",
        b"period,value\n1998Q1,1\n2010Q4,2\n2011Q1,3\n",
        format_name="csv",
        resource_id="quarterly",
        maximum_observation_date="2010-12-31",
    )
    decimal_month = normalize_resource_payload(
        "academic_table",
        b"period,value\n1998.01,1169.05\n2010.12,900.10\n2011.01,800.10\n",
        format_name="csv",
        resource_id="monthly",
        maximum_observation_date="2010-12-31",
    )
    colon_month = normalize_resource_payload(
        "academic_table",
        b"period,value\n1998:01,1\n2010:12,2\n2011:01,3\n",
        format_name="csv",
        resource_id="colon_monthly",
        maximum_observation_date="2010-12-31",
    )

    assert quarterly["date"].dt.strftime("%Y-%m-%d").tolist() == ["1998-01-01", "2010-10-01"]
    assert decimal_month["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "1998-01-01",
        "2010-12-01",
    ]
    assert colon_month["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "1998-01-01",
        "2010-12-01",
    ]


def test_world_bank_monthly_workbook_selects_declared_series() -> None:
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                ["World Bank commodity prices", None, None],
                ["Date", "Crude oil, WTI", "Gold"],
                ["1998M01", 17.0, 290.0],
                ["2010M12", 89.0, 1390.0],
                ["2011M01", 90.0, 1400.0],
            ]
        ).to_excel(writer, sheet_name="Monthly Prices", header=False, index=False)

    frame = normalize_resource_payload(
        "world_bank_pink_sheet",
        workbook.getvalue(),
        format_name="xlsx",
        resource_id="pink",
        maximum_observation_date="2010-12-31",
        resource_metadata={"series": "Gold"},
    )

    assert frame["value"].tolist() == [290.0, 1390.0]
    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["1998-01-01", "2010-12-01"]


def test_cftc_comma_zip_parses_legacy_rows() -> None:
    raw = b"Market_and_Exchange_Names,As_of_Date_In_Form_YYMMDD,Open_Interest_All\nS&P 500,980106,100\nS&P 500,101228,200\n"

    frame = normalize_resource_payload(
        "cftc_legacy_zip",
        _zip_bytes("annual.txt", raw),
        format_name="zip_csv",
        resource_id="cftc",
        maximum_observation_date="2010-12-31",
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["1998-01-06", "2010-12-28"]


def test_cftc_utf16_zip_parses_official_legacy_encoding() -> None:
    text = "Market and Exchange Names,As of Date in Form YYMMDD,Open Interest (All)\r\nS&P 500,980106,100\r\n"

    frame = normalize_resource_payload(
        "cftc_legacy_zip",
        _zip_bytes("annual.txt", text.encode("utf-16")),
        format_name="zip_csv",
        resource_id="cftc_utf16",
        maximum_observation_date="2010-12-31",
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["1998-01-06"]


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


def test_treasury_fiscal_json_normalizes_nested_api_rows_and_bounds_locked_data() -> None:
    payload = json.dumps(
        {
            "data": [
                {"record_date": "2020-12-31", "tot_pub_debt_out_amt": "27747798266968.05"},
                {"record_date": "2021-01-04", "tot_pub_debt_out_amt": "27755349741662.05"},
            ]
        }
    ).encode()

    frame = normalize_resource_payload(
        "treasury_fiscal_json",
        payload,
        format_name="json",
        resource_id="debt",
        maximum_observation_date="2020-12-31",
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2020-12-31"]


def test_sec_master_index_normalizes_filing_dates() -> None:
    payload = b"Description\nCIK|Company Name|Form Type|Date Filed|Filename\n1|Example|8-K|2020-12-31|edgar/data/1/a.txt\n"

    frame = normalize_resource_payload(
        "sec_edgar_index_bundle",
        payload,
        format_name="idx",
        resource_id="2020q4",
        maximum_observation_date="2020-12-31",
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["2020-12-31"]
    assert frame["Form Type"].tolist() == ["8-K"]


def test_world_bank_all_commodities_keeps_every_series() -> None:
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                ["World Bank commodity prices", None, None],
                ["Date", "Crude oil, WTI", "Gold"],
                ["1998M01", 17.0, 290.0],
                ["2020M12", 47.0, 1887.0],
            ]
        ).to_excel(writer, sheet_name="Monthly Prices", header=False, index=False)

    frame = normalize_resource_payload(
        "world_bank_all_commodities",
        workbook.getvalue(),
        format_name="xlsx",
        resource_id="pink_all",
        maximum_observation_date="2020-12-31",
    )

    assert {"Crude oil, WTI", "Gold"} <= set(frame.columns)
    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["1998-01-01", "2020-12-01"]


def test_world_bank_all_commodities_finds_date_after_leading_blank_columns() -> None:
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                [None, "World Bank commodity prices", None, None],
                [None, "Date", "Crude oil, WTI", "Gold"],
                [None, "1998M01", 17.0, 290.0],
                [None, "2020M12", 47.0, 1887.0],
            ]
        ).to_excel(writer, sheet_name="Monthly Prices", header=False, index=False)

    frame = normalize_resource_payload(
        "world_bank_all_commodities",
        workbook.getvalue(),
        format_name="xlsx",
        resource_id="pink_all_offset",
        maximum_observation_date="2020-12-31",
    )

    assert {"Crude oil, WTI", "Gold"} <= set(frame.columns)
    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["1998-01-01", "2020-12-01"]


def test_fomc_archive_keeps_meetings_statements_and_minutes_release_dates() -> None:
    payload = b"""
    <h5>February 3-4 Meeting - 1998</h5>
    <a href="/boarddocs/press/general/1998/19980929/">Statement</a>
    <a href="/fomc/minutes/19980929.htm">Minutes</a> (Released November 19, 1998)
    """

    frame = normalize_resource_payload(
        "fomc_public_archive",
        payload,
        format_name="html",
        resource_id="fomc_1998",
        maximum_observation_date="2020-12-31",
    )

    assert {"meeting", "statement", "minutes_release"} <= set(frame["document_kind"])
    assert {"1998-02-03", "1998-09-29", "1998-11-19"} <= set(
        frame["date"].dt.strftime("%Y-%m-%d")
    )


def test_treasury_tic_fixed_width_history_parses_signed_comma_values() -> None:
    payload = b"""NET PURCHASES OF U.S. TREASURY BONDS & NOTES\n\n
      MONTH        PURCHASES     INSTITUTIONS   FOREIGNERS    ORGANIZATIONS\n
      -------   ---------------  ------------  ------------  ---------------\n
      2020-12           -20,696        -2,280       -18,509               93\n
      1998-01             7,126        -1,093         8,271              -52\n
    """

    frame = normalize_resource_payload(
        "treasury_tic_bundle",
        payload,
        format_name="txt",
        resource_id="tressect",
        maximum_observation_date="2020-12-31",
    )

    assert frame["date"].dt.strftime("%Y-%m-%d").tolist() == ["1998-01-01", "2020-12-01"]
    assert frame["total_net_purchases"].tolist() == [7126, -20696]


def test_spf_multisheet_workbook_is_read_without_assuming_one_header_row() -> None:
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(
            [["YEAR", "QUARTER", "RGDP1"], [1998, 1, 1.2], [2020, 4, 2.3]]
        ).to_excel(writer, sheet_name="RGDP", header=False, index=False)
        pd.DataFrame(
            [["YEAR", "QUARTER", "UNEMP1"], [1998, 1, 4.7], [2020, 4, 6.7]]
        ).to_excel(writer, sheet_name="UNEMP", header=False, index=False)

    frame = normalize_resource_payload(
        "philadelphia_spf_bundle",
        workbook.getvalue(),
        format_name="xlsx",
        resource_id="spf_mean",
        maximum_observation_date="2020-12-31",
    )

    assert set(frame["source_sheet"]) == {"RGDP", "UNEMP"}
    assert frame["date"].min().date().isoformat() == "1998-01-01"
    assert frame["date"].max().date().isoformat() == "2020-01-01"
