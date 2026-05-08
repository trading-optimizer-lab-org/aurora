"""Tests for quantforge.compliance.sec_13f."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from quantforge.compliance.sec_13f import Form13FConfig, Form13FFiler


@pytest.fixture
def filer() -> Form13FFiler:
    return Form13FFiler(Form13FConfig(
        filer_name="Test Manager LLC",
        filer_cik="0001234567",
        report_quarter="2025-Q1",
    ))


@pytest.fixture
def holdings() -> list[dict]:
    return [
        {
            "name_of_issuer": "APPLE INC",
            "title_of_class": "COM",
            "cusip": "037833100",
            "value": 1500000,
            "shares": 8500,
            "share_type": "SH",
            "investment_discretion": "SOLE",
        },
        {
            "name_of_issuer": "MICROSOFT CORP",
            "title_of_class": "COM",
            "cusip": "594918104",
            "value": 2200000,
            "shares": 5300,
            "share_type": "SH",
            "investment_discretion": "SOLE",
            "voting_authority_sole": 5300,
            "voting_authority_shared": 0,
            "voting_authority_none": 0,
        },
    ]


def test_xml_is_well_formed(filer, holdings):
    xml = filer.build_information_table(holdings)
    root = ET.fromstring(xml)
    ns = "{http://www.sec.gov/edgar/document/thirteenf/informationtable}"
    info_tables = root.findall(f"{ns}infoTable")
    assert len(info_tables) == 2


def test_xml_contains_required_fields(filer, holdings):
    xml = filer.build_information_table(holdings)
    assert "<nameOfIssuer>APPLE INC</nameOfIssuer>" in xml
    assert "<cusip>037833100</cusip>" in xml
    assert "<value>1500000</value>" in xml


def test_xml_escapes_special_chars(filer):
    h = [{
        "name_of_issuer": "A&B Corp <Holdings>",
        "title_of_class": "COM",
        "cusip": "000000000",
        "value": 100,
        "shares": 10,
    }]
    xml = filer.build_information_table(h)
    assert "A&amp;B Corp &lt;Holdings&gt;" in xml


def test_file_form_writes_xml(tmp_path, filer, holdings):
    path = filer.file_form(holdings, tmp_path)
    assert path.exists()
    assert path.suffix == ".xml"
    assert "0001234567" in path.name
    assert "2025-Q1" in path.name


def test_amendment_filename_uses_hr_a(tmp_path, holdings):
    f = Form13FFiler(Form13FConfig(
        filer_cik="0007654321", report_quarter="2025-Q2", is_amendment=True,
    ))
    path = f.file_form(holdings, tmp_path)
    assert "HR-A" in path.name


def test_empty_holdings_produces_valid_xml(filer):
    xml = filer.build_information_table([])
    root = ET.fromstring(xml)
    ns = "{http://www.sec.gov/edgar/document/thirteenf/informationtable}"
    assert root.findall(f"{ns}infoTable") == []
