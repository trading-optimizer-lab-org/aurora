"""Tests for R71 (file lease) + R73 + R84 + R90."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from quantforge.deployment.strategy_isolation import (
    IsolationConflict,
    Lease,
)
from quantforge.deployment.strategy_isolation_file import FileLeaseStore
from quantforge.infra.distributed_factory import (
    Coordinator,
    WorkerSpec,
    WorkUnit,
    WorkResult,
)
from quantforge.reporting.pdf_report import (
    PdfRenderConfig,
    can_render_pdf,
    render_html_to_pdf,
)


# --------------------------------------------------------------------------
# R71 file-backed lease store
# --------------------------------------------------------------------------


def test_file_lease_store_acquire_then_release(tmp_path: Path):
    store = FileLeaseStore(store_path=tmp_path / "leases.json")
    lease = store.acquire("alpha", "SPY")
    assert lease.symbol == "SPY"
    assert lease.strategy_id == "alpha"
    assert store.acquired_by("SPY") is not None
    store.release(lease)
    assert store.acquired_by("SPY") is None


def test_file_lease_store_blocks_second_strategy(tmp_path: Path):
    store = FileLeaseStore(store_path=tmp_path / "leases.json")
    store.acquire("alpha", "SPY")
    with pytest.raises(IsolationConflict):
        store.acquire("beta", "SPY")


def test_file_lease_store_idempotent_re_acquire(tmp_path: Path):
    store = FileLeaseStore(store_path=tmp_path / "leases.json")
    a = store.acquire("alpha", "SPY")
    b = store.acquire("alpha", "SPY")
    assert a.strategy_id == b.strategy_id == "alpha"


def test_file_lease_store_release_all_for(tmp_path: Path):
    store = FileLeaseStore(store_path=tmp_path / "leases.json")
    store.acquire("alpha", "SPY")
    store.acquire("alpha", "QQQ")
    store.acquire("beta", "IWM")
    n = store.release_all_for("alpha")
    assert n == 2
    assert store.acquired_by("SPY") is None
    assert store.acquired_by("QQQ") is None
    assert store.acquired_by("IWM") is not None


def test_file_lease_store_persists_across_instances(tmp_path: Path):
    p = tmp_path / "leases.json"
    a = FileLeaseStore(store_path=p)
    a.acquire("alpha", "SPY")
    b = FileLeaseStore(store_path=p)
    held = b.acquired_by("SPY")
    assert held is not None
    assert held.strategy_id == "alpha"


def test_file_lease_store_release_wrong_owner_raises(tmp_path: Path):
    store = FileLeaseStore(store_path=tmp_path / "leases.json")
    store.acquire("alpha", "SPY")
    fake = Lease(strategy_id="beta", symbol="SPY",
                 acquired_at=datetime.utcnow())
    with pytest.raises(IsolationConflict):
        store.release(fake)


# --------------------------------------------------------------------------
# R73 cli __init__ public API
# --------------------------------------------------------------------------


def test_cli_main_is_importable():
    from quantforge.cli import main
    assert callable(main)


# --------------------------------------------------------------------------
# R84 PDF report
# --------------------------------------------------------------------------


def test_can_render_pdf_returns_bool():
    val = can_render_pdf()
    assert val in (True, False)


def test_render_html_to_pdf_raises_when_weasyprint_missing(tmp_path: Path,
                                                            monkeypatch):
    # Force the import to fail by removing weasyprint from sys.modules
    # AND blocking re-import via meta_path.
    import sys
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    with pytest.raises(ImportError):
        render_html_to_pdf("<html><body>hi</body></html>",
                           tmp_path / "out.pdf")


# --------------------------------------------------------------------------
# R90 distributed factory coordinator
# --------------------------------------------------------------------------


def test_coordinator_round_robins_workers():
    coord = Coordinator()
    coord.add_worker(WorkerSpec(worker_id="w1"))
    coord.add_worker(WorkerSpec(worker_id="w2"))
    units = [WorkUnit(unit_id=str(i), seed=i, n_candidates=10) for i in range(4)]
    seen: list[str] = []

    def runner(worker, unit):
        seen.append(worker.worker_id)
        return WorkResult(
            unit_id=unit.unit_id, worker_id=worker.worker_id,
            n_candidates_returned=unit.n_candidates,
            finished_at=datetime.utcnow().isoformat(),
        )

    res = coord.dispatch(units, run_unit=runner)
    assert seen == ["w1", "w2", "w1", "w2"]
    assert all(r.n_candidates_returned == 10 for r in res)


def test_coordinator_no_workers_raises():
    coord = Coordinator()
    with pytest.raises(ValueError):
        coord.dispatch([WorkUnit(unit_id="a", seed=0, n_candidates=1)],
                       run_unit=lambda w, u: WorkResult(
                           unit_id=u.unit_id, worker_id=w.worker_id,
                           n_candidates_returned=0,
                           finished_at=datetime.utcnow().isoformat(),
                       ))


def test_coordinator_records_per_unit_error():
    coord = Coordinator()
    coord.add_worker(WorkerSpec(worker_id="w1"))

    def explode(worker, unit):
        raise RuntimeError("boom")

    res = coord.dispatch(
        [WorkUnit(unit_id="bad", seed=0, n_candidates=5)],
        run_unit=explode,
    )
    assert res[0].error is not None
    assert "boom" in res[0].error
