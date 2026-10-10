"""Explicit high-water exceptions with an owner and a lower target."""

from dataclasses import dataclass
import json
from pathlib import Path

from slopmeister.errors import SlopmeisterError
from slopmeister.quality.budgets import DOCUMENT_WORDS, HARD_MAX_LINES, Violation

FILE_NAME = "quality-allowlist.json"
FIELDS = ("path", "metric", "symbol", "ceiling", "target", "owner", "rationale")


@dataclass(frozen=True)
class Entry:
    path: str
    metric: str
    symbol: str
    ceiling: int
    target: int
    owner: str
    rationale: str

    def covers(self, violation: Violation) -> bool:
        return (self.path, self.metric, self.symbol) == (
            violation.path,
            violation.metric,
            violation.symbol,
        )


def load(root: Path) -> list[Entry]:
    file = root / FILE_NAME
    if not file.exists():
        return []
    document = json.loads(file.read_text())
    entries = [_entry(item) for item in document.get("exceptions", [])]
    for entry in entries:
        if not (root / entry.path).exists():
            raise SlopmeisterError(f"{FILE_NAME}: {entry.path} no longer exists, remove its entry")
    return entries


def _entry(item: dict) -> Entry:
    missing = [field for field in FIELDS if field not in item]
    if missing or not item["rationale"].strip() or not item["owner"].strip():
        raise SlopmeisterError(f"{FILE_NAME}: entry {item.get('path')} lacks {missing or 'text'}")
    if item["target"] >= item["ceiling"]:
        raise SlopmeisterError(f"{FILE_NAME}: {item['path']} target must be below its ceiling")
    limit = DOCUMENT_WORDS if item["metric"] == "document_words" else HARD_MAX_LINES
    if item["target"] > limit:
        raise SlopmeisterError(f"{FILE_NAME}: {item['path']} target must not exceed {limit}")
    return Entry(**{field: item[field] for field in FIELDS})


def apply(violations: list[Violation], entries: list[Entry]) -> tuple[list[Violation], list[str]]:
    """Violations still failing, and messages about entries that no longer earn their place."""
    remaining, notes = [], []
    used = set()
    for violation in violations:
        entry = next((candidate for candidate in entries if candidate.covers(violation)), None)
        if entry is not None:
            used.add(entry)
        if entry is None or violation.value > entry.ceiling:
            remaining.append(violation)
            continue
        if violation.value <= entry.target:
            notes.append(
                f"{entry.path}: {entry.metric} {entry.symbol} reached its target, "
                f"set ceiling to {violation.value} and choose a lower target"
            )
    for entry in entries:
        if entry not in used:
            notes.append(f"{entry.path}: {entry.metric} {entry.symbol} no longer violates, remove")
    return remaining, notes
