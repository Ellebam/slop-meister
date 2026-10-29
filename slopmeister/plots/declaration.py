"""Validate and load plots/<name>/plot.toml declarations."""

from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
from typing import Any

from slopmeister.plots.slot_validation import DEFAULT_MAX
from slopmeister.plots.slot_validation import validate as _validate_slots
from slopmeister.plots.validation import enum, fail, table
from slopmeister.plots.validation import safe as safe

NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


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
    for key in ("setup", "setup_files", "disposable"):
        if key in slots:
            rows.append(f"{key}\t-\t{json.dumps(slots[key])}")
    if "testers" in slots:
        rows.append(f"slots\ttesters\t{slots['testers']}")
    rows.append(f"slots\tmax\t{slots.get('max', DEFAULT_MAX)}")
    return rows
