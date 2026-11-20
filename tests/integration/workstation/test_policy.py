"""Global restrictions preserve client settings and private approval data."""

import ast
import json
import os

import pytest

from slopmeister.render.permissions import memory_denies, permission_contract
from tests.integration.workstation.test_install import ROOT, machine, workstation


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_central_policy_installs_restrictions_without_session_allows(tmp_path, platform):
    home, bin_dir = machine(tmp_path)
    settings = home / ".claude/settings.json"
    settings.parent.mkdir()
    original = {
        "autoMemoryEnabled": True,
        "permissions": {
            "allow": ["Bash(personal-approval *)"],
            "deny": ["Read(~/.ssh/**)", "WebFetch", "Bash(personal-denial *)"],
        },
        "autoMode": {"allow": ["personal classifier rule"]},
        "private_setting": "do-not-print",
    }
    settings.write_text(json.dumps(original))
    saved = home / ".codex/rules/default.rules"
    saved.parent.mkdir(parents=True)
    saved.write_text('prefix_rule(pattern=["personal-approval"], decision="allow")\n')
    before = saved.read_bytes()
    result = workstation(home, bin_dir, "install", "--all", SLOPMEISTER_PLATFORM=platform)
    assert result.returncode == 0, result.stderr
    policy = home / ".codex/rules/permissions.rules"
    assert policy.is_file(), "The ordinary installer omitted the central global policy"
    parsed = {
        tuple(fields["pattern"]): fields["decision"]
        for node in ast.parse(policy.read_text()).body
        if (fields := {field.arg: ast.literal_eval(field.value) for field in node.value.keywords})
    }
    commands = permission_contract(ROOT / "src/permissions.toml")["command"]
    expected = {
        tuple(entry["prefix"].split()): {"deny": "forbidden", "needs_intent": "prompt"}[
            entry["decision"]
        ]
        for entry in commands
        if entry["decision"] != "allow" and not entry.get("terminal_input")
    }
    assert parsed == expected and set(parsed.values()) == {"forbidden", "prompt"}
    current = json.loads(settings.read_text())
    generated = json.loads((ROOT / "dist/claude/settings.json").read_text())
    assert current["permissions"] == {
        "allow": original["permissions"]["allow"],
        "deny": [
            *original["permissions"]["deny"],
            *[rule for rule in generated["permissions"]["deny"] if rule.startswith("Bash(")],
            *memory_denies(permission_contract(ROOT / "src/permissions.toml")),
        ],
    }
    assert current["autoMode"] == {
        "allow": original["autoMode"]["allow"],
        "soft_deny": generated["autoMode"]["soft_deny"],
    }
    assert current["private_setting"] == "do-not-print" and current["autoMemoryEnabled"] is False
    assert saved.read_bytes() == before
    assert "do-not-print" not in result.stdout + result.stderr
    assert "personal-approval" not in result.stdout + result.stderr


def test_policy_diff_never_echoes_live_content(tmp_path):
    home, bin_dir = machine(tmp_path)
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text(
        '{"permissions":{"allow":["Bash(private-approval *)"]},"private":"do-not-print"}'
    )
    (home / ".codex/rules").mkdir(parents=True)
    (home / ".codex/rules/permissions.rules").write_text("private-owned-file-content")
    (home / ".codex/rules/default.rules").write_bytes(b"\xffprivate-saved-approval")
    (home / ".codex/config.toml").write_text(
        'model_context_window = 272000\napi_token = "unrelated-secret-value"\n'
    )
    run = workstation(home, bin_dir, "diff")
    assert run.returncode == 0
    for marker in ("private-", "do-not-print", "unrelated-secret-value"):
        assert marker not in run.stdout + run.stderr
    assert "differs: .codex/config.toml model_context_window" in run.stdout
    assert "differs: .claude/settings.json central restrictions" in run.stdout
    assert "differs: .codex/rules/permissions.rules central restrictions" in run.stdout


@pytest.mark.parametrize(
    "original",
    [
        b'{"private":"do-not-print",',
        b'{"permissions":5}',
        b'{"permissions":{"deny":"private-denial"}}',
        b'{"autoMode":{"soft_deny":"private-denial"}}',
        b'{"autoMode":{"soft_deny":[5]}}',
    ],
)
def test_invalid_policy_preflight_preserves_every_home_entry(tmp_path, original):
    home, bin_dir = machine(tmp_path)
    path = home / ".claude/settings.json"
    path.parent.mkdir()
    path.write_bytes(original)
    result = workstation(home, bin_dir, "install", "--all")
    assert result.returncode == 1 and "nothing written" in result.stderr
    assert path.read_bytes() == original
    assert not (home / ".claude/CLAUDE.md").exists()
    assert not (home / ".codex").exists()
    assert not (home / ".slopmeister-backup").exists()
    assert "do-not-print" not in result.stdout + result.stderr


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
@pytest.mark.parametrize("name", [".claude/settings.json", ".codex/config.toml"])
def test_unsafe_policy_target_is_refused_without_following_or_blocking(tmp_path, kind, name):
    home, bin_dir = machine(tmp_path)
    path = home / name
    path.parent.mkdir()
    target = tmp_path / "untouched.json"
    target.write_text('{"private":"unchanged"}')
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    result = workstation(home, bin_dir, "install", name)
    assert result.returncode == 1 and "unsafe" in result.stderr
    assert target.read_text() == '{"private":"unchanged"}'
    assert not (home / ".slopmeister-backup").exists()


def test_named_policy_install_repairs_owned_decisions_and_leaves_other_entries(tmp_path):
    home, bin_dir = machine(tmp_path)
    policy = home / ".codex/rules/permissions.rules"
    policy.parent.mkdir(parents=True)
    original = b'prefix_rule(pattern=["op","read"],decision="allow")\n'
    policy.write_bytes(original)
    result = workstation(home, bin_dir, "install", ".codex/rules/permissions.rules")
    assert result.returncode == 0
    assert 'pattern=["op", "read"], decision="forbidden"' in policy.read_text()
    backups = list((home / ".slopmeister-backup").glob("*/.codex/rules/permissions.rules"))
    assert [path.read_bytes() for path in backups] == [original]
    assert not (home / ".claude").exists()
    assert not (home / ".codex/AGENTS.md").exists()


def test_policy_install_does_not_overwrite_a_concurrent_client_edit(tmp_path, monkeypatch):
    from slopmeister.errors import SlopmeisterError
    from slopmeister.workstation import rules

    home = tmp_path / "home"
    path = home / rules.CLAUDE_LIVE
    path.parent.mkdir(parents=True)
    original = b'{"private":"initial"}'
    changed = b'{"private":"client edit"}'
    path.write_bytes(original)
    backup = rules._backup

    def concurrent_edit(backups, name, content):
        backup(backups, name, content)
        path.write_bytes(changed)

    monkeypatch.setattr(rules, "_backup", concurrent_edit)
    with pytest.raises(SlopmeisterError, match="changed during install"):
        rules.install(home, tmp_path / "backups", rules.CLAUDE_LIVE)
    assert path.read_bytes() == changed
    assert (tmp_path / "backups" / rules.CLAUDE_LIVE).read_bytes() == original
    assert sorted(p.name for p in path.parent.iterdir()) == ["settings.json"]


def test_central_policy_backups_and_repeat_install_preserve_new_saved_approvals(tmp_path):
    home, bin_dir = machine(tmp_path)
    settings = home / ".claude/settings.json"
    settings.parent.mkdir()
    original = b'{"private":"do-not-print"}'
    settings.write_bytes(original)
    saved = home / ".codex/rules/default.rules"
    saved.parent.mkdir(parents=True)
    saved.write_text('prefix_rule(pattern=["personal-approval"],decision="allow")\n')
    result = workstation(
        home, bin_dir, "install", ".claude/settings.json", ".codex/rules/permissions.rules"
    )
    assert result.returncode == 0
    backups = list((home / ".slopmeister-backup").glob("*/.claude/settings.json"))
    assert [path.read_bytes() for path in backups] == [original]
    assert all(
        path.stat().st_mode & 0o777 == 0o600 and path.parent.stat().st_mode & 0o777 == 0o700
        for path in backups
    )
    saved.write_bytes(
        saved.read_bytes() + b'prefix_rule(pattern=["later-approval"],decision="allow")\n'
    )
    snapshot = {
        path: path.stat().st_mtime_ns
        for path in (settings, home / ".codex/rules/permissions.rules", saved)
    }
    repeat = workstation(
        home, bin_dir, "install", ".claude/settings.json", ".codex/rules/permissions.rules"
    )
    assert repeat.returncode == 0 and "Everything already up to date" in repeat.stdout
    assert {path: path.stat().st_mtime_ns for path in snapshot} == snapshot


def test_custom_soft_denials_survive_without_duplicate_central_entries(tmp_path):
    home, bin_dir = machine(tmp_path)
    settings = home / ".claude/settings.json"
    settings.parent.mkdir()
    central = json.loads((ROOT / "dist/claude/settings.json").read_text())["autoMode"]["soft_deny"]
    previous = [
        central[0],
        "private-soft-rule-one",
        "private-soft-rule-two",
        "private-soft-rule-one",
    ]
    settings.write_text(json.dumps({"autoMode": {"soft_deny": previous}}))
    first = workstation(home, bin_dir, "install", ".claude/settings.json")
    assert first.returncode == 0, first.stderr
    current = json.loads(settings.read_text())["autoMode"]["soft_deny"]
    assert current[: len(previous)] == previous
    assert all(rule in current for rule in central)
    assert all(current.count(rule) == 1 for rule in central if rule not in previous)
    before = settings.stat().st_mtime_ns
    repeat = workstation(home, bin_dir, "install", ".claude/settings.json")
    assert repeat.returncode == 0 and "Everything already up to date" in repeat.stdout
    assert settings.stat().st_mtime_ns == before
    assert "private-soft-rule" not in first.stdout + first.stderr + repeat.stdout + repeat.stderr


def test_missing_central_soft_rule_diffs_beside_custom_rules(tmp_path):
    home, bin_dir = machine(tmp_path)
    settings = home / ".claude/settings.json"
    settings.parent.mkdir()
    generated = json.loads((ROOT / "dist/claude/settings.json").read_text())
    current = {
        "permissions": {
            "deny": [r for r in generated["permissions"]["deny"] if r.startswith("Bash(")]
        },
        "autoMode": {"soft_deny": [*generated["autoMode"]["soft_deny"][:-1], "private-soft-rule"]},
    }
    settings.write_text(json.dumps(current))
    before = workstation(home, bin_dir, "diff")
    assert before.returncode == 0 and "differs: .claude/settings.json" in before.stdout
    repaired = workstation(home, bin_dir, "install", ".claude/settings.json")
    assert repaired.returncode == 0
    after = workstation(home, bin_dir, "diff")
    assert after.returncode == 0 and "unchanged: .claude/settings.json" in after.stdout
    assert "private-soft-rule" in json.loads(settings.read_text())["autoMode"]["soft_deny"]
    assert "private-soft-rule" not in before.stdout + repaired.stdout + after.stdout
