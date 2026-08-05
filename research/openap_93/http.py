"""Shared HTTP identity for audited public-data requests."""

from __future__ import annotations


DEFAULT_USER_AGENT = (
    "Aurora-OpenAP-Research/1.0 "
    "https://github.com/trading-optimizer-lab-org/aurora"
)

# SEC fair-access guidance requires an identifiable organization and contact.
# This address is already public in the repository's Git commit metadata.
SEC_USER_AGENT = "Aurora OpenAP Research dgomezbru@gmail.com"


def public_headers(*, sec: bool = False) -> dict[str, str]:
    return {
        "User-Agent": SEC_USER_AGENT if sec else DEFAULT_USER_AGENT,
        "Accept": "application/json,text/csv,text/plain,application/zip,"
        "application/octet-stream,*/*",
        "Accept-Encoding": "gzip, deflate",
    }


__all__ = ["DEFAULT_USER_AGENT", "SEC_USER_AGENT", "public_headers"]
