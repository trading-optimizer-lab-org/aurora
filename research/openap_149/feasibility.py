"""Fail-closed feasibility reconciliation for the targeted OpenAP 149."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


class FeasibilityError(ValueError):
    """Raised when source evidence cannot be reconciled without guessing."""


REGISTER_COLUMNS = (
    "signal",
    "category",
    "feasibility_class",
    "classification_reason",
    "current_value_calculated",
    "current_status",
    "strict_score_eligible",
    "original_input_class",
    "proposed_free_sources",
    "remaining_blocker",
    "official_formula_url",
    "source_checked_at",
)


def _as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    normalized = series.fillna("").astype(str).str.strip().str.lower()
    allowed = {"true", "false", "1", "0", "yes", "no", ""}
    unexpected = sorted(set(normalized) - allowed)
    if unexpected:
        raise FeasibilityError(f"Valores booleanos no reconocidos: {unexpected}")
    return normalized.isin({"true", "1", "yes"})


def _mapping(contract: Mapping[str, object], key: str) -> dict[str, str]:
    value = contract.get(key)
    if not isinstance(value, Mapping):
        raise FeasibilityError(f"El contrato necesita un mapa {key!r}")
    return {str(name): str(reason) for name, reason in value.items()}


def build_feasibility_register(
    acquisition: pd.DataFrame,
    reaudit: pd.DataFrame,
    contract: Mapping[str, object],
) -> pd.DataFrame:
    """Reconcile 149 targets without treating calculated proxies as approved."""

    required_acquisition = {
        "signal",
        "category",
        "current_value_calculated",
        "status",
        "remaining_blocker",
        "strict_score_eligible",
        "official_formula_url",
    }
    required_reaudit = {
        "signal",
        "strict_historical_classification",
        "primary_free_sources",
        "source_checked_at",
    }
    missing_acquisition = required_acquisition - set(acquisition.columns)
    missing_reaudit = required_reaudit - set(reaudit.columns)
    if missing_acquisition or missing_reaudit:
        raise FeasibilityError(
            "Columnas ausentes: "
            f"acquisition={sorted(missing_acquisition)}, reaudit={sorted(missing_reaudit)}"
        )

    target_count = int(contract.get("target_count", 0))
    if target_count != 149 or len(acquisition) != target_count:
        raise FeasibilityError(
            f"El inventario objetivo debe contener exactamente 149 filas; contiene {len(acquisition)}"
        )
    if acquisition["signal"].isna().any() or acquisition["signal"].duplicated().any():
        raise FeasibilityError("El inventario contiene señales vacías o duplicadas")

    strict = _as_bool(acquisition["strict_score_eligible"])
    if strict.any():
        raise FeasibilityError(
            "La evidencia existente contiene strict_score_eligible=True sin validación independiente"
        )

    names = set(acquisition["signal"].astype(str))
    blocked = _mapping(contract, "source_blocked_signals")
    no_reference = _mapping(contract, "official_reference_unavailable")
    overrides = set(blocked) | set(no_reference)
    unknown = sorted(overrides - names)
    overlap = sorted(set(blocked) & set(no_reference))
    if unknown or overlap:
        raise FeasibilityError(
            f"override inválido: desconocidos={unknown}, solapados={overlap}"
        )

    filtered_reaudit = reaudit.loc[reaudit["signal"].astype(str).isin(names)].copy()
    if filtered_reaudit["signal"].duplicated().any() or len(filtered_reaudit) != target_count:
        raise FeasibilityError("La reauditoría no reconcilia una fila única para cada señal objetivo")

    merged = acquisition.copy()
    merged["signal"] = merged["signal"].astype(str)
    merged = merged.merge(
        filtered_reaudit[
            [
                "signal",
                "strict_historical_classification",
                "primary_free_sources",
                "source_checked_at",
            ]
        ],
        on="signal",
        how="left",
        validate="one_to_one",
    )
    merged["current_value_calculated"] = _as_bool(
        merged["current_value_calculated"]
    )
    merged["strict_score_eligible"] = False
    merged["feasibility_class"] = "unproved"
    merged["classification_reason"] = (
        "source_equivalence_and_stock_level_fidelity_not_demonstrated"
    )
    for signal, reason in blocked.items():
        mask = merged["signal"].eq(signal)
        merged.loc[mask, "feasibility_class"] = "blocked_source"
        merged.loc[mask, "classification_reason"] = reason
    for signal, reason in no_reference.items():
        mask = merged["signal"].eq(signal)
        merged.loc[mask, "feasibility_class"] = "not_evaluable_reference"
        merged.loc[mask, "classification_reason"] = reason

    merged = merged.rename(
        columns={
            "status": "current_status",
            "strict_historical_classification": "original_input_class",
            "primary_free_sources": "proposed_free_sources",
        }
    )
    result = merged.loc[:, REGISTER_COLUMNS].sort_values("signal").reset_index(drop=True)

    expected_raw = contract.get("expected_classes")
    if not isinstance(expected_raw, Mapping):
        raise FeasibilityError("El contrato necesita expected_classes")
    expected = {
        str(key): int(value)
        for key, value in expected_raw.items()
        if str(key) != "approved"
    }
    observed = result["feasibility_class"].value_counts().to_dict()
    if observed != expected or int(contract["expected_classes"].get("approved", -1)) != 0:
        raise FeasibilityError(
            f"Deriva en clases de viabilidad: esperado={expected}, observado={observed}"
        )
    return result


def summarize_feasibility(register: pd.DataFrame) -> dict[str, object]:
    """Return counts that never conflate calculation with strict approval."""

    missing = set(REGISTER_COLUMNS) - set(register.columns)
    if missing:
        raise FeasibilityError(f"Registro incompleto: {sorted(missing)}")
    classes = register["feasibility_class"].value_counts().to_dict()
    strict = _as_bool(register["strict_score_eligible"])
    calculated = _as_bool(register["current_value_calculated"])
    return {
        "target_count": int(len(register)),
        "strictly_approved": int(strict.sum()),
        "previously_calculated_non_strict": int((calculated & ~strict).sum()),
        "feasibility_classes": {str(key): int(value) for key, value in classes.items()},
        "identity_gate_status": "not_run",
    }


__all__ = [
    "FeasibilityError",
    "REGISTER_COLUMNS",
    "build_feasibility_register",
    "summarize_feasibility",
]
