from __future__ import annotations

from pathlib import Path

import pytest

from scripts import download_gtbi_v6_worker_artifacts as downloader


def test_load_names_accepts_more_than_actions_download_artifact_limit(tmp_path: Path) -> None:
    path = tmp_path / "names.txt"
    names = [f"gtbi-v6-worker-{worker}-attempt-0-run-123" for worker in range(360)]
    path.write_text("\n".join(reversed(names)) + "\n", encoding="utf-8")

    assert downloader.load_artifact_names(path, prefix="gtbi-v6-worker-") == sorted(names)


@pytest.mark.parametrize(
    "name",
    ["../escape", "gtbi-v6-worker-/escape", "wrong-prefix", "gtbi-v6-worker-0\\escape"],
)
def test_load_names_rejects_unsafe_or_unrelated_names(tmp_path: Path, name: str) -> None:
    path = tmp_path / "names.txt"
    path.write_text(name + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        downloader.load_artifact_names(path, prefix="gtbi-v6-worker-")


def test_parallel_download_requires_every_artifact_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = [f"gtbi-v6-worker-{worker}-attempt-0-run-123" for worker in range(8)]
    observed: list[str] = []

    def fake_download(**kwargs: object) -> None:
        name = str(kwargs["artifact_name"])
        observed.append(name)
        target = Path(kwargs["output_root"]) / name
        target.mkdir(parents=True)
        (target / "worker_summary.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(downloader, "download_one", fake_download)
    result = downloader.download_worker_artifacts(
        repo="owner/repo",
        run_id="123",
        artifact_names=names,
        output_root=tmp_path / "workers",
        max_workers=4,
        retries=3,
    )

    assert result["downloaded_count"] == 8
    assert sorted(observed) == sorted(names)

