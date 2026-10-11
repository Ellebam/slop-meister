"""Vault todo maintenance works through its delivered thin entry."""

from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "src/skills/vault-todos/scripts/vault_todos.py"


@pytest.mark.parametrize("legacy", (False, True))
@pytest.mark.parametrize("nested", (False, True))
def test_todo_cli_works_without_agent_agreement_and_preserves_unrelated_tasks(
    tmp_path, legacy, nested
):
    vault, task, start, args = _todo_case(tmp_path, legacy, nested)
    before = _snapshot(vault)
    dry = subprocess.run(args, cwd=start, capture_output=True, text=True)
    assert dry.returncode == 0, dry.stderr
    assert "DRY-RUN" in dry.stdout and "rolled=1, moved_done=1" in dry.stdout
    assert before == _snapshot(vault)
    apply = subprocess.run([*args, "--apply"], cwd=start, capture_output=True, text=True)
    assert apply.returncode == 0, apply.stderr
    _assert_todo(task)
    after = _snapshot(vault)
    assert set(before) == set(after)
    assert [path for path in before if before[path] != after[path]] == ["To-Do/example-app.md"]


def _todo_case(tmp_path, legacy, nested):
    vault = tmp_path / "vault"
    (vault / "_system").mkdir(parents=True)
    (vault / "To-Do").mkdir()
    if legacy:
        (vault / "AGENTS.md").write_text("Conflicting legacy instructions\n")
    original = (
        "# Tasks\n\n## Active\n\n"
        "- [ ] Overdue 📅 2026-09-01\n"
        "- [ ] Recurring 📅 2026-09-01 🔁 every day\n"
        "- [ ] Future 📅 2099-01-01\n"
        "- [x] Completed 📅 2026-09-01 ✅ 2026-09-10\n\n## Done\n"
    )
    task = vault / "To-Do/example-app.md"
    task.write_text(original)
    sibling = vault / "To-Do/example-notes.md"
    sibling.write_text("Unrelated tasks stay untouched\n")
    start = vault / "nested/deep" if nested else vault
    start.mkdir(parents=True, exist_ok=True)
    args = [sys.executable, str(HELPER), "--fields", "example-app", "--today", "2026-09-11"]
    if not nested:
        args += ["--root", str(vault)]
    return vault, task, start, args


def _snapshot(vault):
    return {
        str(path.relative_to(vault)): path.read_bytes()
        for path in vault.rglob("*")
        if path.is_file()
    }


def _assert_todo(task):
    active, done = task.read_text().split("## Done")
    assert "Overdue 📅 2026-09-11" in active
    assert "Recurring 📅 2026-09-01 🔁 every day" in active
    assert "Future 📅 2099-01-01" in active
    assert "Completed" not in active and "Completed 📅 2026-09-01 ✅ 2026-09-10" in done


def _vault(tmp_path, files):
    vault = tmp_path / "vault"
    (vault / "_system").mkdir(parents=True)
    (vault / "To-Do").mkdir()
    for name, text in files.items():
        (vault / "To-Do" / name).write_text(text)
    return vault


def _run(vault, *args):
    return subprocess.run(
        [sys.executable, str(HELPER), "--root", str(vault), "--today", "2026-09-11", *args],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("selection", (["--fields", "x", "Y"], ["--add", "X: One; y: Two"], []))
def test_todo_keys_come_from_the_task_files_in_the_vault(tmp_path, selection):
    vault = _vault(
        tmp_path,
        {
            "x.md": "## Active\n- [ ] Late 📅 2026-09-01\n## Done\n",
            "Y.md": (
                "## Active\n- [ ] Late 📅 2026-09-01\n- [ ] Later 📅 2026-09-02\n"
                "- [x] Finished 📅 2026-09-01 ✅ 2026-09-03\n## Done\n"
            ),
            "README.md": "# To-Do System\n",
        },
    )
    before = _snapshot(vault)
    result = _run(vault, *selection)
    assert result.returncode == 0, result.stderr
    added = "1" if selection[:1] == ["--add"] else "0"
    assert f"- x: rolled=1, moved_done=0, added={added}, changed=True" in result.stdout
    assert f"- y: rolled=2, moved_done=1, added={added}, changed=True" in result.stdout
    assert "readme" not in result.stdout.lower()
    assert before == _snapshot(vault)


@pytest.mark.parametrize("selection", (["--fields", "x", "nope"], ["--add", "nope: One"]))
def test_unknown_key_is_refused_with_the_available_keys(tmp_path, selection):
    vault = _vault(
        tmp_path,
        {"x.md": "## Active\n- [ ] Late 📅 2026-09-01\n## Done\n", "y.md": "## Active\n## Done\n"},
    )
    before = _snapshot(vault)
    result = _run(vault, *selection, "--apply")
    assert result.returncode != 0
    assert "Unknown field key: nope. Available: x, y" in result.stderr
    assert before == _snapshot(vault)


@pytest.mark.parametrize("kind", ("directory", "linked-file", "linked-folder"))
def test_only_regular_files_inside_the_vault_are_keys(tmp_path, kind):
    vault = _vault(tmp_path, {"x.md": "## Active\n## Done\n"})
    (tmp_path / "out").mkdir()
    outside = tmp_path / "out/z.md"
    outside.write_text("## Active\n- [ ] Late 📅 2026-09-01\n## Done\n")
    if kind == "directory":
        (vault / "To-Do/z.md").mkdir()
    elif kind == "linked-file":
        (vault / "To-Do/z.md").symlink_to(outside)
    else:
        (vault / "To-Do/x.md").unlink()
        (vault / "To-Do").rmdir()
        (vault / "To-Do").symlink_to(tmp_path / "out")
    default = _run(vault, "--apply")
    assert default.returncode == 0 and "- z:" not in default.stdout, default.stderr
    named = _run(vault, "--fields", "z", "--apply")
    assert "Unknown field key: z. Available:" in named.stderr
    assert outside.read_text() == "## Active\n- [ ] Late 📅 2026-09-01\n## Done\n"


def test_done_before_active_is_refused_without_writing(tmp_path):
    reversed_sections = "## Done\n- [x] Old\n## Active\n- [x] New ✅ 2026-09-10\n"
    vault = _vault(tmp_path, {"x.md": reversed_sections})
    result = _run(vault, "--apply")
    assert result.returncode != 0
    assert "To-Do/x.md: ## Done must come after ## Active" in result.stderr
    assert (vault / "To-Do/x.md").read_text() == reversed_sections


@pytest.mark.parametrize("heading", ("## Active", "## Done"))
def test_apply_writes_nothing_when_a_discovered_file_lacks_a_section(tmp_path, heading):
    good = "## Active\n- [ ] Late 📅 2026-09-01\n## Done\n"
    vault = _vault(tmp_path, {"a.md": good, "z.md": good.replace(heading, "## Other")})
    before = _snapshot(vault)
    result = _run(vault, "--apply")
    assert result.returncode != 0
    assert f"To-Do/z.md: Missing section {heading}" in result.stderr
    assert "Traceback" not in result.stderr
    assert before == _snapshot(vault)


def test_finished_task_moves_with_its_indented_lines(tmp_path):
    active = (
        "## Active\n\n"
        "- [ ] Open parent 📅 2099-01-01\n"
        "    - [x] finished child stays\n"
        "- [x] First 📅 2026-09-01 ✅ 2026-09-05\n"
        "    - first detail\n"
        "\tfirst tabbed note\n"
        "- [ ] Between 📅 2099-01-01\n"
        "- [x] Second 📅 2026-09-01 ✅ 2026-09-10\n"
        "  second detail\n"
        "\n## Done\n"
    )
    vault = _vault(tmp_path, {"x.md": active})
    result = _run(vault, "--fields", "x", "--apply")
    assert result.returncode == 0, result.stderr
    assert "- x: rolled=0, moved_done=2, added=0, changed=True" in result.stdout
    assert (vault / "To-Do/x.md").read_text() == (
        "## Active\n\n"
        "- [ ] Open parent 📅 2099-01-01\n"
        "    - [x] finished child stays\n"
        "- [ ] Between 📅 2099-01-01\n"
        "\n## Done\n"
        "- [x] Second 📅 2026-09-01 ✅ 2026-09-10\n"
        "  second detail\n"
        "- [x] First 📅 2026-09-01 ✅ 2026-09-05\n"
        "    - first detail\n"
        "\tfirst tabbed note\n"
    )


def test_existing_done_lines_keep_their_order_sub_lines_and_blank_lines(tmp_path):
    done = (
        "- [x] Old 📅 2026-08-01 ✅ 2026-08-02\n"
        "    - old detail\n"
        "- [x] Newer below older ✅ 2026-09-09\n"
        "\tplain note\n"
        "\nFree text\n"
    )
    moved = "- [x] New ✅ 2026-09-10\n  new detail\n"
    vault = _vault(tmp_path, {"x.md": "## Active\n" + moved + "## Done\n\n\n" + done})
    result = _run(vault, "--fields", "x", "--apply")
    assert result.returncode == 0, result.stderr
    assert (vault / "To-Do/x.md").read_text() == "## Active\n## Done\n\n\n" + moved + done


def test_addition_for_key_outside_explicit_customers_is_refused(tmp_path):
    late = "## Active\n- [ ] Late 📅 2026-09-01\n## Done\n"
    vault = _vault(tmp_path, {"example-client.md": late, "example-notes.md": late})
    before = _snapshot(vault)
    result = _run(
        vault, "--fields", "example-client", "--add", "example-notes: Read the guide", "--apply"
    )
    assert result.returncode != 0
    assert "Additions for keys not in --fields: example-notes" in result.stderr
    assert before == _snapshot(vault)


@pytest.mark.parametrize("missing", ("_system", "To-Do"))
def test_partial_vault_root_refuses_without_writing(tmp_path, missing):
    for folder in ("_system", "To-Do"):
        if folder != missing:
            (tmp_path / folder).mkdir()
    sentinel = tmp_path / "sentinel.md"
    sentinel.write_text("Keep me\n")
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--root",
            str(tmp_path),
            "--fields",
            "example-app",
            "--apply",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "Could not find vault root" in result.stderr
    assert sentinel.read_text() == "Keep me\n"
