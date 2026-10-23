"""Kickoff adherence checks preserve every legacy refusal and diagnostic."""

from pathlib import Path
import subprocess

import pytest

from tests.support.trees import write

ROOT = Path(__file__).resolve().parents[3]
CHECK = [str(ROOT / "bin/slopmeister"), "kickoff"]
FIXTURES = ROOT / "tests/data/kickoff"
FULL = FIXTURES / "restatements.md"
TRIMMED = FIXTURES / "minimal.md"


def run_check(path: Path | None = None, stdin: str | None = None):
    argv = list(CHECK)
    if path is not None:
        argv.append(str(path))
    return subprocess.run(argv, input=stdin, capture_output=True, text=True)


def with_paragraph(tmp_path: Path, name: str, paragraph: str) -> Path:
    return write(tmp_path, name, TRIMMED.read_text() + "\n" + paragraph + "\n")


def test_synthetic_kickoff_reports_the_six_restatements() -> None:
    result = run_check(FULL)
    expected = f"""kickoff does not adhere: {FULL} (875 bytes, 10 paragraphs)
line 7: restates read-first, carried by the agreement loads automatically
line 7: restates notes-file, carried by the spine paragraph of the agreement
line 7: restates spine-run, carried by the mode line
line 15: restates dummy-shape, carried by the one message of the agreement
line 17: restates review-halts, carried by the review section of the agreement
line 17: restates close-out, carried by harvest or finalize, which the operator types
"""
    assert result.returncode == 1
    assert result.stdout == expected


def test_trimmed_kickoff_adheres() -> None:
    result = run_check(TRIMMED)
    assert result.returncode == 0
    assert result.stdout.startswith("kickoff adheres:")


def test_missing_mode_is_refused(tmp_path: Path) -> None:
    path = write(tmp_path, "no-mode.md", "".join(TRIMMED.read_text().splitlines(keepends=True)[2:]))
    result = run_check(path)
    assert result.returncode == 1
    assert "Mode: spine" in result.stdout


def test_codex_kickoff_form_adheres(tmp_path: Path) -> None:
    path = write(tmp_path, "codex-form.md", "fixture-command\n\n" + TRIMMED.read_text())
    result = run_check(path)
    assert result.returncode == 0, result.stdout


def test_task_check_fact_is_not_a_restatement(tmp_path: Path) -> None:
    paragraph = (
        "`task check` is red on main for a drift this branch did not cause, record it and move on."
    )
    result = run_check(with_paragraph(tmp_path, "near-miss.md", paragraph))
    assert result.returncode == 0, result.stdout


def test_stdin_uses_the_same_checks_as_a_file() -> None:
    result = run_check(Path("-"), FULL.read_text())
    assert result.returncode == 1
    assert "line 7: restates read-first" in result.stdout


def test_missing_or_absent_argument_exits_two(tmp_path: Path) -> None:
    missing = run_check(tmp_path / "does-not-exist.md")
    absent = run_check()
    assert missing.returncode == 2
    assert absent.returncode == 2


PROBES = {
    "read-first": (
        "Read `AGENTS.md` in full first, then read the issue.",
        "the agreement loads automatically",
    ),
    "notes-file": (
        "Create `ISSUE-7-NOTES.md` and keep the four frozen headings.",
        "the spine paragraph of the agreement",
    ),
    "dummy-shape": (
        "Ask every open choice in the dummy shape, one decision per message.",
        "the one message of the agreement",
    ),
    "review-halts": (
        "Both external review gates apply and each is launched once by the operator. "
        "Never start one yourself.",
        "the review section of the agreement",
    ),
    "close-out": (
        "Close out at every pause or completion.",
        "harvest or finalize, which the operator types",
    ),
    "spine-run": ("Run the whole seven-step spine in this one worker.", "the mode line"),
    "writing-style": (
        "No em dashes and no mid-sentence semicolons.",
        "the writing style rule of the agreement",
    ),
    "field-facts": ("No field facts in the repository.", "the security section of the agreement"),
    "dist-generated": (
        "`dist/` is generated, never edit it by hand.",
        "the project rules of the slopmeister",
    ),
    "task-check": ("Run `task check` before every halt.", "the project rules of the slopmeister"),
    "debug-first": ("Debug first on every error before halting.", "the global layer"),
    "commit-messages": (
        "One imperative line per commit and no attribution trailer.",
        "the global layer",
    ),
}


@pytest.mark.parametrize("rule", PROBES)
def test_every_rule_has_a_matching_probe(tmp_path: Path, rule: str) -> None:
    paragraph, home = PROBES[rule]
    result = run_check(with_paragraph(tmp_path, f"probe-{rule}.md", paragraph))
    assert result.returncode == 1
    assert f"line 15: restates {rule}, carried by {home}\n" in result.stdout


def test_rule_table_has_every_expected_probe() -> None:
    result = subprocess.run([*CHECK, "--rules"], capture_output=True, text=True)
    rules = {line.split("\t", 1)[0] for line in result.stdout.splitlines()}
    assert result.returncode == 0
    assert rules == set(PROBES)


def test_two_rules_in_one_paragraph_are_both_reported(tmp_path: Path) -> None:
    paragraph = "Read `AGENTS.md` first and create `ISSUE-1-NOTES.md`."
    result = run_check(with_paragraph(tmp_path, "two-rules.md", paragraph))
    assert result.stdout.count("line 15:") == 2


def test_crlf_input_keeps_size_paragraphs_and_lines(tmp_path: Path) -> None:
    trimmed = write(tmp_path, "crlf.md", TRIMMED.read_text().replace("\n", "\r\n"))
    full = write(tmp_path, "crlf-full.md", FULL.read_text().replace("\n", "\r\n"))
    adhering = run_check(trimmed)
    refused = run_check(full)
    assert adhering.returncode == 0 and "7 paragraphs" in adhering.stdout
    assert (
        refused.stdout.splitlines()[0]
        == f"kickoff does not adhere: {full} (875 bytes, 10 paragraphs)"
    )
    assert "line 15: restates dummy-shape" in refused.stdout


def test_live_sibling_constraint_adheres(tmp_path: Path) -> None:
    paragraph = (
        "Another worker owns `src/skills/close-out/SKILL.md`, do not edit it, and leave "
        "`SIBLING-NOTES.md` alone."
    )
    result = run_check(with_paragraph(tmp_path, "sibling.md", paragraph))
    assert result.returncode == 0, result.stdout


def test_ten_step_wording_trips_spine_rule(tmp_path: Path) -> None:
    paragraph = "Run the whole ten-step spine in this one worker."
    result = run_check(with_paragraph(tmp_path, "ten-step-spine.md", paragraph))
    assert result.returncode == 1
    assert "line 15: restates spine-run, carried by the mode line\n" in result.stdout


def test_stdin_refusal_reports_normalized_size() -> None:
    result = run_check(Path("-"), "x\n")
    assert result.returncode == 1
    assert result.stdout.splitlines()[0] == "kickoff does not adhere: stdin (1 bytes, 1 paragraphs)"


def test_undecodable_bytes_are_checked_not_crashed(tmp_path: Path) -> None:
    """Escaping bug, a kickoff pasted with a stray byte crashes the checker with a traceback."""
    path = tmp_path / "stray-byte.md"
    path.write_bytes(b"Mode: spine\n\n\xff run the close-out now\n")
    result = run_check(path)
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert "line 3: restates close-out" in result.stdout
