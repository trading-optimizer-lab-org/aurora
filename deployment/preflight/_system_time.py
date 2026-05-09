"""System-time / NTP preflight check."""
from __future__ import annotations

import logging
import socket
import struct
import time

from aurora.deployment.preflight._models import PreflightCheck

_log = logging.getLogger(__name__)

# NTP fallback chain. Probed in order; first server that responds within the
# per-attempt timeout wins. If all fail, callers fall back to time.time().
_NTP_FALLBACK_SERVERS: tuple[str, ...] = (
    "pool.ntp.org",
    "time.google.com",
    "time.cloudflare.com",
    "time.nist.gov",
)


def _query_ntp_server(ntp_server: str, timeout: float) -> float | None:
    """Send one NTP request; return server epoch seconds or None on failure."""
    NTP_PORT = 123
    NTP_PACKET = b"\x1b" + 47 * b"\0"
    NTP_DELTA = 2208988800  # 1900 -> 1970
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(NTP_PACKET, (ntp_server, NTP_PORT))
        data, _ = sock.recvfrom(48)
    except Exception:
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
    try:
        secs = struct.unpack("!12I", data)[10]
        return float(secs - NTP_DELTA)
    except Exception:
        return None


def check_system_time(max_drift_sec: float = 1.0,
                      ntp_server: str | None = None,
                      timeout: float = 2.0,
                      ntp_servers: tuple[str, ...] | None = None,
                      soft_skip: bool = False,
                      ) -> PreflightCheck:
    """Compare local clock to NTP with fallback chain.

    Tries each server in ``ntp_servers`` (default: pool.ntp.org, time.google.com,
    time.cloudflare.com, time.nist.gov) in order. The first server to respond
    within ``timeout`` (default 2.0s) wins.

    All-fail behavior
    -----------------
    Default: when **every** server fails to respond, this check FAILS with
    detail "no NTP reachable". Live deployments that silently pass when the
    clock cannot be verified are dangerous — order timestamps, audit
    correlation, and broker session expiry all rely on accurate local time.
    Set ``soft_skip=True`` only in tightly-controlled environments where
    losing NTP is expected (offline labs, paper trading on isolated boxes).

    Args:
        max_drift_sec: max allowed |local - ntp| in seconds.
        ntp_server: optional single server (back-compat). If provided and
            ``ntp_servers`` is None, it is used as the only entry in the chain.
        timeout: per-server timeout in seconds.
        ntp_servers: explicit fallback chain. When None, uses
            ``_NTP_FALLBACK_SERVERS``.
        soft_skip: opt-in fallback that converts an all-fail outcome into a
            PASS instead of a FAIL. Defaults to False so live deployments
            block on unverified clocks.
    """
    if ntp_servers is None:
        if ntp_server is not None:
            servers: tuple[str, ...] = (ntp_server,)
        else:
            servers = _NTP_FALLBACK_SERVERS
    else:
        servers = tuple(ntp_servers)

    tried: list[str] = []
    # Resolve through the package so test monkey-patches of
    # ``aurora.deployment.preflight._query_ntp_server`` are honoured.
    import aurora.deployment.preflight as _pkg
    for server in servers:
        tried.append(server)
        ntp_time = _pkg._query_ntp_server(server, timeout)
        if ntp_time is None:
            continue
        drift = abs(time.time() - ntp_time)
        if drift > max_drift_sec:
            return PreflightCheck(
                "system_time", False,
                f"clock drift {drift:.2f}s > {max_drift_sec:.2f}s "
                f"(server={server})",
            )
        return PreflightCheck(
            "system_time", True, f"drift={drift:.3f}s (server={server})",
        )

    # All servers failed.
    _log.warning(
        "preflight.check_system_time: all NTP servers unreachable (%s)",
        ", ".join(tried),
    )
    if soft_skip:
        return PreflightCheck(
            "system_time", True,
            f"skipped (soft_skip=True, no NTP from {len(tried)} servers)",
        )
    return PreflightCheck(
        "system_time", False,
        f"no NTP reachable (tried {len(tried)} servers: "
        f"{', '.join(tried)})",
    )
