"""Autonomous, train-only SPY long/short discovery campaign."""

from .contracts import (
    LOCKED_START,
    TRAIN_END,
    VALIDATION_END,
    VALIDATION_START,
    VALIDATION_ACK,
)

__all__ = [
    "LOCKED_START",
    "TRAIN_END",
    "VALIDATION_END",
    "VALIDATION_START",
    "VALIDATION_ACK",
]
