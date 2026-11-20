"""The diff check's run: its guide, a clean checkout of the final candidate, its slot, cleanup."""

import argparse
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
import errno
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from slopmeister.errors import SlopmeisterError
from slopmeister.removal import remove_tree
from slopmeister.review.process import CommandResult
from slopmeister.review.redact import redact, sanitize_text
from slopmeister.review.run import owned_reviewer_runner
from slopmeister.review.scenarios import scenario_ids
from slopmeister.review.schema import CrossToolReviewError, ReviewErrorCategory
from slopmeister.session import repositories
from slopmeister.slots import tester as slot_tester
from slopmeister.spine import candidate as repository_candidate
from slopmeister.vault import subject as directory_subject

INPUT_LIMIT = 256_000
# A finished run records its resolved workspace here, so workspace removal can delete it.
FINISHED, PATH_LIMIT = "finished", 4096


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
    members: list[tuple[Path, str, str]] = field(default_factory=list)

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
        for checkout, base, tree in [(self.checkout, self.base, self.tree), *self.members]:
            if _git(checkout, "rev-parse", "HEAD") != base or not (
                repository_candidate.unchanged(checkout, tree)
            ):
                raise CrossToolReviewError(
                    "the checker changed the tested files; refusing the result"
                )

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


def _state() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME", ""))
    if not state.is_absolute():
        state = Path.home() / ".local/state"
    return (state / "slopmeister/checks").resolve()


def _home(workspace: Path) -> Path:
    state = _state()
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


def committed_group(workspace: Path):
    roots = repositories.workspaces(workspace)
    if len(roots) == 1:
        return None
    for root in roots:
        _snapshot(root)
    return repository_candidate.freeze(workspace, workspace.name)


def _new(args: argparse.Namespace, frozen) -> Check:
    text, scenarios = _guide(args.guide)
    workspace = Path(args.cwd).resolve(strict=True)
    if args.subject_manifest:
        subject = directory_subject.load(args.subject_manifest)
        tested = f"directory subject {subject.identity}"
    elif frozen:
        tested = f"candidate tree {frozen.identity} on base {frozen.base}"
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
        check.members = [
            (check.checkout / repositories.DIRECTORY / item.workspace.name, item.base, item.tree)
            for item in frozen.members
        ]
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
        if frozen is None and not args.subject_manifest:
            frozen = committed_group(Path(args.cwd).resolve())
        check = _new(args, frozen)
        if check.checkout is not None:
            _checkout(check, frozen)
        if args.slot_target:
            slot_tester.prepare(check.root, check.run, args.slot_target)
    except BaseException as error:
        if check is not None:
            _finish(check)
        if isinstance(error, (OSError, ValueError, SlopmeisterError, subprocess.SubprocessError)):
            detail = redact(str(error))
            raise _failure(f"the diff check could not be prepared: {detail}") from error
        raise
    try:
        yield check
    finally:
        _finish(check)


def _finish(check: Check) -> None:
    """Clean up, then record the run as finished. A kept checkout or slot leaves no record."""
    check.cleanup_error = _cleanup(check)
    if check.cleanup_error:
        return
    record = check.root / f".{FINISHED}"
    try:
        record.write_text(str(check.workspace))
        record.replace(check.root / FINISHED)
    except OSError:
        pass  # Without its record the run only stays, the review result still counts.


def remove_finished(workspace: Path) -> None:
    """Delete the finished check runs of the removed resolved workspace. Other runs stay."""
    try:
        with os.scandir(_state()) as listing:
            entries = list(listing)
    except FileNotFoundError:
        return
    except OSError as error:
        # The workspace is already gone, so an unreadable checks directory only keeps its runs.
        print(f"check runs kept: {_state()}: {error}", file=sys.stderr)
        return
    owner = str(workspace).encode()
    for entry in entries:
        run = Path(entry.path)
        if not (entry.name.startswith("run-") and entry.is_dir(follow_symlinks=False)):
            continue
        try:
            if _owner(run) == owner:
                remove_tree(run)
        except OSError as error:
            print(f"check run kept: {run}: {error}", file=sys.stderr)


def _owner(run: Path) -> bytes:
    try:
        descriptor = os.open(run / FINISHED, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError, NotADirectoryError:
        return b""
    except OSError as error:
        # A linked record is refused by O_NOFOLLOW, never followed.
        if error.errno == errno.ELOOP:
            return b""
        raise
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return b""
        return stream.read(PATH_LIMIT + 1)


def _cleanup(check: Check) -> str:
    run, checkout = check.run, check.checkout
    run["process_stopped"] = check.stopped
    try:
        if not check.stopped:
            slot_tester.cleanup(check.root, run)
            raise OSError("reviewer stop unverified, checkout and slot kept")
        if checkout is not None and checkout.is_symlink():
            raise OSError("checkout is a symlink, not removed")
        if error := slot_tester.cleanup(check.root, run):
            run["slot_cleanup_error"] = error
            raise OSError(error)
        if error := run.get("slot_cleanup_error"):
            raise OSError(error)
        if checkout is not None:
            remove_tree(checkout)
    except FileNotFoundError:
        pass
    except (OSError, SlopmeisterError) as error:
        return redact(str(error))
    return ""
