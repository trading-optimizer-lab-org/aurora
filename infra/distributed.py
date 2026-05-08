"""Distributed backtester wrapper.

Two backends are supported via lazy import:

- ``ray``  : ``ray.remote`` task graph (default; preferred when available)
- ``dask`` : ``dask.delayed`` graph

The wrapper falls back to a sequential in-process map when neither SDK is
installed, so unit tests run offline with no extra dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional


@dataclass
class DistributedConfig:
    """Static config for :class:`DistributedBacktester`.

    Attributes:
        backend: ``"ray"``, ``"dask"`` or ``"local"``. ``"auto"`` picks the
            first available backend in that order.
        n_workers: hint passed to the cluster init (None = backend default).
        address: optional cluster address for ``ray.init`` / dask scheduler.
    """
    backend: str = "auto"
    n_workers: Optional[int] = None
    address: Optional[str] = None


class DistributedBacktester:
    """Distribute a backtest function across many parameter sets.

    Usage::

        runner = DistributedBacktester()
        results = runner.map(backtest_fn, [params_a, params_b, ...])
    """

    _VALID_BACKENDS = {"auto", "ray", "dask", "local"}

    def __init__(self, config: Optional[DistributedConfig] = None) -> None:
        self.config = config or DistributedConfig()
        if self.config.backend not in self._VALID_BACKENDS:
            raise ValueError(
                f"backend must be one of {sorted(self._VALID_BACKENDS)}, "
                f"got {self.config.backend!r}"
            )
        self._resolved_backend: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def map(
        self,
        fn: Callable[[Any], Any],
        params_list: Iterable[Any],
    ) -> list:
        """Apply ``fn`` to every entry in ``params_list``. Returns results."""
        params_list = list(params_list)
        if not params_list:
            return []
        backend = self._resolve_backend()
        if backend == "ray":
            return self._map_ray(fn, params_list)
        if backend == "dask":
            return self._map_dask(fn, params_list)
        return self._map_local(fn, params_list)

    @property
    def resolved_backend(self) -> str:
        """The backend actually in use after resolution."""
        return self._resolve_backend()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _resolve_backend(self) -> str:
        if self._resolved_backend is not None:
            return self._resolved_backend
        requested = self.config.backend
        if requested == "ray":
            self._resolved_backend = "ray" if self._has_ray() else "local"
        elif requested == "dask":
            self._resolved_backend = "dask" if self._has_dask() else "local"
        elif requested == "auto":
            if self._has_ray():
                self._resolved_backend = "ray"
            elif self._has_dask():
                self._resolved_backend = "dask"
            else:
                self._resolved_backend = "local"
        else:
            self._resolved_backend = "local"
        return self._resolved_backend

    @staticmethod
    def _has_ray() -> bool:
        try:
            import ray  # type: ignore  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def _has_dask() -> bool:
        try:
            import dask  # type: ignore  # noqa: F401
        except ImportError:
            return False
        return True

    def _map_local(
        self,
        fn: Callable[[Any], Any],
        params_list: list,
    ) -> list:
        return [fn(p) for p in params_list]

    def _map_ray(
        self,
        fn: Callable[[Any], Any],
        params_list: list,
    ) -> list:  # pragma: no cover - integration path
        import ray  # type: ignore

        if not ray.is_initialized():
            kwargs: dict[str, Any] = {}
            if self.config.address is not None:
                kwargs["address"] = self.config.address
            if self.config.n_workers is not None:
                kwargs["num_cpus"] = int(self.config.n_workers)
            ray.init(ignore_reinit_error=True, **kwargs)
        remote_fn = ray.remote(fn)
        futures = [remote_fn.remote(p) for p in params_list]
        return list(ray.get(futures))

    def _map_dask(
        self,
        fn: Callable[[Any], Any],
        params_list: list,
    ) -> list:  # pragma: no cover - integration path
        from dask import compute, delayed  # type: ignore

        tasks = [delayed(fn)(p) for p in params_list]
        return list(compute(*tasks))
