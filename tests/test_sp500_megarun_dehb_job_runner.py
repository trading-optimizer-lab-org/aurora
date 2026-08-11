from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace


def _hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _contract() -> SimpleNamespace:
    return SimpleNamespace(
        sha256="a" * 64,
        data_contract_file_sha256="1" * 64,
        data_contract_canonical_sha256="2" * 64,
        feature_contract_sha256="3" * 64,
        dehb_lock_domain_sha256="4" * 64,
        train_source_run_id="123",
        train_artifact_name="train",
        train_artifact_digest_sha256="b" * 64,
        train_snapshot_manifest_sha256="c" * 64,
        train_spy_sha256="d" * 64,
        train_partition="train_snapshot_1993_2010",
        search_start="1998-01-01",
        search_end="2010-12-31",
    )


def _launch() -> SimpleNamespace:
    return SimpleNamespace(
        sha256="f" * 64,
        campaign_contract_sha256="a" * 64,
        runtime_input_aggregate_sha256="e" * 64,
        validation_opened=False,
        locked_opened=False,
    )


def _payload(*, resume: bool) -> dict:
    value = {
        "schema_version": 1,
        "campaign_contract_sha256": "a" * 64,
        "launch_contract_sha256": "f" * 64,
        "job_id": "J001",
        "job_index": 0,
        "shard_id": "A",
        "wave": 2,
        "train_source_run_id": "123",
        "train_artifact_name": "train",
        "train_artifact_digest_sha256": "b" * 64,
        "train_snapshot_manifest_sha256": "c" * 64,
        "train_spy_sha256": "d" * 64,
        "train_partition": "train_snapshot_1993_2010",
        "search_start": "1998-01-01",
        "search_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "islands": [
            {
                "island_id": "F001-R1",
                "lane_id": "F001",
                "replicate": 1,
                "restart_ordinal": 0,
                "restart_seed": 10,
                "resume_from_previous_wave": resume,
                "n_workers": 4,
            },
            {
                "island_id": "F121-R2",
                "lane_id": "F121",
                "replicate": 2,
                "restart_ordinal": 2,
                "restart_seed": 20,
                "resume_from_previous_wave": False,
                "n_workers": 4,
            },
        ],
    }
    value["payload_sha256"] = _hash_payload(value)
    return value


def test_two_island_job_is_sequential_closed_and_resumes_only_marked_island(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_job_runner import run_dehb_job

    pack = tmp_path / "pack"
    pack.mkdir()
    prior = tmp_path / "prior"
    (prior / "islands" / "F001-R1").mkdir(parents=True)
    calls: list[dict] = []

    def island_runner(_contract, _feature_contract, **kwargs):
        calls.append(kwargs)
        Path(kwargs["output_dir"]).mkdir(parents=True)
        return {
            "status": "paused_at_runner_slice",
            "stop_reason": "runner_slice_elapsed",
            "checkpoint_sha256": "f" * 64,
            "evaluations": 4,
            "full_fidelity_evaluations": 1,
            "champion": None,
        }

    result = run_dehb_job(
        _contract(),
        object(),
        launch_contract=_launch(),
        payload=_payload(resume=True),
        runtime_input_pack=pack,
        output_dir=tmp_path / "out",
        previous_worker_dir=prior,
        island_runner=island_runner,
        pack_verifier=lambda *_args, **_kwargs: {},
    )

    assert [call["assignment"]["island_id"] for call in calls] == [
        "F001-R1",
        "F121-R2",
    ]
    assert calls[0]["prior_bundle"] == prior / "islands" / "F001-R1"
    assert calls[1]["prior_bundle"] is None
    assert result["validation_opened"] is False
    assert result["locked_opened"] is False
    assert result["launch_contract_sha256"] == "f" * 64
    assert (tmp_path / "out" / "worker_result.json").is_file()


def test_job_payload_hash_tampering_is_rejected(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.dehb_job_runner import (
        DehbJobRunnerError,
        load_verified_job_payload,
    )

    payload = _payload(resume=False)
    payload["wave"] = 3
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        load_verified_job_payload(path)
    except DehbJobRunnerError as exc:
        assert "JOB_PAYLOAD_SHA256_MISMATCH" in str(exc)
    else:
        raise AssertionError("tampered payload was accepted")
