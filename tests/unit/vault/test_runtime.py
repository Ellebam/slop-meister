"""Small vault-runtime units that do not need a subprocess or repository."""

import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from slopmeister.vault.runtime import lint, obsidian, repository, retro
from slopmeister.vault.runtime import retro_legacy as legacy
from slopmeister.vault.runtime.__main__ import _parser


def test_runtime_spills_to_machine_state_not_a_checkout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("RETRO_SPILL_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert legacy.spill_dir() == tmp_path / ".local/state/slopmeister/retro-spill"


def test_retro_fsyncs_the_failure_spill(tmp_path: Path, monkeypatch) -> None:
    synced = []
    monkeypatch.setenv("RETRO_SPILL_DIR", str(tmp_path / "spill"))
    monkeypatch.setattr(retro.os, "fsync", synced.append)
    args = SimpleNamespace(repo="fixture", task="task", note="fixture.md")
    assert legacy._spill("entry\n", args) == 1
    assert len(synced) == 1
    assert next((tmp_path / "spill").glob("*.md")).read_text() == "entry\n"


def test_retro_has_no_second_vault_selector() -> None:
    argv = [
        "retro",
        "--repo",
        "r",
        "--task",
        "t",
        "--title",
        "x",
        "--tool",
        "c",
        "--model",
        "m",
        "--vault",
        "other",
    ]
    with pytest.raises(SystemExit):
        _parser().parse_args(argv)


def test_retro_rejects_cli_rewritten_and_table_input() -> None:
    assert retro.input_problem("--repo", "a|b", table=True) == "--repo cannot carry a pipe"
    assert retro.input_problem("--title", r"a\nb") == (
        "--title carries a literal backslash-n or backslash-t sequence"
    )
    assert retro.input_problem("--task", "one line") is None


def test_heading_matches_text_slug_and_percent_encoding(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("# Top\n\n## Punctuation: A/B?\n")
    assert lint.heading_exists(note, "Punctuation: A/B?")
    assert lint.heading_exists(note, "punctuation-ab")
    assert lint.heading_exists(note, "Punctuation%3A%20A%2FB%3F")
    assert not lint.heading_exists(note, "Missing")


def test_missing_obsidian_binary_is_an_optional_adapter_failure(monkeypatch) -> None:
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(obsidian.subprocess, "Popen", missing)
    assert obsidian.call(["vault=obsidian", "search", "query=term"])[0] == 127


def test_note_bytes_refuses_a_dataless_note_and_names_the_drive_mirror(
    tmp_path: Path, monkeypatch
) -> None:
    """Escaping bug: a placeholder is read as an empty note and the retro log is overwritten."""
    (tmp_path / "note.md").write_bytes(b"")
    monkeypatch.setattr(repository, "_dataless", lambda path: True)
    with pytest.raises(OSError, match="Drive mirror.*find .* -flags \\+dataless"):
        repository.note_bytes("note.md", tmp_path)


def test_note_bytes_refuses_symlink_and_parent_escape(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("private\n")
    (vault / "linked.md").symlink_to(outside)
    with pytest.raises(OSError, match="symlink"):
        repository.note_bytes("linked.md", vault)
    with pytest.raises(OSError, match="vault-relative"):
        repository.note_bytes("../outside.md", vault)


def test_retro_spills_without_overwriting_a_dataless_note(tmp_path: Path, monkeypatch) -> None:
    note = tmp_path / "fixture.md"
    note.write_bytes(b"remote bytes\n")
    monkeypatch.setenv("SLOPMEISTER_VAULT_LOCKED", "1")
    monkeypatch.setenv("RETRO_SPILL_DIR", str(tmp_path / "spill"))
    monkeypatch.setattr(
        repository, "note_bytes", lambda *args: (_ for _ in ()).throw(OSError("dataless"))
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("one\ntwo\nthree\n"))
    args = SimpleNamespace(
        repo="fixture",
        task="task",
        title="title",
        tool="codex",
        model="model",
        note="fixture.md",
    )
    assert legacy.run(args) == 1
    spills = list((tmp_path / "spill").glob("*.md"))
    assert len(spills) == 1 and "- one\n- two\n- three\n" in spills[0].read_text()
    assert note.read_bytes() == b"remote bytes\n"


def test_retro_names_the_machine_and_has_no_cost_field(monkeypatch) -> None:
    """Bugs: an entry does not say which machine wrote it, a dotted host name puts the domain
    into the log, and the cost field nobody fills returns to the command and the log table."""
    monkeypatch.setattr(retro.socket, "gethostname", lambda: "box.home.example")
    base = ["retro", "--repo", "r", "--task", "t", "--title", "x", "--tool", "c", "--model", "m"]
    args = _parser().parse_args(base)
    table = "| Repository | Tool | Model | Machine |\n|---|---|---|---|\n| r | c | m | box |\n"
    assert table in retro._entry(args, ["one", "two", "three"])
    with pytest.raises(SystemExit):
        _parser().parse_args([*base, "--cost", "0"])
