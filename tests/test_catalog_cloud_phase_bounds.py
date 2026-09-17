from datetime import datetime, timezone

import pytest

from scripts.catalog_cloud_intake import _post_bounds
from tests.test_catalog_cloud_authority import emission


class Client:
    repository = "trading-optimizer-lab-org/aurora"

    def __init__(self):
        self.run = {"id": 500, "run_attempt": 1, "head_branch": "main", "head_sha": "a" * 40,
                    "path": ".github/workflows/catalog-cloud-intake.yml",
                    "repository": {"full_name": self.repository},
                    "run_started_at": "2026-09-17T12:00:00Z"}
        self.job = {"name": "intake", "run_id": 500, "run_attempt": 1, "head_sha": "a" * 40,
                    "started_at": "2026-09-17T14:00:00Z"}

    def get_json(self, path):
        if path.endswith("/attempts/1"):
            return self.run, None
        assert path.endswith("/attempts/1/jobs?per_page=100&page=1")
        return {"jobs": [self.job]}, None


def uncertain():
    return emission().advance("PUBLICACION_INCIERTA", post_run_id=500, post_run_attempt=1)


def test_queue_delay_does_not_move_post_window_to_workflow_start():
    lower, upper = _post_bounds(Client(), uncertain())
    assert lower == datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)
    assert (upper - lower).total_seconds() == 900


@pytest.mark.parametrize("field,value", [("run_id", 501), ("run_attempt", 2), ("head_sha", "b" * 40), ("name", "other")])
def test_other_job_cannot_accredit_post_timestamp(field, value):
    client = Client()
    client.job[field] = value
    with pytest.raises(ValueError, match="POST_JOB_INVALID"):
        _post_bounds(client, uncertain())
