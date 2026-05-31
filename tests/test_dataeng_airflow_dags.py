"""Tests for aurora.dataeng.airflow_dags."""
from __future__ import annotations

import os

import pytest

from aurora.dataeng.airflow_dags import (
    AirflowConfig,
    AirflowDAGGenerator,
    TaskSpec,
)


@pytest.fixture
def gen() -> AirflowDAGGenerator:
    return AirflowDAGGenerator(AirflowConfig(dag_id="qf_test"))


def test_render_includes_dag_id(gen: AirflowDAGGenerator):
    src = gen.render([TaskSpec(task_id="t1", bash_command="echo hi")])
    assert "dag_id='qf_test'" in src
    assert "BashOperator" in src


def test_render_emits_dependencies(gen: AirflowDAGGenerator):
    tasks = [
        TaskSpec(task_id="extract", bash_command="echo extract"),
        TaskSpec(task_id="load", bash_command="echo load",
                 upstream=("extract",)),
    ]
    src = gen.render(tasks)
    assert "extract >> load" in src


def test_render_rejects_unknown_upstream(gen: AirflowDAGGenerator):
    tasks = [TaskSpec(task_id="t", bash_command="x", upstream=("ghost",))]
    with pytest.raises(ValueError):
        gen.render(tasks)


def test_render_rejects_invalid_task_id(gen: AirflowDAGGenerator):
    with pytest.raises(ValueError):
        gen.render([TaskSpec(task_id="bad-id", bash_command="x")])


def test_write_creates_file(gen: AirflowDAGGenerator, tmp_path):
    path = gen.write([TaskSpec(task_id="t1", bash_command="echo")],
                     str(tmp_path))
    assert os.path.isfile(path)
    assert path.endswith("qf_test.py")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "dag_id='qf_test'" in content
