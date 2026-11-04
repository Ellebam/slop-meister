"""Run, replay or explicitly replace one independent cross-tool review result."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import dataclasses
from pathlib import Path
import sys
import time

from slopmeister.review import check
from slopmeister.review.config import ReviewerConfig, command_timeout_seconds, load_config
from slopmeister.review.process import stderr_tail_log
from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.redact import sanitize_text
from slopmeister.review.render import BLOCKING, render_hard_gate, status
from slopmeister.review.run import owned_reviewer_runner, run_review
from slopmeister.review.schema import CrossToolReviewError, ReviewDirection, ReviewErrorCategory
from slopmeister.review.state import (
    read_result,
    result_path,
    save_result,
)
from slopmeister.session import launch_identity
from slopmeister.spine import candidate as repository_candidate

_monotonic = time.monotonic
REJECTED_OUTPUT_CHARS = 16 * 1024


def _feedback(message: str) -> None:
    print(f"cross-tool-review: {message}", file=sys.stderr)


def _prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    if args.prompt_file == "-":
        value = sys.stdin.read()
        if not value.strip():
            raise CrossToolReviewError("review prompt from stdin is empty")
        return value
    try:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    except OSError as error:
        raise CrossToolReviewError(f"review prompt could not be read: {error}") from error


def _config(args: argparse.Namespace, direction: ReviewDirection) -> ReviewerConfig:
    config = load_config()
    tool = "claude" if direction == ReviewDirection.CODEX_TO_CLAUDE else "codex"
    updates = {
        f"{tool}_{key}": value
        for key, value in (("model", args.model), ("effort", args.effort))
        if value
    }
    return dataclasses.replace(config, **updates)


def _refuse(message: str) -> CrossToolReviewError:
    return CrossToolReviewError(message, category=ReviewErrorCategory.START_PRECONDITION)


def _arguments(args: argparse.Namespace) -> None:
    if args.subject_manifest and args.read_dirs:
        raise _refuse("--subject-manifest cannot be combined with --read-dir")
    if args.mode == "plan" and (args.guide or args.slot_target):
        raise _refuse("--guide and --slot-target apply to --mode diff only")


def _review(args: argparse.Namespace) -> int:
    _arguments(args)
    direction = ReviewDirection(args.direction)
    identity = launch_identity.read(Path.cwd(), direction.value.split("-to-")[0])
    path = result_path(args, identity["task"])
    if args.candidate and (args.mode != "diff" or args.subject_manifest):
        raise CrossToolReviewError("candidate review requires repository diff mode")
    frozen = repository_candidate.load(Path(args.cwd), identity["task"]) if args.candidate else None
    existing = _existing(args, path, frozen)
    if existing is not None:
        return existing
    # After replay, so a session on an older procedure still replays its saved result.
    if args.mode == "diff" and not args.guide:
        raise _refuse(
            "--mode diff needs --guide <absolute test guide>, the diff check runs its "
            "scenarios in a clean checkout of the final candidate"
        )
    return _execute(args, direction, (path, frozen))


def _existing(args, path: Path, frozen) -> int | None:
    if path.exists():
        gate, code, bound = read_result(path)
        if bound != (frozen.tree if frozen else None):
            raise CrossToolReviewError("candidate differs from final review result")
        _feedback(f"replaying final result from {path}")
        print(gate)
        return code
    if args.exempt_reason is None:
        return None
    if not args.exempt_reason.strip():
        raise CrossToolReviewError("review exemption needs a nonempty reason")
    gate = "Independent review: N/A - " + sanitize_text(args.exempt_reason)
    save_result(path, gate, (0, frozen.tree if frozen else None))
    _feedback(f"result artifact: {path}")
    print(gate)
    return 0


def _execute(args, direction: ReviewDirection, target_state) -> int:
    path, frozen = target_state
    config = _config(args, direction)
    model, effort = config.for_direction(direction)
    _feedback(
        f"preflight direction={direction.value} model={model} effort={effort} "
        f"timeout={command_timeout_seconds()}s"
    )
    started = _monotonic()
    _feedback("reviewer launch")
    prompt = _prompt(args) + (repository_candidate.reading_guide(frozen) if frozen else "")
    if args.mode == "plan":
        target = ReviewTarget(prompt, args.cwd, args.read_dirs, args.subject_manifest)
        result = _run(direction, target, (config, started), {})
        return _complete(result, (path, started, None), "")
    prepared = None
    try:
        with check.prepared(args, frozen) as prepared:
            target = ReviewTarget(
                prompt,
                str(prepared.checkout or args.cwd),
                args.read_dirs,
                args.subject_manifest,
                check_root=str(prepared.root),
                scenarios=prepared.scenarios,
            )
            options = {"runner": prepared.runner, "check": prepared}
            result = _run(direction, target, (config, started), options)
    finally:
        if prepared is not None:
            _feedback(f"check run: {prepared.root}")
            if prepared.cleanup_error:
                _feedback(f"check cleanup kept {prepared.root}: {prepared.cleanup_error}")
    bound = frozen.tree if frozen else None
    return _complete(result, (path, started, bound), "\n\n" + prepared.footer())


def _run(direction: ReviewDirection, target: ReviewTarget, context: tuple, options: dict):
    config, started = context
    options = {"runner": owned_reviewer_runner, "config": config} | options
    try:
        return run_review(direction, target, **options)
    except CrossToolReviewError as error:
        _feedback(f"failed category={error.category.value} elapsed={_monotonic() - started:.3f}s")
        for line in stderr_tail_log(error.stderr_tail):
            _feedback(line)
        raise


def _complete(result, context: tuple[Path, float, str | None], footer: str) -> int:
    path, started, candidate = context
    if candidate:
        # A materialized candidate always differs from its base; that is not a dirty worktree.
        result = dataclasses.replace(result, preexisting_dirty=False)
    gate = render_hard_gate(result) + footer
    code = 1 if status(result) in BLOCKING else 0
    _feedback(f"completed elapsed={_monotonic() - started:.3f}s")
    save_result(path, gate, (code, candidate))
    _feedback(f"result artifact: {path}")
    print(gate)
    return code


def _replace(args: argparse.Namespace) -> int:
    identity = launch_identity.read(Path.cwd())
    path = result_path(args, identity["task"])
    if path.exists():
        read_result(path)
        path.unlink()
        print(f"review result removed: {path}")
    else:
        print(f"review result already absent: {path}")
    return 0


def _target(parser: argparse.ArgumentParser) -> None:
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--cwd", default=".")
    target.add_argument("--subject-manifest")
    parser.add_argument("--mode", choices=["plan", "diff"], required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review")
    review.add_argument(
        "--direction", choices=[item.value for item in ReviewDirection], required=True
    )
    _target(review)
    review.add_argument("--candidate", action="store_true")
    review.add_argument("--read-dir", dest="read_dirs", action="append", default=[])
    source = review.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt")
    source.add_argument("--prompt-file")
    review.add_argument("--model")
    review.add_argument("--effort")
    review.add_argument("--exempt-reason")
    review.add_argument("--guide", help="Absolute test guide the diff check runs.")
    review.add_argument("--slot-target", help="Reserve this plot's ports for the check.")
    _target(sub.add_parser("replace"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _review(args) if args.command == "review" else _replace(args)
    except (CrossToolReviewError, OSError, ValueError, KeyError, TypeError) as error:
        failure = (
            error
            if isinstance(error, CrossToolReviewError)
            else CrossToolReviewError(str(error), category="START_PRECONDITION")
        )
        if failure.category == ReviewErrorCategory.INVALID_REVIEWER_JSON and failure.raw_stdout:
            output = sanitize_text(failure.raw_stdout)
            _feedback(
                "rejected output, not a review result, gate remains BLOCKED, "
                "do not record findings as a disposition: " + output[:REJECTED_OUTPUT_CHARS]
            )
            if len(output) > REJECTED_OUTPUT_CHARS:
                _feedback(f"rejected output truncated at {REJECTED_OUTPUT_CHARS} characters")
        print(render_hard_gate(failure))
        return 1
