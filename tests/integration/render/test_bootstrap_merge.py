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
    preflight = source[: source.index("## Continue")]
    assert "CI is absent or uncertain, stop" in preflight
    assert "gh pr checks <number>" in preflight
    assert "A refusal stops finalize" in preflight


def test_finalize_delegates_only_after_its_completed_task_gates():
    """Compatibility must not bypass acceptance, document pre-flight or exact integration proof."""
    finalize = (ROOT / "src/skills/finalize/SKILL.md").read_text()
    harvest = (ROOT / "src/skills/harvest/SKILL.md").read_text()
    assert "testing acceptance" in finalize and "verification only" in finalize
    assert "Missing or failed proof stops the sequence" in finalize
    assert finalize.index("## Pre-flight") < finalize.index("## Continue")
    assert harvest.index("## 3. The branch") < harvest.index("## 4. The ticket")
    assert "A tracker closes only after step 3 verified the merged state" in harvest


def test_finalize_endings_preserve_foreign_repositories_and_unmerged_branches():
    """The compatibility ending must retain its no-merge authority and branch protection."""
    text = (ROOT / "src/skills/finalize/SKILL.md").read_text()
    endings = text[text.index("## Endings") : text.index("## Pre-flight")]
    assert "Verify read-only that the pull request is open" in endings
    assert "Never close, merge or edit" in endings
    assert "Keep both branches while the pull request is open" in endings
    harvest = (ROOT / "src/skills/harvest/SKILL.md").read_text()
    assert "git branch -d <branch>" in harvest and "never use `-D`" in harvest


def test_merge_requires_action_specific_approval_after_refusal():
    """Bug: a generic approval retries an action whose native approval was refused."""
    source = (ROOT / "src/skills/merge/SKILL.md").read_text()
    assert "do not retry it and do not work around it" in source
    assert "reply that names the merge" in source


def test_integration_requires_exact_commit_proof_without_workflow_dispatch():
    source = (ROOT / "src/skills/merge/integration.md").read_text()
    assert "dispatch a release or deployment workflow" in source
    assert "pending, failed, cancelled or skipped gate is not success" in source
