"""Native trust updates preserve unrelated projects, including disconnected folders."""

import json
from pathlib import Path
import tomllib

import pytest

from slopmeister.install import trust
from slopmeister.install.trust import TrustRequest


def _claude_store(path: Path, live: Path) -> dict:
    data = {
        "userID": "account",
        "hasCompletedOnboarding": True,
        "projects": {
            str(live): {"hasTrustDialogAccepted": False, "lastCost": 1.5},
            "/gone/worktree": {
                "hasTrustDialogAccepted": True,
                "allowedTools": ["Read"],
                "mcpServers": {"docs": {"command": "docs"}},
            },
        },
    }
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o600)
    return data


def test_store_edit_preserves_account_state(tmp_path):
    """Trusting one project must preserve account state and absent foreign projects."""
    store, live = tmp_path / ".claude.json", tmp_path / "repo"
    live.mkdir()
    original = _claude_store(store, live)
    trust.trust(TrustRequest("write", store, str(live)), "claude")
    after = json.loads(store.read_text())
    assert {k: v for k, v in after.items() if k != "projects"} == {
        k: v for k, v in original.items() if k != "projects"
    }
    expected = {
        **original["projects"],
        str(live): {"hasTrustDialogAccepted": True, "lastCost": 1.5},
    }
    assert after["projects"] == expected
    assert not Path(str(store) + ".plot-session.bak").exists()
    assert store.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("trust_line", ('trust_level = "untrusted"\n', ""))
def test_codex_trust_preserves_absent_projects_and_target_settings(tmp_path, trust_line):
    """An absent volume and target-specific tools must survive the trust flag update."""
    store, live = tmp_path / "config.toml", tmp_path / "repo"
    live.mkdir()
    store.write_text(
        'model = "m"\n\n[projects."/gone/one"]\ntrust_level = "trusted"\n'
        'allowedTools = ["Read"]\n[projects."/gone/one".mcp_servers.docs]\ncommand = "docs"\n'
        f'[projects."{live}"]\n{trust_line}allowedTools = ["Edit"]\n'
        f'[projects."{live}".mcp_servers.docs]\ncommand = "local-docs"\n'
        '[mcp_servers.docs]\ncommand = "docs"\n'
    )
    original = tomllib.loads(store.read_text())
    original["projects"][str(live)]["trust_level"] = "trusted"
    trust.trust(TrustRequest("write", store, str(live)), "codex")
    parsed = tomllib.loads(store.read_text())
    assert parsed == original
    assert parsed["model"] == "m"
    assert parsed["mcp_servers"] == {"docs": {"command": "docs"}}


@pytest.mark.parametrize("tool", ("claude", "codex"))
def test_trusted_store_with_absent_foreign_projects_is_not_rewritten(tmp_path, tool):
    """Bug: every launch rewrites the account store and widens the race with Claude."""
    store, live = tmp_path / ".claude.json", tmp_path / "repo"
    live.mkdir()
    if tool == "claude":
        data = _claude_store(store, live)
        data["projects"][str(live)]["hasTrustDialogAccepted"] = True
        store.write_text(json.dumps(data))
    else:
        store.write_text(
            f'[projects."{live}"]\ntrust_level = "trusted"\n'
            '[projects."/absent/volume"]\ntrust_level = "trusted"\nallowedTools = ["Read"]\n'
        )
    before = store.stat().st_mtime_ns, store.read_bytes()
    trust.trust(TrustRequest("write", store, str(live)), tool)
    assert (store.stat().st_mtime_ns, store.read_bytes()) == before
    assert not Path(str(store) + ".plot-session.bak").exists()


def test_concurrent_store_change_is_never_overwritten(tmp_path, monkeypatch):
    """Bug: a Claude write between read and replace is silently lost."""
    store, live = tmp_path / ".claude.json", tmp_path / "repo"
    live.mkdir()
    _claude_store(store, live)
    real = trust._read_bytes
    calls = []

    def racing(path):
        calls.append(path)
        seen = real(path)
        if len(calls) == 1:
            data = json.loads(seen)
            data["numStartups"] = 7
            store.write_text(json.dumps(data))
        return seen

    monkeypatch.setattr(trust, "_read_bytes", racing)
    trust.trust(TrustRequest("write", store, str(live)), "claude")
    after = json.loads(store.read_text())
    assert after["numStartups"] == 7
    assert after["projects"][str(live)]["hasTrustDialogAccepted"] is True


@pytest.mark.parametrize(("tool", "text"), [("claude", "{broken"), ("codex", "[broken")])
def test_unparseable_store_refuses_without_change(tmp_path, tool, text):
    """Bug: a store that does not parse is rewritten and the account state is destroyed."""
    store = tmp_path / "store"
    store.write_text(text)
    with pytest.raises(SystemExit, match="does not parse"):
        trust.trust(TrustRequest("write", store, str(tmp_path)), tool)
    assert store.read_text() == text


def test_symlinked_store_is_refused(tmp_path):
    """Bug: a symlinked store redirects the account write elsewhere."""
    target, store = tmp_path / "real.json", tmp_path / ".claude.json"
    target.write_text("{}")
    store.symlink_to(target)
    with pytest.raises(SystemExit, match="symlink"):
        trust.trust(TrustRequest("write", store, str(tmp_path)), "claude")
    assert target.read_text() == "{}"


def test_codex_append_preserves_unrelated_multiline_values(tmp_path, capsys):
    """Trusting a new root must leave unrelated multiline TOML values intact."""
    store, live = tmp_path / "config.toml", tmp_path / "repo"
    live.mkdir()
    text = '[projects."/gone/one"]\ntrust_level = "trusted"\nlists = [\n  ["a"],\n]\n'
    store.write_text(text)
    trust.trust(TrustRequest("write", store, str(live)), "codex")
    parsed = tomllib.loads(store.read_text())
    assert parsed["projects"]["/gone/one"]["lists"] == [["a"]]
    assert parsed["projects"][str(live)] == {"trust_level": "trusted"}
    assert "pruned" not in capsys.readouterr().out


@pytest.mark.parametrize("name", ['splice"]\ntrust_level="trusted"', "back\\slash"])
@pytest.mark.parametrize("mode", ["check", "write"])
def test_hostile_codex_path_is_refused_before_any_write(tmp_path, mode, name):
    """Bug: a quote or backslash in a session path splices a table or escape into Codex trust."""
    store = tmp_path / "config.toml"
    store.write_text('model = "m"\n')
    hostile = str(tmp_path / name)
    with pytest.raises(SystemExit, match="no Codex trust entry can name it"):
        trust.trust(TrustRequest(mode, store, hostile), "codex")
    assert store.read_text() == 'model = "m"\n'


def test_unrewritable_codex_layout_refuses_without_change(tmp_path):
    """Bug: an inline projects table is rewritten into a store Codex would not load."""
    store = tmp_path / "config.toml"
    text = 'projects = { "/gone" = { trust_level = "trusted" } }\n'
    store.write_text(text)
    with pytest.raises(SystemExit, match="cannot rewrite safely"):
        trust.trust(TrustRequest("write", store, str(tmp_path)), "codex")
    assert store.read_text() == text
