"""Report files, console lines and bounded failure excerpts."""

import json
from pathlib import Path
import shutil

FAILURE_LINES = 100
FAILURE_BYTES = 32 * 1024


def failure_excerpt(path: Path) -> tuple[list[str], bool]:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        offset = max(0, size - FAILURE_BYTES)
        stream.seek(offset)
        text = stream.read().decode(errors="replace").replace("##[", "## [")
    display = text.encode()
    display_truncated = len(display) > FAILURE_BYTES
    if display_truncated:
        text = display[-FAILURE_BYTES:].decode(errors="ignore")
    lines = text.splitlines()
    truncated = offset > 0 or display_truncated or len(lines) > FAILURE_LINES
    return lines[-FAILURE_LINES:], truncated


def console_lines(result: dict, *, terminal: bool) -> list[str]:
    lines = []
    for row in result["results"]:
        passed = row["returncode"] == 0
        lines.append(f"{'PASS' if passed else 'FAIL'} {row['id']} {row['elapsed_seconds']:.1f}s")
        if not passed:
            lines.append("  log: " + row["log"])
            if terminal:
                continue
            excerpt, truncated = failure_excerpt(Path(row["log"]))
            lines.append(f"  excerpt: last {FAILURE_LINES} lines, {FAILURE_BYTES // 1024} KiB max")
            lines.extend("  | " + line for line in excerpt)
            if truncated:
                lines.append("  ... truncated; complete log retained with the check report")
    return lines


def slowest(result: dict, count: int = 20) -> list[str]:
    rows = sorted(result["results"], key=lambda row: -row["elapsed_seconds"])[:count]
    return [f"  {row['elapsed_seconds']:6.1f}s {row['id']}" for row in rows]


def finish(result: dict, evidence: tuple[Path, Path], keep: bool) -> str:
    """Write or discard the evidence, report and logs, and return the one-line gate verdict."""
    report, logs = evidence
    if keep:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(result, indent=2) + "\n")
    else:
        shutil.rmtree(logs)
    detail = f"; report: {report}" if keep else ""
    verdict = "PASS" if result["passed"] else "FAIL"
    return f"{verdict} complete gate {result['elapsed_seconds']:.1f}s{detail}"
