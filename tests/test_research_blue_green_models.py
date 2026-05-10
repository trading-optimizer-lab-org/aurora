"""Tests for quantforge.research.blue_green_models."""
from __future__ import annotations
import pytest

from aurora.research.blue_green_models import (
    BlueGreenModelDeployer,
    DeploymentReport,
)


def test_construction_default_active():
    d = BlueGreenModelDeployer()
    assert d.active == "blue"
    assert d.staging == "green"


def test_deploy_and_predict():
    d = BlueGreenModelDeployer()
    d.deploy("blue", "v1", lambda x: x + 1)
    assert d.predict(10) == 11
    rep = d.report()
    assert isinstance(rep, DeploymentReport)
    assert rep.blue_version == "v1"
    assert rep.green_version is None


def test_switch_atomic():
    d = BlueGreenModelDeployer()
    d.deploy("blue", "v1", lambda x: x + 1)
    d.deploy("green", "v2", lambda x: x * 2)
    assert d.predict(3) == 4
    new_active = d.switch()
    assert new_active == "green"
    assert d.predict(3) == 6
    rep = d.report()
    assert rep.n_switches == 1


def test_rollback():
    d = BlueGreenModelDeployer()
    d.deploy("blue", "v1", lambda x: x + 1)
    d.deploy("green", "v2", lambda x: x * 2)
    d.switch()
    d.rollback()
    assert d.active == "blue"
    assert d.predict(10) == 11
    assert d.report().n_switches == 2


def test_switch_without_staging_raises():
    d = BlueGreenModelDeployer()
    d.deploy("blue", "v1", lambda x: x + 1)
    with pytest.raises(RuntimeError):
        d.switch()


def test_predict_without_model_raises():
    d = BlueGreenModelDeployer()
    with pytest.raises(RuntimeError):
        d.predict(1)


def test_predict_staging():
    d = BlueGreenModelDeployer()
    d.deploy("blue", "v1", lambda x: x + 1)
    d.deploy("green", "v2", lambda x: x * 2)
    assert d.predict_staging(5) == 10
    rep = d.report()
    assert rep.n_predictions["green"] == 1


def test_invalid_color_rejected():
    d = BlueGreenModelDeployer()
    with pytest.raises(ValueError):
        d.deploy("red", "v1", lambda x: x)


def test_empty_version_rejected():
    d = BlueGreenModelDeployer()
    with pytest.raises(ValueError):
        d.deploy("blue", "", lambda x: x)


def test_non_callable_predict_fn_rejected():
    d = BlueGreenModelDeployer()
    with pytest.raises(TypeError):
        d.deploy("blue", "v1", 42)
