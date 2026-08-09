"""Selective recovery helpers for large GitHub Actions ZIP artifacts."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from io import RawIOBase
from zipfile import ZipFile


class HttpRangeReader(RawIOBase):
    """Expose an exact byte-range callback as a seekable binary reader."""

    def __init__(
        self,
        size: int,
        fetch_range: Callable[[int, int], bytes],
    ) -> None:
        super().__init__()
        if size < 0:
            raise ValueError("range reader size cannot be negative")
        self._size = int(size)
        self._fetch_range = fetch_range
        self._position = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            position = offset
        elif whence == 1:
            position = self._position + offset
        elif whence == 2:
            position = self._size + offset
        else:
            raise ValueError(f"unsupported seek mode: {whence}")
        if position < 0:
            raise ValueError("negative seek position")
        self._position = int(position)
        return self._position

    def read(self, size: int = -1) -> bytes:
        if self._position >= self._size or size == 0:
            return b""
        start = self._position
        end = self._size - 1 if size is None or size < 0 else min(
            self._size - 1, start + size - 1
        )
        payload = self._fetch_range(start, end)
        expected = end - start + 1
        if len(payload) != expected:
            raise OSError(
                f"range response length mismatch: expected={expected}:actual={len(payload)}"
            )
        self._position += len(payload)
        return payload


def read_zip_members(
    reader: HttpRangeReader,
    member_names: Iterable[str],
) -> dict[str, bytes]:
    """Read exact ZIP members and reject missing or duplicate archive names."""

    requested = tuple(member_names)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("requested ZIP members must be unique and non-empty")
    with ZipFile(reader) as archive:
        names = archive.namelist()
        for member_name in requested:
            if names.count(member_name) != 1:
                raise ValueError(
                    f"expected one ZIP member {member_name}, found {names.count(member_name)}"
                )
        return {member_name: archive.read(member_name) for member_name in requested}


__all__ = ["HttpRangeReader", "read_zip_members"]
