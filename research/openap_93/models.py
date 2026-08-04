"""Typed observations emitted by the current OpenAP 93 extension."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .registry import FidelityClass


@dataclass(frozen=True)
class SignalObservation:
    """One current signal value with fail-closed provenance."""

    formation_date: str
    symbol: str
    signal: str
    value: float | None
    fidelity: FidelityClass
    current_usable: bool
    formula_id: str
    source_ids: tuple[str, ...]
    data_available_at: str
    observation_count: int
    missing_reason: str = ""
    caveat: str = ""

    def __post_init__(self) -> None:
        usable_classes = {
            FidelityClass.EXACT,
            FidelityClass.RECONSTRUCTED,
            FidelityClass.VALIDATED_PROXY,
        }
        expected_usable = self.value is not None and self.fidelity in usable_classes
        if self.current_usable != expected_usable:
            raise ValueError(
                f"{self.signal}/{self.symbol}: current_usable must equal "
                "value-present and exact/reconstructed/validated_proxy"
            )
        if self.value is None and not self.missing_reason:
            raise ValueError(f"{self.signal}/{self.symbol}: missing value needs a reason")
        if not self.formula_id:
            raise ValueError(f"{self.signal}/{self.symbol}: formula_id is required")

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["fidelity"] = self.fidelity.value
        record["source_ids"] = "|".join(self.source_ids)
        return record
