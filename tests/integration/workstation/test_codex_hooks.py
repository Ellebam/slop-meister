"""The home install adds the prompt record and memory guard hooks to Codex's hooks file and keeps
every other hook.

It also trusts both in Codex's config, so no person approves them in `/hooks` on each machine.
"""

import json
from pathlib import Path
import tomllib

import pytest

from slopmeister.workstation import codex_hooks, manifest
from tests.integration.workstation.test_install import machine, workstation

ORCA_GROUP = {"hooks": [{"type": "command", "command": ": orca-agent-hook-form=1; true"}]}
OURS = {
    "hooks": [
        {"type": "command", "command": "~/.local/bin/slopmeister-prompt notice", "timeout": 10}
    ]
}
GUARD = {
    "matcher": "^(apply_patch|Bash)$",
    "hooks": [
        {
            "type": "command",
            "command": "~/.local/bin/slopmeister-prompt guard"
            " '~/.claude/projects/*/memory' '~/.codex/memories' '~/.codex/memories_v2' || exit 2",
            "timeout": 30,
        }
    ],
}
OLD_GUARD = {
    "matcher": "^(apply_patch|Bash)$",
    "hooks": [{"type": "command", "command": "~/.local/bin/slopmeister-prompt guard ~/old"}],
}
RETIRED = {"hooks": [{"type": "command", "command": "~/.claude/prompt-notice.sh", "timeout": 10}]}


def hooks_file(home, document):
    path = home / ".codex/hooks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document if isinstance(document, str) else json.dumps(document))
    return path


def test_retired_group_is_replaced_in_place_and_orca_groups_stay(tmp_path):
    """Bug: the migration dropped Orca's hooks or left the retired script registered."""
    home, bin_dir = machine(tmp_path)
    original = {
        "hooks": {
            "Stop": [ORCA_GROUP],
            "PermissionRequest": [ORCA_GROUP, RETIRED, {"matcher": "x", **ORCA_GROUP}],
            "PreToolUse": [ORCA_GROUP, OLD_GUARD],
        }
    }
    path = hooks_file(home, original)
    before = path.read_bytes()
    preview = workstation(home, bin_dir, "diff")
    assert "differs: .codex/hooks.json PermissionRequest group" in preview.stdout
    assert path.read_bytes() == before
    assert (
        workstation(
            home, bin_dir, "install", *manifest.HOOK_RUNTIME, ".codex/hooks.json"
        ).returncode
        == 0
    )
    assert json.loads(path.read_text()) == {
        "hooks": {
            "Stop": [ORCA_GROUP],
            "PermissionRequest": [ORCA_GROUP, OURS, {"matcher": "x", **ORCA_GROUP}],
            "PreToolUse": [ORCA_GROUP, GUARD],
        }
    }
    backups = list((home / ".slopmeister-backup").glob("*/.codex/hooks.json"))
    assert [saved.read_bytes() for saved in backups] == [before]
    again = workstation(home, bin_dir, "diff").stdout
    assert "unchanged: .codex/hooks.json" in again


def test_hook_install_requires_its_executable_and_modules_before_any_write(tmp_path):
    home, bin_dir = machine(tmp_path)
    helper, guard, *others = manifest.HOOK_RUNTIME
    for selected, missing in (((), helper), ((helper, *others), guard)):
        result = workstation(home, bin_dir, "install", ".codex/hooks.json", *selected)
        assert result.returncode and missing in result.stderr
        assert not (home / ".codex/hooks.json").exists()
        assert not (home / helper).exists()
    assert workstation(home, bin_dir, "install", *manifest.HOOK_RUNTIME).returncode == 0
    (home / helper).chmod(0o600)
    assert helper in workstation(home, bin_dir, "install", ".codex/hooks.json").stderr
    assert workstation(home, bin_dir, "install", helper, ".codex/hooks.json").returncode == 0


def test_missing_file_gets_only_our_groups(tmp_path):
    home, bin_dir = machine(tmp_path)
    assert (
        workstation(
            home, bin_dir, "install", *manifest.HOOK_RUNTIME, ".codex/hooks.json"
        ).returncode
        == 0
    )
    path = home / ".codex/hooks.json"
    expected = {"hooks": {"PermissionRequest": [OURS], "PreToolUse": [GUARD]}}
    assert json.loads(path.read_text()) == expected
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("broken", ["invalid", "shape", "link"])
def test_unusable_hooks_file_stops_the_whole_install_before_any_write(tmp_path, broken):
    """Bug: a bad hooks file failed midway and left earlier migration writes in place."""
    home, bin_dir = machine(tmp_path)
    if broken == "link":
        target = hooks_file(tmp_path, {"hooks": {}})
        (home / ".codex").mkdir()
        (home / ".codex/hooks.json").symlink_to(target)
    else:
        shape = {"hooks": {"PermissionRequest": {}}}
        hooks_file(home, "{ not json" if broken == "invalid" else shape)
    message = "unsafe symlink" if broken == "link" else "unreadable: .codex/hooks.json"
    assert message in workstation(home, bin_dir, "diff").stdout
    result = workstation(home, bin_dir, "install", "--all")
    assert result.returncode != 0 and "nothing written" in result.stderr.lower()
    assert not (home / ".local/bin/slopmeister-prompt").exists()
    assert not (home / ".slopmeister-backup").exists()


def test_a_broken_hooks_file_beside_a_current_config_is_named_in_the_diff(tmp_path):
    """Bug: the config's trust check raised on the hooks file and ended the whole diff."""
    home, bin_dir = machine(tmp_path)
    for item in (".codex/hooks.json", ".codex/config.toml"):
        assert workstation(home, bin_dir, "install", *manifest.HOOK_RUNTIME, item).returncode == 0
    hooks_file(home, "{ not json")
    preview = workstation(home, bin_dir, "diff")
    assert "unreadable: .codex/hooks.json" in preview.stdout, preview.stderr


def test_trust_hash_is_the_one_codex_computes(monkeypatch):
    """Bug: Codex skipped the hook because its trust entry had another key or hash."""
    # The operator's /hooks approval in Codex 0.166 wrote this entry for the 10 second group.
    monkeypatch.setitem(codex_hooks.GROUP["hooks"][0], "timeout", 10)
    assert codex_hooks.trust(Path("/h"))[0] == (
        "/h/.codex/hooks.json:permission_request:0:0",
        "sha256:6e5ffafb6d5968007b8a663f50be913897903911d7feffc2258124785ae7ba6f",
    )
    # The guard's matcher is part of its identity, the native memory test proves Codex agrees.
    assert codex_hooks.trust(Path("/h"))[1][0] == "/h/.codex/hooks.json:pre_tool_use:0:0"


ORCA_TRUST = (
    '[hooks.state."{hooks}:permission_request:0:0"]\nenabled = true\ntrusted_hash = "sha256:orca"\n'
)
STALE = (
    '[hooks.state."{hooks}:permission_request:1:0"]\n'
    '{enabled}trusted_hash = "sha256:old" # by hand\n'
)


@pytest.mark.parametrize("enabled", ["", "enabled = false\n"])
def test_stale_trust_is_replaced_in_its_own_table_with_one_backup(tmp_path, enabled):
    """Bug: a changed hook stayed untrusted on a new machine, or the install changed the operator's
    own switch or failed on a second backup of the same file."""
    home, bin_dir = machine(tmp_path)
    hooks_file(home, {"hooks": {"PermissionRequest": [ORCA_GROUP, OURS]}})
    hooks = home / ".codex/hooks.json"
    config = home / ".codex/config.toml"
    config.write_text(
        "model_context_window = 1\n[hooks.state]\n\n" + ORCA_TRUST.format(hooks=hooks)
        + STALE.format(hooks=hooks, enabled=enabled) + "[features]\nmemories = true\n"
    )  # fmt: skip
    before = tomllib.loads(config.read_text())
    preview = workstation(home, bin_dir, "diff").stdout
    assert "differs: .codex/config.toml" in preview
    assert ("disabled in /hooks: a Slopmeister hook" in preview) is bool(enabled)
    assert workstation(home, bin_dir, "install", ".codex/config.toml").returncode == 0
    after = tomllib.loads(config.read_text())
    (key, digest), (guard, guard_digest) = codex_hooks.trust(home)
    assert key.endswith(":permission_request:1:0")
    assert after["hooks"]["state"][key] == before["hooks"]["state"][key] | {"trusted_hash": digest}
    entries = before["hooks"]["state"] | {
        key: after["hooks"]["state"][key],
        guard: {"trusted_hash": guard_digest},
    }
    assert after["hooks"]["state"] == entries
    assert len(list((home / ".slopmeister-backup").glob("*/.codex/config.toml"))) == 1
    status = "differs" if enabled else "unchanged"
    assert f"{status}: .codex/config.toml" in workstation(home, bin_dir, "diff").stdout
    config.write_text(config.read_text().replace(digest, "sha256:old"))
    assert "differs: .codex/config.toml" in workstation(home, bin_dir, "diff").stdout
