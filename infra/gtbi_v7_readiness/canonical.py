"""RFC 8785-compatible canonical JSON and GTBI domain-separated hashing.

The bootstrap quality records deliberately use a small JSON type surface, but
this serializer also implements the RFC 8785 number formatting boundaries so
the same primitive can be reused by later V7 contracts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SAFE_INTEGER_MAX = 9_007_199_254_740_991
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class CanonicalizationError(ValueError):
    """Raised when a value has no unambiguous canonical JSON representation."""


def _validate_string(value: str) -> None:
    for character in value:
        codepoint = ord(character)
        if 0xD800 <= codepoint <= 0xDFFF:
            raise CanonicalizationError("lone UTF-16 surrogate is not valid JSON text")


def _utf16_sort_key(value: str) -> bytes:
    _validate_string(value)
    return value.encode("utf-16-be")


def _json_string(value: str) -> str:
    _validate_string(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _fixed_from_shortest(shortest: str) -> str:
    """Render a shortest decimal token without exponent notation."""
    mantissa, exponent_text = shortest.lower().split("e")
    exponent = int(exponent_text)
    sign = ""
    if mantissa.startswith("-"):
        sign = "-"
        mantissa = mantissa[1:]
    integer, dot, fraction = mantissa.partition(".")
    digits = integer + fraction
    decimal_position = len(integer) + exponent
    if decimal_position <= 0:
        rendered = "0." + ("0" * -decimal_position) + digits
    elif decimal_position >= len(digits):
        rendered = digits + ("0" * (decimal_position - len(digits)))
    else:
        rendered = digits[:decimal_position] + "." + digits[decimal_position:]
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return sign + rendered


def _scientific_from_shortest(shortest: str) -> str:
    """Normalize a shortest decimal token to ECMAScript exponent spelling."""
    value = shortest.lower()
    if "e" not in value:
        sign = ""
        if value.startswith("-"):
            sign = "-"
            value = value[1:]
        integer, dot, fraction = value.partition(".")
        digits = (integer + fraction).lstrip("0")
        if not digits:
            return "0"
        if integer.lstrip("0"):
            exponent = len(integer.lstrip("0")) - 1
        else:
            leading_fraction_zeros = len(fraction) - len(fraction.lstrip("0"))
            exponent = -(leading_fraction_zeros + 1)
        coefficient = digits[0]
        tail = digits[1:].rstrip("0")
        if tail:
            coefficient += "." + tail
        return f"{sign}{coefficient}e{exponent:+d}"
    mantissa, exponent_text = value.split("e")
    exponent = int(exponent_text)
    if mantissa.endswith(".0"):
        mantissa = mantissa[:-2]
    return f"{mantissa}e{exponent:+d}"


def _float_token(value: float) -> str:
    if not math.isfinite(value):
        raise CanonicalizationError("NaN and infinity are not JSON numbers")
    if value == 0.0:
        return "0"
    shortest = repr(value).lower()
    absolute = abs(value)
    if 1e-6 <= absolute < 1e21:
        token = _fixed_from_shortest(shortest) if "e" in shortest else shortest
        if token.endswith(".0"):
            token = token[:-2]
        return token
    return _scientific_from_shortest(shortest)


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if not -SAFE_INTEGER_MAX <= value <= SAFE_INTEGER_MAX:
            raise CanonicalizationError(
                "integer is outside the RFC 8785 interoperable range"
            )
        return str(value)
    if isinstance(value, float):
        return _float_token(value)
    if isinstance(value, str):
        return _json_string(value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalizationError("JSON object keys must be strings")
        members = []
        for key in sorted(value, key=_utf16_sort_key):
            members.append(f"{_json_string(key)}:{_serialize(value[key])}")
        return "{" + ",".join(members) + "}"
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    raise CanonicalizationError(
        f"unsupported canonical JSON type: {type(value).__name__}"
    )


def canonical_text(value: Any) -> str:
    """Return canonical JSON text without a final newline."""
    return _serialize(value)


def canonical_bytes(value: Any) -> bytes:
    """Return canonical UTF-8 JSON bytes without a BOM or final newline."""
    return canonical_text(value).encode("utf-8")


def raw_sha256(data_or_path: bytes | bytearray | memoryview | str | Path) -> str:
    """Return a lower-case, algorithm-prefixed SHA-256 digest."""
    if isinstance(data_or_path, (str, Path)):
        data = Path(data_or_path).read_bytes()
    else:
        data = bytes(data_or_path)
    return "sha256:" + hashlib.sha256(data).hexdigest()


def git_blob_id(data: bytes) -> str:
    """Return the Git SHA-1 blob identity for exact bytes."""
    preimage = f"blob {len(data)}\0".encode("ascii") + data
    return hashlib.sha1(preimage, usedforsecurity=False).hexdigest()


def domain_digest(
    domain: str,
    payload: Any,
    *,
    omit_top_level_fields: Sequence[str] = (),
) -> str:
    """Hash a typed payload using the frozen GTBI domain-separation formula."""
    if not domain or "\x00" in domain:
        raise CanonicalizationError("hash domain must be non-empty and contain no NUL")
    if omit_top_level_fields:
        if not isinstance(payload, Mapping):
            raise CanonicalizationError("digest field omission requires an object")
        payload = {
            key: value
            for key, value in payload.items()
            if key not in set(omit_top_level_fields)
        }
    digest = hashlib.sha256(
        domain.encode("utf-8") + b"\x00" + canonical_bytes(payload)
    ).hexdigest()
    return "sha256:" + digest


def require_digest(value: str) -> str:
    """Validate and return a canonical SHA-256 digest string."""
    if not _DIGEST_RE.fullmatch(value):
        raise ValueError("expected sha256:<64 lowercase hex>")
    return value
