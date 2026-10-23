"""Start a slot's declared Compose project and decide when it is ready."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation

COMPOSE_TIMEOUT = 60
COMPOSE_LOG_TIMEOUT = 90


def _compose_up(claim: allocation.Claim, evidence: Path | None = None) -> None:
    if not claim.compose:
        return
    relative = claim.compose.relative_to(claim.live.worktree)
    compose = allocation.resolve_compose(claim.live.worktree, str(relative))
    env = str(claim.data / allocation.ALLOCATION)
    project = f"{claim.live.target}-slot{claim.live.slot}"
    prefix = ["--env-file", env, "-f", str(compose), "-p", project]
    deadline = time.monotonic() + COMPOSE_TIMEOUT
    wait = ["up", "-d", "--wait", "--wait-timeout", str(COMPOSE_TIMEOUT)]
    detail = ""
    try:
        result = allocation.compose([*prefix, *wait], ok=False)
        detail = result.stderr.strip() if result.returncode else ""
        while result.returncode and not _compose_ready(prefix):
            if time.monotonic() >= deadline:
                raise SlopmeisterError("compose readiness did not complete within its time limit")
            time.sleep(1)
    except SlopmeisterError as error:
        logs = _save_logs(claim, prefix, evidence)
        message = f"{detail}\n{error}" if detail else str(error)
        raise SlopmeisterError(f"{message}\n{logs}") from error


def _save_logs(claim: allocation.Claim, prefix: list[str], evidence: Path | None) -> str:
    path = None
    try:
        if evidence is None:
            evidence = Path(
                tempfile.mkdtemp(prefix=f"{claim.live.name}.failed-", dir=claim.data.parent)
            )
        path = evidence / "compose.log"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            # Raw bytes retain partial output and logs that are not valid UTF-8.
            result = subprocess.run(
                ["docker", "compose", *prefix, "logs", "--no-color", "--timestamps"],
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=COMPOSE_LOG_TIMEOUT,
            )
        if result.returncode:
            return (
                f"could not save complete compose logs (exit {result.returncode}); evidence: {path}"
            )
    except (OSError, subprocess.SubprocessError) as error:
        return f"could not save compose logs: {error}; evidence: {path}"
    return f"compose logs: {path}"


def _compose_ready(prefix: list[str]) -> bool:
    """False means valid services are still starting. Definite failures abort preparation."""
    services = allocation.compose([*prefix, "config", "--services"], ok=False)
    state = allocation.compose([*prefix, "ps", "--all", "--format", "json"], ok=False)
    if services.returncode or state.returncode:
        raise SlopmeisterError("cannot inspect compose readiness")
    try:
        rows = [json.loads(line) for line in state.stdout.splitlines()]
    except json.JSONDecodeError as error:
        raise SlopmeisterError("invalid compose readiness output") from error
    if len(rows) == 1 and isinstance(rows[0], list):
        rows = rows[0]
    expected = set(services.stdout.split())
    if not expected or not all(isinstance(row, dict) for row in rows):
        raise SlopmeisterError("invalid compose service state")
    if {row.get("Service") for row in rows} != expected:
        raise SlopmeisterError("compose service state is incomplete")
    for row in rows:
        if not _service_ready(row) and not (
            row.get("State") == "running" and row.get("Health") == "starting"
        ):
            raise SlopmeisterError(f"compose service {row.get('Service')} failed readiness")
    return all(_service_ready(row) for row in rows)


def _service_ready(row: dict) -> bool:
    return (row.get("State") == "running" and row.get("Health", "") in ("", "healthy")) or (
        row.get("State") == "exited" and row.get("ExitCode") == 0
    )
