from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import aurora.infra.sp500_megarun.catalog_chat_intent as chat_intent
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogRunIntentDraftV1,
    canonical_model_bytes,
)
from aurora.infra.sp500_megarun.catalog_chat_intent import (
    CatalogChatIntentBindingV1,
    CatalogChatIntentV1,
    load_or_bind_chat_intent,
    parse_chat_intent,
)


CAMPAIGN = "sp500-optimized-catalog-v1"
INTENT_ID = "018f47a2-6e91-4c34-8000-000000000001"
REQUEST_ID_1 = "018f47a2-6e91-7c34-8000-000000000001"
REQUEST_ID_2 = "018f47a2-6e91-7c34-8000-000000000002"


def _intent(*, campaign_key: str = CAMPAIGN, intent_id: str = INTENT_ID) -> CatalogChatIntentV1:
    return CatalogChatIntentV1(
        schema_version="1",
        campaign_key=campaign_key,
        intent_id=intent_id,
    )


def _draft(
    *, request_id: str = REQUEST_ID_1, campaign_key: str = CAMPAIGN
) -> CatalogRunIntentDraftV1:
    return CatalogRunIntentDraftV1(
        schema_version="1",
        request_id=request_id,
        campaign_key=campaign_key,
        launch_generation=1,
        launch_ticket_sha256="3" * 64,
        previous_terminal_request_sha256=None,
        campaign_definition_sha256="1" * 64,
        prompt_sha256="2" * 64,
        authorization="USER_EXPLICITLY_REQUESTED_NEW_CATALOG_RUN",
        free_resources_only=True,
        automatic_recovery=True,
        max_same_failure_count=3,
    )


def _valid_payload() -> bytes:
    return json.dumps(
        {
            "schema_version": "1",
            "campaign_key": CAMPAIGN,
            "intent_id": INTENT_ID,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def test_parse_chat_intent_accepts_the_closed_shape() -> None:
    parsed = parse_chat_intent(_valid_payload())

    assert parsed == _intent()
    assert set(parsed.model_fields) == {"schema_version", "campaign_key", "intent_id"}


def test_binding_revalidates_a_preconstructed_intent(tmp_path: Path) -> None:
    invalid = _intent().model_copy(update={"intent_id": "NOT-A-UUID"})
    with pytest.raises(ValueError, match="CHAT_INTENT_INVALID"):
        load_or_bind_chat_intent(state_dir=tmp_path, intent=invalid, resolve_draft=_draft)
    assert not list(tmp_path.iterdir())


def test_binding_revalidates_a_preconstructed_draft(tmp_path: Path) -> None:
    invalid = _draft().model_copy(update={"launch_generation": 0})
    with pytest.raises(ValueError, match="CHAT_INTENT_INVALID"):
        load_or_bind_chat_intent(state_dir=tmp_path, intent=_intent(), resolve_draft=lambda: invalid)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "payload",
    [
        b'{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        b'"intent_id":"018f47a2-6e91-4c34-8000-000000000001","extra":true}',
        b'{"schema_version":1,"campaign_key":"sp500-optimized-catalog-v1",'
        b'"intent_id":"018f47a2-6e91-4c34-8000-000000000001"}',
        b'{"schema_version":"1","campaign_key":7,'
        b'"intent_id":"018f47a2-6e91-4c34-8000-000000000001"}',
        b'{"schema_version":"1","campaign_key":"../sp500-optimized-catalog-v1",'
        b'"intent_id":"018f47a2-6e91-4c34-8000-000000000001"}',
        b'{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        b'"intent_id":"018f47a2-6e91-1c34-8000-000000000001"}',
        b'{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        b'"intent_id":"018F47A2-6E91-4C34-8000-000000000001"}',
        b'{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        b'"intent_id":"018f47a2-6e91-4c34-8000-000000000001",'
        b'"intent_id":"018f47a2-6e91-4c34-8000-000000000001"}',
        b'{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        b'"intent_id":NaN}',
        _valid_payload()[:-1],
        b'[]',
    ],
)
def test_parse_chat_intent_rejects_ambiguous_or_unsafe_payloads(payload: bytes) -> None:
    with pytest.raises(ValueError):
        parse_chat_intent(payload)


def test_parse_chat_intent_rejects_payload_over_4096_bytes() -> None:
    assert len(_valid_payload() + b" " * (4097 - len(_valid_payload()))) == 4097

    with pytest.raises(ValueError):
        parse_chat_intent(_valid_payload() + b" " * (4097 - len(_valid_payload())))


def test_parse_chat_intent_rejects_campaign_over_128_characters() -> None:
    too_long_campaign = "a" * 126 + "-v1"
    payload = json.dumps(
        {
            "schema_version": "1",
            "campaign_key": too_long_campaign,
            "intent_id": INTENT_ID,
        }
    ).encode()

    with pytest.raises(ValueError):
        parse_chat_intent(payload)


def test_load_binds_once_and_replays_without_resolving_a_new_ticket(tmp_path: Path) -> None:
    state_dir = tmp_path / "protected-state"
    state_dir.mkdir()
    intent = _intent()
    calls = 0

    def resolve_first() -> CatalogRunIntentDraftV1:
        nonlocal calls
        calls += 1
        return _draft()

    first = load_or_bind_chat_intent(
        state_dir=state_dir, intent=intent, resolve_draft=resolve_first
    )

    def resolve_changed_ticket() -> CatalogRunIntentDraftV1:
        pytest.fail("a durable replay must not resolve a changed ticket")

    replay = load_or_bind_chat_intent(
        state_dir=state_dir, intent=intent, resolve_draft=resolve_changed_ticket
    )

    assert calls == 1
    assert replay == first
    assert first.draft.request_id == REQUEST_ID_1
    assert list(state_dir.iterdir()) == [state_dir / f"{INTENT_ID}.json"]
    assert (state_dir / f"{INTENT_ID}.json").read_bytes() == canonical_model_bytes(first)


def test_existing_conflicting_campaign_fails_before_callback(tmp_path: Path) -> None:
    state_dir = tmp_path / "protected-state"
    state_dir.mkdir()
    intent = _intent()
    load_or_bind_chat_intent(
        state_dir=state_dir, intent=intent, resolve_draft=lambda: _draft()
    )

    conflicting_intent = _intent(campaign_key="sp500-other-catalog-v1")

    with pytest.raises(ValueError):
        load_or_bind_chat_intent(
            state_dir=state_dir,
            intent=conflicting_intent,
            resolve_draft=lambda: pytest.fail("conflicts must fail before callback"),
        )


@pytest.mark.parametrize("state_kind", ["missing", "file"])
def test_state_directory_must_already_exist_as_a_directory(
    tmp_path: Path, state_kind: str
) -> None:
    state_dir = tmp_path / "protected-state"
    if state_kind == "file":
        state_dir.write_bytes(b"not a directory")

    with pytest.raises(ValueError):
        load_or_bind_chat_intent(
            state_dir=state_dir,
            intent=_intent(),
            resolve_draft=lambda: pytest.fail("invalid state must fail before callback"),
        )


def test_corrupt_or_oversized_existing_binding_fails_closed(tmp_path: Path) -> None:
    state_dir = tmp_path / "protected-state"
    state_dir.mkdir()
    binding_path = state_dir / f"{INTENT_ID}.json"
    binding_path.write_bytes(b'{"schema_version":"1"')

    with pytest.raises(ValueError):
        load_or_bind_chat_intent(
            state_dir=state_dir,
            intent=_intent(),
            resolve_draft=lambda: pytest.fail("corrupt state must not resolve a draft"),
        )

    binding_path.write_bytes(b"x" * 65537)
    with pytest.raises(ValueError):
        load_or_bind_chat_intent(
            state_dir=state_dir,
            intent=_intent(),
            resolve_draft=lambda: pytest.fail("oversized state must not resolve a draft"),
        )


def _skip_if_symlink_unavailable(path: Path, target: Path, *, directory: bool) -> None:
    try:
        path.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")


def test_rejects_symlink_state_directory(tmp_path: Path) -> None:
    real_state = tmp_path / "real-state"
    real_state.mkdir()
    state_link = tmp_path / "protected-state"
    _skip_if_symlink_unavailable(state_link, real_state, directory=True)

    with pytest.raises(ValueError):
        load_or_bind_chat_intent(
            state_dir=state_link,
            intent=_intent(),
            resolve_draft=lambda: pytest.fail("symlink state must fail before callback"),
        )


def test_rejects_symlink_binding_file(tmp_path: Path) -> None:
    state_dir = tmp_path / "protected-state"
    state_dir.mkdir()
    target = tmp_path / "outside.json"
    target.write_bytes(b"partial")
    binding_link = state_dir / f"{INTENT_ID}.json"
    _skip_if_symlink_unavailable(binding_link, target, directory=False)

    with pytest.raises(ValueError):
        load_or_bind_chat_intent(
            state_dir=state_dir,
            intent=_intent(),
            resolve_draft=lambda: pytest.fail("symlink binding must fail before callback"),
        )


def test_two_writers_with_different_drafts_return_the_single_winner(tmp_path: Path) -> None:
    state_dir = tmp_path / "protected-state"
    state_dir.mkdir()
    intent = _intent()
    entered = 0
    entered_lock = threading.Lock()
    both_callbacks_entered = threading.Event()

    def wait_then_return(draft: CatalogRunIntentDraftV1) -> CatalogRunIntentDraftV1:
        nonlocal entered
        with entered_lock:
            entered += 1
            if entered == 2:
                both_callbacks_entered.set()
        assert both_callbacks_entered.wait(timeout=5)
        return draft

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                load_or_bind_chat_intent,
                state_dir=state_dir,
                intent=intent,
                resolve_draft=lambda: wait_then_return(_draft(request_id=REQUEST_ID_1)),
            ),
            pool.submit(
                load_or_bind_chat_intent,
                state_dir=state_dir,
                intent=intent,
                resolve_draft=lambda: wait_then_return(_draft(request_id=REQUEST_ID_2)),
            ),
        ]
        results = [future.result(timeout=10) for future in futures]

    assert results[0] == results[1]
    assert results[0].draft.request_id in {REQUEST_ID_1, REQUEST_ID_2}
    assert (state_dir / f"{INTENT_ID}.json").read_bytes() == canonical_model_bytes(results[0])


def test_interrupted_or_unsupported_publish_never_accepts_a_partial_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path / "protected-state"
    state_dir.mkdir()
    intent = _intent()
    stale_temp = state_dir / f".{INTENT_ID}.crashed.tmp"
    stale_temp.write_bytes(b'{"schema_version":"1"')

    binding = load_or_bind_chat_intent(
        state_dir=state_dir, intent=intent, resolve_draft=lambda: _draft()
    )
    final_path = state_dir / f"{INTENT_ID}.json"
    assert final_path.read_bytes() == canonical_model_bytes(binding)
    assert stale_temp.read_bytes() == b'{"schema_version":"1"'

    retry_dir = tmp_path / "retry-state"
    retry_dir.mkdir()

    def unsupported_link(*args: object, **kwargs: object) -> None:
        raise OSError("hard links unsupported")

    monkeypatch.setattr(chat_intent, "_publish_binding_exclusively", unsupported_link)
    with pytest.raises(ValueError):
        load_or_bind_chat_intent(
            state_dir=retry_dir, intent=intent, resolve_draft=lambda: _draft()
        )
    assert not (retry_dir / f"{INTENT_ID}.json").exists()
    assert not list(retry_dir.glob("*.tmp"))

    monkeypatch.undo()
    retried = load_or_bind_chat_intent(
        state_dir=retry_dir, intent=intent, resolve_draft=lambda: _draft()
    )
    assert retried == binding


def test_binding_model_has_only_intent_and_exact_draft() -> None:
    binding = CatalogChatIntentBindingV1(
        schema_version="1", intent=_intent(), draft=_draft()
    )

    assert binding.intent == _intent()
    assert binding.draft == _draft()
    assert set(binding.model_fields) == {"schema_version", "intent", "draft"}


def test_exclusive_publication_does_not_replace_an_existing_binding(tmp_path: Path) -> None:
    source = tmp_path / "own-temp"
    target = tmp_path / "binding"
    source.write_bytes(b"new")
    target.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        chat_intent._publish_binding_exclusively(str(source), target)
    assert target.read_bytes() == b"original"
    assert source.read_bytes() == b"new"


def test_exclusive_publication_exposes_complete_bytes(tmp_path: Path) -> None:
    source = tmp_path / "own-temp"
    target = tmp_path / "binding"
    source.write_bytes(b"complete")
    chat_intent._publish_binding_exclusively(str(source), target)
    assert target.read_bytes() == b"complete"
