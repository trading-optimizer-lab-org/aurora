from pathlib import Path

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.sp500_megarun.catalog_fast_authority_github import authority_publication_step_names


ROOT = Path(__file__).resolve().parents[1]


def workflow():
    return load_github_yaml(ROOT / ".github/workflows/catalog-cloud-intake.yml")


def test_intake_has_no_scientific_dispatch_or_schedule():
    document = workflow()
    assert set(document["on"]) == {"issues", "issue_comment"}
    assert document["on"]["issues"]["types"] == ["opened"]
    assert document["on"]["issue_comment"]["types"] == ["created"]
    text = (ROOT / ".github/workflows/catalog-cloud-intake.yml").read_text("utf-8")
    assert "workflow_dispatch" not in text and "gh workflow run" not in text
    assert "CATALOG_CLOUD_INTAKE_MODE != 'OFF'" in text


def test_validation_precedes_secret_and_writer_lock_does_not_wait_for_science():
    document = workflow()
    validate, intake = document["jobs"]["validate"], document["jobs"]["intake"]
    assert "secrets." not in str(validate)
    assert document["permissions"]["issues"] == "read"
    assert intake["needs"] == "validate"
    assert intake["permissions"] == {"contents": "read", "actions": "read", "issues": "write"}
    assert intake["environment"] == "catalog-cloud-intake"
    assert intake["concurrency"] == {
        "group": "aurora-catalog-fast-admission-v1", "queue": "max", "cancel-in-progress": False,
    }
    assert "wait" not in " ".join(str(step.get("run", "")) for step in intake["steps"])


def test_publication_labels_and_recovery_match_real_provenance_reader():
    steps = workflow()["jobs"]["intake"]["steps"]
    names = [step.get("name") for step in steps]
    post_index = names.index("Submit once or reconcile exact signed request")
    for phase in ("intake-signed", "intake-uncertain", "intake-published"):
        write, upload = authority_publication_step_names(phase)
        recovery = f"Recover missing authority publication ({phase})"
        assert names.count(write) == names.count(upload) == names.count(recovery) == 1
        assert names.index(write) < names.index(upload) < names.index(recovery)
        if phase != "intake-published":
            assert names.index(recovery) < post_index
        else:
            assert post_index < names.index(write)
        recover_step = steps[names.index(recovery)]
        assert "verification_exit == '4'" in recover_step["if"]
        assert recover_step["with"]["retention-days"] == 90


def test_checkout_is_exact_and_action_dependencies_are_pinned():
    for job in workflow()["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"
        for step in job["steps"]:
            if "uses" in step:
                assert len(step["uses"].split("@")[1]) == 40
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"] == {"ref": "${{ github.sha }}", "persist-credentials": False}


def test_qualification_has_no_scientific_or_authority_write_capability():
    document = load_github_yaml(ROOT / '.github/workflows/catalog-cloud-qualification.yml')
    assert set(document['on']) == {'workflow_dispatch'}
    assert document['permissions'] == {'contents': 'read', 'actions': 'read', 'issues': 'read'}
    assert set(document['jobs']) == {'qualify'}
    job = document['jobs']['qualify']
    assert job['environment'] == 'catalog-cloud-intake'
    assert "github.ref == 'refs/heads/main'" in job['if']
    assert "vars.CATALOG_CLOUD_INTAKE_MODE == 'OFF'" in job['if']
    assert 'permissions' not in job
    for step in job['steps']:
        if 'uses' in step:
            assert len(step['uses'].split('@')[1]) == 40
        if step.get('uses', '').startswith('actions/upload-artifact@'):
            assert step['with']['path'] == '${{ runner.temp }}/catalog-cloud-qualification-v1.json'
        if 'secrets.' in str(step):
            assert 'scripts/qualify_catalog_cloud_origin.py' in step['run']


def test_intake_jobs_receive_qualification_locator_without_api_variable_reads():
    for job in workflow()['jobs'].values():
        assert job['env']['CATALOG_CLOUD_QUALIFICATION_RUN_ID'] == '${{ vars.CATALOG_CLOUD_QUALIFICATION_RUN_ID }}'
