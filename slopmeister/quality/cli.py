"""`slopmeister quality`, exit 1 on any uncovered violation or any identifier or style finding."""

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys

from slopmeister.errors import EXIT_FAILURE
from slopmeister.paths import ROOT
from slopmeister.quality import allowlist, budgets, identifiers, imports, inventory, style
from slopmeister.quality.budgets import HARD_MAX_LINES, Violation


def all_violations(root: Path) -> list[Violation]:
    sources = inventory.sources(root)
    found = []
    for source in sources:
        found.extend(budgets.measure(source, root))
    found.extend(imports.import_violations(sources, root))
    return sorted(found, key=lambda v: (v.path, v.line, v.metric))


def inventory_report(
    root: Path, violations: list[Violation], entries: list[allowlist.Entry]
) -> str:
    over_hard = [
        violation
        for violation in violations
        if violation.metric == "file_lines" and violation.value > HARD_MAX_LINES
    ]
    report = {
        "files": inventory.summary(root),
        f"oversized_{HARD_MAX_LINES}": len(over_hard),
        "cycles": sum(violation.metric == "import_cycle" for violation in violations),
        "runtime_edges_py_to_py": sum(
            violation.metric == "runtime_edge" for violation in violations
        ),
        "allowlist": [
            {
                "path": entry.path,
                "metric": entry.metric,
                "ceiling": entry.ceiling,
                "target": entry.target,
                "owner": entry.owner,
            }
            for entry in entries
        ],
    }
    return json.dumps(report, indent=1)


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="slopmeister quality")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--inventory", action="store_true", help="print the inventory summary")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    # Other checks print paths and symbols. Refuse private content before they can echo it.
    private = identifiers.findings(root)
    if private:
        for finding in private:
            print(finding)
        return EXIT_FAILURE
    entries = allowlist.load(root)
    violations = all_violations(root)
    remaining, notes = allowlist.apply(violations, entries)
    if args.inventory:
        print(inventory_report(root, violations, entries))
    for violation in remaining:
        print(violation.render())
    for note in notes:
        print(note)
    # Writing rules remain outside the numeric budget allowlist.
    rules = style.findings(root)
    for finding in rules:
        print(finding)
    if remaining or notes or rules:
        return EXIT_FAILURE
    count = len(inventory.sources(root))
    print(f"quality: ok, {count} files, {len(entries)} allowlist entries", file=sys.stdout)
    return 0
