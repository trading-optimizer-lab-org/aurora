"""Canonical signal registry and fail-closed fidelity contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class RegistryError(ValueError):
    """Raised when the 93-signal contract is incomplete or ambiguous."""


class FidelityClass(str, Enum):
    EXACT = "exact"
    RECONSTRUCTED = "reconstructed"
    VALIDATED_PROXY = "validated_proxy"
    UNVALIDATED_PROXY = "unvalidated_proxy"
    UNAVAILABLE = "unavailable"
    STALE_REFERENCE_ONLY = "stale_reference_only"


REQUIRED_93 = (
    "AOP", "AbnormalAccruals", "AccrualsBM", "AgeIPO", "AnnouncementReturn",
    "BMdec", "BPEBM", "BetaLiquidityPS", "BetaTailRisk", "BrandInvest",
    "CBOperProf", "ChInvIA", "ChNNCOA", "ChangeInRecommendation", "CitationsRD",
    "CompEquIss", "ConvDebt", "CoskewACX", "Coskewness", "CredRatDG",
    "CustomerMomentum", "DelBreadth", "DelNetFin", "DivInit", "DivOmit",
    "DivSeason", "DivYieldST", "EBM", "EarnSupBig", "EarningsConsistency",
    "EarningsForecastDisparity", "EarningsStreak", "EarningsSurprise", "EntMult",
    "EquityDuration", "ExchSwitch", "ExclExp", "FEPS", "FirmAgeMom",
    "ForecastDispersion", "Frontier", "Governance", "GrLTNOA", "Herf", "HerfBE",
    "IO_ShortInterest", "IdioVol3F", "IndIPO", "IndRetBig", "IntanBM", "IntanCFP",
    "IntanEP", "IntanSP", "MS", "MeanRankRevGrowth", "Mom6mJunk", "MomRev",
    "MomVol", "NumEarnIncrease", "OScore", "OrderBacklog", "OrderBacklogChg",
    "OrgCap", "PS", "PatentsRD", "PctTotAcc", "PriceDelayRsq",
    "ProbInformedTrading", "RDIPO", "RDS", "RIO_Disp", "RIO_MB", "RIO_Turnover",
    "RIO_Volatility", "Recomm_ShortInterest", "ResidualMomentum", "ReturnSkew3F",
    "RevenueSurprise", "ShortInterest", "Spinoff", "Tax", "betaVIX",
    "dCPVolSpread", "dNoa", "dVolCall", "fgr5yrLag", "hire", "iomom_supp",
    "retConglomerate", "roaq", "zerotrade12M", "zerotrade1M", "zerotrade6M",
)


@dataclass(frozen=True)
class SignalSpec:
    name: str
    data_family: str
    natural_frequency: str
    required_inputs: tuple[str, ...]
    candidate_sources: tuple[str, ...]
    openap_script: str
    expected_best_class: FidelityClass
    notes: str = ""


def _signal_from_mapping(name: str, value: dict[str, Any]) -> SignalSpec:
    required = {
        "data_family", "natural_frequency", "required_inputs", "candidate_sources",
        "openap_script", "expected_best_class",
    }
    missing = required.difference(value)
    if missing:
        raise RegistryError(f"{name}: missing fields {sorted(missing)}")
    try:
        fidelity = FidelityClass(str(value["expected_best_class"]))
    except ValueError as exc:
        raise RegistryError(f"{name}: invalid fidelity class") from exc
    return SignalSpec(
        name=name,
        data_family=str(value["data_family"]),
        natural_frequency=str(value["natural_frequency"]),
        required_inputs=tuple(str(item) for item in value["required_inputs"]),
        candidate_sources=tuple(str(item) for item in value["candidate_sources"]),
        openap_script=str(value["openap_script"]),
        expected_best_class=fidelity,
        notes=str(value.get("notes", "")),
    )


def load_signal_registry(path: str | Path) -> dict[str, SignalSpec]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("signals"), dict):
        raise RegistryError("signals_93.yaml must contain a signals mapping")
    registry = {
        str(name): _signal_from_mapping(str(name), dict(value))
        for name, value in payload["signals"].items()
    }
    required = set(REQUIRED_93)
    actual = set(registry)
    if actual != required:
        raise RegistryError(
            f"93-signal mismatch: missing={sorted(required-actual)}, extra={sorted(actual-required)}"
        )
    if len(registry) != 93:
        raise RegistryError(f"Expected 93 unique signals, found {len(registry)}")
    return registry
