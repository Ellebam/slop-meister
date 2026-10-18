"""The owning worktree's authority precedes any host or SSH access."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from slopmeister.session import bloom
from tests.support.repos import git

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "src/skills/bloom/scripts/bloom.py"
ORIGIN = "https://agent.example.ts.net:8443"


@pytest.fixture(autouse=True)
def isolated_intake(tmp_path, monkeypatch):
    # A broken source guard must never send a fixture to the machine's live Grove.
    monkeypatch.setattr(bloom.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        bloom,
        "HOST_COMMAND",
        (sys.executable, str(ENTRY), "receive", "--config", str(tmp_path / "absent-intake")),
    )


def scene(tmp_path, policy="tailnet"):
    root = tmp_path / "worktree"
    root.mkdir()
    git(root, "init", "-q")
    (root / ".gitignore").write_text("tmp/\n")
    git(root, "add", ".gitignore")
    git(root, "commit", "-qm", "Seed fixture")
    scratch = root / "tmp"
    scratch.mkdir()
    page = scratch / "bloom-example.html"
    page.write_text("<!doctype html><html><title>Example</title>Example</html>")
    state = root / ".git/slopmeister-config/state.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"version": 3, "worktree": str(root), "bloom": policy}))
    state.chmod(0o600)
    pages = tmp_path / "pages"
    pages.mkdir(mode=0o750)
    config = tmp_path / "grove.json"
    config.write_text(json.dumps({"base_url": ORIGIN, "directory": str(pages)}))
    config.chmod(0o640)
    return root, page, state, pages, config


def publish_args(root, page, config):
    return ["publish", "--worktree", str(root), "--page", str(page), "--config", str(config)]


def test_nested_repository_cannot_hide_a_tracked_page(tmp_path, monkeypatch, capsys):
    root, page, _, pages, config = scene(tmp_path)
    nested = page.parent / "nested"
    nested.mkdir()
    git(nested, "init", "-q")
    page = page.rename(nested / page.name)
    git(nested, "add", page.name)
    git(nested, "commit", "-qm", "Track nested fixture")
    monkeypatch.setattr(bloom, "_send", lambda *_: "unexpected publication")
    assert bloom.main(publish_args(root, page, config)) == 1
    assert "page belongs to another repository" in capsys.readouterr().err
    assert list(pages.iterdir()) == []


def test_local_publication_calls_the_installed_protocol_and_keeps_git_state(
    tmp_path, monkeypatch, capsys
):
    root, page, _, pages, config = scene(tmp_path)
    monkeypatch.setattr(
        bloom, "HOST_COMMAND", (sys.executable, str(ENTRY), "receive", "--config", str(config))
    )
    before = git(root, "status", "--porcelain")
    assert bloom.main(publish_args(root, page, config)) == 0
    url = capsys.readouterr().out.strip()
    assert url.startswith(ORIGIN + "/")
    assert (pages / url.rsplit("/", 1)[1]).read_bytes() == page.read_bytes()
    assert git(root, "status", "--porcelain") == before


@pytest.mark.parametrize("policy", ["local", None])
def test_excluded_owning_worktree_never_opens_settings_or_transport(
    tmp_path, monkeypatch, capsys, policy
):
    root, page, state, pages, _ = scene(tmp_path, policy)
    if policy is None:
        state.unlink()
    caller_folder = tmp_path / "caller"
    caller_folder.mkdir()
    caller, _, _, _, _ = scene(caller_folder, "tailnet")
    monkeypatch.setattr(bloom, "_send", lambda *_: pytest.fail("transport opened"))
    monkeypatch.setattr(bloom, "_config", lambda *_: pytest.fail("settings opened"))
    monkeypatch.chdir(caller)
    assert bloom.main(publish_args(root, page, tmp_path / "absent")) == 0
    assert capsys.readouterr().out.strip() == str(page)
    assert list(pages.iterdir()) == []


def test_identity_mismatch_cannot_borrow_another_worktrees_grant(tmp_path, capsys):
    root, page, state, pages, config = scene(tmp_path)
    state.write_text(json.dumps({"version": 3, "worktree": str(ROOT), "bloom": "tailnet"}))
    assert bloom.main(publish_args(root, page, config)) == 1
    assert "saved owning worktree identity differs" in capsys.readouterr().err
    assert list(pages.iterdir()) == []


def test_unavailable_service_keeps_local_artifact_with_a_diagnostic(tmp_path, capsys):
    root, page, _, pages, _ = scene(tmp_path)
    assert bloom.main(publish_args(root, page, tmp_path / "absent")) == 0
    output = capsys.readouterr()
    assert output.out.strip() == str(page)
    assert "Grove unavailable" in output.err
    assert page.exists() and list(pages.iterdir()) == []


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("tracked", "must not be tracked"),
        ("symlink", "Too many levels of symbolic links"),
        ("parent-symlink", "Git check-ignore failed"),
        ("traversal", "unsafe page path"),
        ("fifo", "regular file without links"),
    ],
)
def test_source_boundary_preserves_outside_data(tmp_path, capsys, kind, expected):
    root, page, _, pages, config = scene(tmp_path)
    outside = tmp_path / "outside.html"
    outside.write_text("private sentinel")
    match kind:
        case "tracked":
            git(root, "add", "-f", "tmp/bloom-example.html")
        case "symlink":
            page.unlink()
            page.symlink_to(outside)
        case "parent-symlink":
            page.unlink()
            page.parent.rmdir()
            page.parent.symlink_to(tmp_path, target_is_directory=True)
        case "traversal":
            page = root / "tmp/../../outside.html"
        case "fifo":
            page.unlink()
            os.mkfifo(page)
    assert bloom.main(publish_args(root, page, config)) == 1
    diagnostic = capsys.readouterr().err
    assert expected in diagnostic
    assert outside.read_text() == "private sentinel"
    assert list(pages.iterdir()) == []


def test_mac_uses_pinned_alias_and_sends_page_only_on_stdin(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ssh = home / ".ssh"
    ssh.mkdir(parents=True)
    (ssh / "slopmeister-remote.conf").write_text("Host example\n  HostName example\n")
    monkeypatch.setattr(bloom.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(bloom.Path, "home", classmethod(lambda _: home))
    payload = b"<html>text with $(commands) and `backticks`</html>"
    receipt = ORIGIN + "/" + "a" * 32 + ".html"
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, (receipt + "\n").encode(), b"")

    monkeypatch.setattr(bloom.subprocess, "run", run)
    assert bloom._send(payload, {"host": "example", "base_url": ORIGIN}) == receipt
    command, options = calls[0]
    assert command[:3] == ["ssh", "-F", str(ssh / "slopmeister-remote.conf")]
    assert "StrictHostKeyChecking=yes" in command and "IdentityAgent=none" in command
    assert options["input"] == payload
    assert payload.decode() not in " ".join(command)


@pytest.mark.parametrize("reply", [b"https://example.org/page.html", b"garbage", b"x" * 1025])
def test_invalid_remote_receipt_cannot_be_presented_as_a_link(monkeypatch, reply):
    monkeypatch.setattr(bloom.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        bloom.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, reply, b"")
    )
    with pytest.raises(ValueError, match="invalid publication URL|oversized receipt"):
        bloom._send(b"page", {"base_url": ORIGIN})


@pytest.mark.parametrize("unsafe", ["public-origin", "group-writable", "world-writable"])
def test_untrusted_settings_cannot_open_transport(tmp_path, monkeypatch, capsys, unsafe):
    root, page, _, pages, config = scene(tmp_path)
    if unsafe == "public-origin":
        data = json.loads(config.read_text())
        data["base_url"] = "https://example.org:8443"
        config.write_text(json.dumps(data))
    else:
        config.chmod(0o664 if unsafe == "group-writable" else 0o666)
    monkeypatch.setattr(bloom, "_send", lambda *_: pytest.fail("untrusted settings used"))
    assert bloom.main(publish_args(root, page, config)) == 0
    output = capsys.readouterr()
    assert output.out.strip() == str(page) and "Grove unavailable" in output.err
    assert list(pages.iterdir()) == []


def test_hardlinked_source_cannot_export_outside_data(tmp_path, monkeypatch, capsys):
    root, page, _, pages, config = scene(tmp_path)
    outside = tmp_path / "outside.html"
    outside.write_text("private sentinel")
    page.unlink()
    os.link(outside, page)
    monkeypatch.setattr(
        bloom, "_send", lambda *_: pytest.fail("linked outside data reached transport")
    )
    assert bloom.main(publish_args(root, page, config)) == 1
    assert "regular file without links" in capsys.readouterr().err
    assert outside.read_text() == "private sentinel" and list(pages.iterdir()) == []
