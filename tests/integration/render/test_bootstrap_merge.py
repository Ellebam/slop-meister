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


def test_merge_requires_action_specific_approval_after_refusal():
    """Bug: a generic approval retries an action whose native approval was refused."""
    source = (ROOT / "src/skills/merge/SKILL.md").read_text()
    assert "do not retry it and do not work around it" in source
    assert "reply that names the merge" in source


def test_integration_requires_exact_commit_proof_without_workflow_dispatch():
    source = (ROOT / "src/skills/merge/integration.md").read_text()
    assert "dispatch a release or deployment workflow" in source
    assert "pending, failed, cancelled or skipped gate is not success" in source
