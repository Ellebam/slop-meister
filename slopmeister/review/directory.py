"""Directory-subject review setup."""

from pathlib import Path

from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.schema import CrossToolReviewError
from slopmeister.vault import subject as directory_subject
from slopmeister.vault.subject import DirectorySubject, scope_lines


def isolated_target(target: ReviewTarget, subject: DirectorySubject, copied: Path) -> ReviewTarget:
    return ReviewTarget(
        target.prompt,
        str(copied),
        (),
        None,
        scope_lines(subject),
    )


def verify_copy(copied: Path, before: str, manifest: Path) -> None:
    if before != directory_subject.tree_digest(copied):
        raise CrossToolReviewError("reviewer changed directory subject copy")
    directory_subject.load(manifest)
