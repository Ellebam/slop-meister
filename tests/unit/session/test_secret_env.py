"""The env file reader reads what the real op run reads, so the tier decision misses nothing."""

import pytest

from slopmeister.session.secret_env import environment


def test_env_file_forms_and_precedence(tmp_path, monkeypatch):
    """Bug: comments, export prefixes, quotes, expansion or literals break a real env file."""
    first = tmp_path / "first.env"
    first.write_text(
        "# comment\n\nexport TOKEN=op://Example/Item/credential\n"
        "NOTE=op://Example/Item/note # inline comment\n"
        "PLAIN='literal value # kept'\nBASE=Example Vault/My Item\n"
        'HOST="op://${BASE}/hostname"\nUSER_HOME=$HOME/x\n'
    )
    second = tmp_path / "second.env"
    second.write_text("TOKEN=op://Example/Other/credential\n")
    monkeypatch.setenv("HOME", "/h")
    monkeypatch.setenv("SHELL_REF", "op://Example/Shell/field?ssh-format=openssh")
    monkeypatch.setenv("TOKEN", "op://Example/Shell/overridden")
    literals, references = environment([str(first), str(second)])
    assert literals == {
        "PLAIN": "literal value # kept",
        "BASE": "Example Vault/My Item",
        "USER_HOME": "/h/x",
    }
    assert references == {
        "TOKEN": "op://Example/Other/credential",
        "NOTE": "op://Example/Item/note",
        "HOST": "op://Example Vault/My Item/hostname",
        "SHELL_REF": "op://Example/Shell/field?ssh-format=openssh",
    }


def test_empty_and_escaped_values_match_the_real_command(tmp_path):
    """Bug: EMPTY= crashes op run, and an escaped quote ends a value early, unlike the real op."""
    (tmp_path / "x.env").write_text(
        'EMPTY=\nTEXT="say \\"hello\\""\nSINGLE=\'a "b"\'\nKNOWN=k\nKEPT="\\$KNOWN and $KNOWN"\n'
    )
    literals, references = environment([str(tmp_path / "x.env")])
    assert references == {}
    assert literals == {
        "EMPTY": "",
        "TEXT": 'say "hello"',
        "SINGLE": 'a "b"',
        "KNOWN": "k",
        "KEPT": "$KNOWN and k",
    }


def test_escapes_read_in_one_pass_like_the_real_command(tmp_path):
    """Bug: a doubled backslash stays doubled, so a command receives a different literal."""
    (tmp_path / "x.env").write_text('TEXT="a\\\\b \\"q\\" \\$x"\n')
    literals, _ = environment([str(tmp_path / "x.env")])
    assert literals == {"TEXT": 'a\\b "q" $x'}


def test_multi_line_quoted_value_is_refused_not_misread(tmp_path):
    """Bug: a quoted multi-line value silently becomes a one-line secret reference."""
    (tmp_path / "x.env").write_text('KEY="first line\nsecond line"\n')
    with pytest.raises(ValueError, match="multi-line"):
        environment([str(tmp_path / "x.env")])


@pytest.mark.parametrize("value", ["op://A/B", "op://A/B/C?x y", "op://A/B/C/D/E"])
def test_malformed_references_are_refused_before_any_request(tmp_path, value):
    """Bug: a malformed reference reaches the notification or the real op."""
    (tmp_path / "x.env").write_text(f"X={value}\n")
    with pytest.raises(ValueError):
        environment([str(tmp_path / "x.env")])
