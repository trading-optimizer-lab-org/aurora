from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_component_store import (
    CatalogComponentStore,
    ComponentStoreWriter,
)
from scripts import run_sp500_optimized_recipe_worker as worker


DATA_SNAPSHOT = "a" * 64
EVALUATOR = "b" * 64


def _write_bundle(
    root: Path,
    components: dict[str, np.ndarray],
    *,
    bundle_identity: str,
) -> CatalogComponentStore:
    writer = ComponentStoreWriter(
        root,
        data_snapshot_sha256=DATA_SNAPSHOT,
        evaluator_sha256=EVALUATOR,
        session_count=3,
    )
    for source_id, values in components.items():
        writer.add(source_id, values)
    manifest = writer.commit()
    identity = {
        "schema_version": "1",
        "bundle_identity_sha256": bundle_identity,
        "component_store_manifest_sha256": manifest.manifest_sha256,
        "component_count": len(components),
        "components": [
            {
                "component_id": f"{index + 1:064x}",
                "source_configuration_sha256": entry.component_id,
                "result_sha256": entry.result_sha256,
            }
            for index, entry in enumerate(manifest.entries)
        ],
        "validation_opened": False,
        "locked_opened": False,
    }
    (root / "component_bundle_manifest.json").write_text(
        json.dumps(
            {**identity, "manifest_sha256": canonical_sha256(identity)},
            sort_keys=True,
        )
        + "\n",
        "utf-8",
    )
    return CatalogComponentStore.open(
        root,
        expected_data_snapshot_sha256=DATA_SNAPSHOT,
        expected_evaluator_sha256=EVALUATOR,
    )


def _overlapping_payload(tmp_path: Path) -> tuple[Path, str, str, str]:
    payload_root = tmp_path / "components"
    source_a, source_b, source_c = ("a" * 64, "b" * 64, "c" * 64)
    _write_bundle(
        payload_root / "bundle-a",
        {
            source_a: np.array([1, 0, -1], dtype=np.int8),
            source_b: np.array([-1, 1, 0], dtype=np.int8),
        },
        bundle_identity="1" * 64,
    )
    _write_bundle(
        payload_root / "bundle-b",
        {
            source_b: np.array([-1, 1, 0], dtype=np.int8),
            source_c: np.array([1, 1, -1], dtype=np.int8),
        },
        bundle_identity="2" * 64,
    )
    return payload_root, source_a, source_b, source_c


def test_subset_payload_ignores_unselected_overlap_and_none_keeps_strict_mode(
    tmp_path: Path,
) -> None:
    payload_root, source_a, source_b, source_c = _overlapping_payload(tmp_path)

    payload = worker._open_exact_component_payload(
        payload_root,
        data_snapshot_sha256=DATA_SNAPSHOT,
        evaluator_sha256=EVALUATOR,
        required_source_ids=(source_a, source_c),
    )
    np.testing.assert_array_equal(payload.get(source_a), [1, 0, -1])
    np.testing.assert_array_equal(payload.get(source_c), [1, 1, -1])
    with pytest.raises(KeyError):
        payload.get(source_b)

    with pytest.raises(ValueError, match="COMPONENT_PAYLOAD_DUPLICATE"):
        worker._open_exact_component_payload(
            payload_root,
            data_snapshot_sha256=DATA_SNAPSHOT,
            evaluator_sha256=EVALUATOR,
        )


def test_identical_selected_overlap_is_accepted_deterministically(tmp_path: Path) -> None:
    payload_root, _, source_b, _ = _overlapping_payload(tmp_path)

    payload = worker._open_exact_component_payload(
        payload_root,
        data_snapshot_sha256=DATA_SNAPSHOT,
        evaluator_sha256=EVALUATOR,
        required_source_ids=(source_b,),
    )

    assert payload._entries[source_b].root == payload_root / "bundle-a"
    np.testing.assert_array_equal(payload.get(source_b), [-1, 1, 0])


def test_selected_overlap_conflict_and_missing_source_are_rejected(
    tmp_path: Path,
) -> None:
    payload_root, _, source_b, source_c = _overlapping_payload(tmp_path)
    conflict_root = tmp_path / "conflict-components" / "bundle-b"
    conflict_store = _write_bundle(
        conflict_root,
        {
            source_b: np.array([1, 1, 0], dtype=np.int8),
            source_c: np.array([1, 1, -1], dtype=np.int8),
        },
        bundle_identity="2" * 64,
    )

    with pytest.raises(ValueError, match="COMPONENT_PAYLOAD_RESULT_CONFLICT"):
        worker._ExactComponentPayload(
            (
                CatalogComponentStore.open(payload_root / "bundle-a"),
                conflict_store,
            ),
            required_source_ids=(source_b,),
        )

    with pytest.raises(ValueError, match="COMPONENT_PAYLOAD_INCOMPLETE"):
        worker._open_exact_component_payload(
            payload_root,
            data_snapshot_sha256=DATA_SNAPSHOT,
            evaluator_sha256=EVALUATOR,
            required_source_ids=("d" * 64,),
        )


def test_persistent_initializer_propagates_required_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, tuple[str, ...] | None]] = []

    def fake_open(
        root: Path, *, required_source_ids: tuple[str, ...] | None, **kwargs: object,
    ) -> object:
        calls.append((root, required_source_ids))
        return object()

    class DummyObjective:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(worker, "_open_exact_component_payload", fake_open)
    monkeypatch.setattr(
        worker,
        "load_train_total_return_ledger",
        lambda *_args, **_kwargs: pd.DataFrame(index=pd.RangeIndex(1)),
    )
    monkeypatch.setattr(worker, "FastTrainObjective", DummyObjective)

    worker._initialize_recipe_process(
        "components",
        DATA_SNAPSHOT,
        EVALUATOR,
        "snapshot",
        "2010-12-31",
        "c" * 64,
        "d" * 64,
        ("a" * 64, "c" * 64),
    )

    assert calls == [
        (Path("components"), ("a" * 64, "c" * 64)),
    ]
