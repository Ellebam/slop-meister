"""Migrated cross-tool review regressions."""

from __future__ import annotations

import json
import time

import pytest

from slopmeister.review.redact import redact, sanitize_text
from slopmeister.review.render import render_hard_gate
from slopmeister.review.schema import (
    parse_review_json,
)
from tests.support.review_helpers import (
    env_with_scrubbed_api_keys,
)


def test_env_with_scrubbed_api_keys_helper_removes_metered_auth_keys():
    parent, child = env_with_scrubbed_api_keys()
    assert parent["SAFE_VALUE"] == "removed"
    assert child == {
        "PATH": "/usr/bin",
        "HOME": "/Users/tester",
        "USER": "tester",
        "TMPDIR": "/tmp/tester",
        "LANG": "de_DE.UTF-8",
        "LC_ALL": "C.UTF-8",
        "LC_CTYPE": "UTF-8",
    }
    assert child["PATH"] == "/usr/bin"
    assert child["HOME"] == "/Users/tester"
    assert "OPENAI_API_KEY" not in child
    assert "ANTHROPIC_API_KEY" not in child


def test_child_env_scrubs_openai_and_anthropic_api_keys():
    parent, child = env_with_scrubbed_api_keys()
    rendered = redact(str(parent))
    assert "OPENAI_API_KEY" in rendered
    assert "ANTHROPIC_API_KEY" in rendered
    assert "sk-openai-test" not in rendered
    assert "SAFE_VALUE" not in child
    assert child["PATH"] == "/usr/bin"
    assert child["HOME"] == "/Users/tester"


def test_redaction_handles_common_secret_shapes():
    text = (
        "OPENAI_API_KEY=sk-" + "openai12345678901234567890 "
        "ANTHROPIC_API_KEY=sk-" + "anthropic12345678901234567890 "
        "Bearer abcdefghijklmnopqrstuvwxyz123456 "
        "op://vault/item/field "
        "secret_trackerlike123456789 "
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    )
    redacted = redact(text)
    assert "sk-openai" not in redacted
    assert "sk-anthropic" not in redacted
    assert "Bearer abc" not in redacted
    assert "op://vault" not in redacted
    assert redacted.count("[REDACTED]") >= 5


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
        "github_pat_" + "11ABCDEFG0abcdefghijklmn",
        "AKIAIOSFODNN7EXAMPLE",
        "xoxb-1234567890-abcdefghij",
        "AIza" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q",
        "glpat-" + "aBcDeFgHiJkLmNoPqRsT",
    ],
)
def test_redaction_covers_common_prefixed_credentials(secret: str):
    """Escaping bug: a reviewer quoting a hard-coded token it found prints and persists it."""
    assert secret not in redact(f"token {secret} found")
    payload = {
        "findings": [
            {
                "severity": "MUST-FIX",
                "file": "config.py",
                "line": 3,
                "title": "Hard-coded credential",
                "rationale": f"The value {secret} is committed.",
                "suggested_action": "Rotate it.",
                "confidence": "high",
            }
        ],
        "security_lens": {
            "finding": 1,
            "checks": ["secrets"],
            "evidence": f"Committed value {secret}.",
        },
    }
    assert secret not in render_hard_gate(parse_review_json(json.dumps(payload)))


def test_redaction_keeps_a_commit_hash():
    sha = "9af9f99c0ffee0ddba11f00d5e1ec7ed01234567"
    assert sha in redact(f"see {sha} on main")


def test_redaction_preserves_long_test_identifiers():
    """Masking ordinary identifiers destroys quoted evidence and regression names."""
    name = "test_detached_tester_survives_launcher_exit_and_collect_is_idempotent"
    assert redact(name) == name


@pytest.mark.parametrize(
    "text,value",
    [
        ("GITHUB_TOKEN=token-fixture", "token-fixture"),
        ("password: password-fixture", "password-fixture"),
        ('service_api_key: "two word fixture"', "two word fixture"),
        ("SECRET='quoted fixture'", "quoted fixture"),
        ("OPENAI_API_KEY: key-fixture", "key-fixture"),
        ("AWS_ACCESS_KEY_ID: id-fixture", "id-fixture"),
        ('AWS_SECRET_ACCESS_KEY="two word fixture"', "two word fixture"),
    ],
)
def test_redaction_masks_explicit_credential_labels(text, value):
    """A clearly labelled credential must not rely on a recognizable value prefix."""
    masked = redact(text)
    assert value not in masked
    assert "[REDACTED]" in masked
    assert masked.endswith("[REDACTED]")
    assert redact(masked) == masked
    assert redact("token_count=12 password_length: 20 release: ordinary-value") == (
        "token_count=12 password_length: 20 release: ordinary-value"
    )


@pytest.mark.parametrize(
    "label,secret",
    [
        ("password", "plain-fixture"),
        ("password", 'prefix"private-suffix'),
        ("ANTHROPIC_BASE_URL", "plain-fixture"),
    ],
)
def test_redaction_masks_json_quoted_credentials_without_losing_neighboring_evidence(label, secret):
    text = json.dumps({label: secret, "note": "retained evidence"})
    masked = redact(text)
    assert "plain-fixture" not in masked and "private-suffix" not in masked
    assert "[REDACTED]" in masked and "retained evidence" in masked
    assert redact(masked) == masked


def test_sanitizing_terminal_controls_keeps_printable_unicode():
    text = "café 日本語 \x9b31m RED \x9d0;title\x07 \u202eevil"
    safe = sanitize_text(text)
    assert all(char not in safe for char in ("\x9b", "\x9d", "\x07", "\u202e"))
    assert "café 日本語" in safe and "evil" in safe


def test_json_depth_failure_does_not_fall_back_to_escaped_secret_text():
    text = "[" * 2000 + json.dumps(json.dumps({"password": "deep-fixture"})) + "]" * 2000
    masked = redact(text)
    assert "deep-fixture" not in masked
    assert "JSON exceeds decoding limits" in masked


def test_redaction_keeps_hyphenated_scenario_labels():
    """Credential test-case names in actual tester output are not credential assignments."""
    text = "prefixed-credential: status=blocked newline-credential: status=blocked"
    assert redact(text) == text


def test_redaction_masks_url_user_information():
    """Escaping bug: a credential in a URL argument survived into a leftover process listing."""
    assert redact("clone https://user:pw-fixture@host/r") == "clone https://[REDACTED]@host/r"
    assert redact("https://token-fixture@host/r") == "https://[REDACTED]@host/r"
    assert redact("https://host/r@v1 user@host") == "https://host/r@v1 user@host"


@pytest.mark.parametrize(
    "text",
    [
        "--token flag-fixture",
        "--token=flag-fixture",
        "--github-token flag-fixture",
        "--api-key flag-fixture",
        "--user alice:flag-fixture",
        "--proxy-user bob:flag-fixture",
        "--auth flag-fixture",
    ],
)
def test_redaction_masks_credential_flag_values(text):
    """Escaping bug: a secret passed as a separate flag value survived into a process listing."""
    masked = redact(f"helper {text} --verbose")
    assert "flag-fixture" not in masked and masked.endswith("[REDACTED] --verbose")
    assert redact(masked) == masked
    for kept in ("--token-file path --sort-key name", "--token --verbose"):
        assert redact(kept) == kept


def test_redaction_masks_a_credential_flag_value_on_the_next_line():
    """Escaping bug: a timeout log exposed a flag value printed on its own line."""
    assert redact("--token\nflag-fixture") == "--token\n[REDACTED]"
    assert redact("--token\n--verbose") == "--token\n--verbose"


def test_redaction_masks_a_flag_value_after_blank_lines():
    """Escaping bug: blank stderr lines left a flag value visible in the timeout tail."""
    for separator in ("\n\n", "\n \n", "\r"):
        assert redact(f"--token{separator}flag-fixture") == f"--token{separator}[REDACTED]"
    assert redact("--token\n\n--verbose") == "--token\n\n--verbose"


def test_redaction_does_not_rescan_long_flag_like_runs():
    """Escaping bug: reviewer stderr could stall timeout reporting after the process stopped."""
    text = "a--" * 10_000
    start = time.perf_counter()
    assert redact(text) == text
    assert time.perf_counter() - start < 2.0
