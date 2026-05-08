"""Blue/green model deployer.

Hold two model versions: ``blue`` (live) and ``green`` (staged). The
deployer routes ``predict`` calls to the active color and supports an
atomic ``switch`` once the staged model is healthy. ``rollback`` is the
mirror operation.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Literal


Color = Literal["blue", "green"]


@dataclass
class DeploymentReport:
    active: Color
    blue_version: str | None
    green_version: str | None
    n_switches: int
    n_predictions: dict[str, int]


class _ModelSlot:
    def __init__(self, version: str, predict_fn: Callable[[Any], Any]):
        self.version = version
        self.predict_fn = predict_fn
        self.n_predictions = 0


class BlueGreenModelDeployer:
    """Atomic switch between two model versions."""

    def __init__(self):
        self._slots: dict[Color, _ModelSlot | None] = {
            "blue": None, "green": None,
        }
        self._active: Color = "blue"
        self._n_switches = 0

    @property
    def active(self) -> Color:
        return self._active

    @property
    def staging(self) -> Color:
        return "green" if self._active == "blue" else "blue"

    def deploy(self, color: Color, version: str,
               predict_fn: Callable[[Any], Any]) -> None:
        if color not in ("blue", "green"):
            raise ValueError(f"unknown color: {color!r}")
        if not version:
            raise ValueError("version must be non-empty")
        if not callable(predict_fn):
            raise TypeError("predict_fn must be callable")
        self._slots[color] = _ModelSlot(version=version, predict_fn=predict_fn)

    def predict(self, x: Any) -> Any:
        slot = self._slots[self._active]
        if slot is None:
            raise RuntimeError(f"active slot {self._active!r} has no model")
        slot.n_predictions += 1
        return slot.predict_fn(x)

    def predict_staging(self, x: Any) -> Any:
        slot = self._slots[self.staging]
        if slot is None:
            raise RuntimeError(f"staging slot {self.staging!r} has no model")
        slot.n_predictions += 1
        return slot.predict_fn(x)

    def switch(self) -> Color:
        """Atomically promote staging -> active. Requires a model in staging."""
        target = self.staging
        if self._slots[target] is None:
            raise RuntimeError(f"cannot switch: {target!r} slot empty")
        self._active = target
        self._n_switches += 1
        return self._active

    def rollback(self) -> Color:
        """Mirror of switch: flip back to the other slot if loaded."""
        target = self.staging
        if self._slots[target] is None:
            raise RuntimeError(f"cannot rollback: {target!r} slot empty")
        self._active = target
        self._n_switches += 1
        return self._active

    def report(self) -> DeploymentReport:
        blue = self._slots["blue"]
        green = self._slots["green"]
        return DeploymentReport(
            active=self._active,
            blue_version=blue.version if blue else None,
            green_version=green.version if green else None,
            n_switches=self._n_switches,
            n_predictions={
                "blue": blue.n_predictions if blue else 0,
                "green": green.n_predictions if green else 0,
            },
        )
