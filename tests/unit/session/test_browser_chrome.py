"""Browser connections use an installed Node outside the task workspace."""

from pathlib import Path

import pytest

from slopmeister.session import browser_runtime as runtime


def test_repository_node_shim_is_not_an_installed_runtime(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SLOPMEISTER_SESSION_WORKSPACE", str(tmp_path))
    fake = tmp_path / "node"
    fake.write_text("not an installed runtime")
    monkeypatch.setattr(runtime.shutil, "which", lambda _: str(fake))
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    monkeypatch.setattr(runtime.os, "access", lambda *_: True)
    with pytest.raises(ValueError, match="BROWSER_PREREQUISITE"):
        runtime.node()


def test_home_directory_can_use_its_installed_node(tmp_path, monkeypatch):
    monkeypatch.delenv("SLOPMEISTER_SESSION_WORKSPACE", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(home)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(runtime, "TEMP_ROOT", tmp_path / "temporary")
    installed = home / ".local/bin/node"
    monkeypatch.setattr(runtime.shutil, "which", lambda _: str(installed))
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    monkeypatch.setattr(runtime.os, "access", lambda *_: True)
    assert runtime.node() == installed
