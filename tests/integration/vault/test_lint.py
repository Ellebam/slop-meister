"""Portable vault lint contracts over disposable notes."""

import os
from pathlib import Path
import subprocess

import pytest

from slopmeister.vault.runtime import lint

ROOT = Path(__file__).resolve().parents[3]
COMMAND = [str(ROOT / "bin/slopmeister"), "vault", "lint"]


def run(vault: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        COMMAND + list(args),
        env={
            **os.environ,
            "HOME": str(vault.parent / "home"),
            "SLOPMEISTER_VAULT": str(vault),
        },
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_area_resolves_supported_links_and_reports_only_broken_routes(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    area = vault / "fields/demo"
    (area / "nested").mkdir(parents=True)
    (vault / "other").mkdir()
    (area / "target.md").write_text("# Target\n\n## Exact Heading\n")
    (vault / "other/basename.md").write_text("# Other\n")
    (area / "note.md").write_text(
        "[[target]] [[target|alias]] [[target#Exact Heading]] [[basename]]\n"
        "[relative](target.md) [heading](target.md#exact-heading) [web](https://example.invalid)\n"
        "[[missing]] [gone](nested/gone.md)\n"
        "`[[inline-example]]`\n```md\n[[fenced-example]]\n```\n"
    )
    result = run(vault, "--area", "fields/demo")
    assert result.returncode == 1
    assert "fields/demo/note.md: [[missing]]" in result.stdout
    assert "fields/demo/note.md: [gone](nested/gone.md)" in result.stdout
    assert "example" not in result.stdout
    assert result.stdout.rstrip().endswith(
        "area fields/demo: alias-pipe rows 0, bare wikilinks 0, unresolved links 2"
    )


@pytest.mark.parametrize(
    "area", ["", ".", "/etc", "../", "fields/../other", "missing", "fields/demo/note.md"]
)
def test_area_refuses_uncontained_or_nonfolder_input(tmp_path: Path, area: str) -> None:
    vault = tmp_path / "vault"
    (vault / "fields/demo").mkdir(parents=True)
    (vault / "fields/demo/note.md").write_text("# Note\n")
    result = run(vault, "--area", area)
    assert result.returncode == 2 and result.stderr.startswith("refused: --area")
    assert "/etc/" not in result.stderr and "/private/tmp" not in result.stderr


def test_area_rejects_symlink_escape_and_checks_fragments(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    area = vault / "fields/demo"
    area.mkdir(parents=True)
    (area / "target.md").write_text("# Target\n\n## Present\n")
    (area / "note.md").write_text("[[target#Missing]] [[target#^block-id]] [[target#Present]]\n")
    (vault / "escape").symlink_to(tmp_path)
    refused = run(vault, "--area", "escape")
    assert refused.returncode == 2 and "resolves outside the vault" in refused.stderr
    result = run(vault, "--area", "fields/demo")
    assert result.returncode == 1
    assert "[[target#Missing]]" in result.stdout
    assert "unsupported fragment in [[target#^block-id]]" in result.stdout
    assert result.stdout.rstrip().endswith("unresolved links 2")


def test_global_mode_keeps_the_count_surface(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("| x | [[target|alias]] |\n[[README]]\n")
    result = run(vault)
    assert result.returncode == 1
    assert result.stdout.splitlines()[:2] == [
        "alias-pipe rows:  1 (must be 0)",
        "bare wikilinks:   1 (must be 0)",
    ]
    assert result.stdout.splitlines()[2] == "unresolved links: 2 (direct resolver)"


def test_heading_fragments_require_real_markdown_headings(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    area = vault / "fields/demo/headings"
    area.mkdir(parents=True)
    (area / "target.md").write_text("# Target\n\n## Encoded heading\n\n### Punctuation: A/B?\n")
    (area / "evidence.pdf").write_bytes(b"%PDF-1.4\n")
    (area / "alternate.markdown").write_text("# Alternate\n")
    (area / "note.md").write_text(
        "# Local heading\n\n[[target#Encoded heading]]\n"
        "[encoded](target.md#Encoded%20heading)\n[[target#Punctuation: A/B?]]\n"
        "[slug](target.md#punctuation-ab)\n[[#Local heading]]\n[local](#local-heading)\n"
        "[[evidence.pdf#page=3]]\n[evidence](evidence.pdf#page=2)\n"
        "[[alternate.markdown#Missing heading]]\n[[target#Missing heading]]\n"
        "[[target#^block-id]]\n`[[target#Inline example]]`\n"
        "```markdown\n[[target#Fenced example]]\n```\n"
    )
    result = run(vault, "--area", "fields/demo/headings")
    assert result.returncode == 1
    assert result.stdout.rstrip().endswith("unresolved links 3")
    assert "[[alternate.markdown#Missing heading]]" in result.stdout
    assert "[[target#Missing heading]]" in result.stdout
    assert "unsupported fragment in [[target#^block-id]]" in result.stdout
    assert "example" not in result.stdout


def test_area_skips_unavailable_notes_and_never_follows_note_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Escaping bug: an unavailable note crashes lint and a note symlink leaks outside text."""
    vault = tmp_path / "vault"
    area = vault / "fields/demo"
    area.mkdir(parents=True)
    (area / "readable.md").write_text("# Readable\n\n[[linked.md#Secret]]\n")
    unavailable = area / "unavailable.md"
    unavailable.write_text("[[missing]]\n")
    outside = tmp_path / "outside.md"
    outside.write_text("# Secret\n\n[[also-missing]]\n")
    (area / "linked.md").symlink_to(outside)
    native_read = Path.read_text

    def read_text(path: Path, *args, **kwargs) -> str:
        if path == unavailable:
            raise OSError(11, "Resource deadlock avoided")
        return native_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setenv("SLOPMEISTER_VAULT", str(vault))
    assert lint.run("fields/demo") == 1
    out = capsys.readouterr().out
    assert "fields/demo/readable.md: [[linked.md#Secret]]" in out
    assert out.rstrip().endswith("unresolved links 1")


def test_relative_override_from_inside_and_from_parent(tmp_path: Path) -> None:
    """Escaping bug: a relative SLOPMEISTER_VAULT crashed lint against its resolved root."""
    vault = tmp_path / "vault"
    (vault / "fields/demo").mkdir(parents=True)
    (vault / "fields/demo/note.md").write_text("[[missing]]\n")
    for relative, cwd in ((Path("."), vault), (Path("vault"), tmp_path)):
        whole = run(relative, cwd=cwd)
        assert whole.returncode == 0 and "Traceback" not in whole.stderr
        assert whole.stdout.splitlines()[2] == "unresolved links: 1 (direct resolver)"
        area = run(relative, "--area", "fields/demo", cwd=cwd)
        assert area.returncode == 1 and "Traceback" not in area.stderr
        assert area.stdout.rstrip().endswith("unresolved links 1")


def test_shallow_area_skips_subfolder_areas_but_resolves_into_them(tmp_path: Path) -> None:
    """Escaping bugs: a field-root close-out blocked by project defects it may not fix, a shallow
    resolver that breaks links into subfolders, and a default that silently stops recursing."""
    vault = tmp_path / "vault"
    project = vault / "fields/demo/project"
    project.mkdir(parents=True)
    (vault / "fields/demo/README.md").write_text("# Demo\n\n[[project/plan]]\n")
    (project / "plan.md").write_text("# Plan\n\n| x | [[plan|alias]] |\n[[README]]\n[[missing]]\n")
    shallow = run(vault, "--area", "fields/demo", "--shallow")
    assert shallow.returncode == 0, shallow.stdout
    assert shallow.stdout.rstrip().endswith(
        "area fields/demo: alias-pipe rows 0, bare wikilinks 0, unresolved links 0"
    )
    own = run(vault, "--area", "fields/demo/project")
    assert own.returncode == 1
    assert "fields/demo/project/plan.md: [[missing]]" in own.stdout
    assert own.stdout.rstrip().endswith(
        "area fields/demo/project: alias-pipe rows 1, bare wikilinks 1, unresolved links 1"
    )
    assert run(vault, "--area", "fields/demo").returncode == 1


def test_published_mirror_links_are_protected_and_never_fail_the_area(tmp_path: Path) -> None:
    """Bug: an area with a published page mirror never passes, nobody may fix the mirror's links."""
    vault = tmp_path / "vault"
    area = vault / "fields/demo"
    area.mkdir(parents=True)
    (area / "page.md").write_text("---\nstatus: published\n---\n\n[Sibling](Sibling-Page)\n")
    mirror_only = run(vault, "--area", "fields/demo")
    protected = "fields/demo/page.md: protected (published mirror) [Sibling](Sibling-Page)"
    assert mirror_only.returncode == 0 and protected in mirror_only.stdout, mirror_only.stdout
    assert mirror_only.stdout.rstrip().endswith("unresolved links 0, protected links 1")
    (area / "draft.md").write_text("---\nstatus: draft\n---\n\nstatus: published\n\n[[gone]]\n")
    (area / "unclosed.md").write_text("---\nstatus: published\n\n[[lost]]\n")
    mixed = run(vault, "--area", "fields/demo")
    assert mixed.returncode == 1 and protected in mixed.stdout
    assert "draft.md: [[gone]]" in mixed.stdout and "unclosed.md: [[lost]]" in mixed.stdout
    assert mixed.stdout.rstrip().endswith("unresolved links 2, protected links 1")
    assert run(vault).stdout.splitlines()[2] == "unresolved links: 3 (direct resolver)"


def test_empty_override_means_the_default_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Escaping bug: an empty override linted the working directory and reported it clean."""
    (tmp_path / "note.md").write_text("# Clean\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOPMEISTER_VAULT", "")
    assert lint.run(None) == 1
    assert capsys.readouterr().out.startswith("vault not reachable at ")


def conflict_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    for folder in ("fields/demo", "fields/other", ".obsidian"):
        (vault / folder).mkdir(parents=True)
    (vault / "fields/demo/note.md").write_text("# Note\n")
    (vault / "fields/demo/note.sync-conflict-drive.md").write_text("# Older\n")
    (vault / "fields/other/scan.sync-conflict-linux.pdf").write_text("older scan\n")
    (vault / ".obsidian/app.sync-conflict-linux.json").write_text("{}\n")
    return vault


def test_conflict_copies_fail_the_vault_wide_run_and_name_the_merge_steps(tmp_path: Path) -> None:
    """Bug: the older version a sync set aside stays unmerged because nothing reports it."""
    vault = conflict_vault(tmp_path)
    result = run(vault)
    assert result.returncode == 1
    assert result.stdout.splitlines()[3:6] == [
        "conflict copies:  2 (must be 0)",
        "  fields/demo/note.sync-conflict-drive.md",
        "  fields/other/scan.sync-conflict-linux.pdf",
    ]
    for step in ("vaultgit log -p -- <note>", "git merge-file <note> <base> <copy>", "older"):
        assert step in result.stdout
    (vault / "fields/demo/note.sync-conflict-drive.md").unlink()
    (vault / "fields/other/scan.sync-conflict-linux.pdf").unlink()
    clean = run(vault)
    assert clean.returncode == 0
    assert clean.stdout.splitlines()[3:] == ["conflict copies:  0 (must be 0)"]


def test_area_run_reports_the_conflict_copies_inside_the_area_only(tmp_path: Path) -> None:
    """Bug: a close-out reports a clean area that still holds an unmerged older version."""
    result = run(conflict_vault(tmp_path), "--area", "fields/demo")
    assert result.returncode == 1
    assert "fields/demo/note.sync-conflict-drive.md: conflict copy" in result.stdout
    assert "fields/other" not in result.stdout
    assert result.stdout.rstrip().endswith("unresolved links 0, conflict copies 1")
