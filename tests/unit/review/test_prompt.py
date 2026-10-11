"""Migrated cross-tool review regressions."""

from __future__ import annotations

from pathlib import Path

from slopmeister.review.prompt import ReviewTarget, build_review_prompt

CHECKS = (
    "secrets and sensitive-data handling",
    "untrusted inputs and trust-boundary validation",
    "authentication, authorization and privilege boundaries",
    "injection, unsafe evaluation and command execution",
    "output encoding, logging and data exposure",
    "filesystem and path safety including traversal and temporary-file permissions",
    "process isolation and lifecycle safety",
    "resource exhaustion, blocking and denial-of-service risks",
    "dependency and supply-chain integrity",
    "safe execution of target code during review or testing",
)


def test_prompt_asks_for_all_mandatory_security_lens_checks():
    """Escaping bug: one Security Lens copy can silently retain the old four checks."""
    prompt = build_review_prompt(ReviewTarget(prompt="Review."))
    sentence = next(
        line for line in prompt.splitlines() if line.startswith("Run the Security Lens")
    )
    agreement = (Path(__file__).resolve().parents[3] / "plots/code/plot.md").read_text()
    for check in CHECKS:
        assert check in sentence
        assert check in agreement
    assert "security_lens" in sentence
    assert "null" in sentence
    assert "1-based index" in sentence


def test_prompt_demands_the_smallest_remedy_without_weakening_safety():
    """A reviewer can create more machinery or mislabel a real safety boundary as excess."""
    prompt = build_review_prompt(ReviewTarget(prompt="Review."))
    assert "Challenge accidental complexity in the target and in your own remedies" in prompt
    assert "Prefer the smallest behavior-preserving remedy" in prompt
    assert "Report only findings that are valid, reachable and proportionate" in prompt
    assert "do not propose new machinery without demonstrated need" in prompt
    assert "Security, data-loss, irreversible-operation, explicit-authority and recovery" in prompt
    assert "mandatory, not overengineering" in prompt


def test_prompt_lets_the_reviewer_run_the_work_but_not_change_it():
    """Escaping bug: a reviewer told it is read-only judged tests it never ran."""
    prompt = build_review_prompt(ReviewTarget(prompt="Review."))
    assert "colleague's pull request" in prompt
    assert "Run any command or test" in prompt
    assert "Never change code or files" in prompt
    assert "read-only" not in prompt
