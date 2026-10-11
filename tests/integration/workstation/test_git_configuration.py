"""Workstation writers never take ownership of Git's global configuration."""

from pathlib import Path

from tests.integration.workstation.test_install import machine, workstation


def _seed(root: Path) -> dict[Path, bytes]:
    home = root / "home"
    xdg = root / "xdg/git"
    xdg.mkdir(parents=True)
    files = {
        home / ".gitconfig": (
            b"[user]\n\tname = Operator\n\temail = operator@example.invalid\n"
            b'[commit]\n\tgpgsign = true\n[includeIf "gitdir:~/customer-a/**"]\n'
            b"\tpath = ~/.gitconfig-customer-a\n"
        ),
        xdg / "config": (
            b'[gpg]\n\tformat = ssh\n[includeIf "gitdir:~/customer-b/**"]\n'
            b"\tpath = ~/.gitconfig-customer-b\n"
        ),
        root / "explicit-gitconfig": (
            b"[user]\n\tsigningkey = ~/.ssh/signing-key\n"
            b'[includeIf "gitdir:~/customer-c/**"]\n\tpath = ~/.gitconfig-customer-c\n'
        ),
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return files


def _unchanged(files: dict[Path, bytes]) -> None:
    assert {path: path.read_bytes() for path in files} == files


def test_home_diff_named_install_and_full_install_preserve_global_git_bytes(tmp_path):
    """Bug: a home install silently replaces identity, signing or conditional includes."""
    home, bin_dir = machine(tmp_path)
    files = _seed(tmp_path)
    env = {
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "explicit-gitconfig"),
    }

    assert workstation(home, bin_dir, "diff", **env).returncode == 0
    _unchanged(files)
    assert workstation(home, bin_dir, "install", ".codex/AGENTS.md", **env).returncode == 0
    _unchanged(files)
    assert workstation(home, bin_dir, "install", "--all", **env).returncode == 0
    _unchanged(files)
