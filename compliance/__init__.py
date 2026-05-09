"""Compliance and regulatory reporting modules for QuantForge v3.0 Batch F.

Each submodule exposes a primary class with a dataclass config and a main
method. Optional vendor SDKs (sqlcipher, pyotp, cryptography) are imported
lazily inside methods so the package remains importable without those
dependencies installed. All modules ship with deterministic offline paths
so tests run without network or external services.

Module index:
- mifid_reporting: MiFID II RTS 22 transaction reports.
- sec_13f: SEC Form 13F-HR quarterly holdings filings.
- cftc_form: CFTC Form CTA position reporting.
- trade_reconstruction: T+5 reproducible trade reconstruction.
- best_execution: SEC Rule 605/606 best execution reporting.
- pii_handler: GDPR-compliant PII masking and encryption.
- soc2_audit: Append-only audit log with tamper-evident hash chain.
- encryption_at_rest: SQLCipher wrapper for encrypted SQLite (lazy import).
- rbac: Role-based access control engine.
- two_factor: TOTP two-factor authentication for critical actions.
"""
from __future__ import annotations

__all__: list[str] = []


def _try_export(module_name: str, symbols: tuple[str, ...]) -> None:
    """Best-effort import a sibling module and re-export selected symbols.

    Failures are swallowed so that a single broken optional-dep submodule does
    not block ``import aurora.compliance``. Importers can still target
    submodules directly to surface the underlying ImportError.
    """
    try:
        mod = __import__(f"aurora.compliance.{module_name}", fromlist=symbols)
    except Exception:  # noqa: BLE001 - optional dep failures must not crash init
        return
    for sym in symbols:
        if hasattr(mod, sym):
            globals()[sym] = getattr(mod, sym)
            __all__.append(sym)


_try_export("mifid_reporting", ("MiFIDIIReporter", "MiFIDConfig"))
_try_export("sec_13f", ("Form13FFiler", "Form13FConfig"))
_try_export("cftc_form", ("CTAFormReporter", "CTAFormConfig"))
_try_export("trade_reconstruction", ("TradeReconstructor", "ReconstructionConfig"))
_try_export("best_execution", ("BestExecutionReporter", "BestExecutionConfig"))
_try_export("pii_handler", ("PIIHandler", "PIIConfig"))
_try_export("soc2_audit", ("SOC2AuditTrail", "SOC2Config"))
_try_export("encryption_at_rest", ("SQLCipherWrapper", "SQLCipherConfig"))
_try_export("rbac", ("RBACEngine", "RBACConfig"))
_try_export("two_factor", ("TwoFactorAuth", "TwoFactorConfig"))
