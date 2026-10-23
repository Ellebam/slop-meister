"""Validate slot setup outputs and nonoverlapping worker and tester port ranges."""

from pathlib import Path
import re
from typing import Any

from slopmeister.plots.validation import fail, integer, table

VARIABLE = re.compile(r"[A-Z][A-Z0-9_]*")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
RESERVED = {"SLOT", "SLOT_TARGET", "SLOT_NAME", "SLOT_PROJECT", "SLOT_DATA", "SLOT_COMPOSE"}
DEFAULT_MAX = 6
MAX_SLOTS = 99
MIN_PORT = 1024
MAX_PORT = 65535
SLOT_KEYS = {"none", "max", "compose", "ports", "setup", "setup_files", "testers"}


def _slot_ports(slots: dict, path: Path) -> list[tuple[str, int]]:
    ports: list[tuple[str, int]] = []
    for name, port in table(slots.get("ports", {}), None, (path, "slots.ports")).items():
        key = f"slots.ports.{name}"
        if not isinstance(name, str) or not VARIABLE.fullmatch(name):
            fail(path, key, "variable must match [A-Z][A-Z0-9_]*")
        if name in RESERVED:
            fail(path, key, "variable is reserved for the allocation")
        integer(port, (MIN_PORT, MAX_PORT), (path, key))
        ports.append((name, port))
    return ports


def _validate_collisions(slots: dict, ports: list[tuple[str, int]], path: Path) -> None:
    maximum = slots.get("max", DEFAULT_MAX) + slots.get("testers", 0)
    used: dict[int, str] = {}
    for slot in range(1, maximum + 1):
        for name, base_port in ports:
            port = base_port + slot
            if port > MAX_PORT:
                fail(
                    path, f"slots.ports.{name}", f"reaches {port} at slot {slot}, above {MAX_PORT}"
                )
            if port in used:
                fail(
                    path,
                    f"slots.ports.{name}",
                    f"{used[port]} and {name} at slot {slot} both use port {port}, "
                    "a plot may not collide with itself",
                )
            used[port] = f"{name} at slot {slot}"


def _relative(value: Any, *, output: bool = False) -> bool:
    if not isinstance(value, str) or not value or value.startswith("/"):
        return False
    forbidden = {".", "..", "", ".git", ".slot.env"} if output else {".."}
    return not set(value.split("/")) & forbidden and not CONTROL.search(value)


def _validate_setup(slots: dict, path: Path) -> None:
    command = slots.get("setup")
    if command is not None and (
        not isinstance(command, list)
        or not command
        or any(not isinstance(arg, str) or not arg or CONTROL.search(arg) for arg in command)
    ):
        fail(path, "slots.setup", "expected a nonempty argument array without control characters")
    for key in ("setup_files",):
        names = slots.get(key, [])
        if not isinstance(names, list) or any(not _relative(n, output=True) for n in names):
            fail(path, "slots." + key, "expected unique relative output paths")
        needs_setup = key == "setup_files" and command is None
        if len(names) != len(set(names)) or (names and needs_setup):
            fail(path, "slots." + key, "expected unique outputs, setup_files requires setup")


def validate(data: dict, path: Path) -> None:
    slots = table(data.get("slots"), SLOT_KEYS, (path, "slots"))
    if "none" in slots:
        if slots["none"] is not True or len(slots) != 1:
            fail(path, "slots.none", "must be boolean true and the only slots key")
        return
    integer(slots.get("max", DEFAULT_MAX), (1, MAX_SLOTS), (path, "slots.max"))
    integer(slots.get("testers", 0), (0, MAX_SLOTS), (path, "slots.testers"))
    if slots.get("max", DEFAULT_MAX) + slots.get("testers", 0) > MAX_SLOTS:
        fail(path, "slots.testers", f"max and testers together exceed {MAX_SLOTS} slots")
    if (compose := slots.get("compose")) is not None and not _relative(compose):
        fail(path, "slots.compose", "expected a nonempty relative path without .. or controls")
    _validate_setup(slots, path)
    ports = _slot_ports(slots, path)
    if not ports:
        fail(path, "slots", "declare at least one port variable, or none = true alone")
    _validate_collisions(slots, ports, path)
