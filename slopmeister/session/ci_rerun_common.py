"""Task identity, bounded commands and data shared by the three CI providers."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import quote, unquote, urlsplit

from slopmeister.session import git_environment, repositories

DEADLINE_SECONDS = 90
COMMAND_SECONDS = 30
PAGE_SIZE = 100
MAX_PAGES = 100
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


@dataclass(frozen=True)
class Job:
    id: str
    name: str
    result: str
    attempt: int
    native: dict


@dataclass(frozen=True)
class Run:
    url: str
    result: str
    complete: bool
    generation: int
    jobs: tuple[Job, ...]
    native: dict


@dataclass(frozen=True)
class Context:
    repo: Path
    branch: str
    sha: str
    provider: str
    host: str
    project: str
    deadline: float

    def command(self, *args: str, body: str | None = None) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError(
                "CI command deadline reached; use the printed read-only status command"
            )
        env = git_environment.child() | {
            "GH_PROMPT_DISABLED": "1",
            "GLAB_PROMPT_DISABLED": "1",
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
        }
        try:
            result = subprocess.run(
                args,
                cwd=self.repo,
                env=env,
                input=body,
                capture_output=True,
                text=True,
                timeout=min(COMMAND_SECONDS, remaining),
            )
        except subprocess.TimeoutExpired:
            raise ValueError(
                f"{args[0]} timed out; mutation outcome may be unknown; do not retry"
            ) from None
        if result.returncode:
            raise ValueError(f"{args[0]} failed ({result.returncode}); no write was retried")
        if len(result.stdout.encode()) > MAX_RESPONSE_BYTES:
            raise ValueError("provider response exceeds the size limit")
        return result.stdout.strip()


def object_value(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("provider returned an invalid object")
    return value


def rows(value: object) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("provider returned an invalid list")
    return value


def number(value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("provider returned an invalid positive identifier or attempt")
    return value


def text(value: object) -> str:
    if not isinstance(value, str) or not value or not value.isprintable():
        raise ValueError("provider returned invalid text")
    return value


def commit(value: object) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("provider returned an invalid commit")
    return value


def encoded(value: str) -> str:
    return quote(value, safe="")


def pages(fetch, endpoint: str, key: str | None = None) -> list[dict]:
    result = []
    separator = "&" if "?" in endpoint else "?"
    for page in range(1, MAX_PAGES + 1):
        value = fetch(f"{endpoint}{separator}per_page={PAGE_SIZE}&page={page}")
        batch = rows(object_value(value)[key] if key else value)
        result.extend(batch)
        if len(batch) < PAGE_SIZE:
            return result
    raise ValueError("provider pagination exceeds the limit")


def remote(value: str) -> tuple[str, str, str]:
    normalized = value.replace("git@ssh.dev.azure.com:v3/", "https://dev.azure.com/")
    normalized = re.sub(
        r"^([^@/]+)@vs-ssh\.visualstudio\.com:v3/", "https://dev.azure.com/", normalized
    )
    normalized = re.sub(r"^git@([^:]+):", r"https://\1/", normalized)
    url = urlsplit(normalized)
    if url.scheme != "https" or url.username or url.password or url.query or url.fragment:
        raise ValueError("unsupported repository remote")
    host = url.hostname or ""
    path = url.path.removeprefix("/").removesuffix(".git")
    parts = [unquote(part) for part in path.split("/")]
    if any(not re.fullmatch(r"[A-Za-z0-9_. -]+", part) for part in parts):
        raise ValueError("unsupported repository remote")
    path = "/".join(parts)
    if not host or url.port or any(part in ("", ".", "..") for part in parts):
        raise ValueError("unsupported repository remote")
    if host == "github.com" and len(parts) == 2:
        return "github", host, path
    if host == "dev.azure.com":
        parts = [part for part in parts if part != "_git"]
        if len(parts) == 3:
            return "azure", host, "/".join(parts)
    if host.endswith(".visualstudio.com") and len(parts) == 3 and parts[1] == "_git":
        return "azure", "dev.azure.com", "/".join([host.split(".")[0], parts[0], parts[2]])
    if len(parts) >= 2 and re.fullmatch(r"[A-Za-z0-9.-]+", host):
        return "gitlab", host, path
    raise ValueError("unsupported repository remote")


def entry_workspace() -> Path:
    entry = Path(sys.argv[0]).absolute()
    if entry.parts[-4:] != ("skills", "ci-rerun", "scripts", "ci_rerun.py"):
        raise ValueError("use the session's fixed CI rerun entry")
    return entry.parents[4].resolve()


def verify_snapshot(directory: Path, state: dict) -> None:
    root = directory / "snapshot"
    manifest = root / "manifest.json"
    if (
        manifest.is_symlink()
        or hashlib.sha256(manifest.read_bytes()).hexdigest() != state["snapshot_sha256"]
    ):
        raise ValueError("saved runtime snapshot manifest changed")
    expected = object_value(json.loads(manifest.read_text()))
    actual = {}
    for path in root.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError("saved runtime snapshot contains a symlink")
        if path.is_file() and path != manifest:
            actual[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError("saved runtime snapshot changed")


def context(repo: Path | None) -> tuple[Context, Path]:
    owner = entry_workspace()
    repo = repo.resolve() if repo else owner
    if repo != owner and repo not in [Path(row["worktree"]) for row in repositories.members(owner)]:
        raise ValueError("CI rerun target is outside this session")
    if git_environment.redirect():
        raise ValueError("CI rerun refuses Git context overrides")
    state = repositories.read(repo)
    if state.get("directory") or state.get("proof_owner"):
        raise ValueError("directory and proof sessions cannot rerun CI")
    directory = repositories.state_path(repo).parent
    verify_snapshot(directory, state)
    target = object_value(state["ship_target"])
    origin = repositories.git(repo, "remote", "get-url", "--push", "--all", "origin")
    if (
        origin != target["remote"]
        or repositories.git(repo, "remote", "get-url", "--all", "origin") != origin
    ):
        raise ValueError("origin differs from the saved repository")
    branch = repositories.git(repo, "branch", "--show-current")
    if not branch or branch != target["branch"]:
        raise ValueError("current branch differs from the saved task branch")
    provider, host, project = remote(origin)
    ctx = Context(
        repo,
        branch,
        commit(repositories.git(repo, "rev-parse", "HEAD")),
        provider,
        host,
        project,
        time.monotonic() + DEADLINE_SECONDS,
    )
    ctx.command(sys.executable, str(directory / "config-install.py"), "--verify-shipping")
    return ctx, directory


def task_run(ctx: Context, branch: str, sha: str, default: str) -> bool:
    if branch == ctx.branch and branch != default and commit(sha) == ctx.sha:
        return True
    if branch != default:
        raise ValueError("run does not belong to the saved task branch")
    return False
