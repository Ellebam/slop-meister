"""Doctor answers that need no scratch home. Each names the bug that escapes without it."""

from contextlib import closing

import pytest

from slopmeister import cli
from slopmeister.workstation import doctor, host, memory
from tests.support.fakes import fake_binary, memory_database, path_with


@pytest.fixture(autouse=True)
def snapshots_stay_within_the_unit_test(tmp_path, monkeypatch):
    factory = memory.tempfile.TemporaryDirectory

    def temporary(**kwargs):
        return factory(**{**kwargs, "dir": tmp_path})

    monkeypatch.setattr(memory.tempfile, "TemporaryDirectory", temporary)


@pytest.mark.parametrize(
    "tool,variable", [("claude", "CLAUDE_CONFIG_DIR"), ("codex", "CODEX_HOME")]
)
def test_memory_checks_active_relocated_stores(tmp_path, monkeypatch, tool, variable):
    root = tmp_path / "relocated"
    name = "projects/example/memory" if tool == "claude" else "memories_v2"
    store = root / name
    store.mkdir(parents=True)
    (store / "note").touch()
    settings = "settings.json" if tool == "claude" else "config.toml"
    (root / settings).write_text(
        '{"autoMemoryEnabled": false}' if tool == "claude" else "[features]\nmemories = false\n"
    )
    monkeypatch.setenv(variable, str(root))
    found = memory.check(tmp_path / "normal", tool)
    assert found.status == "problem" and found.evidence == "private memory store is populated"


@pytest.mark.parametrize(
    "text,status",
    [
        (None, "problem"),
        ("{}", "problem"),
        ('{"autoMemoryEnabled": true}', "problem"),
        ('{"autoMemoryEnabled": false}', "ok"),
        ("[]", "problem"),
        ("", "unknown"),
        ("{", "unknown"),
    ],
)
def test_relocated_claude_switch_must_be_explicitly_false(tmp_path, monkeypatch, text, status):
    root = tmp_path / "relocated"
    root.mkdir()
    if text is not None:
        (root / "settings.json").write_text(text)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(root))
    found = memory.check(tmp_path / "normal", "claude")
    assert found.status == status
    if status == "problem":
        assert "switch is not false" in found.evidence
    if status == "unknown":
        assert "unreadable or unsafe" in found.evidence


def _account_home(tmp_path, monkeypatch, projects):
    home = tmp_path / "account"
    home.mkdir()
    (home / "settings.json").write_text('{"autoMemoryEnabled": false}')
    (home / "projects").symlink_to(projects, target_is_directory=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))


@pytest.mark.parametrize(("note", "status"), [(False, "ok"), (True, "problem")])
def test_account_home_shares_the_inspected_projects_folder(tmp_path, monkeypatch, note, status):
    """Bug: the memory row reads unknown in every Orca account home, or skips the shared store."""
    store = tmp_path / "normal/.claude/projects/example/memory"
    store.mkdir(parents=True)
    if note:
        (store / "note").touch()
    _account_home(tmp_path, monkeypatch, tmp_path / "normal/.claude/projects")
    assert memory.check(tmp_path / "normal", "claude").status == status


def test_projects_link_to_another_folder_stays_unsafe(tmp_path, monkeypatch):
    """Bug: accepting the account link also admits a store redirected somewhere unchecked."""
    (tmp_path / "elsewhere").mkdir()
    _account_home(tmp_path, monkeypatch, tmp_path / "elsewhere")
    assert memory.check(tmp_path / "normal", "claude").status == "unknown"


def test_empty_memory_and_general_session_database_are_not_defects(tmp_path):
    for name in ("memories", "memories_v2"):
        (tmp_path / ".codex" / name).mkdir(parents=True)
    (tmp_path / ".codex/memories/rollout_summaries").mkdir()
    (tmp_path / ".codex/state_5.sqlite").write_bytes(b"session state")
    (tmp_path / ".claude/projects/example/memory").mkdir(parents=True)
    database = memory_database(tmp_path / ".codex/memories_1.sqlite")
    database.execute("PRAGMA journal_mode=WAL")
    database.close()
    before = {p.name: p.read_bytes() for p in (tmp_path / ".codex").iterdir() if p.is_file()}
    assert all(memory.check(tmp_path, tool).status == "ok" for tool in ("claude", "codex"))
    assert {
        p.name: p.read_bytes() for p in (tmp_path / ".codex").iterdir() if p.is_file()
    } == before


@pytest.mark.parametrize("table", ["stage1_outputs", "jobs", "consolidation_progress"])
def test_memory_database_data_is_a_defect_without_exposing_values(tmp_path, table):
    path = tmp_path / ".codex/memories_1.sqlite"
    database = memory_database(path)
    if table == "consolidation_progress":
        database.execute("UPDATE consolidation_progress SET max_thread_count=1")
    else:
        database.execute(f"INSERT INTO {table} VALUES(?)", ("private-do-not-print",))
    database.commit()
    database.close()
    before = path.read_bytes()
    result = memory.check(tmp_path, "codex")
    assert result.status == "problem" and "private-do-not-print" not in result.evidence
    assert path.read_bytes() == before


def test_memory_database_reads_committed_wal_without_touching_live_files(tmp_path):
    path = tmp_path / ".codex/memories_1.sqlite"
    database = memory_database(path)
    try:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        database.execute("INSERT INTO stage1_outputs VALUES(?)", ("wal-private-do-not-print",))
        database.commit()
        before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
        result = memory.check(tmp_path, "codex")
        assert result.status == "problem" and "wal-private" not in result.evidence
        assert {p.name: p.read_bytes() for p in path.parent.iterdir()} == before
    finally:
        database.close()


def test_invalid_memory_database_is_unknown_without_disclosing_input(tmp_path):
    path = tmp_path / ".codex/memories_1.sqlite"
    path.parent.mkdir()
    path.write_bytes(b"private-invalid-database")
    result = memory.check(tmp_path, "codex")
    assert result.status == "unknown" and "private-invalid" not in result.evidence


def test_memory_snapshot_is_bounded_before_sqlite_parses_it(tmp_path):
    path = tmp_path / "memories_1.sqlite"
    with path.open("wb") as stream:
        stream.truncate(memory.MEMORY_READ_LIMIT + 1)
    with pytest.raises(ValueError, match="read limit"):
        memory._database_populated(path)


def test_changing_memory_database_is_unknown(tmp_path, monkeypatch):
    path = tmp_path / ".codex/memories_1.sqlite"
    memory_database(path).close()
    connect = memory.sqlite3.connect
    changed = []

    def concurrent(*args, **kwargs):
        if not changed:
            with closing(connect(path)) as database:
                database.execute("INSERT INTO stage1_outputs VALUES('concurrent-data')")
                database.commit()
            changed.append(True)
        return connect(*args, **kwargs)

    monkeypatch.setattr(memory.sqlite3, "connect", concurrent)
    assert memory.check(tmp_path, "codex").status == "unknown" and changed


def test_sqlite_never_opens_the_live_memory_database(tmp_path, monkeypatch):
    path = tmp_path / ".codex/memories_1.sqlite"
    memory_database(path).close()
    connect = memory.sqlite3.connect

    def private_copy(database, *args, **kwargs):
        assert str(database).split("?")[0] not in (str(path), path.as_uri())
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(memory.sqlite3, "connect", private_copy)
    assert memory.check(tmp_path, "codex").status == "ok"


def test_unreadable_memory_is_unknown(tmp_path, monkeypatch):
    store = tmp_path / ".codex/memories"
    store.mkdir(parents=True)
    original = type(store).iterdir

    def unreadable(path):
        if path == store:
            raise PermissionError("private-name-do-not-print")
        return original(path)

    monkeypatch.setattr(type(store), "iterdir", unreadable)
    result = memory.check(tmp_path, "codex")
    assert result.status == "unknown" and "private-name" not in result.evidence


@pytest.mark.parametrize(
    "tool,relative",
    [
        ("codex", ".codex/memories"),
        ("codex", ".codex/memories/nested/link"),
        ("claude", ".claude/projects/example"),
        ("codex", "Library/Application Support/orca/codex-runtime-home/home/config.toml"),
    ],
)
def test_memory_check_refuses_links_without_following_them(tmp_path, monkeypatch, tool, relative):
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "darwin")
    target = tmp_path / "unrelated"
    target.mkdir()
    store = tmp_path / relative
    store.parent.mkdir(parents=True)
    store.symlink_to(target, target_is_directory=True)
    assert memory.check(tmp_path, tool).status == "unknown"
    assert list(target.iterdir()) == []


@pytest.mark.parametrize(
    "platform,relative",
    [("darwin", "Library/Application Support/orca"), ("linux", ".config/orca")],
)
@pytest.mark.parametrize("defect", ["store", "switch"])
def test_orca_codex_runtime_is_checked_even_when_it_is_not_active(
    tmp_path, monkeypatch, platform, relative, defect
):
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", platform)
    root = tmp_path / relative / "codex-runtime-home/home"
    root.mkdir(parents=True)
    (root / "config.toml").write_text(
        "[features]\nmemories = " + ("true" if defect == "switch" else "false") + "\n"
    )
    if defect == "store":
        database = memory_database(root / "memories_1.sqlite")
        database.execute("INSERT INTO stage1_outputs VALUES(?)", ("private-do-not-print",))
        database.commit()
        database.close()
    found = memory.check(tmp_path, "codex")
    assert found.status == "problem" and "private" in found.evidence


@pytest.mark.parametrize(
    "text,status",
    [("[features]\nmemories = false\n", "ok"), ("[features]\n", "problem"), ("[broken", "unknown")],
)
def test_orca_codex_switch_must_be_explicitly_false(tmp_path, monkeypatch, text, status):
    data = tmp_path / "orca-data"
    root = data / "codex-runtime-home/home"
    root.mkdir(parents=True)
    (root / "config.toml").write_text(text)
    monkeypatch.setenv("ORCA_USER_DATA_PATH", str(data))
    assert memory.check(tmp_path, "codex").status == status


@pytest.mark.parametrize("fixed", ["missing", "executable", "not-executable"])
def test_codex_requires_the_fixed_launcher_path(tmp_path, monkeypatch, fixed):
    monkeypatch.setenv("HOME", str(tmp_path))
    prefix = tmp_path / "homebrew/bin"
    fake_binary(prefix, "codex", "exit 0")
    monkeypatch.setenv("PATH", str(prefix))
    if fixed != "missing":
        binary = fake_binary(tmp_path / ".local/bin", "codex", "exit 0")
        if fixed == "not-executable":
            binary.chmod(0o600)
    found = doctor._tool("codex")
    assert found.status == ("ok" if fixed == "executable" else "problem")
    if found.status == "problem":
        assert "~/.local/bin/codex" in found.evidence + found.fix


@pytest.mark.parametrize("tool", ("shellcheck", "jq"))
def test_missing_linux_system_tool_needs_the_operator(tmp_path, monkeypatch, tool):
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "linux")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert tool in doctor.TOOLS
    found = doctor._tool(tool)
    assert found.status == "problem" and found.evidence == "not on PATH"
    assert "ask the operator" in found.fix


def test_old_python_names_the_floor_before_any_command_loads():
    """Escaping bug, a new Mac's system python3 crashes on import instead of naming the floor."""
    assert cli.python_problem((3, 9, 6)) == (
        "Python 3.14 or newer is required, python3 here is 3.9.6"
    )
    assert cli.python_problem((3, 14, 0)) is None


def test_vault_precedence_is_argument_then_environment_then_default(tmp_path, monkeypatch):
    """Escaping bug, the chosen vault is validated but a later task receives another path."""
    monkeypatch.setenv("SLOPMEISTER_VAULT", str(tmp_path / "from-env"))
    assert doctor.vault_path(str(tmp_path / "from-cli"), tmp_path) == tmp_path / "from-cli"
    assert doctor.vault_path(None, tmp_path) == tmp_path / "from-env"
    monkeypatch.setenv("SLOPMEISTER_VAULT", "")
    assert doctor.vault_path(None, tmp_path) == tmp_path / ".slopmeister/vault"


def test_invalid_vaults_are_refused(tmp_path):
    assert "Directory not found" in doctor.vault_problem(tmp_path / "missing")
    (tmp_path / "empty/_system").mkdir(parents=True)
    assert "No Markdown files" in doctor.vault_problem(tmp_path / "empty")
    (tmp_path / "empty/_system/start.md").write_text("# Fixture\n")
    assert doctor.vault_problem(tmp_path / "empty") is None


@pytest.mark.parametrize("tool", ["gh", "glab"])
def test_hanging_probe_is_unknown_not_a_hang(tmp_path, monkeypatch, tool):
    """Bug: one stuck launchctl, gh or glab call stalls the whole report or reads as ok."""
    fake_binary(tmp_path, tool, "sleep 5")
    monkeypatch.setenv("PATH", path_with(tmp_path))
    monkeypatch.setattr(host, "TIMEOUT", 0.2)
    found = doctor.cli_login(tool)
    assert found.status == "unknown"
    assert "timed out" in found.evidence


@pytest.mark.parametrize("reply", ["not json", '{"other": true}'])
def test_unreadable_claude_login_is_unknown(tmp_path, monkeypatch, reply):
    """Bug: an unexpected auth reply reads as logged in, or as logged out when it is not."""
    fake_binary(tmp_path, "claude", f"printf '%s\\n' '{reply}'")
    monkeypatch.setenv("PATH", path_with(tmp_path))
    assert doctor.claude_login().status == "unknown"


@pytest.mark.parametrize(
    ("code", "logged_in", "expected"),
    [(1, "true", "unknown"), (1, "false", "problem"), (0, "true", "ok")],
)
def test_claude_login_needs_a_clean_exit_to_be_ok(tmp_path, monkeypatch, code, logged_in, expected):
    """Bug: a failed claude auth status that still printed loggedIn=true read as logged in."""
    fake_binary(tmp_path, "claude", f"printf '{{\"loggedIn\": {logged_in}}}\\n'; exit {code}")
    monkeypatch.setenv("PATH", path_with(tmp_path))
    assert doctor.claude_login().status == expected


def test_missing_login_tool_is_unknown_not_a_second_problem(tmp_path, monkeypatch):
    """Bug: a missing gh or glab is blamed twice, once as a tool and once as a login."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert doctor.cli_login("gh").status == "unknown"
    assert doctor.cli_login("glab").status == "unknown"
    assert doctor.claude_login().status == "unknown"


def test_glab_is_logged_in_when_one_host_is_despite_the_unused_default_host(tmp_path, monkeypatch):
    """Bug: glab fails the unused gitlab.com entry and exits 1, so a working login reads broken."""
    fake_binary(tmp_path, "glab", "echo 'x gitlab.com: 401'; echo 'Logged in to h as u'; exit 1")
    monkeypatch.setenv("PATH", path_with(tmp_path))
    found = doctor.cli_login("glab")
    assert found.status == "ok"
    assert found.evidence == "glab auth status exited 1, one host is logged in"
    fake_binary(tmp_path, "gh", "echo 'Logged in to h as u'; exit 1")
    assert doctor.cli_login("gh").status == "problem"
