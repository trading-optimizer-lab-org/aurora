"""Unprivileged sender tests: no Windows authorization or live run claims."""

import json
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun.catalog_chat_intent import CatalogChatIntentV1
from aurora.infra.sp500_megarun.catalog_chat_sender import enqueue_chat_intent

INTENT = CatalogChatIntentV1(
    schema_version="1", campaign_key="sp500-optimized-catalog-v1",
    intent_id="018f47a2-6e91-4c34-8000-000000000001",
)


def test_sender_exclusively_creates_one_closed_input(tmp_path: Path) -> None:
    inbox = tmp_path / "chat-inbox"
    inbox.mkdir()
    first = enqueue_chat_intent(broker_root=tmp_path, intent=INTENT)
    before = next(inbox.iterdir()).read_bytes()
    second = enqueue_chat_intent(broker_root=tmp_path, intent=INTENT)
    assert first == second == {"status": "pending", "intent_id": INTENT.intent_id, "campaign_key": INTENT.campaign_key}
    assert len(list(inbox.iterdir())) == 1
    assert next(inbox.iterdir()).read_bytes() == before
    assert json.loads(before) == INTENT.model_dump(mode="json")


def test_sender_does_not_overwrite_conflicting_input(tmp_path: Path) -> None:
    inbox = tmp_path / "chat-inbox"
    inbox.mkdir()
    target = inbox / f"{INTENT.intent_id}.intent.json"
    target.write_bytes(b"interrupted-or-invalid")
    with pytest.raises(ValueError, match="CHAT_INPUT_CONFLICT"):
        enqueue_chat_intent(broker_root=tmp_path, intent=INTENT)
    assert target.read_bytes() == b"interrupted-or-invalid"


def test_sender_does_not_create_uninstalled_directories(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        enqueue_chat_intent(broker_root=tmp_path, intent=INTENT)
    assert not list(tmp_path.iterdir())


def test_sender_uses_accessible_inbox_to_validate_private_parent_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inbox = tmp_path / "chat-inbox"
    inbox.mkdir()
    resolve = Path.resolve

    def resolve_with_private_parent(path: Path, *, strict: bool = False) -> Path:
        if path == tmp_path:
            raise PermissionError("private parent cannot be opened by sender")
        return resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_with_private_parent)
    result = enqueue_chat_intent(broker_root=tmp_path, intent=INTENT)
    assert result == {"status": "pending", "intent_id": INTENT.intent_id, "campaign_key": INTENT.campaign_key}
    assert json.loads((inbox / f"{INTENT.intent_id}.intent.json").read_bytes()) == {
        "schema_version": "1", "campaign_key": "sp500-optimized-catalog-v1",
        "intent_id": "018f47a2-6e91-4c34-8000-000000000001",
    }
    assert len(list(inbox.iterdir())) == 1


@pytest.mark.parametrize("defect", ["redirected_ancestor", "inaccessible_inbox"])
def test_sender_rejects_unverified_full_inbox_path_before_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str) -> None:
    inbox = tmp_path / "chat-inbox"
    inbox.mkdir()
    resolve = Path.resolve

    def invalid_inbox(path: Path, *, strict: bool = False) -> Path:
        if path == inbox:
            if defect == "inaccessible_inbox":
                raise PermissionError("inbox cannot be opened")
            return tmp_path / "redirected" / "chat-inbox"
        return resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", invalid_inbox)
    with pytest.raises(ValueError, match="CHAT_ENTRY_NOT_INSTALLED_OR_UNSAFE"):
        enqueue_chat_intent(broker_root=tmp_path, intent=INTENT)
    assert not list(inbox.iterdir())


def test_sender_revalidates_model_before_using_identifier(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        enqueue_chat_intent(broker_root=tmp_path, intent=INTENT.model_copy(update={"intent_id": "invalid"}))
    assert not list(tmp_path.iterdir())


def test_public_sender_uses_fixed_root_and_only_campaign_and_intent(monkeypatch, capsys):
    from scripts import submit_catalog_chat_intent as cli
    import sys

    seen = []
    def capture(**kwargs):
        seen.append(kwargs)
        return {"status": "pending", "intent_id": INTENT.intent_id, "campaign_key": INTENT.campaign_key}
    monkeypatch.setattr(cli, "enqueue_chat_intent", capture)
    monkeypatch.setattr(sys, "argv", ["sender", "--campaign-key", INTENT.campaign_key, "--intent-id", INTENT.intent_id])
    assert cli.main() == 0
    assert seen == [{"broker_root": Path("C:/ProgramData/AURORA/CatalogRequester"), "intent": INTENT.model_dump(mode="json")}]
    assert json.loads(capsys.readouterr().out)["status"] == "pending"


@pytest.mark.parametrize("extra", ["--command", "--root", "--workflow", "--token"])
def test_public_sender_rejects_execution_options(monkeypatch, extra):
    from scripts import submit_catalog_chat_intent as cli
    import sys

    monkeypatch.setattr(cli, "enqueue_chat_intent", lambda **kw: pytest.fail("invalid input must not enqueue"))
    monkeypatch.setattr(sys, "argv", ["sender", "--campaign-key", INTENT.campaign_key, "--intent-id", INTENT.intent_id, extra, "value"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
