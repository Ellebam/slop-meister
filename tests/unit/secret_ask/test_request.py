"""Untrusted request text and credential files cannot redirect what the broker resolves."""

import pytest

from slopmeister.secret_ask.broker import REFERENCE_LIMIT, command, references
from slopmeister.secret_ask.config import private_token


@pytest.mark.parametrize("key", ["", "1A", "x y", "A" * 65])
def test_invalid_variable_names_are_refused(key):
    """Bug: a name the shell cannot export reaches the audit log and the panel."""
    with pytest.raises(ValueError):
        references({key: "op://Example/Demo/password"})


@pytest.mark.parametrize(
    "reference", ["plain-value", "op://A/B", "op://A/B/C?x y", "op://A/B/C\nx", "op://A/B/C/D/E"]
)
def test_only_literal_references_are_admitted(reference):
    """Bug: plain values or malformed references enter the request and audit log."""
    with pytest.raises(ValueError):
        references({"TOKEN": reference})


def test_section_and_query_references_are_admitted():
    """Bug: example-app's SSH key reference with its ssh-format query is refused."""
    assert references({"KEY": "op://example-app/SSH/private_key?ssh-format=openssh"})
    assert references({"X": "op://v/i/section/field"})


def test_reference_count_is_bounded():
    """Bug: an env file with hundreds of lines becomes an unbounded notification."""
    with pytest.raises(ValueError):
        references({f"V{i}": "op://A/B/C" for i in range(REFERENCE_LIMIT + 1)})
    with pytest.raises(ValueError):
        references({})


def test_command_keeps_empty_arguments_and_bounds_length():
    """Bug: an empty argument such as -c '' changes the displayed command, or a example-app
    target's multi-line sh -c script is refused."""
    assert command(["sh", "-c", ""]) == ["sh", "-c", ""]
    script = "set -e\n\tvaults=$(op vault list) || exit 1\nprintf '%s' \"$vaults\"\n"
    assert command(["sh", "-c", script]) == ["sh", "-c", script]
    with pytest.raises(ValueError):
        command(["sh", "-c", "bell\x07"])
    with pytest.raises(ValueError):
        command(["x" * 5000])
    with pytest.raises(ValueError):
        command("sh -c")


@pytest.mark.parametrize("mode", [0o644, 0o640])
def test_token_file_cannot_be_read_by_another_account(tmp_path, mode):
    """Bug: a world-readable token quietly becomes the service credential."""
    token = tmp_path / "token"
    token.write_text("synthetic")
    token.chmod(mode)
    with pytest.raises(ValueError):
        private_token(token)


def test_token_symlink_is_refused(tmp_path):
    """Bug: a credential path can be redirected outside the protected file."""
    target = tmp_path / "token"
    target.write_text("synthetic")
    target.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(OSError):
        private_token(link)
