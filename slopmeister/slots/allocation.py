"""Validated slot definitions, allocations and workstation inventories."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

from slopmeister.errors import SlopmeisterError
from slopmeister.paths import main_checkout, plot_declarations
from slopmeister.plots.declaration import load_all
from slopmeister.slots.models import Claim as Claim
from slopmeister.slots.models import Listener as Listener
from slopmeister.slots.models import Live as Live
from slopmeister.slots.models import Resource as Resource

ALLOCATION = ".slot.env"
TESTER_RECORD = "tester.json"
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
RESOURCE_QUERIES = (
    ("container", ("ps", "-a"), "{{.ID}}\t{{.Names}}\t{{.Status}}"),
    ("volume", ("volume", "ls"), "{{.Name}}\t{{.Name}}"),
    ("network", ("network", "ls"), "{{.ID}}\t{{.Name}}"),
)


def declarations_path() -> Path:
    return plot_declarations()


def state_path() -> Path:
    return Path(os.environ.get("SLOT_STATE_DIR") or main_checkout() / "tmp/slots")


def validate_name(value: str, label: str) -> None:
    if not NAME.fullmatch(value):
        raise SlopmeisterError(f"{label} name '{value}' must match [a-z0-9][a-z0-9-]*")


def declarations() -> dict[str, dict]:
    try:
        return load_all(declarations_path())
    except (OSError, ValueError) as error:
        raise SlopmeisterError(str(error)) from error


def definition(target: str) -> dict:
    data = declarations().get(target)
    path = declarations_path() / target / "plot.toml"
    if data is None or "target" not in data or "repository" not in data["target"]:
        raise SlopmeisterError(f"{path}: slots: requires target.repository")
    return data["slots"]


def is_none(slots: dict) -> bool:
    return slots.get("none") is True


def maximum(slots: dict) -> int:
    return slots.get("max", 6)


def testers(slots: dict) -> int:
    return slots.get("testers", 0)


def compose_relative(slots: dict) -> str:
    return slots.get("compose", "")


def expand(slots: dict, number: int) -> dict[str, int]:
    return dict(sorted((name, port + number) for name, port in slots.get("ports", {}).items()))


def run(argv: list[str], *, capture: bool = False, ok: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(argv, capture_output=capture, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SlopmeisterError(f"cannot run {Path(argv[0]).name}") from error
    if ok and result.returncode:
        detail = result.stderr.strip() if capture else ""
        raise SlopmeisterError(detail or f"{Path(argv[0]).name} failed")
    return result


def compose(argv: list[str], *, ok: bool = True) -> subprocess.CompletedProcess:
    return run(["docker", "compose", *argv], ok=ok, capture=not ok)


def project_resources(project: str) -> tuple[Resource, ...] | None:
    docker = shutil.which("docker")
    if not docker or run([docker, "info"], ok=False, capture=True).returncode:
        return None
    label = f"label=com.docker.compose.project={project}"
    found = []
    for kind, command, output in RESOURCE_QUERIES:
        argv = [docker, *command, "--filter", label, "--format", output]
        result = run(argv, capture=True, ok=False)
        if result.returncode:
            raise SlopmeisterError(f"cannot inspect Docker {kind} resources for {project}")
        for row in result.stdout.splitlines():
            fields = row.split("\t", 2)
            if len(fields) >= 2 and all(fields[:2]):
                found.append(
                    Resource(kind, fields[0], fields[1], fields[2] if len(fields) == 3 else "")
                )
    return tuple(found)


def remove_project(project: str) -> list[str]:
    resources = project_resources(project)
    if resources is None:
        raise SlopmeisterError(f"Docker is unavailable, refusing to release {project}")
    commands = {
        "container": ["docker", "rm", "-f"],
        "volume": ["docker", "volume", "rm"],
        "network": ["docker", "network", "rm"],
    }
    labels = {"container": "containers", "volume": "volumes", "network": "networks"}
    removed = []
    for kind in commands:
        identifiers = [item.identifier for item in resources if item.kind == kind]
        if identifiers:
            run([*commands[kind], *identifiers])
            removed.append(labels[kind])
    residue = project_resources(project)
    if residue is None or residue:
        raise SlopmeisterError(f"Docker resources remain for {project}, refusing partial release")
    return removed


def main_root(argument: str) -> Path:
    candidate = Path(argument).expanduser()
    if not candidate.is_dir():
        raise SlopmeisterError(f"target repository not found: {argument}")
    top = run(["git", "-C", str(candidate), "rev-parse", "--show-toplevel"], capture=True, ok=False)
    if (
        top.returncode
        or not top.stdout.strip()
        or Path(top.stdout.strip()).resolve() != candidate.resolve()
    ):
        raise SlopmeisterError(f"not a non-bare git repository: {argument}")
    common = run(
        ["git", "-C", str(candidate), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture=True,
    ).stdout.strip()
    return Path(common).parent.resolve()


def read(path: Path) -> Live:
    try:
        lines = path.read_text().splitlines()
    except OSError as error:
        raise SlopmeisterError(f"cannot read allocation {path}") from error
    patterns = {
        "target": re.compile(r"SLOT_TARGET=([a-z0-9][a-z0-9-]*)$"),
        "slot": re.compile(r"SLOT=([1-9][0-9]?)$"),
        "name": re.compile(r"SLOT_NAME=([a-z0-9][a-z0-9-]*)$"),
    }
    values = {
        key: next((match.group(1) for line in lines if (match := pattern.fullmatch(line))), "")
        for key, pattern in patterns.items()
    }
    if not all(values.values()):
        raise SlopmeisterError(
            f"allocation {path} does not carry SLOT_TARGET, SLOT and SLOT_NAME in their "
            "strict shape, refusing to act on it"
        )
    return Live(values["target"], int(values["slot"]), values["name"], path.parent)


def live(root: Path) -> list[Live]:
    return [read(path) for path in sorted((root / ".worktrees").glob(f"*/{ALLOCATION}"))]


def bound_ports() -> list[Listener]:
    executable = shutil.which("lsof")
    if not executable:
        raise SlopmeisterError("lsof not found on PATH, the port preflight cannot run")
    result = run([executable, "-nP", "-iTCP", "-sTCP:LISTEN"], capture=True, ok=False)
    if result.returncode not in (0, 1):
        raise SlopmeisterError("cannot inspect live TCP listeners")
    found = set()
    for row in result.stdout.splitlines()[1:]:
        fields = row.split()
        if len(fields) < 9:
            continue
        try:
            found.add(Listener(int(fields[-2].rsplit(":", 1)[-1]), int(fields[1]), fields[0]))
        except ValueError:
            continue
    return sorted(found, key=lambda item: (item.port, item.pid, item.command))


def resolve_compose(root: Path, relative: str) -> Path:
    candidate = root / relative
    if not candidate.is_file() or not os.access(candidate, os.R_OK):
        raise SlopmeisterError(f"readable compose file not found at {candidate}")
    real_root, real = root.resolve(), candidate.resolve()
    if not real.is_relative_to(real_root):
        raise SlopmeisterError(
            f"compose path {relative} resolves to {real}, outside the checkout {real_root}"
        )
    return real


def content(claim: Claim) -> str:
    item, data, compose, ports = claim.live, claim.data, claim.compose, claim.ports
    rows = {
        "SLOT": str(item.slot),
        "SLOT_TARGET": item.target,
        "SLOT_NAME": item.name,
        "SLOT_PROJECT": f"{item.target}-slot{item.slot}",
        "SLOT_DATA": str(data),
        **({"SLOT_COMPOSE": str(compose)} if compose else {}),
        **{name: str(port) for name, port in ports.items()},
    }
    return "".join(f"{name}={value}\n" for name, value in sorted(rows.items()))


def write(path: Path, claim: Claim) -> None:
    path.write_text(content(claim))
