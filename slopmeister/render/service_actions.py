"""Copy fixed service-action payloads into the rendered tree."""

from pathlib import Path
import shutil

from slopmeister.render.check import reject_symlinks


def render_service_actions(src: Path, out: Path, manifest: list) -> None:
    actions = src / "service-actions"
    if not actions.exists():
        return
    reject_symlinks(actions)
    for path in sorted(actions.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(actions)
        destination = out / "service-actions" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        manifest.append(("service-action", relative.as_posix(), "selected", False, False))
