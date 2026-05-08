"""SEC Form 13F-HR holdings filing assist.

Builds the Information Table portion of a 13F-HR filing as a stub XML
document. Real EDGAR submission requires the cover page, summary page, and
proper test-filing protocol via the EDGAR Filer Management portal; this
module produces the data payload that an operator can attach.

Filing threshold: $100M in 13(f) securities under management at the end of
any month in a calendar year. This module does not enforce eligibility;
the operator is responsible for confirming filing requirement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from xml.sax.saxutils import escape


@dataclass
class Form13FConfig:
    """Static config for the Form 13F filer.

    Attributes:
        filer_name: legal name of the filing manager.
        filer_cik: 10-digit CIK assigned by SEC.
        report_quarter: e.g. '2025-Q1'.
        is_amendment: whether this is an amendment (HR/A).
        confidential_treatment: optional confidential treatment request flag.
    """
    filer_name: str = "UNKNOWN MANAGER"
    filer_cik: str = "0000000000"
    report_quarter: str = "2025-Q1"
    is_amendment: bool = False
    confidential_treatment: bool = False
    extra_disclosures: tuple[str, ...] = field(default_factory=tuple)


class Form13FFiler:
    """Build 13F-HR Information Table XML stub."""

    def __init__(self, config: Optional[Form13FConfig] = None) -> None:
        self.config = config or Form13FConfig()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_information_table(self, holdings: Iterable[dict]) -> str:
        """Return the Information Table XML for ``holdings``.

        Args:
            holdings: iterable of dicts with keys: name_of_issuer, title_of_class,
                cusip, value (in thousands), shares, share_type ('SH' or 'PRN'),
                investment_discretion ('SOLE'|'DFND'|'OTR'), voting_authority_sole,
                voting_authority_shared, voting_authority_none.
        """
        rows = list(holdings)
        parts: list[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">',
        ]
        for h in rows:
            parts.append(self._render_holding(h))
        parts.append("</informationTable>")
        return "\n".join(parts)

    def file_form(self, holdings: Iterable[dict], out_dir: str | Path) -> Path:
        """Write XML stub to ``out_dir`` and return the file path."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        suffix = "HR-A" if self.config.is_amendment else "HR"
        ts = datetime.now(timezone.utc).strftime("%Y%m%d")
        fname = f"form13F_{suffix}_{self.config.filer_cik}_{self.config.report_quarter}_{ts}.xml"
        fpath = out / fname
        fpath.write_text(self.build_information_table(holdings), encoding="utf-8")
        return fpath

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _render_holding(self, h: dict) -> str:
        name = escape(str(h.get("name_of_issuer", "UNKNOWN")))
        title = escape(str(h.get("title_of_class", "COM")))
        cusip = escape(str(h.get("cusip", "000000000")))
        value = int(h.get("value", 0))
        shares = int(h.get("shares", 0))
        share_type = escape(str(h.get("share_type", "SH")))
        discretion = escape(str(h.get("investment_discretion", "SOLE")))
        v_sole = int(h.get("voting_authority_sole", shares))
        v_shared = int(h.get("voting_authority_shared", 0))
        v_none = int(h.get("voting_authority_none", 0))
        return (
            "  <infoTable>\n"
            f"    <nameOfIssuer>{name}</nameOfIssuer>\n"
            f"    <titleOfClass>{title}</titleOfClass>\n"
            f"    <cusip>{cusip}</cusip>\n"
            f"    <value>{value}</value>\n"
            "    <shrsOrPrnAmt>\n"
            f"      <sshPrnamt>{shares}</sshPrnamt>\n"
            f"      <sshPrnamtType>{share_type}</sshPrnamtType>\n"
            "    </shrsOrPrnAmt>\n"
            f"    <investmentDiscretion>{discretion}</investmentDiscretion>\n"
            "    <votingAuthority>\n"
            f"      <Sole>{v_sole}</Sole>\n"
            f"      <Shared>{v_shared}</Shared>\n"
            f"      <None>{v_none}</None>\n"
            "    </votingAuthority>\n"
            "  </infoTable>"
        )
