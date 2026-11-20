"""The doctor reports each requirement from its own evidence and writes nothing."""

from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import shutil
import time

import pytest

from slopmeister import paths
from slopmeister.workstation import doctor, manifest, rules
from tests.integration.workstation.test_install import machine, workstation
from tests.support.fakes import fake_binary, memory_database

TOOLS = (
    *("task", "uv", "gh", "glab", "claude", "codex"),
    *("rg", "op", "zsh", "lsof", "shellcheck", "jq"),
)
# These read fixed system paths no scratch home can stand in for, the unit tests own them.
HOST_BOUND = {"sleep-guard", "service-actions"}
RUNNING = "printf 'state = running\\n'"
ORCA_UP = (
    "case \"$1\" in status) printf '%s\\n' "
    '\'{"ok":true,"result":{"app":{"running":true},"runtime":{"reachable":true}}}\';; '
    'agent) printf \'%s\\n\' \'{"ok":true,"result":{"enabled":true,"statuses":['
    '{"agent":"claude","state":"installed","managedHooksPresent":true},'
    '{"agent":"codex","state":"installed","managedHooksPresent":true}]}}\';; esac'
)


DENY = "Bash(gh auth token *)"
PRIVATE = "Bash(private-live-approval *)"


def healthy(tmp_path: Path, platform: str = "darwin") -> tuple[Path, Path]:
    home, bin_dir = machine(tmp_path)
    (home / manifest.VAULT_REPOSITORY).mkdir(parents=True)
    (home / manifest.VAULT_REPOSITORY / "HEAD").write_text("ref: refs/heads/main\n")
    install = workstation(home, bin_dir, "install", "--all", SLOPMEISTER_PLATFORM=platform)
    assert install.returncode == 0
    vault = home / paths.DEFAULT_VAULT
    (vault / "_system").mkdir(parents=True)
    (vault / "note.md").write_text("# note\n")
    (vault.parent / doctor.BUNDLE).parent.mkdir()
    (vault.parent / doctor.BUNDLE).write_bytes(b"bundle")
    for tool in TOOLS:
        fake_binary(bin_dir, tool, "exit 0")
    fake_binary(home / ".local/bin", "codex", "exit 0")
    fake_binary(bin_dir, "claude", "printf '{\"loggedIn\": true}\\n'")
    fake_binary(bin_dir, "launchctl", RUNNING)
    fake_binary(bin_dir, "orca", ORCA_UP)
    return home, bin_dir


def results(home: Path, bin_dir: Path, platform: str = "darwin") -> dict[str, dict]:
    run = workstation(home, bin_dir, "doctor", SLOPMEISTER_PLATFORM=platform)
    assert run.returncode == 0, run.stderr
    found = json.loads(run.stdout)
    assert all(set(item) == {"name", "status", "evidence", "fix"} for item in found)
    assert all(item["evidence"] and item["fix"] for item in found)
    return {item["name"]: item for item in found}


def tree(root: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in sorted(root.rglob("*"))
    }


def test_healthy_machine_reports_every_requirement_ok(tmp_path):
    """Bug: a requirement silently drops out of the report or reads ok with no evidence."""
    found = results(*healthy(tmp_path))
    assert {name for name, item in found.items() if item["status"] != "ok"} <= HOST_BOUND
    expected = {f"tool:{tool}" for tool in ("git", *TOOLS)} | {
        "login:gh",
        "login:glab",
        "login:claude",
        "login:codex",
        f"launchd:{manifest.VAULT_LABEL}",
        f"launchd:{manifest.CLAUDE_LABEL}",
        "orca:runtime",
        "orca:hooks",
        "home-install",
        "memory:claude",
        "memory:codex",
        "vault",
        "vault-repository",
        "vault-history",
        "vault-local",
    }
    assert set(found) == expected | HOST_BOUND


def test_doctor_writes_nothing(tmp_path):
    """Bug: the read-only report changes the home it inspects, including LaunchAgents."""
    home, bin_dir = healthy(tmp_path)
    before = tree(home)
    results(home, bin_dir)
    assert tree(home) == before


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.parametrize(
    "relative",
    [
        ".claude/projects/example/memory/MEMORY.md",
        ".codex/memories/MEMORY.md",
        ".codex/memories_v2/summary.md",
        ".codex/memories_1.sqlite",
        ".codex/memories_1.sqlite-wal",
    ],
)
def test_doctor_reports_remaining_memory_without_exposing_its_text(tmp_path, platform, relative):
    home, bin_dir = healthy(tmp_path, platform)
    store = home / relative
    store.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as resources:
        if ".sqlite" in store.name:
            database = resources.enter_context(
                closing(memory_database(store.with_name("memories_1.sqlite")))
            )
            database.execute(
                "PRAGMA journal_mode=WAL"
                if store.name.endswith("-wal")
                else "PRAGMA journal_mode=DELETE"
            )
            database.execute(
                "INSERT INTO stage1_outputs VALUES(?)", ("private-memory-do-not-print",)
            )
            database.commit()
        else:
            store.write_bytes(b"private-memory-do-not-print")
            store.chmod(0)
        before = store.stat().st_mtime_ns
        found = results(home, bin_dir, platform)
        tool = "claude" if ".claude/" in relative else "codex"
        assert found[f"memory:{tool}"]["status"] == "problem"
        assert "populated" in found[f"memory:{tool}"]["evidence"]
        assert "private-memory-do-not-print" not in json.dumps(found)
        assert store.stat().st_mtime_ns == before


@pytest.mark.parametrize("tool", ["claude", "codex"])
def test_doctor_reports_reenabled_switch_as_home_install_defect(tmp_path, tool):
    home, bin_dir = healthy(tmp_path)
    path = home / f".{tool}" / ("settings.json" if tool == "claude" else "config.toml")
    text = path.read_text()
    path.write_text(
        text.replace('"autoMemoryEnabled": false', '"autoMemoryEnabled": true')
        if tool == "claude"
        else text.replace("memories = false", "memories = true")
    )
    found = results(home, bin_dir)
    assert found["home-install"]["status"] == "problem"
    assert str(path.relative_to(home)) in found["home-install"]["evidence"]


def _missing_tool(home, bin_dir):
    # A user-level tool, so no system path on any machine can hold a real one.
    (bin_dir / "uv").unlink()


def _gh_logged_out(home, bin_dir):
    fake_binary(bin_dir, "gh", "echo 'You are not logged into any GitHub hosts' >&2; exit 1")


def _glab_logged_out(home, bin_dir):
    fake_binary(bin_dir, "glab", "echo 'No GitLab instances have been authenticated' >&2; exit 1")


def _claude_logged_out(home, bin_dir):
    fake_binary(bin_dir, "claude", "printf '{\"loggedIn\": false}\\n'")


def _claude_agent_unloaded(home, bin_dir):
    script = f'case "$2" in *{manifest.CLAUDE_LABEL}) exit 113;; *) {RUNNING};; esac'
    fake_binary(bin_dir, "launchctl", script)


def _vault_agent_unloaded(home, bin_dir):
    script = f'case "$2" in *{manifest.VAULT_LABEL}) exit 113;; *) {RUNNING};; esac'
    fake_binary(bin_dir, "launchctl", script)


def _claude_agent_stopped(home, bin_dir):
    stopped = "printf 'state = not running\\n'"
    script = f'case "$2" in *{manifest.CLAUDE_LABEL}) {stopped};; *) {RUNNING};; esac'
    fake_binary(bin_dir, "launchctl", script)


def _orca_closed(home, bin_dir):
    reply = '{"ok":true,"result":{"app":{"running":false},"runtime":{"reachable":false}}}'
    fake_binary(bin_dir, "orca", f"printf '%s\\n' '{reply}'")


def _home_entry_changed(home, bin_dir):
    (home / ".claude/CLAUDE.md").write_text("edited by hand\n")


def _vault_missing(home, bin_dir):
    (home / paths.DEFAULT_VAULT / "note.md").unlink()


def _vault_repository_empty(home, bin_dir):
    (home / manifest.VAULT_REPOSITORY / "HEAD").unlink()


def _vault_repository_missing(home, bin_dir):
    shutil.rmtree(home / manifest.VAULT_REPOSITORY)


def _bundle_missing(home, bin_dir):
    ((home / paths.DEFAULT_VAULT).parent / doctor.BUNDLE).unlink()


def _bundle_stale(home, bin_dir):
    old = time.time() - 3 * 24 * 60 * 60
    os.utime((home / paths.DEFAULT_VAULT).parent / doctor.BUNDLE, (old, old))


def _deny_rule_absent(home, bin_dir):
    live = home / rules.CLAUDE_LIVE
    settings = json.loads(live.read_text())
    settings["permissions"]["deny"].remove(DENY)
    settings["permissions"].setdefault("allow", []).append(PRIVATE)
    live.write_text(json.dumps(settings))


def _live_rules_unreadable(home, bin_dir):
    (home / rules.CLAUDE_LIVE).write_text("{ not json")


@pytest.mark.parametrize(
    ("breakage", "name"),
    [
        (_missing_tool, "tool:uv"),
        (_gh_logged_out, "login:gh"),
        (_glab_logged_out, "login:glab"),
        (_claude_logged_out, "login:claude"),
        (_claude_agent_unloaded, f"launchd:{manifest.CLAUDE_LABEL}"),
        (_vault_agent_unloaded, f"launchd:{manifest.VAULT_LABEL}"),
        (_claude_agent_stopped, f"launchd:{manifest.CLAUDE_LABEL}"),
        (_orca_closed, "orca:runtime"),
        (_home_entry_changed, "home-install"),
        (_vault_missing, "vault"),
        (_vault_repository_missing, "vault-repository"),
        (_vault_repository_empty, "vault-repository"),
        (_bundle_missing, "vault-history"),
        (_bundle_stale, "vault-history"),
        (_deny_rule_absent, "home-install"),
        (_live_rules_unreadable, "home-install"),
    ],
)
def test_each_breakage_is_a_problem_with_evidence(tmp_path, breakage, name):
    """Bug: a broken requirement reads ok, or another requirement takes the blame."""
    home, bin_dir = healthy(tmp_path)
    breakage(home, bin_dir)
    found = results(home, bin_dir)
    assert found[name]["status"] == "problem"
    blamed = {key for key, item in found.items() if item["status"] == "problem"}
    # A closed Orca cannot answer the hooks question, which is unknown, not a problem.
    assert blamed - HOST_BOUND == {name}


def test_a_glab_login_report_never_carries_the_command_output(tmp_path):
    """Bug: glab names its hosts in the status output, and the report passes them on."""
    home, bin_dir = healthy(tmp_path)
    fake_binary(bin_dir, "glab", "echo 'private-host.example token: glpat-secret'; exit 1")
    run = workstation(home, bin_dir, "doctor")
    assert "private-host" not in run.stdout + run.stderr
    assert "glpat" not in run.stdout + run.stderr


def test_entries_waiting_for_the_vault_repository_are_not_reported_ok(tmp_path):
    """Bug: the exclude file waiting for the vault repository read as a matching home install."""
    home, bin_dir = healthy(tmp_path)
    _vault_repository_missing(home, bin_dir)
    found = results(home, bin_dir)["home-install"]
    assert found["status"] == "unknown"
    assert f"{manifest.VAULT_REPOSITORY}/info/exclude" in found["evidence"]


def test_a_missing_deny_rule_reports_owned_policy_and_no_live_content(tmp_path):
    """Bug: a deny rule missing from the live file stays invisible, or live approvals leak."""
    home, bin_dir = healthy(tmp_path)
    _deny_rule_absent(home, bin_dir)
    run = workstation(home, bin_dir, "doctor")
    found = {item["name"]: item for item in json.loads(run.stdout)}
    assert "differs: .claude/settings.json" in found["home-install"]["evidence"]
    assert "private-live-approval" not in run.stdout + run.stderr


def test_a_stopped_job_is_named_with_its_log(tmp_path):
    """Bug: the job stops and the agent that finds it has no cause and no place to look."""
    home, bin_dir = healthy(tmp_path)
    _bundle_stale(home, bin_dir)
    found = results(home, bin_dir)["vault-history"]
    assert "older than two days" in found["evidence"]
    assert "vault-commit.log" in found["fix"] and "docs/vault-history-scheduled.md" in found["fix"]


def test_vault_walk_skips_a_vanished_note_only(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOPMEISTER_PLATFORM", "darwin")
    note = tmp_path / "moving.md"
    note.touch()
    lstat = Path.lstat
    for error in (FileNotFoundError, PermissionError):

        def race(path, error=error):
            if path == note:
                raise error
            return lstat(path)

        monkeypatch.setattr(Path, "lstat", race)
        if error is FileNotFoundError:
            assert doctor._vault_local(tmp_path)[0].status == "ok"
        else:
            with pytest.raises(PermissionError):
                doctor._vault_local(tmp_path)
