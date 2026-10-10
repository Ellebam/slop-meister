"""Validate and load plots/<name>/plot.toml declarations."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib
from typing import Any

NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
VARIABLE = re.compile(r"[A-Z][A-Z0-9_]*")
RESERVED = {"SLOT", "SLOT_TARGET", "SLOT_NAME", "SLOT_PROJECT", "SLOT_DATA", "SLOT_COMPOSE"}
DEFAULT_MAX = 6
MAX_SLOTS = 99
MIN_PORT = 1024
MAX_PORT = 65535


def safe(text: object) -> str:
    """Make diagnostics one printable line."""
    return str(text).encode("unicode_escape").decode("ascii")


def fail(path: Path, key: str, reason: str) -> None:
    raise ValueError(f"{safe(path)}: {safe(key)}: {safe(reason)}")


def table(value: Any, keys: set[str] | None, context: tuple[Path, str]) -> dict:
    path, key = context
    if not isinstance(value, dict):
        fail(path, key, "expected a table")
    unknown = set(value) - keys if keys is not None else set()
    if unknown:
        field = sorted(unknown)[0]
        fail(path, f"{key}.{field}" if key != "<document>" else field, "unknown key")
    return value


def enum(value: Any, values: tuple[str, ...], context: tuple[Path, str]) -> None:
    if not isinstance(value, str) or value not in values:
        fail(*context, "required string, expected " + ", ".join(values))


def integer(value: Any, bounds: tuple[int, int], context: tuple[Path, str]) -> None:
    low, high = bounds
    if type(value) is not int or not low <= value <= high:
        fail(*context, f"expected an integer in {low} to {high}")


def _validate_plot(data: dict, path: Path) -> tuple[dict, str]:
    plot = table(data.get("plot"), {"base", "open-points", "seed"}, (path, "plot"))
    base = plot.get("base")
    if not isinstance(base, str) or not NAME.fullmatch(base):
        fail(path, "plot.base", "required name matching [a-z0-9][a-z0-9-]*")
    if "seed" in plot and type(plot["seed"]) is not bool:
        fail(path, "plot.seed", "expected a boolean recording outside-source history")
    points = plot.get("open-points")
    valid = (
        isinstance(points, list)
        and points
        and all(isinstance(point, str) and re.fullmatch(r"[a-z0-9-]+", point) for point in points)
    )
    if points is not None and (not valid or len(set(points)) != len(points)):
        fail(
            path,
            "plot.open-points",
            "expected a nonempty array of unique point names matching [a-z0-9-]+",
        )
    return plot, base


def _validate_target(data: dict, plot: dict, path: Path) -> dict:
    target = table(
        data["target"], {"tasks", "repository", "service_actions", "bloom"}, (path, "target")
    )
    if "bloom" in target:
        enum(target["bloom"], ("local", "tailnet"), (path, "target.bloom"))
    actions = target.get("service_actions", [])
    valid_actions = isinstance(actions, list) and all(
        isinstance(action, str) and NAME.fullmatch(action) for action in actions
    )
    if not valid_actions or len(set(actions)) != len(actions):
        fail(path, "target.service_actions", "expected an array of unique action names")
    enum(target.get("tasks"), ("github", "vault", "manual"), (path, "target.tasks"))
    if "open-points" in plot:
        fail(path, "plot.open-points", "a launchable plot must leave no points open")
    return target


def _validate_repository(target: dict, base: str, path: Path) -> dict | None:
    if "repository" not in target:
        if base != "freeform":
            fail(path, "plot.base", "a plot without a repository requires freeform")
        return None
    repository = table(
        target["repository"], {"commit", "shipping", "default"}, (path, "target.repository")
    )
    enum(repository.get("commit"), ("allow", "deny"), (path, "target.repository.commit"))
    if "shipping" in repository:
        enum(repository["shipping"], ("allow", "deny"), (path, "target.repository.shipping"))
    if "default" in repository:
        default = repository["default"]
        valid = (
            isinstance(default, str)
            and (default.startswith("/") or default.startswith("~/"))
            and ".." not in default.split("/")
            and not any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in default)
        )
        if not valid:
            fail(path, "target.repository.default", "expected safe absolute or ~/ path")
    return repository


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
    maximum = slots.get("max", DEFAULT_MAX)
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


def _validate_slots(data: dict, path: Path) -> None:
    slots = table(data.get("slots"), {"none", "max", "compose", "ports"}, (path, "slots"))
    if "none" in slots:
        if slots["none"] is not True or len(slots) != 1:
            fail(path, "slots.none", "must be boolean true and the only slots key")
        return
    integer(slots.get("max", DEFAULT_MAX), (1, MAX_SLOTS), (path, "slots.max"))
    compose = slots.get("compose")
    unsafe = compose is not None and (
        not isinstance(compose, str)
        or not compose
        or compose.startswith("/")
        or ".." in compose.split("/")
        or any(
            ord(char) < 32 or 127 <= ord(char) <= 159 or char in "\u2028\u2029" for char in compose
        )
    )
    if unsafe:
        fail(
            path,
            "slots.compose",
            "expected a nonempty relative path without .. segments or control characters",
        )
    ports = _slot_ports(slots, path)
    if not ports:
        fail(path, "slots", "declare at least one port variable, or none = true alone")
    _validate_collisions(slots, ports, path)


def validate(data: Any, path: Path) -> dict:
    data = table(data, {"plot", "target", "slots"}, (path, "<document>"))
    plot, base = _validate_plot(data, path)
    if "target" not in data:
        if "slots" in data:
            fail(path, "slots", "requires target.repository")
        return data
    target = _validate_target(data, plot, path)
    repository = _validate_repository(target, base, path)
    if repository is None:
        if "slots" in data:
            fail(path, "slots", "requires target.repository")
        return data
    _validate_slots(data, path)
    return data


def load_file(path: Path) -> dict:
    if not NAME.fullmatch(path.parent.name):
        fail(path, "<document>.<name>", "plot name must match [a-z0-9][a-z0-9-]*")
    if path.parent.is_symlink() or path.is_symlink():
        fail(path, "<document>.<path>", "symlinks are not allowed in declaration sources")
    if not path.is_file():
        fail(path, "<document>.<path>", "expected a regular plot.toml file")
    if (path.parent / "plot.md").exists() or (path.parent / "plot.md").is_symlink():
        fail(path, "<document>.<path>", "a plot cannot carry both plot.md and plot.toml")
    try:
        return validate(tomllib.loads(path.read_text(encoding="utf-8")), path)
    except (OSError, UnicodeError) as error:
        fail(path, "<document>.<syntax>", f"cannot read UTF-8 TOML ({type(error).__name__})")
    except tomllib.TOMLDecodeError as error:
        location = re.search(r"\(at (?:line \d+, column \d+|end of document)\)$", str(error))
        fail(path, "<document>.<syntax>", "invalid TOML " + (location.group() if location else ""))


def load_all(directory: Path) -> dict[str, dict]:
    if directory.is_symlink() or not directory.is_dir():
        fail(directory, "<document>.<path>", "expected a regular declaration directory")
    declarations: dict[str, dict] = {}
    for plot in sorted(directory.iterdir()):
        path = plot / "plot.toml"
        if plot.is_symlink():
            fail(path, "<document>.<path>", "symlinks are not allowed in plot sources")
        if plot.is_dir() and (path.exists() or path.is_symlink()):
            declarations[plot.name] = load_file(path)
    return declarations


def slot_rows(data: dict) -> list[str]:
    slots = data["slots"]
    if slots.get("none"):
        return ["none\t-\t-"]
    rows = [f"port\t{name}\t{port}" for name, port in slots.get("ports", {}).items()]
    if "compose" in slots:
        rows.append(f"compose\t-\t{slots['compose']}")
    rows.append(f"slots\tmax\t{slots.get('max', DEFAULT_MAX)}")
    return rows
