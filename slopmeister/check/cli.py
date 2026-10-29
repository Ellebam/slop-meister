"""`slopmeister check`, the complete local gate and the CI layers from one catalogue."""

import argparse
from collections.abc import Sequence
import fcntl
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time

from slopmeister.check import catalogue, ownership, results
from slopmeister.check.scheduler import Settings, run_checks
from slopmeister.errors import UsageError
from slopmeister.paths import ROOT


def parse(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="slopmeister check")
    parser.add_argument("vault", nargs="?", help="Legacy path forwarded only to the drift check")
    parser.add_argument("--layer", choices=("portable", "all"), default="all")
    parser.add_argument("--kind", choices=("lint", "quality", "tests", "all"), default="all")
    parser.add_argument("--ci", action="store_true", help="the same as --layer portable")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--list", action="store_true", help="print the selected commands")
    parser.add_argument("--clean", action="store_true", help="only clear ended runs' leftovers")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        raise UsageError("--jobs must be positive")
    if args.ci:
        args.layer = "portable"
    return args


def evidence_paths(report: Path | None) -> tuple[Path, Path]:
    if report is None:
        logs = Path(tempfile.mkdtemp(prefix="slopmeister-check-")) / "logs"
        return logs / "report.json", logs
    report.parent.mkdir(parents=True, exist_ok=True)
    logs = report.with_suffix(".logs")
    if logs.exists():
        raise UsageError(f"evidence already exists: {logs}")
    try:
        report.open("x").close()
    except FileExistsError as error:
        raise UsageError(f"evidence already exists: {report}") from error
    return report, logs


def clean_leftovers(stream) -> bool:
    try:
        stopped, removed = ownership.clean()
    except (OSError, subprocess.SubprocessError) as error:
        print(f"leftover cleanup failed: {error}", file=stream)
        return False
    counts = f"stopped {stopped} test processes, removed {removed} run folders"
    print(f"leftovers: {counts}", file=stream)
    return True


def run_with_interrupts(checks, settings):
    def interrupt(*_: object) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        return run_checks(checks, settings)
    finally:
        signal.signal(signal.SIGTERM, previous)


def main(argv: Sequence[str]) -> int:
    args = parse(argv)
    if args.ci or args.list or args.clean:
        return execute(args)
    lock = Path.home() / ".local/state/slopmeister/check.lock"
    lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock.open("a") as stream:
        print(f"check: waiting for {lock}", flush=True)
        fcntl.flock(stream, fcntl.LOCK_EX)
        return execute(args)


def execute(args: argparse.Namespace) -> int:
    started = time.monotonic()
    if args.clean:
        return 0 if clean_leftovers(sys.stdout) else 1
    child_umask = os.umask(0o077)
    selection = catalogue.Selection(args.layer, args.kind, args.vault)
    checks = catalogue.catalogue(selection)
    if args.list:
        for check, line in zip(checks, catalogue.describe(checks), strict=True):
            print(f"{line}  {shlex.join(check.argv)}")
        return 0
    clean_leftovers(sys.stderr)
    report, logs = evidence_paths(args.report)
    result = run_with_interrupts(checks, Settings(args.jobs, ROOT, logs, child_umask))
    result.update(elapsed_seconds=time.monotonic() - started)
    keep = args.report is not None or not result["passed"]
    verdict = results.finish(result, (report, logs), keep)
    if not keep:
        logs.parent.rmdir()  # the temporary folder that held the discarded logs
    console = "\n".join(results.console_lines(result, terminal=sys.stdout.isatty()))
    encoding = sys.stdout.encoding or "utf-8"
    print(console.encode(encoding, errors="replace").decode(encoding))
    print("slowest:\n" + "\n".join(results.slowest(result)))
    print(verdict)
    return 0 if result["passed"] else 1
