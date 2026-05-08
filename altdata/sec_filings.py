"""SEC EDGAR filings adapter.

Pulls 10-K, 10-Q, 8-K, and Form 4 (insider trades) from SEC EDGAR using only
``urllib`` from the stdlib; no third-party SDK is required. Network access is
opt-in. Tests use ``mock=True`` to bypass the HTTP layer.

Reference endpoints:
    https://data.sec.gov/submissions/CIK{padded_cik}.json
    https://www.sec.gov/cgi-bin/browse-edgar
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

# SEC requires a User-Agent header that identifies the requester.
_DEFAULT_UA = "QuantForge altdata/0.1 (research)"
_SUB_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

_VALID_FORMS = frozenset({"10-K", "10-Q", "8-K", "4"})


@dataclass
class SECConfig:
    """Static config for the SEC adapter.

    Attributes:
        user_agent: required by SEC fair-access policy.
        timeout_s: per-request timeout in seconds.
        max_filings: cap on returned rows per CIK to avoid pagination loops.
    """
    user_agent: str = _DEFAULT_UA
    timeout_s: float = 10.0
    max_filings: int = 200


class SECFilingsAdapter:
    """Filing metadata fetch."""

    _COLS = (
        "cik", "ticker", "form_type", "filing_date",
        "accession_number", "primary_doc", "filing_url",
    )

    def __init__(self, config: Optional[SECConfig] = None) -> None:
        self.config = config or SECConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def get_filings(
        self,
        cik: str,
        ticker: str = "",
        forms: tuple[str, ...] = ("10-K", "10-Q", "8-K", "4"),
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return DataFrame of recent filings for ``cik``.

        Args:
            cik: numeric CIK; will be zero-padded to 10 digits.
            ticker: optional symbol for downstream join convenience.
            forms: filter to these form types.
        """
        bad = [f for f in forms if f not in _VALID_FORMS]
        if bad:
            raise ValueError(f"unsupported form(s): {bad}")
        cik_padded = self._pad_cik(cik)
        if mock:
            return self._mock_frame(cik_padded, ticker, forms)
        raw = self._fetch_submissions(cik_padded)
        return self._parse(raw, cik_padded, ticker, forms)

    @staticmethod
    def _pad_cik(cik: str) -> str:
        digits = "".join(ch for ch in str(cik) if ch.isdigit())
        if not digits:
            raise ValueError(f"cik must contain digits, got {cik!r}")
        return digits.zfill(10)

    @staticmethod
    def build_filing_url(
        cik: str,
        accession: str,
        primary_doc: str,
    ) -> str:
        """Construct canonical SEC filing URL."""
        no_dash = accession.replace("-", "")
        cik_int = int(cik)
        return (
            f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
            f"{no_dash}/{primary_doc}"
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _fetch_submissions(self, cik_padded: str) -> dict:  # pragma: no cover - network
        url = _SUB_URL.format(cik=cik_padded)
        req = Request(url, headers={
            "User-Agent": self.config.user_agent,
            "Accept": "application/json",
        })
        try:
            with urlopen(req, timeout=self.config.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError) as e:
            raise RuntimeError(f"SEC fetch failed: {e}") from e

    def _parse(
        self,
        raw: dict,
        cik: str,
        ticker: str,
        forms: tuple[str, ...],
    ) -> pd.DataFrame:
        recent = raw.get("filings", {}).get("recent", {}) or {}
        accs = recent.get("accessionNumber", []) or []
        ftypes = recent.get("form", []) or []
        fdates = recent.get("filingDate", []) or []
        docs = recent.get("primaryDocument", []) or []
        n = min(len(accs), len(ftypes), len(fdates), len(docs))
        wanted = set(forms)
        rows = []
        for i in range(n):
            if ftypes[i] not in wanted:
                continue
            rows.append({
                "cik": cik,
                "ticker": ticker.upper(),
                "form_type": ftypes[i],
                "filing_date": pd.Timestamp(fdates[i]),
                "accession_number": accs[i],
                "primary_doc": docs[i],
                "filing_url": self.build_filing_url(cik, accs[i], docs[i]),
            })
            if len(rows) >= self.config.max_filings:
                break
        return pd.DataFrame(rows, columns=list(self._COLS))

    def _mock_frame(
        self,
        cik: str,
        ticker: str,
        forms: tuple[str, ...],
    ) -> pd.DataFrame:
        base = pd.Timestamp("2024-01-15")
        rows = []
        for i, f in enumerate(forms):
            acc = f"0001234567-24-{str(i).zfill(6)}"
            doc = f"{ticker.lower() or 'doc'}-{f.lower()}.htm"
            rows.append({
                "cik": cik,
                "ticker": ticker.upper(),
                "form_type": f,
                "filing_date": base + pd.Timedelta(days=i * 7),
                "accession_number": acc,
                "primary_doc": doc,
                "filing_url": self.build_filing_url(cik, acc, doc),
            })
        return pd.DataFrame(rows, columns=list(self._COLS))
