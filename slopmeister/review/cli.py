"""Run, replay or explicitly replace one independent cross-tool review result."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from contextlib import nullcontext
import dataclasses
from pathlib import Path
import sys
import time

from slopmeister.review.config import ReviewerConfig, command_timeout_seconds, load_config
from slopmeister.review.process import stderr_tail_log
from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.redact import sanitize_text
from slopmeister.review.render import render_hard_gate
from slopmeister.review.run import owned_reviewer_runner, run_review
from slopmeister.review.schema import CrossToolReviewError, ReviewDirection
from slopmeister.review.state import (
    read_result,
    result_path,
    save_result,
)
from slopmeister.session import launch_identity
from slopmeister.spine import candidate as repository_candidate

_monotonic = time.monotonic


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


def _review(args: argparse.Namespace) -> int:
    direction = ReviewDirection(args.direction)
    identity = launch_identity.read(Path.cwd(), direction.value.split("-to-")[0])
    path = result_path(args, identity["task"])
    if args.candidate and (args.mode != "diff" or args.subject_manifest):
        raise CrossToolReviewError("candidate review requires repository diff mode")
    frozen = repository_candidate.load(Path(args.cwd), identity["task"]) if args.candidate else None
    existing = _existing(args, path, frozen)
    return existing if existing is not None else _execute(args, direction, (path, frozen))


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
    context = repository_candidate.isolated(frozen) if frozen else nullcontext(Path(args.cwd))
    prompt = _prompt(args) + (repository_candidate.reading_guide(frozen) if frozen else "")
    with context as cwd:
        target = ReviewTarget(prompt, str(cwd), args.read_dirs, args.subject_manifest)
        try:
            result = run_review(direction, target, runner=owned_reviewer_runner, config=config)
        except CrossToolReviewError as error:
            _feedback(
                f"failed category={error.category.value} elapsed={_monotonic() - started:.3f}s"
            )
            for line in stderr_tail_log(error.stderr_tail):
                _feedback(line)
            raise
    return _complete(result, (path, started, frozen.tree if frozen else None))


def _complete(result, context: tuple[Path, float, str | None]) -> int:
    path, started, candidate = context
    if candidate:
        # A materialized candidate always differs from its base; that is not a dirty worktree.
        result = dataclasses.replace(result, preexisting_dirty=False)
    gate = render_hard_gate(result)
    code = 1 if any(finding.severity == "MUST-FIX" for finding in result.findings) else 0
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
        print(render_hard_gate(failure))
        return 1
