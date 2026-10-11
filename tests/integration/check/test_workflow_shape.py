"""Public CI uses isolated hosted runners and keeps its failure evidence."""

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[3]
SETUP_UV = "uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4"


def trigger_block() -> str:
    return (ROOT / ".github/workflows/check.yml").read_text().split("jobs:\n", 1)[0]


def job_block(job: str) -> str:
    workflow = (ROOT / ".github/workflows/check.yml").read_text()
    start = workflow.index(f"  {job}:\n")
    later_jobs = (
        workflow.find(f"  {other}:\n", start + 1) for other in ("lint", "quality", "tests")
    )
    end = min((index for index in later_jobs if index != -1), default=len(workflow))
    return workflow[start:end]


def test_pull_request_heads_do_not_also_run_the_push_trigger() -> None:
    """Escaping bug: one PR head update launched both push and pull-request runs."""
    triggers = trigger_block()
    assert "  push:\n    branches: [main]\n" in triggers
    assert triggers.count("  push:") == 1
    assert triggers.count("  pull_request:") == 1


def test_main_push_and_manual_dispatch_remain_triggers() -> None:
    """Escaping bug: removing duplicate branch runs also removed required entry points."""
    triggers = trigger_block()
    assert "    branches: [main]" in triggers
    assert triggers.count("  workflow_dispatch:") == 1


@pytest.mark.parametrize("job", ["lint", "quality", "tests"])
def test_each_ci_job_declares_its_failed_check_evidence(job: str) -> None:
    block = job_block(job)
    step = job + "_check"
    setup_uv = block.index(SETUP_UV)
    tools = block.index("run: task tools")
    check = block.index(f"id: {step}")
    upload = block.index("uses: actions/upload-artifact@")
    assert setup_uv < tools < check < upload
    assert block.count(SETUP_UV) == 1
    assert 'version: "0.12.15"' in block
    assert "enable-cache: true" in block
    assert f"--report ci-evidence/{job}.json" in block
    assert f"failure() && steps.{step}.outcome == 'failure'" in block
    assert f"name: failed-check-{job}" in block
    assert f"ci-evidence/{job}.logs" in block
    assert block.count("uses: actions/upload-artifact@") == 1
    assert block.count("retention-days: 7") == 1
    assert block.count("if-no-files-found: error") == 1


@pytest.mark.parametrize("job", ["lint", "quality", "tests"])
def test_public_jobs_use_hosted_runners_for_fork_contributions(job: str) -> None:
    block = job_block(job)
    assert "runs-on: ubuntu-24.04" in block
    assert "timeout-minutes: 20" in block
    assert "github.event.pull_request.head.repo.full_name" not in block
    assert "persist-credentials: false" in block
    assert "pull_request_target:" not in trigger_block()


@pytest.mark.parametrize("job", ["lint", "quality", "tests"])
def test_each_ci_job_takes_the_pinned_python_from_setup_python(job: str) -> None:
    """Escaping bug: one job provisioned Python differently from the others."""
    block = job_block(job)
    assert block.index("uses: actions/setup-python@") < block.index(SETUP_UV)
    assert 'python-version: "3.14"' in block
    assert "uv python install" not in block
    assert 'dirname "${python}"' not in block


def test_ephemeral_runners_install_the_portable_system_prerequisites() -> None:
    lint, tests = job_block("lint"), job_block("tests")
    assert "sudo apt-get update" in lint and "shellcheck" in lint
    assert "sudo apt-get update" in tests
    assert all(package in tests for package in ("lsof", "zsh", "uuid-runtime"))


def test_every_action_is_pinned_to_a_commit_with_its_version_named() -> None:
    """Escaping bug: a moved tag ran unreviewed action code in CI."""
    workflow = (ROOT / ".github/workflows/check.yml").read_text()
    uses = [line.strip() for line in workflow.splitlines() if "uses: " in line]
    assert uses
    for line in uses:
        assert re.fullmatch(r"(- )?uses: [\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", line), line


def test_the_workflow_token_is_read_only() -> None:
    """Escaping bug: the default token let a compromised step write to the repository."""
    assert "\npermissions:\n  contents: read\n" in trigger_block()
