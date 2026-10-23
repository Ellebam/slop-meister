"""Preserve public vault selectors while removing child-process startup injection."""

import os
from pathlib import Path


def vault_path(value: str | None = None) -> Path:
    """The installed runtime imports no checkout, so it repeats the per-machine default."""
    default = Path.home() / ".slopmeister/vault"
    return Path(value or os.environ.get("SLOPMEISTER_VAULT") or default).expanduser()


def git_path() -> Path:
    return Path(os.environ.get("VAULT_GIT_DIR", Path.home() / ".vault-git/obsidian.git"))


def commit_environment() -> dict[str, str]:
    # Resolve public selectors before removing interpreter and Git startup injection.
    root = Path.home() / ".vault-git"
    selected = dict(
        SLOPMEISTER_VAULT=str(vault_path().resolve()), VAULT_GIT_DIR=str(git_path().resolve())
    )
    for name, default in (
        ("VAULTGIT", root / "bin/vaultgit"),
        ("VAULT_LOCK", root / "bin/vault-lock.py"),
    ):
        selected[name] = str(Path(os.environ.get(name, default)).expanduser().resolve())
    if launcher := os.environ.get("SLOPMEISTER_VAULT_LAUNCHER"):
        selected["SLOPMEISTER_VAULT_LAUNCHER"] = str(Path(launcher).expanduser().resolve())
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("PYTHON")
        and name not in {"BASH_ENV", "ENV"}
        and (not name.startswith("GIT_") or name.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_")))
    }
    return environment | selected | {"GIT_LITERAL_PATHSPECS": "1", "GIT_PAGER": "cat"}
