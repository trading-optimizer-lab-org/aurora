from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.run_paper_spy_daily_event_sharpe2 import (
    LOCKED_START,
    build_event_frame,
    parse_fomc_dates_from_html,
)


def test_parse_fomc_range_takes_announcement_day() -> None:
    html = "Meeting: January 31-February 1, 1996. Another meeting: March 26, 1996."
    dates = parse_fomc_dates_from_html(html, 1996)
    assert pd.Timestamp("1996-02-01") in dates
    assert pd.Timestamp("1996-03-26") in dates
    assert pd.Timestamp("1996-01-31") not in dates


def test_event_frame_uses_known_calendar_without_locked() -> None:
    index = pd.bdate_range("2020-12-20", "2020-12-31")
    events = build_event_frame(index, [pd.Timestamp("2020-12-29")])
    assert events.index.max() < LOCKED_START
    assert events.loc[pd.Timestamp("2020-12-29"), "fomc_event_day"] == 1.0
    assert events.loc[pd.Timestamp("2020-12-28"), "pre_fomc_days"] == 1.0


def test_daily_event_workflow_has_360_jobs_and_no_locked_open() -> None:
    workflow = Path(".github/workflows/paper-spy-daily-event-sharpe2-360jobs.yml").read_text(encoding="utf-8")
    assert "stage + 180" in workflow
    assert "range(180)" in workflow
    assert workflow.count("max-parallel: 180") == 1
    assert "paper-spy-daily-event-sharpe2-360jobs-results" in workflow
    script = Path("scripts/run_paper_spy_daily_event_sharpe2.py").read_text(encoding="utf-8")
    assert '"locked_opened": False' in script
    assert '"validation_used_for_selection": False' in script
    assert "TARGET_SHARPE = 2.0" in script
