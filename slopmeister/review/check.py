"""The diff check's run: its guide, a clean checkout of the final candidate, its slot, cleanup."""

import argparse
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
import tempfile

from slopmeister.errors import SlopmeisterError
from slopmeister.removal import remove_tree
from slopmeister.review.process import CommandResult
from slopmeister.review.redact import redact, sanitize_text
from slopmeister.review.run import owned_reviewer_runner
from slopmeister.review.scenarios import scenario_ids
from slopmeister.review.schema import CrossToolReviewError, ReviewErrorCategory
from slopmeister.slots import allocation
from slopmeister.slots import tester as slot_tester
from slopmeister.spine import candidate as repository_candidate
from slopmeister.vault import subject as directory_subject

INPUT_LIMIT = 256_000


@dataclass
class Check:
    root: Path
    workspace: Path
    scenarios: tuple[str, ...]
    tested: str
    # None for a directory subject, which the runner copies itself.
    checkout: Path | None = None
    base: str = ""
    tree: str = ""
    run: dict = field(default_factory=dict)
    stopped: bool = True
    cleanup_error: str = ""

    def runner(self, argv: Sequence[str], **options) -> CommandResult:
        """The owned reviewer runner, remembering whether its process group is known stopped."""
        self.stopped = False
        try:
            result = owned_reviewer_runner(argv, **options)
        except CrossToolReviewError as error:
            never_started = error.category == ReviewErrorCategory.START_PRECONDITION
            self.stopped = error.process_stopped or never_started
            raise
        self.stopped = True
        return result

    def verify(self) -> None:
        """The checker may add files to its copy, never change what it tests."""
        if self.checkout is None:
            return
        if _git(self.checkout, "rev-parse", "HEAD") != self.base or not (
            repository_candidate.unchanged(self.checkout, self.tree)
        ):
            raise CrossToolReviewError("the checker changed the tested files; refusing the result")

    def footer(self) -> str:
        lines = [f"**Tested:** {sanitize_text(self.tested)}"]
        lines.append(f"**Evidence:** {sanitize_text(str(self.root / 'evidence'))}")
        if self.cleanup_error:
            retained = f"retained {self.root}: {self.cleanup_error}"
            lines.append(f"**Cleanup:** {sanitize_text(retained)}")
        return "\n".join(lines)


def _failure(message: str) -> CrossToolReviewError:
    return CrossToolReviewError(message, category=ReviewErrorCategory.START_PRECONDITION)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=True,
    )
    return result.stdout.strip()


def _home(workspace: Path) -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME", ""))
    if not state.is_absolute():
        state = Path.home() / ".local/state"
    state = (state / "slopmeister/checks").resolve()
    if state.is_relative_to(workspace.resolve()):
        raise _failure("diff check evidence must live outside the reviewed checkout")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    return state


def _guide(path: str) -> tuple[str, tuple[str, ...]]:
    guide = Path(path)
    if not guide.is_absolute():
        raise _failure("--guide needs an absolute path to the test guide")
    try:
        text = guide.read_text()
    except (OSError, ValueError) as error:
        raise _failure(f"the test guide could not be read: {error}") from error
    if len(text) > INPUT_LIMIT:
        raise _failure(f"the test guide exceeds {INPUT_LIMIT} characters")
    return text, scenario_ids(text)


def _snapshot(workspace: Path) -> str:
    # Plain status respects the launcher's skip-worktree entries, a rebuilt index does not.
    if _git(workspace, "status", "--porcelain", "--untracked-files=all"):
        raise _failure(
            "the diff check tests the snapshot commit, and the worktree has uncommitted "
            "changes. Commit them, or with commits denied freeze them and pass --candidate"
        )
    return _git(workspace, "rev-parse", "--verify", "HEAD^{commit}")


def _new(args: argparse.Namespace, frozen) -> Check:
    text, scenarios = _guide(args.guide)
    workspace = Path(args.cwd).resolve(strict=True)
    if args.subject_manifest:
        subject = directory_subject.load(args.subject_manifest)
        tested = f"directory subject {subject.identity}"
    elif frozen:
        tested = f"candidate tree {frozen.tree} on base {frozen.base}"
    else:
        commit = _snapshot(workspace)
        tested = f"commit {commit}"
    root = Path(tempfile.mkdtemp(prefix="run-", dir=_home(workspace)))
    check = Check(root, workspace, scenarios, tested)
    if not (args.subject_manifest or frozen):
        check.base = commit
    (root / "guide.md").write_text(text)
    (root / "evidence").mkdir(mode=0o700)
    if not args.subject_manifest:
        check.checkout = root / "checkout"
        check.run = {"checkout": str(check.checkout), "cwd": str(workspace)}
    return check


def _checkout(check: Check, frozen) -> None:
    if frozen:
        repository_candidate.materialize(frozen, check.checkout)
        check.base, check.tree = frozen.base, frozen.tree
        return
    commit = check.base
    _git(check.root, "clone", "-q", "--local", "--no-hardlinks", "--no-checkout",
         str(check.workspace), str(check.checkout))  # fmt: skip
    # The clone's origin/* would mirror the worker's local branches, give it the worker's upstream.
    _git(check.checkout, "fetch", "-q", "--no-tags", "--prune", str(check.workspace),
         "+refs/remotes/*:refs/remotes/*")  # fmt: skip
    _git(check.checkout, "checkout", "-q", "--detach", commit)
    check.base, check.tree = commit, _git(check.checkout, "rev-parse", f"{commit}^{{tree}}")


@contextmanager
def prepared(args: argparse.Namespace, frozen):
    """Yield the prepared check. Its checkout and slot go when the reviewer is known stopped."""
    if args.slot_target and args.subject_manifest:
        raise _failure("--slot-target needs a repository checkout")
    check = None
    try:
        check = _new(args, frozen)
        if check.checkout is not None:
            _checkout(check, frozen)
        if args.slot_target:
            slot_tester.prepare(check.root, check.run, args.slot_target)
    except BaseException as error:
        if check is not None:
            check.cleanup_error = _cleanup(check)
        if isinstance(error, (OSError, ValueError, SlopmeisterError, subprocess.SubprocessError)):
            detail = redact(str(error))
            raise _failure(f"the diff check could not be prepared: {detail}") from error
        raise
    try:
        yield check
    finally:
        check.cleanup_error = _cleanup(check)


def _cleanup(check: Check) -> str:
    run, checkout = check.run, check.checkout
    run["process_stopped"] = check.stopped
    try:
        if not check.stopped:
            slot_tester.cleanup(check.root, run)
            raise OSError("reviewer stop unverified, checkout and slot kept")
        if checkout is not None and checkout.is_symlink():
            raise OSError("checkout is a symlink, not removed")
        # A slot whose teardown failed may still have containers mounting the checkout.
        if error := run.get("slot_cleanup_error"):
            raise OSError(error)
        images = _stack_images(run)
        if error := slot_tester.cleanup(check.root, run):
            raise OSError(error)
        if checkout is not None:
            _reclaim(checkout, images)
            remove_tree(checkout)
    except FileNotFoundError:
        pass
    except (OSError, SlopmeisterError) as error:
        return redact(str(error))
    return ""


def _stack_images(run: dict) -> list[str]:
    """Read while the containers exist, the exact project label names the run's own stack."""
    if not run.get("slot", {}).get("compose"):
        return []
    label = f"label=com.docker.compose.project={Path(run['slot']['state']).name}"
    argv = ["docker", "ps", "-a", "--filter", label, "--format", "{{.Image}}"]
    try:
        return sorted(set(allocation.run(argv, capture=True, ok=False).stdout.split()))
    except SlopmeisterError:
        return []


def _reclaim(checkout: Path, images: list[str]) -> None:
    """A rootful daemon's bind mounts leave files the operator cannot delete. One project image
    hands them back, and the checkout's removal reports anything left."""
    mount, owner = f"{checkout}:/checkout", f"{os.getuid()}:{os.getgid()}"
    argv = ["docker", "run", "--rm", "--network", "none", "--user", "0:0", "-v", mount]
    argv += ["--entrypoint", "chown"]
    for image in images:
        if not allocation.run([*argv, image, "-R", "-h", owner, "/checkout"], ok=False).returncode:
            return
