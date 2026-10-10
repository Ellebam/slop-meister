"""`slopmeister kickoff`, refuse the recorded restatements of rules the loaded layers carry.

A kickoff carries the task, the live siblings and the constraints no loaded layer enforces, the
contract is docs/contracts.md. This refuses the paragraphs a dispatcher copies forward from the
last kickoff, and a kickoff without its mode line. It matches the recorded phrasings, so a
paraphrase passes, and the operator's read of the first kickoff after a change stays the
semantic check. Exit 0 when the kickoff adheres, 1 when it does not, 2 on usage.
"""

from collections.abc import Sequence
from pathlib import Path
import re
import sys

from slopmeister.errors import EXIT_USAGE

MODE_LINES = 3  # the Codex form carries the session name on line one and a blank line
MODES = ("Mode: spine", "Mode: freeform")
USAGE = "usage: slopmeister kickoff <file> | - | --rules"
# Rule, pattern, home. Case-insensitive over one paragraph, anchored on the instruction form of
# each rule so a sibling constraint that merely names a notes file or the close-out passes. The
# tests read this table through --rules and probe every rule with its home hard-coded.
RULES = (
    ("read-first", r"read .?agents\.md.? (in full )?first", "the agreement loads automatically"),
    (
        "notes-file",
        r"create .?[A-Z0-9-]*NOTES\.md|frozen heading",
        "the spine paragraph of the agreement",
    ),
    (
        "dummy-shape",
        r"dummy shape|four-beat|one decision per message|operator silence approves nothing",
        "the one message of the agreement",
    ),
    (
        "review-halts",
        r"launched once by the operator|never start (one|them|it) yourself"
        r"|stop at each gate|both external review gates apply",
        "the review section of the agreement",
    ),
    (
        "close-out",
        r"close[- ]out at every|run (the |a )?close-out",
        "finalize, which the operator types",
    ),
    ("spine-run", r"run the (whole |entire )?((seven|ten)-step )?spine", "the mode line"),
    (
        "writing-style",
        r"em dash|semicolon|writing style",
        "the writing style rule of the agreement",
    ),
    ("field-facts", r"field fact", "the security section of the agreement"),
    (
        "dist-generated",
        r"dist/. is generated|edit(ed)? .?dist/?. by hand",
        "the project rules of the slopmeister",
    ),
    ("task-check", r"task check. before", "the project rules of the slopmeister"),
    ("debug-first", r"debug first|diagnose (first|before)", "the global layer"),
    (
        "commit-messages",
        r"co-authored|attribution (line|trailer)|imperative line",
        "the global layer",
    ),
)


def paragraphs(lines: list[str]) -> list[tuple[int, str]]:
    """(first line number, joined text) for every run of non-empty lines."""
    found, current, start = [], [], 0
    for number, line in enumerate([*lines, ""], 1):
        if line:
            start = start if current else number
            current.append(line)
        elif current:
            found.append((start, " ".join(current)))
            current = []
    return found


def hits(text: str) -> tuple[list[str], int]:
    lines = text.split("\n")
    found = [
        f"line {start}: restates {rule}, carried by {home}"
        for start, paragraph in paragraphs(lines)
        for rule, pattern, home in RULES
        if re.search(pattern, paragraph, re.IGNORECASE)
    ]
    if not any(line in MODES for line in lines[:MODE_LINES]):
        missing = f"no 'Mode: spine' or 'Mode: freeform' line within the first {MODE_LINES} lines"
        found.insert(0, f"line 1: {missing}")
    return found, len(paragraphs(lines))


def _load(argv: Sequence[str]) -> tuple[str, str] | int:
    """The kickoff's name and normalized text, or the usage exit code."""
    if len(argv) != 1 or (argv[0].startswith("-") and argv[0] != "-"):
        print(USAGE, file=sys.stderr)
        return EXIT_USAGE
    if argv[0] == "-":
        name, raw = "stdin", sys.stdin.read()
    elif Path(argv[0]).is_file():
        name, raw = argv[0], Path(argv[0]).read_text(errors="replace")
    else:
        print(f"kickoff not found: {argv[0]}", file=sys.stderr)
        return EXIT_USAGE
    # An issue body fetched through gh can carry CRLF endings, and trailing newlines never count.
    text = raw.replace("\r", "").rstrip("\n")
    if not text:
        print(f"kickoff is empty: {name}", file=sys.stderr)
        return EXIT_USAGE
    return name, text


def main(argv: Sequence[str]) -> int:
    if list(argv) == ["--rules"]:
        print("\n".join("\t".join(row) for row in RULES))
        return 0
    loaded = _load(argv)
    if isinstance(loaded, int):
        return loaded
    name, text = loaded
    found, count = hits(text)
    verdict = "does not adhere" if found else "adheres"
    print(f"kickoff {verdict}: {name} ({len(text.encode())} bytes, {count} paragraphs)")
    if found:
        print("\n".join(found))
    return int(bool(found))
