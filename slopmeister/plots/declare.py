"""Interactive creation of one validated plot declaration."""

from contextlib import suppress
import json
import os
from pathlib import Path
import tomllib

from slopmeister.plots.declaration import enum, fail, load_all, safe, validate


def _answers(path: Path) -> dict:
    tasks = input("Task source (github, vault, manual): ")
    has_repo = input("Does this plot have a repository? (yes/no): ")
    enum(has_repo, ("yes", "no"), (path, "target.repository"))
    data = {"plot": {"base": "freeform"}, "target": {"tasks": tasks}}
    if has_repo == "yes":
        permission = input("Agent commit permission (allow, deny): ")
        data["plot"]["base"] = "inject"
        data["target"]["repository"] = {"commit": permission}
        data["slots"] = {"none": True}
    return validate(data, path)


def _render(data: dict) -> str:
    plot, target = data["plot"], data["target"]
    text = f"[plot]\nbase = {json.dumps(plot['base'])}\n\n[target]\n"
    text += f"tasks = {json.dumps(target['tasks'])}\n"
    if "repository" in target:
        permission = target["repository"]["commit"]
        text += (
            f"\n[target.repository]\ncommit = {json.dumps(permission)}\n\n[slots]\nnone = true\n"
        )
    return text


def _write(directory: Path, name: str, text: str) -> None:
    root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with suppress(FileExistsError):
            os.mkdir(name, dir_fd=root_fd)
        plot_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        try:
            if "plot.md" in os.listdir(plot_fd):
                fail(
                    directory / name / "plot.toml",
                    "<document>.<path>",
                    "plot.md appeared, nothing declared",
                )
            fd = os.open("plot.toml", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644, dir_fd=plot_fd)
            with os.fdopen(fd, "w") as stream:
                stream.write(text)
        finally:
            os.close(plot_fd)
    finally:
        os.close(root_fd)


def declare(directory: Path, name: str) -> str:
    path = directory / name / "plot.toml"
    if name in load_all(directory):
        return f"plot '{name}' is already declared, nothing to do"
    if (path.parent / "plot.md").exists():
        fail(path, "<document>.<path>", "cannot turn an existing plot.md base into a declaration")
    data = _answers(path)
    text = _render(data)
    validate(tomllib.loads(text), path)
    print(f"\nDeclaration for {safe(path)}:\n{text}", end="")
    if input("Write this declaration? (yes/no): ") != "yes":
        fail(path, "<document>.<confirmation>", "not confirmed, nothing declared")
    load_all(directory)
    _write(directory, name, text)
    return f"\ndeclared: {name}"
