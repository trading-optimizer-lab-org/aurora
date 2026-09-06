"""Check the installed entry point opts into the tested nonblocking spool flow."""

import ast
from pathlib import Path
import pytest

from aurora.infra.sp500_megarun.catalog_requester_cli import _parser


def test_cli_accepts_stable_intention_without_path_or_command_options() -> None:
    args = _parser().parse_args([
        "--campaign-key", "sp500-optimized-catalog-v1",
        "--intent-id", "ca5e1c3a-b049-4db5-98cb-af847454ed34",
    ])
    assert args.intent_id == "ca5e1c3a-b049-4db5-98cb-af847454ed34"
    assert vars(args).keys() == {"campaign_key", "intent_id", "serve_chat"}
    assert args.serve_chat is False


@pytest.mark.parametrize("option", ["--command", "--state-dir", "--draft", "--token"])
def test_cli_rejects_sender_control_of_execution(option: str) -> None:
    with pytest.raises(SystemExit) as exc:
        _parser().parse_args(["--campaign-key", "sp500-optimized-catalog-v1", option, "value"])
    assert exc.value.code == 2


def test_service_mode_is_distinct_from_a_campaign_request() -> None:
    args = _parser().parse_args(["--serve-chat"])
    assert args.serve_chat is True
    assert args.campaign_key is None
    with pytest.raises(SystemExit):
        _parser().parse_args(["--serve-chat", "--campaign-key", "sp500-optimized-catalog-v1"])


def test_service_is_entered_only_after_existing_application_verification() -> None:
    source = Path(__file__).parents[1] / "infra/sp500_megarun/catalog_requester_cli.py"
    main = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == "main")
    verification = next(index for index, node in enumerate(main.body) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "verify_installed_requester_application")
    service_mode = next(index for index, node in enumerate(main.body) if isinstance(node, ast.If) and isinstance(node.test, ast.Attribute) and node.test.attr == "serve_chat")
    assert service_mode > verification


def test_installed_entry_point_does_not_wait_for_broker_refresh() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "infra/sp500_megarun/catalog_requester_cli.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    submissions = [
        node for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "submit_registered_catalog_campaign"
    ]
    assert len(submissions) == 1
    wait_options = [
        option.value for option in submissions[0].keywords
        if option.arg == "_wait_for_refresh"
    ]
    assert len(wait_options) == 1, "Installed CLI must not use the 90-second wait default"
    assert isinstance(wait_options[0], ast.Constant)
    assert wait_options[0].value is False
