from pathlib import Path
from types import SimpleNamespace

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml


@pytest.mark.parametrize("matrix_count,result,expected", [
    ("0", "skipped", True), ("1", "skipped", False),
    ("1", "success", True), ("1", "failure", True),
])
def test_initial_reconcile_preserves_zero_pending_and_failure_routes(matrix_count, result, expected):
    workflow = load_github_yaml(Path(__file__).parents[1] / ".github/workflows/catalog-optimized-run.yml")
    expression = workflow["jobs"]["reconcile_wave_0"]["if"].strip()[3:-2].strip()
    expression = expression.replace("!cancelled()", "True").replace("&&", " and ").replace("||", " or ")
    expression = " ".join(expression.split())
    needs = SimpleNamespace(
        engine_verify_sealed_plan=SimpleNamespace(result="success", outputs=SimpleNamespace(
            reduction_only="false", recipe_matrix_a_count=matrix_count,
            recipe_matrix_b_count="0", recipe_matrix_c_count="0")),
        verify_component_store=SimpleNamespace(result="success"),
        evaluate_a=SimpleNamespace(result=result),
        evaluate_b=SimpleNamespace(result="skipped"), evaluate_c=SimpleNamespace(result="skipped"),
    )
    assert eval(expression, {"__builtins__": {}}, {
        "needs": needs, "inputs": SimpleNamespace(execution_mode="run"), "always": lambda: True,
    }) is expected
