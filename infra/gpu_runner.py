"""GPU runner for ML training/inference.

Detects CUDA via ``torch`` (lazy import). Runs a callable on GPU when
available; falls back to CPU otherwise. Exposes a single ``run`` entry
point that converts numpy arrays / scalars / lists to torch tensors,
moves them to the resolved device, calls the function, and moves the
result back to CPU as numpy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class GPUConfig:
    """Static config for :class:`GPURunner`.

    Attributes:
        device: ``"auto"``, ``"cuda"``, ``"cpu"`` or explicit ``"cuda:0"``.
        force_cpu: when True, ignore CUDA even if available.
        dtype: torch dtype string (``"float32"`` / ``"float64"`` / ``"float16"``).
    """
    device: str = "auto"
    force_cpu: bool = False
    dtype: str = "float32"


class GPURunner:
    """Run a function on GPU when CUDA available, else CPU.

    The wrapper is intentionally torch-centric: ML modules in this
    project use torch and benefit from a single ``device`` resolver.
    Non-torch callers can still use :meth:`is_cuda_available` to gate
    GPU code paths without forcing a torch import.
    """

    def __init__(self, config: Optional[GPUConfig] = None) -> None:
        self.config = config or GPUConfig()
        self._resolved_device: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @staticmethod
    def is_cuda_available() -> bool:
        """True if torch is importable and reports a CUDA device."""
        try:
            import torch  # type: ignore
        except ImportError:
            return False
        try:
            return bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001 - defensive against torch oddities
            return False

    @property
    def device(self) -> str:
        """Resolved device string (e.g. ``"cuda:0"`` or ``"cpu"``)."""
        return self._resolve_device()

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Call ``fn`` with args. If torch installed, set default device.

        ``fn`` is responsible for tensor placement; this wrapper just
        guarantees a device context is active and torch.set_default_dtype
        matches the configured precision.
        """
        device = self._resolve_device()
        try:
            import torch  # type: ignore
        except ImportError:
            return fn(*args, **kwargs)
        prev_dtype = torch.get_default_dtype()
        target_dtype = getattr(torch, self.config.dtype, torch.float32)
        torch.set_default_dtype(target_dtype)
        try:
            with torch.device(device):  # type: ignore[attr-defined]
                return fn(*args, **kwargs)
        except (TypeError, AttributeError):  # pragma: no cover - older torch
            # ``torch.device`` context manager added in 1.13. Fall back to
            # set_default_device when context manager not supported.
            try:
                torch.set_default_device(device)  # type: ignore[attr-defined]
            except AttributeError:
                pass
            return fn(*args, **kwargs)
        finally:
            torch.set_default_dtype(prev_dtype)

    def to_device(self, tensor_like: Any) -> Any:
        """Move ``tensor_like`` to the resolved device when torch is present."""
        try:
            import torch  # type: ignore
        except ImportError:
            return tensor_like
        device = self._resolve_device()
        if isinstance(tensor_like, torch.Tensor):
            return tensor_like.to(device)
        try:
            return torch.as_tensor(tensor_like).to(device)
        except Exception:  # noqa: BLE001 - non-tensor passthrough
            return tensor_like

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _resolve_device(self) -> str:
        if self._resolved_device is not None:
            return self._resolved_device
        if self.config.force_cpu:
            self._resolved_device = "cpu"
            return self._resolved_device
        if self.config.device == "cpu":
            self._resolved_device = "cpu"
        elif self.config.device.startswith("cuda"):
            self._resolved_device = (
                self.config.device if self.is_cuda_available() else "cpu"
            )
        else:  # auto
            self._resolved_device = "cuda" if self.is_cuda_available() else "cpu"
        return self._resolved_device
