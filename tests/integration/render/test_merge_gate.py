"""Execute the delivered merge step without credentials or a route to a real repository."""

import subprocess

import pytest

from tests.integration.render.helpers import (
    HEAD,
    PR,
    git,
    merge_environment,
    merge_subject,
    run_gate,
)
from tests.integration.render.helpers import gate as gate


def assert_refused(gate, result, calls, reason):
    assert result.returncode != 0, result.stdout
    assert "MERGE REFUSED: " + reason in result.stderr, result.stderr
    assert not (gate["root"] / "merged").exists()
    assert not any(call[:2] == ["pr", "merge"] for call in calls)


@pytest.mark.parametrize("comparison", ("ahead", "identical", "diverged"))
@pytest.mark.parametrize("review", ("PASS", "N/A"))
def test_green_mergeable_head_merges_once_without_branch_refresh(gate, comparison, review):
    pr = dict(PR, body=f"Independent review: {review} - satisfied")
    result, calls = run_gate(gate, snapshots=[pr], comparison=comparison)
    assert result.returncode == 0, result.stderr
    assert (gate["root"] / "merged").read_text() == HEAD
    assert [call[:2] for call in calls] == [["pr", "view"], ["api", "--hostname"], ["pr", "merge"]]


@pytest.mark.parametrize(
    "comparison,reason",
    (
        ("behind", "checked head is behind the base"),
        ("unknown", "base comparison status is unknown or unsupported"),
        ("", "base comparison status is unknown or unsupported"),
    ),
)
def test_refused_comparison_cannot_fall_through_to_merge(gate, comparison, reason):
    result, calls = run_gate(gate, comparison=comparison)
    assert calls[-1][:2] == ["api", "--hostname"]
    assert_refused(gate, result, calls, reason)


@pytest.mark.parametrize(
    "failure,reason",
    (("view", "PR snapshot read failed"), ("compare", "base comparison API failed")),
)
def test_failed_read_cannot_fall_through_to_merge(gate, failure, reason):
    result, calls = run_gate(gate, failure=failure)
    assert calls
    assert_refused(gate, result, calls, reason)


@pytest.mark.parametrize(
    "body",
    (
        "",
        "Independent review: PENDING - owed",
        "Independent review: REVIEW - unresolved",
        "Independent review: PASS",
        "Independent review: PASS - ",
        "Independent review: PASS -  ",
        "Independent review: N/A - \t",
        "Independent review: PASS - first\nIndependent review: N/A - second",
        "Independent review: PASS - first\nIndependent review: REVIEW - second",
    ),
)
def test_review_requires_exactly_one_well_formed_accepted_line(gate, body):
    result, calls = run_gate(gate, snapshots=[dict(PR, body=body)])
    assert calls[0][:2] == ["pr", "view"]
    assert_refused(gate, result, calls, "Independent review requires exactly one PASS or N/A line")


@pytest.mark.parametrize(
    "change",
    (
        {"state": "CLOSED"},
        {"baseRefName": "other"},
        {"headRefOid": "b" * 40},
        {"isCrossRepository": True},
    ),
)
def test_changed_pr_identity_refuses_before_comparing_or_merging(gate, change):
    result, calls = run_gate(gate, snapshots=[dict(PR, **change)])
    assert len(calls) == 1 and calls[0][:2] == ["pr", "view"]
    assert_refused(gate, result, calls, "PR state, base, head or repository identity changed")


def test_conflicting_head_refuses(gate):
    result, calls = run_gate(gate, snapshots=[dict(PR, mergeable="CONFLICTING")])
    assert len(calls) == 1
    assert_refused(gate, result, calls, "PR is not MERGEABLE")


def test_unknown_mergeability_has_bounded_reads(gate):
    result, calls = run_gate(gate, snapshots=[dict(PR, mergeable="UNKNOWN")])
    assert len(calls) == 3 and all(call[:2] == ["pr", "view"] for call in calls)
    assert_refused(gate, result, calls, "mergeability remains UNKNOWN")


def test_transient_unknown_refreshes_the_whole_snapshot(gate):
    snapshots = [dict(PR, mergeable="UNKNOWN"), dict(PR, body="Independent review: REVIEW - owed")]
    result, calls = run_gate(gate, snapshots=snapshots)
    assert len(calls) == 2
    assert_refused(gate, result, calls, "Independent review requires exactly one PASS or N/A line")


def test_unknown_then_mergeable_can_merge(gate):
    result, calls = run_gate(gate, snapshots=[dict(PR, mergeable="UNKNOWN"), PR])
    assert result.returncode == 0, result.stderr
    assert len(calls) == 4 and (gate["root"] / "merged").read_text() == HEAD


@pytest.mark.parametrize("comparison", ("ahead", "identical", "diverged"))
def test_bootstrap_still_requires_a_head_that_contains_the_base(gate, comparison):
    gate["env"]["merge_proof"] = "bootstrap"
    result, calls = run_gate(gate, comparison=comparison)
    if comparison == "diverged":
        assert_refused(gate, result, calls, "diverged base needs fresh bootstrap proof")
    else:
        assert result.returncode == 0, result.stderr
        assert (gate["root"] / "merged").exists()


@pytest.mark.parametrize(
    "variable",
    (
        "merge_repository",
        "merge_number",
        "merge_base",
        "merge_head",
        "merge_proof",
    ),
)
def test_unset_inputs_fail_before_any_github_call(gate, variable):
    del gate["env"][variable]
    result, calls = run_gate(gate)
    assert not calls
    assert_refused(gate, result, calls, "set " + variable)


def test_invalid_route_fails_before_any_github_call(gate):
    gate["env"]["merge_proof"] = "unproven"
    result, calls = run_gate(gate)
    assert not calls
    assert_refused(gate, result, calls, "proof route must be ci or bootstrap")


def test_pinned_merge_failure_is_terminal_without_retry(gate):
    result, calls = run_gate(gate, failure="merge")
    assert result.returncode != 0 and "pinned merge failed" in result.stderr
    assert sum(call[:2] == ["pr", "merge"] for call in calls) == 1
    assert not (gate["root"] / "merged").exists()


def test_pr_body_is_data_even_when_it_contains_shell_commands(gate):
    body = "Summary\n$(touch exposed)\nIndependent review: PASS - `touch exposed`"
    result, _ = run_gate(gate, snapshots=[dict(PR, body=body)])
    assert result.returncode == 0, result.stderr
    assert (gate["root"] / "merged").exists() and not (gate["root"] / "exposed").exists()


@pytest.mark.parametrize(
    "words,stale,reason",
    (
        (1980, False, "bin/slopmeister quality failed on merge tree"),
        (1970, True, "bin/slopmeister render --check failed on merge tree"),
        (1970, False, ""),
    ),
)
def test_merge_tree_checks_the_combined_tree_before_any_merge(gate, words, stale, reason):
    merge_subject(gate, words, stale)
    assert git(gate["root"], "rev-parse", "--is-shallow-repository") == "true"
    merge_environment(gate)
    head = gate["env"]["merge_head"]
    for commit in ("main", head):
        git(gate["root"], "checkout", "--detach", commit)
        proof = subprocess.run(["bin/slopmeister", "quality"], cwd=gate["root"], env=gate["env"],
                               capture_output=True, text=True, timeout=30)  # fmt: skip
        assert proof.returncode == 0 and "quality: ok" in proof.stdout, proof.stdout + proof.stderr
    result, calls = run_gate(gate)
    assert not list((gate["root"].parent / "scratch").iterdir())
    if reason:
        assert_refused(gate, result, calls, reason)
        assert "document_words" in result.stdout if words == 1980 else "render" in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "quality: ok" in result.stdout
        assert (gate["root"] / "merged").read_text() == head
        assert sum(call[:2] == ["pr", "merge"] for call in calls) == 1


@pytest.mark.parametrize("comparison", ("ahead", "identical"))
def test_merge_tree_is_skipped_when_the_head_contains_the_base(gate, comparison):
    gate["command"] = gate["project"] + " &&\n" + gate["command"]
    result, calls = run_gate(gate, comparison=comparison)
    assert result.returncode == 0, result.stderr
    assert (gate["root"] / "merged").read_text() == HEAD
    assert len(calls) == 4


def test_merge_tree_checks_work_from_a_repository_subdirectory(gate):
    merge_subject(gate, 1970, False)
    merge_environment(gate)
    nested = gate["root"] / "nested"
    nested.mkdir()
    gate["root"] = nested
    result, calls = run_gate(gate)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "quality: ok" in result.stdout and "dist/ is up to date" in result.stdout
    assert (nested / "merged").read_text() == gate["env"]["merge_head"]
    assert sum(call[:2] == ["pr", "merge"] for call in calls) == 1
