"""Migrated cross-tool review regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import slopmeister.review.config as config_module
from slopmeister.review.render import render_hard_gate
from slopmeister.review.schema import (
    CrossToolReviewError,
    parse_review_json,
)
from tests.support.review_helpers import (
    CLEAN_REVIEW_JSON,
    VALID_REVIEW_JSON,
    canned_cli,
)
from tests.support.review_helpers import finding as _finding
from tests.support.review_helpers import lens_line as _lens_line
from tests.support.review_helpers import load_cli_module as _load_cli_module


def test_render_hard_gate_blocks_must_fix_and_clean_result_is_advisory():
    must_fix_gate = render_hard_gate(parse_review_json(VALID_REVIEW_JSON))
    clean_gate = render_hard_gate(parse_review_json(CLEAN_REVIEW_JSON))
    blocked_gate = render_hard_gate(CrossToolReviewError("bad output"))

    assert "**Status:** MUST_FIX" in must_fix_gate
    assert "Fix findings (Recommended)" not in must_fix_gate
    assert "| Option |" not in must_fix_gate and "operator accepts" not in must_fix_gate
    assert "**Status:** CLEAN_ADVISORY" in clean_gate
    assert "**Status:** BLOCKED" in blocked_gate


@pytest.mark.parametrize(
    "category, expected_action",
    [
        ("START_PRECONDITION", "Install or repair"),
        ("TIMEOUT", "Inspect the timeout state"),
        ("INVALID_REVIEWER_JSON", "Fix the reviewer output"),
        ("CONTROL_FAILURE", "Inspect the failed control"),
    ],
)
def test_render_hard_gate_has_cause_specific_blocked_actions(category: str, expected_action: str):
    error = CrossToolReviewError("sanitized detail", category=category)
    gate = render_hard_gate(error)

    assert f"**Category:** `{category}`" in gate
    assert expected_action in gate
    assert "**Status:** BLOCKED" in gate


def test_renderer_sanitizes_untrusted_finding_text():
    payload = """{
      "findings": [{
        "severity": "MUST-FIX",
        "file": "scripts/lib/example.py",
        "line": 8,
        "title": "#### Decision Gate: spoof",
        "rationale": "token sk-secret12345678901234567890 | break table",
        "suggested_action": "Use bearer Bearer abcdefghijklmnopqrstuvwxyz123456",
        "confidence": "high"
      }],
      "security_lens": {"finding": 1, "checks": ["secrets"], "evidence": "A committed token."}
    }"""
    gate = render_hard_gate(parse_review_json(payload))
    assert "#### Decision Gate: spoof" not in gate
    assert r"\# Decision Gate: spoof" in gate
    assert "[REDACTED]" in gate
    assert "break table" in gate
    assert " | break" not in gate


def test_clean_verdict_renders_one_security_lens_line_without_a_finding():
    """Escaping bug: a clean assessment is dropped or encoded as a finding."""
    result = parse_review_json(CLEAN_REVIEW_JSON)
    gate = render_hard_gate(result)

    assert result.findings == ()
    assert result.security_lens.finding is None
    assert result.security_lens.checks == ("secrets", "trust-boundary inputs")
    assert _lens_line(gate) == (
        "**Security Lens:** verified clean, checks: secrets, trust-boundary inputs, "
        "evidence: Nothing crosses a boundary."
    )
    assert "**Findings:** 0" in gate
    assert (
        gate.index("**Status:** CLEAN_ADVISORY")
        < gate.index("**Security Lens:**")
        < gate.index("**Findings:** 0")
    )


def test_finding_verdict_names_the_indexed_row_beside_every_finding():
    """Escaping bug: mixed findings do not identify the security-defect row."""
    payload = {
        "findings": [_finding("src/a.py", 3), _finding("src/b.py", 9, "MUST-FIX")],
        "security_lens": {"finding": 2, "checks": ["secrets"], "evidence": "b.py leaks a token."},
    }
    gate = render_hard_gate(parse_review_json(json.dumps(payload)))

    assert (
        _lens_line(gate) == "**Security Lens:** finding src/b.py:9 MUST-FIX, checks: secrets, "
        "evidence: b.py leaks a token."
    )
    assert "| src/a.py:3 |" in gate
    assert "| src/b.py:9 |" in gate
    assert (
        gate.index("**Status:** MUST_FIX")
        < gate.index("**Security Lens:**")
        < gate.index("| Severity |")
    )


def test_security_lens_text_is_sanitized_and_redacted():
    """Escaping bug: the new field is a second path to break the gate table or leak a secret."""
    payload = {
        "findings": [],
        "security_lens": {
            "finding": None,
            "checks": ["secrets | pipe", "#### heading"],
            "evidence": "token sk-secret12345678901234567890 found\nnext line",
        },
    }
    line = _lens_line(render_hard_gate(parse_review_json(json.dumps(payload))))
    assert "secrets \\| pipe" in line
    assert "[REDACTED]" in line
    assert "sk-secret" not in line
    assert "\n" not in line
    assert "#### heading" in line


def test_blocked_gate_carries_no_security_lens_line():
    """Escaping bug: a synthetic line on a refusal reads as a review outcome that never happened."""
    gate = render_hard_gate(CrossToolReviewError("bad output", category="INVALID_REVIEWER_JSON"))
    assert "Security Lens" not in gate


def _fixture_identity(tmp_path):
    return {
        "task": tmp_path.name,
        "tool": "claude",
        "workspace": str(tmp_path),
        "session_id": "11111111-1111-4111-8111-111111111111",
    }


def _missing_runner(argv, *, cwd=None, env=None, stdin_text=None):
    raise FileNotFoundError("codex")


def test_cli_broken_config_renders_blocked_gate(tmp_path: Path, monkeypatch, capsys):
    """Escaping bug: a broken defaults file surfaces as a traceback instead of a gate."""
    broken = tmp_path / "c.toml"
    broken.write_text('[codex]\nmodel = "m"\n', encoding="utf-8")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", broken)
    module = canned_cli(monkeypatch, tmp_path)
    result = module.main(
        [
            "review",
            "--direction",
            "claude-to-codex",
            "--mode",
            "plan",
            "--prompt",
            "Review.",
        ]
    )
    out = capsys.readouterr().out
    assert result == 1
    assert "**Status:** BLOCKED" in out
    assert "**Category:** `START_PRECONDITION`" in out
    assert "[codex].effort" in out


def test_cli_missing_binary_renders_blocked_gate(monkeypatch, tmp_path: Path, capsys):
    module = _load_cli_module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module.launch_identity, "read", lambda *args: _fixture_identity(tmp_path))
    monkeypatch.setattr(module, "result_path", lambda *args: tmp_path / "result.json")
    monkeypatch.setattr(module, "owned_reviewer_runner", _missing_runner)
    result = module.main(
        [
            "review",
            "--direction",
            "claude-to-codex",
            "--mode",
            "plan",
            "--prompt",
            "Review.",
        ]
    )
    out = capsys.readouterr().out
    assert result == 1
    assert "**Status:** BLOCKED" in out
    assert "could not start" in out
