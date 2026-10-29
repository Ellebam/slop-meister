"""Render declared and live slot status."""

from __future__ import annotations

from pathlib import Path
import shutil

from slopmeister.errors import SlopmeisterError
from slopmeister.slots import allocation, tester
from slopmeister.threads import occupants


def static() -> int:
    shared: dict[int, list[tuple[str, int]]] = {}
    for target, data in allocation.declarations().items():
        if "target" not in data:
            continue
        if "repository" not in data["target"]:
            print(f"{target}: no repository")
            continue
        slots = data["slots"]
        if allocation.is_none(slots):
            print(f"{target}: none")
            continue
        compose = allocation.compose_relative(slots)
        suffix = f", compose {compose}" if compose else ""
        suffix += f", {allocation.testers(slots)} tester slots" if allocation.testers(slots) else ""
        print(f"{target}: {allocation.maximum(slots)} slots{suffix}")
        for number in range(1, allocation.maximum(slots) + allocation.testers(slots) + 1):
            ports = allocation.expand(slots, number)
            print(f"  slot {number}: " + " ".join(f"{key}={value}" for key, value in ports.items()))
            for port in ports.values():
                shared.setdefault(port, []).append((target, number))
    for port, rows in sorted(shared.items()):
        if len({target for target, _ in rows}) > 1:
            print("shared", port, " ".join(f"{target} slot {number}" for target, number in rows))
    return 0


def _compose_state(project: str, declared: bool) -> tuple[str, tuple[allocation.Resource, ...]]:
    if not declared:
        return "no compose", ()
    resources = allocation.project_resources(project)
    if resources is None:
        return "compose unavailable", ()
    return ("compose up" if resources else "compose down"), resources


def _working_directories(pids: list[int]) -> dict[int, Path]:
    if not pids:
        return {}
    executable = shutil.which("lsof")
    if not executable:
        return {}
    result = allocation.run(
        [executable, "-a", "-p", ",".join(map(str, pids)), "-d", "cwd", "-Fpn"],
        capture=True,
        ok=False,
    )
    if result.returncode:
        raise SlopmeisterError("cannot inspect listener working directories")
    found, pid = {}, None
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            found[pid] = Path(line[1:]).resolve()
    return found


def _workers(current: list[allocation.Live]) -> None:
    for item in current:
        try:
            processes = occupants.census(str(item.worktree))
        except occupants.CensusError:
            print(f"  {item.name} worker census unavailable")
            continue
        for process in processes:
            if process.inside:
                row = f"{process.kind} pid {process.pid} in {occupants.printable(process.cwd)}"
                print(f"  {item.name} worker {row}")


def _slot(item: allocation.Live) -> None:
    slots = allocation.definition(item.target)
    ports = allocation.expand(slots, item.slot)
    project = f"{item.target}-slot{item.slot}"
    state, resources = _compose_state(project, bool(allocation.compose_relative(slots)))
    values = " ".join(f"{key}={value}" for key, value in ports.items())
    print(f"{item.name} slot {item.slot} {item.target} {values} {state}")
    for resource in resources:
        suffix = f" {resource.state}" if resource.state else ""
        print(f"  {item.name} {resource.kind} {resource.name}{suffix}")


def live(repo: str) -> int:
    root = allocation.main_root(repo)
    current = [*allocation.live(root), *tester.live(root)]
    for item in current:
        _slot(item)
    if not current:
        print(f"no live slots under {root / '.worktrees'}")
    listeners = allocation.bound_ports()
    cwds = _working_directories(sorted({item.pid for item in listeners}))
    for item in current:
        slots = allocation.definition(item.target)
        expected = set(allocation.expand(slots, item.slot).values())
        worktree = item.worktree.resolve()
        for listener in listeners:
            cwd = cwds.get(listener.pid)
            if cwd and cwd.is_relative_to(worktree):
                suffix = "" if listener.port in expected else " stray"
                print(
                    f"  {item.name} listener {listener.port} pid {listener.pid} "
                    f"{listener.command}{suffix}"
                )
    _workers(current)
    return 0
