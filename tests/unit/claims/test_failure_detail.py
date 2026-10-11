"""A failed claim transport says what the child printed, without credentials."""

import sys

import pytest

from slopmeister.claims import github


def test_detail_is_the_first_line_bounded_printable_and_without_credentials():
    """Bug: a token in a remote URL reached the launcher output and its logs."""
    stderr = "\nfatal: unable to access 'https://user:token@host/x.git/': 403\x1b[0m\nsecond line\n"
    assert github.detail(stderr) == ": fatal: unable to access 'https://host/x.git/': 403?[0m"
    assert github.detail("x" * 500) == ": " + "x" * github.DETAIL_LIMIT
    assert github.detail(" \n") == ""
    assert github.detail("see https://u:p@ss@host/a@b") == ": see https://host/a@b"


def test_failed_command_carries_the_first_stderr_line():
    """Bug: a bare exit code hid why git or gh failed."""
    script = "import sys; sys.stderr.write('HTTP 401: Bad credentials\\nhint\\n'); sys.exit(1)"
    with pytest.raises(ValueError) as error:
        github.command([sys.executable, "-c", script])
    assert str(error.value).endswith("operation failed (1): HTTP 401: Bad credentials")
