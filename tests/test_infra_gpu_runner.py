"""Tests for aurora.infra.gpu_runner.GPURunner."""
from __future__ import annotations

from unittest.mock import patch

from aurora.infra.gpu_runner import GPURunner, GPUConfig


def test_force_cpu_resolves_cpu_regardless_of_cuda():
    runner = GPURunner(GPUConfig(force_cpu=True))
    assert runner.device == "cpu"


def test_auto_resolves_cpu_when_cuda_unavailable():
    with patch.object(GPURunner, "is_cuda_available", return_value=False):
        runner = GPURunner(GPUConfig(device="auto"))
        assert runner.device == "cpu"


def test_auto_resolves_cuda_when_available():
    with patch.object(GPURunner, "is_cuda_available", return_value=True):
        runner = GPURunner(GPUConfig(device="auto"))
        assert runner.device == "cuda"


def test_explicit_cuda_falls_back_to_cpu_when_unavailable():
    with patch.object(GPURunner, "is_cuda_available", return_value=False):
        runner = GPURunner(GPUConfig(device="cuda:0"))
        assert runner.device == "cpu"


def test_run_executes_function_without_torch(monkeypatch):
    # Simulate torch import failure inside .run by patching builtins.__import__.
    import builtins

    real_import = builtins.__import__

    def raising_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("no torch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", raising_import)
    runner = GPURunner(GPUConfig(force_cpu=True))
    assert runner.run(lambda a, b: a + b, 2, 3) == 5


def test_to_device_passthrough_when_torch_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def raising_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("no torch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", raising_import)
    runner = GPURunner(GPUConfig(force_cpu=True))
    assert runner.to_device([1, 2, 3]) == [1, 2, 3]


def test_is_cuda_available_returns_bool():
    # Real call; just ensures no crash and returns a bool.
    assert isinstance(GPURunner.is_cuda_available(), bool)
