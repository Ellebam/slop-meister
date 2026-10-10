"""Publish an eligible worktree's Bloom through Grove, or keep its local path."""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys

from slopmeister.session import bloom_storage as store
from slopmeister.session import git_environment, remote_ssh
from slopmeister.session.launch_identity import private_json

HOST_COMMAND = ("/usr/local/bin/grove", "receive")
HOST_CONFIG = Path("/etc/slopmeister/grove.json")
COMMAND_SECONDS = 30
MAX_RECEIPT_BYTES = 1024


def _git(root: Path, *args: str) -> str:
    if git_environment.redirect():
        raise ValueError("Bloom refuses Git repository redirection")
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=COMMAND_SECONDS,
        env=git_environment.child(),
    )
    if result.returncode:
        raise ValueError(f"Git {args[0]} failed for the owning worktree")
    return result.stdout.strip()


def _policy(root: Path) -> str:
    state_file = (
        Path(_git(root, "rev-parse", "--absolute-git-dir")) / "slopmeister-config/state.json"
    )
    if not state_file.exists() and not state_file.is_symlink():
        return "local"
    state = private_json(state_file, "owning worktree state")
    if state.get("worktree") != str(root) or state.get("version") != 3:
        raise ValueError("Bloom's saved owning worktree identity differs")
    permission = state.get("bloom", "local")
    if permission not in ("local", "tailnet"):
        raise ValueError("invalid saved Bloom publication permission")
    return "local" if state.get("directory") else permission


def _source(root: Path, page: Path) -> tuple[Path, bytes]:
    if root != Path(_git(root, "rev-parse", "--show-toplevel")).resolve():
        raise ValueError("name the owning worktree root")
    page = page if page.is_absolute() else root / page
    relative = page.relative_to(root)
    if ".." in relative.parts or any(ord(char) < 32 for char in str(page)):
        raise ValueError("unsafe page path")
    if not re.fullmatch(r"bloom-[a-z0-9-]+\.html", page.name):
        raise ValueError("page name must be bloom-<topic>.html")
    if _git(root, "ls-files", "--", ":(literal)" + str(relative)):
        raise ValueError("Bloom page must not be tracked")
    _git(root, "check-ignore", "--", str(relative))
    with store.directory(page.parent) as parent:
        descriptor = os.open(page.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Bloom page must be a regular file without links")
            data = store.read_page(stream)
    return page, data


def _config(path: Path) -> dict:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with store.directory(path.parent) as parent:
        descriptor = os.open(path.name, flags, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid not in (0, os.getuid())
                or info.st_mode & 0o022
            ):
                raise ValueError("unsafe Grove settings")
            data = stream.read(MAX_RECEIPT_BYTES + 1)
    if len(data) > MAX_RECEIPT_BYTES:
        raise ValueError("Grove settings are oversized")
    config = json.loads(data)
    if not isinstance(config, dict) or set(config) - {"base_url", "directory", "host"}:
        raise ValueError("invalid Grove settings")
    url = config.get("base_url")
    if not isinstance(url, str) or len(url) > 256 or any(ord(char) < 33 for char in url):
        raise ValueError("Grove requires its HTTPS base URL")
    pattern = r"https://[a-z0-9][a-z0-9.-]*\.ts\.net:8443/?"
    if not re.fullmatch(pattern, url):
        raise ValueError("Grove requires a tailnet HTTPS origin on port 8443")
    config["base_url"] = url.rstrip("/")
    return config


def _send(data: bytes, config: dict) -> str:
    command = list(HOST_COMMAND)
    if platform.system() == "Darwin":
        host = config.get("host")
        if not isinstance(host, str):
            raise ValueError("Mac Grove settings require a declared SSH alias")
        command = remote_ssh.argv(
            Path.home(), host, " ".join(remote_ssh.shq(p) for p in HOST_COMMAND)
        )
    try:
        result = subprocess.run(
            command,
            input=data,
            capture_output=True,
            timeout=COMMAND_SECONDS,
            env=git_environment.child(),
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Grove intake timed out") from None
    if result.returncode:
        raise ValueError("Grove intake failed")
    if len(result.stdout) > MAX_RECEIPT_BYTES:
        raise ValueError("Grove returned an oversized receipt")
    receipt = result.stdout.decode("utf-8", errors="replace").strip()
    expected = re.escape(config["base_url"]) + r"/[0-9a-f]{32}\.html"
    if not re.fullmatch(expected, receipt):
        raise ValueError("Grove returned an invalid publication URL")
    return receipt


def _publish(args: argparse.Namespace) -> int:
    root = Path(args.worktree).resolve()
    baseline = _git(root, "status", "--porcelain", "--untracked-files=all")
    page, data = _source(root, Path(args.page))
    link = str(page)
    if _policy(root) == "tailnet":
        try:
            link = _send(data, _config(Path(args.config)))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            print(f"Grove unavailable; kept the page locally: {error}", file=sys.stderr)
    if _git(root, "status", "--porcelain", "--untracked-files=all") != baseline:
        raise ValueError("owning worktree status changed during publication")
    print(link)
    return 0


def _host(args: argparse.Namespace) -> int:
    config = _config(Path(args.config))
    folder = config.get("directory")
    if not isinstance(folder, str):
        raise ValueError("Grove settings require the absolute page directory")
    if args.command == "receive":
        name = store.publish(Path(folder), store.read_page(sys.stdin.buffer))
        print(config["base_url"] + "/" + name)
    else:
        removed, size = store.cleanup(Path(folder))
        print(f"Grove cleanup: removed {removed} pages; retained {size} bytes")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bloom")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("publish", "receive", "cleanup"):
        command = commands.add_parser(name)
        default = HOST_CONFIG
        if name == "publish" and platform.system() == "Darwin":
            default = Path.home() / ".config/slopmeister/grove.json"
        command.add_argument("--config", default=str(default))
        if name == "publish":
            command.add_argument("--worktree", required=True)
            command.add_argument("--page", required=True)
    args = parser.parse_args(argv)
    try:
        return _publish(args) if args.command == "publish" else _host(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Bloom: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
