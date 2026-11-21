from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH: Path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "deploy.yaml"
PUSH_TO_MAIN_ONLY: str = "github.event_name == 'push' && github.ref == 'refs/heads/main'"


def _workflow() -> dict[Any, Any]:
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _triggers() -> dict[str, Any]:
    workflow = _workflow()
    # PyYAML (YAML 1.1) parses the bare key `on` as boolean True.
    return workflow.get("on", workflow.get(True))


def test_workflow_runs_on_pull_requests_to_main() -> None:
    assert _triggers()["pull_request"]["branches"] == ["main"]


def test_workflow_still_runs_on_push_to_main() -> None:
    assert _triggers()["push"]["branches"] == ["main"]


def test_tests_run_for_every_trigger() -> None:
    assert "if" not in _workflow()["jobs"]["test"]


def test_build_and_deploy_only_run_on_push_to_main() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["changes"]["if"] == PUSH_TO_MAIN_ONLY
    assert jobs["build-and-push"]["if"] == f"{PUSH_TO_MAIN_ONLY} && needs.changes.outputs.deploy == 'true'"
    # deploy needs build-and-push, so it is skipped whenever the build is.
    assert jobs["deploy"]["if"] == PUSH_TO_MAIN_ONLY


def test_deploy_still_requires_build_and_build_requires_tests() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["build-and-push"]["needs"] == ["test", "changes"]
    assert jobs["deploy"]["needs"] == "build-and-push"


def test_deploy_decision_comes_from_the_diff_script() -> None:
    changes = _workflow()["jobs"]["changes"]
    assert changes["outputs"]["deploy"] == "${{ steps.diff.outputs.deploy }}"
    checkout, diff = changes["steps"]
    assert checkout["with"]["fetch-depth"] == 0
    assert diff["id"] == "diff"
    assert ".github/scripts/needs_deploy.sh" in diff["run"]


def test_workflow_permissions_are_read_only_by_default() -> None:
    assert _workflow()["permissions"] == {"contents": "read"}


def test_only_build_job_can_write_packages() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["build-and-push"]["permissions"] == {"contents": "read", "packages": "write"}
    for job_name, job in jobs.items():
        if job_name != "build-and-push":
            assert "packages" not in job.get("permissions", {}), job_name


def test_outdated_runs_are_cancelled_only_for_pull_requests() -> None:
    """Cancelling on main could interrupt a deploy halfway through its SSH script."""
    concurrency = _workflow()["concurrency"]
    assert "github.ref" in concurrency["group"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
