"""Read-only reviewer child execution and mutation checks."""

from collections.abc import Callable, Sequence
from functools import partial
import json
from pathlib import Path
import subprocess

from slopmeister.check import jobs
from slopmeister.review.command import build_review_command, cleanup_schema_file
from slopmeister.review.config import command_timeout_seconds, load_config
from slopmeister.review.directory import isolated_target, verify_copy
from slopmeister.review.process import (
    CommandResult,
    _AnchoredPopen,
    _finish_output,
    group_members,
    project_child_env,
    stderr_tail,
    subprocess_runner,
)
from slopmeister.review.prompt import ReviewTarget, build_review_prompt
from slopmeister.review.redact import redact
from slopmeister.review.result import check_returncode, parse_result
from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewDirection,
    ReviewErrorCategory,
    ReviewResult,
)
from slopmeister.spine import candidate as repository_candidate
from slopmeister.vault import subject as directory_subject

type CommandRunner = Callable[..., CommandResult]


def owned_reviewer_runner(argv: Sequence[str], **options) -> CommandResult:
    """Own the review process group so a timed-out reviewer is not left running."""
    if Path(argv[0]).name not in {"claude", "codex"}:
        return subprocess_runner(argv, **options)
    process = _start_reviewer(argv, options)
    timeout = command_timeout_seconds()
    try:
        stdout, stderr = process.communicate(options.get("stdin_text"), timeout=timeout)
    except subprocess.TimeoutExpired as error:
        _stop_reviewer(process)
        stdout, stderr = _finish_output(process, (error.stdout, error.stderr))
        raise CrossToolReviewError(
            f"reviewer timed out after {timeout}s",
            category=ReviewErrorCategory.TIMEOUT,
            process_stopped=True,
            raw_stdout=redact(stdout),
            stderr_tail=stderr_tail(stderr),
        ) from None
    except BaseException:
        _stop_reviewer(process)
        raise
    _check_reviewer_group(process)
    process.reap()
    return CommandResult(process.returncode, stdout, stderr, process_stopped=True)


def _check_reviewer_group(process: subprocess.Popen) -> None:
    try:
        members = group_members(process.pid)
    except (OSError, subprocess.SubprocessError) as error:
        _stop_reviewer(process)
        raise CrossToolReviewError(
            f"cannot inspect reviewer group {process.pid}: {error}",
            category=ReviewErrorCategory.CONTROL_FAILURE,
            process_stopped=True,
        ) from error
    except BaseException:
        _stop_reviewer(process)
        raise
    if not members:
        return
    _stop_reviewer(process)
    raise CrossToolReviewError(
        f"reviewer left a live process group {process.pid}: {'; '.join(members)}",
        process_stopped=True,
    )


def _stop_reviewer(process: subprocess.Popen) -> None:
    try:
        stop_owned_group(process)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise CrossToolReviewError(
            f"cannot signal reviewer group {process.pid}: {error}",
            category=ReviewErrorCategory.CONTROL_FAILURE,
            process_stopped=False,
        ) from error


def stop_owned_group(process: subprocess.Popen) -> None:
    jobs.stop_group(process, anchored=True)


def _start_reviewer(argv: Sequence[str], options: dict) -> subprocess.Popen:
    cwd, env, stdin_text = (options.get(name) for name in ("cwd", "env", "stdin_text"))
    try:
        return _AnchoredPopen(
            list(argv),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        raise CrossToolReviewError(
            f"reviewer could not start: {error}", category="START_PRECONDITION"
        ) from error


def _run(runner: CommandRunner, argv: Sequence[str], context: tuple) -> CommandResult:
    target, env, stdin_text = context
    try:
        return runner(
            argv,
            cwd=target.cwd,
            env=env,
            **({"stdin_text": stdin_text} if stdin_text is not None else {}),
        )
    except OSError as error:
        command = argv[0] if argv else "command"
        raise CrossToolReviewError(
            f"review command could not start ({command}): {error}",
            category=ReviewErrorCategory.START_PRECONDITION,
        ) from error
    except subprocess.TimeoutExpired as error:
        command = argv[0] if argv else "command"
        raise CrossToolReviewError(
            f"review command timed out ({command})", category=ReviewErrorCategory.TIMEOUT
        ) from error


def _worktree(cwd: str) -> tuple[str, bool]:
    """The tree of every file Git sees in the work tree, and whether it differs from HEAD.

    Status text cannot show an edit to an already-modified file or a new file in an
    already-untracked folder.
    """
    try:
        tree = repository_candidate.worktree_tree(Path(cwd))
        return tree, tree != repository_candidate.head_tree(Path(cwd))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise CrossToolReviewError(
            f"cannot read the reviewed worktree: {redact(str(error))}"
        ) from error


def _mutation(cwd: str, before: str) -> str:
    try:
        return "unchanged" if _worktree(cwd)[0] == before else "changed"
    except CrossToolReviewError:
        return "unverified"


def _directory_mutation(copied: Path, before: str, manifest: Path) -> str:
    try:
        copied_state = directory_subject.tree_digest(copied)
        directory_subject.load(manifest)
    except OSError, ValueError, json.JSONDecodeError:
        return "unverified"
    return "unchanged" if copied_state == before else "changed"


def run_review(direction: ReviewDirection, target: ReviewTarget, **options) -> ReviewResult:
    if target.subject_manifest:
        return _run_directory_review(direction, target, options)
    return _run_repository_review(direction, target, options)


def _run_repository_review(
    direction: ReviewDirection, target: ReviewTarget, options: dict
) -> ReviewResult:
    runner = options.get("runner", subprocess_runner)
    settings = options.get("config") or load_config()
    child_env = project_child_env(options.get("env"))
    before, dirty = _worktree(target.cwd)
    argv = build_review_command(direction, target, config=settings)
    try:
        mutation = partial(_mutation, target.cwd, before)
        review = _execute_review(direction, target, (runner, child_env, argv, mutation))
        after, _ = _worktree(target.cwd)
    finally:
        cleanup_schema_file(argv)
    if before != after:
        raise CrossToolReviewError("reviewer changed the worktree; refusing clean verdict")
    check_returncode(review)
    parsed = parse_result(direction, review)
    return ReviewResult(parsed.findings, parsed.security_lens, dirty)


def _run_directory_review(direction, target, options) -> ReviewResult:
    subject = directory_subject.load(target.subject_manifest)
    temporary, copied = directory_subject.isolated_copy(subject)
    directory_subject.load(subject.manifest)
    isolated = isolated_target(target, subject, copied)
    runner = options.get("runner", subprocess_runner)
    settings = options.get("config") or load_config()
    child_env = project_child_env(options.get("env"))
    before = directory_subject.tree_digest(copied)
    argv = build_review_command(direction, isolated, config=settings)
    try:
        mutation = partial(_directory_mutation, copied, before, subject.manifest)
        review = _execute_review(direction, isolated, (runner, child_env, argv, mutation))
        verify_copy(copied, before, subject.manifest)
        check_returncode(review)
        parsed = parse_result(direction, review)
        return ReviewResult(parsed.findings, parsed.security_lens, False)
    finally:
        cleanup_schema_file(argv)
        temporary.cleanup()


def _execute_review(
    direction: ReviewDirection, target: ReviewTarget, context: tuple
) -> CommandResult:
    runner, env, argv, mutation = context
    stdin = build_review_prompt(target) if direction == ReviewDirection.CODEX_TO_CLAUDE else None
    try:
        return _run(runner, argv, (target, env, stdin))
    except CrossToolReviewError as error:
        if error.category != ReviewErrorCategory.TIMEOUT:
            raise
        raise CrossToolReviewError(
            str(error),
            category=ReviewErrorCategory.TIMEOUT,
            mutation_state=mutation(),
            process_stopped=error.process_stopped,
            raw_stdout=error.raw_stdout,
            stderr_tail=error.stderr_tail,
        ) from error
