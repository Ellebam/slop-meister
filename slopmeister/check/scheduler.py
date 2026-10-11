"""Phases first, parallel, last. Every selected check runs once or the gate is incomplete."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import time

from slopmeister.check import ownership
from slopmeister.check.jobs import Check, Context, execute

PHASES = ("first", "parallel", "last")


def validate(checks: list[Check], jobs: int) -> None:
    if jobs < 1:
        raise ValueError("jobs must be positive")
    if not checks:
        raise ValueError("no checks selected")
    names = [check.id for check in checks]
    if len(names) != len(set(names)):
        raise ValueError("duplicate check identity")
    if any(check.phase not in PHASES for check in checks):
        raise ValueError("unknown check phase")


def _run_phases(checks: list[Check], context: Context, executor: ThreadPoolExecutor) -> list:
    results = []
    # Keep spawn and registration off the signal-handling thread in every phase.
    for check in (c for c in checks if c.phase == "first"):
        results.append(executor.submit(execute, check, context).result())
    parallel = sorted((c for c in checks if c.phase == "parallel"), key=lambda c: -c.seconds)
    futures = [executor.submit(execute, check, context) for check in parallel]
    results.extend(future.result() for future in as_completed(futures))
    for check in (c for c in checks if c.phase == "last"):
        results.append(executor.submit(execute, check, context).result())
    return results


@dataclass(frozen=True)
class Settings:
    jobs: int
    cwd: Path
    logs: Path
    child_umask: int = -1


def _execute_all(checks: list[Check], context: Context, jobs: int) -> list[dict]:
    results: list = []
    executor = ThreadPoolExecutor(max_workers=jobs)
    try:
        results = _run_phases(checks, context, executor)
    except KeyboardInterrupt:
        context.cancelled.set()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return [row for row in results if row is not None]


def run_checks(checks: list[Check], settings: Settings) -> dict:
    validate(checks, settings.jobs)
    settings.logs.mkdir(parents=True, exist_ok=False, mode=0o700)
    started, started_at = time.monotonic(), ownership.utc()
    context = Context(cwd=settings.cwd, logs=settings.logs, child_umask=settings.child_umask)
    results = _execute_all(checks, context, settings.jobs)
    complete = sorted(row["id"] for row in results) == sorted(check.id for check in checks)
    return {
        "jobs": settings.jobs,
        "started_at": started_at,
        "finished_at": ownership.utc(),
        "complete": complete,
        "passed": complete and all(row["returncode"] == 0 for row in results),
        "interrupted": context.cancelled.is_set(),
        "results": results,
        "elapsed_seconds": time.monotonic() - started,
    }
