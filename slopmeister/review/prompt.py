"""Review target validation and prompt construction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from slopmeister.review.schema import CrossToolReviewError, ReviewErrorCategory, review_json_schema


def normalize_read_dirs(directories: Sequence[str]) -> tuple[str, ...]:
    resolved = []
    for directory in directories:
        try:
            if not directory or not all(char.isprintable() for char in directory):
                raise ValueError
            path = Path(directory)
            if not path.is_absolute():
                raise ValueError
            path = path.resolve(strict=True)
            if not path.is_dir() or path == path.parent or not str(path).isprintable():
                raise ValueError
        except OSError, ValueError, RuntimeError:
            raise CrossToolReviewError(
                "--read-dir requires an absolute existing directory without control characters, "
                "other than the filesystem root",
                category=ReviewErrorCategory.START_PRECONDITION,
            ) from None
        resolved.append(str(path))
    return tuple(resolved)


@dataclass(frozen=True)
class ReviewTarget:
    prompt: str
    cwd: str = "."
    read_dirs: tuple[str, ...] = ()
    subject_manifest: str | None = None
    subject_scope: tuple[str, ...] = ()
    check_root: str | None = None
    scenarios: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "read_dirs", normalize_read_dirs(self.read_dirs))


def build_review_prompt(target: ReviewTarget) -> str:
    lines = [
        "Review this work the way you would review a colleague's pull request.",
        "Run any command or test that helps you check it. Never change code or files, push, "
        "merge, release, run deployment workflows or mutate any tracker.",
        f"The review target's root is {Path(target.cwd).resolve()}. Cite every finding's file "
        "path relative to that root, never as an absolute path.",
        "Report only findings that are valid, reachable and proportionate, each with the smallest "
        "remedy. Challenge accidental complexity in the target and in your own remedies. Prefer "
        "the smallest behavior-preserving remedy and do not propose new machinery without "
        "demonstrated need. Security, data-loss, irreversible-operation, explicit-authority and "
        "recovery requirements are mandatory, not overengineering.",
        "Run the Security Lens over the target. Run and name every mandatory check: secrets "
        "and sensitive-data handling; untrusted inputs and trust-boundary validation; "
        "authentication, authorization and privilege boundaries; injection, unsafe evaluation "
        "and command execution; output encoding, logging and data exposure; filesystem and "
        "path safety including traversal and temporary-file permissions; process isolation and "
        "lifecycle safety; resource exhaustion, blocking and denial-of-service risks; dependency "
        "and supply-chain integrity; and safe execution of target code during review or testing. "
        "Additional checks may be named. Report it in security_lens: finding is the 1-based index "
        "of the finding that is a security defect, or null when the target is verified clean, "
        "checks names every check that ran, evidence is one line of evidence.",
        *(_check_lines(target) if target.check_root else ()),
        "Return only JSON matching this schema:",
        review_json_schema(check=bool(target.check_root)),
        "",
        target.prompt,
    ]
    if target.subject_scope:
        lines.extend(("", "The immutable directory subject contains only:", *target.subject_scope))
    return "\n".join(lines)


def _check_lines(target: ReviewTarget) -> tuple[str, ...]:
    root = Path(target.check_root)
    return (
        f"This review is also the independent test of the change. The test guide is "
        f"{root / 'guide.md'}. Your working directory is a fresh copy of the change without "
        "development tools, so run the setup that the guide, README or CONTRIBUTING names "
        "before you call a scenario not runnable. Run every guide scenario, including its "
        "falsification cases, and decide each by its written steps and expected results. Then "
        "make your own attempts to break the change and report each one that holds as a finding.",
        f"Save the stdout and stderr of every scenario command directly to files under "
        f"{root / 'evidence'}, and copy any checkout file you quote there, because the copy is "
        "deleted after the run. Cite each file by its path relative to "
        f"{root}, such as evidence/basic.out. Each quote must be an exact, nonempty substring of "
        "its saved file, never reconstructed or paraphrased. When success means empty output, "
        "check that the command succeeded and save a nonempty marker that says so. A pass or "
        "fail without a verified quote counts as could_not_run.",
        "Report every scenario ID exactly once as pass, fail or could_not_run, with the reason "
        "for fail and could_not_run. A failed or unavailable scenario is never pass. When a "
        "guide step is wrong or impossible, add a guide finding that names the scenario and the "
        "step, then continue with the remaining scenarios. Stop every process you start before "
        "you finish, because a process left running fails the check. Do not launch reviews or "
        "other agents. Scenario IDs: " + ", ".join(target.scenarios) + ".",
    )
