from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_bootstrap_merge_keeps_zero_checks_outside_the_normal_gate():
    """Bug: absent checks or changed code bypass explicit bootstrap authority and proof."""
    source = (ROOT / "src/skills/merge/SKILL.md").read_text()
    gate = source.split("### 3. Prove", 1)[0]
    for token in (
        "Zero checks reported, refuse unless",
        "operator's own message",
        "no external CI is expected",
        "accepted tester verdict and review disposition",
        "git diff <proved-commit>..<headRefOid>",
        "local gate on that head",
        "without renewed tester and review proof",
        "Never create a status",
    ):
        assert token in gate


def test_bootstrap_finalize_checks_before_issue_close():
    """Bug: finalize writes to GitHub before checking absent or unproven CI."""
    source = (ROOT / "src/skills/finalize/SKILL.md").read_text()
    preflight = source[: source.index("### 2. Project document duties")]
    assert "CI is absent or uncertain, stop" in preflight
    assert "gh pr checks <number>" in preflight
    assert "A refusal stops finalize" in preflight


def test_finalize_refreshes_before_waiting_and_closes_a_github_issue_after_the_merge():
    """Bug: a refused merge closes its issue, or stale code waits before refresh."""
    merge = (ROOT / "src/skills/merge/SKILL.md").read_text()
    order = [
        "Before the first check or wait",
        "only to count the checks",
        "Otherwise refresh at once",
        "gh pr checks <number> --watch",
        "compare/<baseRefName>...<headRefOid>",
    ]
    assert sorted(order, key=merge.index) == order
    finalize = (ROOT / "src/skills/finalize/SKILL.md").read_text()
    order = ["### 3. Ship", "### 4. Merge", "### 5. Close the task", "### 6. Close out"]
    assert sorted(order, key=finalize.index) == order
    assert "after step 4 verified the merged state" in finalize


def test_finalize_endings_never_act_on_a_repository_we_do_not_own():
    """Bug: finalize writes to a customer repository or discards an unmerged branch."""
    text = (ROOT / "src/skills/finalize/SKILL.md").read_text()
    endings = text[text.index("## Endings") : text.index("## Steps")]
    assert "confirm read-only that the PR is open" in endings
    assert "never closes, merges or edits" in endings
    assert "git branch -d <branch>" in text
    assert "never use `-D`" in text


def test_merge_requires_action_specific_approval_after_refusal():
    """Bug: a generic approval retries an action whose native approval was refused."""
    source = (ROOT / "src/skills/merge/SKILL.md").read_text()
    assert "do not retry it and do not work around it" in source
    assert "reply that names the merge" in source
