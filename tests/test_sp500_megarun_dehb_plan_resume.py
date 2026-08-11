from __future__ import annotations

import json
from pathlib import Path


def test_plan_script_accepts_only_closed_matching_prior_decision(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )
    from scripts.plan_sp500_megarun_dehb_campaign import _load_prior_decision

    repo = Path(__file__).resolve().parents[1]
    campaign = load_and_validate_campaign_contract(
        repo / "config" / "sp500_megarun_dehb_campaign_v1.json"
    )
    decision = {
        "campaign_contract_sha256": campaign.sha256,
        "action": "dispatch_next_wave",
        "next_wave": 1,
        "next_island_restart_ordinals": {
            f"F{lane:03d}-R{replicate}": 1
            for replicate in range(1, 4)
            for lane in range(1, 241)
        },
        "resume_island_ids": [],
        "validation_opened": False,
        "locked_opened": False,
    }
    target = tmp_path / "decision.json"
    target.write_text(json.dumps(decision), encoding="utf-8")
    action, ordinals, resume, retry = _load_prior_decision(
        target, campaign_sha256=campaign.sha256, wave=1
    )
    assert action == "dispatch_next_wave"
    assert len(ordinals) == 720
    assert resume == frozenset()
    assert retry == []

    decision["validation_opened"] = True
    target.write_text(json.dumps(decision), encoding="utf-8")
    try:
        _load_prior_decision(target, campaign_sha256=campaign.sha256, wave=1)
    except ValueError as exc:
        assert "PRIOR_CONTROLLER_DECISION_INVALID" in str(exc)
    else:
        raise AssertionError("opened validation decision was accepted")
