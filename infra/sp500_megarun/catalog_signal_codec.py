"""Exact compact representation for ternary catalog signals."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EncodedSignalsV1:
    payload: np.ndarray
    logical_shape: tuple[int, ...]
    bit_packed: bool


def _checked(values: np.ndarray) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=np.int8)
    if result.ndim < 1 or not np.isin(result, (-1, 0, 1)).all():
        raise ValueError("CATALOG_SIGNAL_VALUES_INVALID")
    return result


def encode_signals(values: np.ndarray, *, bit_packed: bool = False) -> EncodedSignalsV1:
    checked = _checked(values)
    if not bit_packed:
        return EncodedSignalsV1(checked.copy(), checked.shape, False)
    mapped = (checked.reshape(-1).astype(np.uint8) + 1).astype(np.uint8)
    padding = (-mapped.size) % 4
    if padding:
        mapped = np.pad(mapped, (0, padding), constant_values=1)
    groups = mapped.reshape(-1, 4)
    payload = (
        groups[:, 0]
        | (groups[:, 1] << 2)
        | (groups[:, 2] << 4)
        | (groups[:, 3] << 6)
    ).astype(np.uint8)
    return EncodedSignalsV1(payload, checked.shape, True)


def decode_signals(encoded: EncodedSignalsV1) -> np.ndarray:
    if not encoded.bit_packed:
        result = _checked(encoded.payload)
        if result.shape != encoded.logical_shape:
            raise ValueError("CATALOG_SIGNAL_SHAPE_INVALID")
        return result.copy()
    payload = np.asarray(encoded.payload, dtype=np.uint8).reshape(-1)
    unpacked = np.column_stack(
        [
            payload & 0b11,
            (payload >> 2) & 0b11,
            (payload >> 4) & 0b11,
            (payload >> 6) & 0b11,
        ]
    ).reshape(-1)
    size = int(np.prod(encoded.logical_shape, dtype=np.int64))
    unpacked = unpacked[:size]
    if np.any(unpacked > 2):
        raise ValueError("CATALOG_SIGNAL_PAYLOAD_INVALID")
    return (unpacked.astype(np.int8) - 1).reshape(encoded.logical_shape)


__all__ = ["EncodedSignalsV1", "decode_signals", "encode_signals"]
