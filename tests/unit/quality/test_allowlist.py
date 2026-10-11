"""Explicit exceptions refuse growth and carry a lower target."""

import json
from pathlib import Path

import pytest

from slopmeister.errors import SlopmeisterError
from slopmeister.quality import allowlist
from slopmeister.quality.budgets import Violation
from tests.support.trees import write

ENTRY = {
    "path": "scripts/x.sh",
    "metric": "file_lines",
    "symbol": "__file__",
    "ceiling": 400,
    "target": 250,
    "owner": "issue-223",
    "rationale": "approved high-water mark",
}


def save(root: Path, entries: list[dict]) -> None:
    write(root, allowlist.FILE_NAME, json.dumps({"version": 1, "exceptions": entries}))


def test_growth_past_the_ceiling_still_fails(tmp_path: Path) -> None:
    write(tmp_path, "scripts/x.sh", "")
    save(tmp_path, [ENTRY])
    remaining, _ = allowlist.apply(
        [Violation("scripts/x.sh", 1, "file_lines", "__file__", 401, 250)], allowlist.load(tmp_path)
    )
    assert [violation.value for violation in remaining] == [401]


def test_within_ceiling_passes_and_reaching_target_requires_a_lower_target(
    tmp_path: Path,
) -> None:
    write(tmp_path, "scripts/x.sh", "")
    save(tmp_path, [ENTRY])
    entries = allowlist.load(tmp_path)
    assert allowlist.apply(
        [Violation("scripts/x.sh", 1, "file_lines", "__file__", 399, 250)], entries
    ) == ([], [])
    save(tmp_path, [{**ENTRY, "ceiling": 401, "target": 400}])
    _, notes = allowlist.apply(
        [Violation("scripts/x.sh", 1, "file_lines", "__file__", 400, 250)],
        allowlist.load(tmp_path),
    )
    assert notes == [
        "scripts/x.sh: file_lines __file__ reached its target, "
        "set ceiling to 400 and choose a lower target"
    ]


def test_entry_for_a_missing_file_is_refused(tmp_path: Path) -> None:
    save(tmp_path, [ENTRY])
    with pytest.raises(SlopmeisterError, match="no longer exists"):
        allowlist.load(tmp_path)


def test_entry_without_owner_rationale_or_lower_target_is_refused(tmp_path: Path) -> None:
    write(tmp_path, "scripts/x.sh", "")
    for broken in ({**ENTRY, "owner": " "}, {**ENTRY, "rationale": ""}, {**ENTRY, "target": 400}):
        save(tmp_path, [broken])
        with pytest.raises(SlopmeisterError):
            allowlist.load(tmp_path)


def test_exception_above_hard_maximum_must_target_400_or_lower(tmp_path: Path) -> None:
    write(tmp_path, "scripts/x.sh", "")
    save(tmp_path, [{**ENTRY, "ceiling": 401, "target": 401}])
    with pytest.raises(SlopmeisterError, match="target"):
        allowlist.load(tmp_path)
    save(tmp_path, [{**ENTRY, "ceiling": 401, "target": 400}])
    assert allowlist.load(tmp_path)[0].ceiling == 401


def test_unused_entry_is_reported_for_removal(tmp_path: Path) -> None:
    write(tmp_path, "scripts/x.sh", "")
    save(tmp_path, [ENTRY])
    _, notes = allowlist.apply([], allowlist.load(tmp_path))
    assert notes == ["scripts/x.sh: file_lines __file__ no longer violates, remove"]


def test_document_exception_targets_words_and_still_forbids_growth(tmp_path: Path):
    write(tmp_path, "docs/guide.md", "")
    entry = {**ENTRY, "path": "docs/guide.md", "metric": "document_words", "ceiling": 2101}
    save(tmp_path, [{**entry, "target": 2001}])
    with pytest.raises(SlopmeisterError, match="target"):
        allowlist.load(tmp_path)
    save(tmp_path, [{**entry, "target": 2000}])
    entries = allowlist.load(tmp_path)
    violation = Violation("docs/guide.md", 1, "document_words", "__file__", 2101, 2000)
    assert allowlist.apply([violation], entries) == ([], [])
    over = Violation("docs/guide.md", 1, "document_words", "__file__", 2102, 2000)
    assert allowlist.apply([over], entries)[0] == [over]
    assert allowlist.apply([], entries)[1] == [
        "docs/guide.md: document_words __file__ no longer violates, remove"
    ]
