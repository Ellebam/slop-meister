"""Compose plot documents from bases and responsibility fragments."""

from pathlib import Path
import re

from slopmeister.plots import load_file
from slopmeister.render.check import FILL_MARKER, reject_symlinks
from slopmeister.render.skills import SkillRequest, render_skill

HOME_RENDERINGS = (("claude", "CLAUDE.md", "Claude Code"), ("codex", "AGENTS.md", "Codex"))


def check_text(text: str, origin: Path, allow_markers: bool) -> None:
    if "\r" in text:
        raise ValueError(f"{origin}: CRLF/CR line endings are not supported — convert to LF")
    for number, line in enumerate(text.splitlines(), 1):
        if allow_markers and FILL_MARKER.fullmatch(line):
            continue
        if "{{" in line.replace("{{TOOL}}", ""):
            raise ValueError(f"{origin}:{number}: unsanctioned '{{{{' token")


def h1_lines(text: str) -> list[int]:
    fenced, hits = False, []
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and re.match(r" {0,3}# ", line):
            hits.append(number)
    return hits


def base_markers(text: str, origin: Path) -> list[str]:
    names = []
    for line in text.splitlines():
        match = FILL_MARKER.fullmatch(line)
        if not match:
            continue
        if match.group(1) in names:
            raise ValueError(f"{origin}: duplicate insertion point {{{{FILL:{match.group(1)}}}}}")
        names.append(match.group(1))
    return names


def _document_base(base: Path, meta_path: Path) -> tuple[str, Path]:
    base_md, base_meta = base / "plot.md", base / "plot.toml"
    if base_meta.is_file():
        raise ValueError(f"{meta_path}: base {base.name!r} carries both plot.md and plot.toml")
    if base.is_symlink() or base_md.is_symlink():
        raise ValueError(f"{base_md}: symlinks are not allowed in plot sources")
    text = base_md.read_bytes().decode("utf-8")
    check_text(text, base_md, True)
    if len(h1_lines(text)) != 1:
        raise ValueError(
            f"{base_md}: a base carries exactly one H1 title, found {len(h1_lines(text))}"
        )
    return text, base_md


def _base_text(plots: Path, name: str, context: tuple[Path, bool]) -> tuple[str, Path]:
    meta_path, may_chain = context
    base = plots / name
    if (base / "plot.md").is_file():
        return _document_base(base, meta_path)
    if (base / "plot.toml").is_file():
        if not may_chain:
            raise ValueError(
                f"{meta_path}: base {name!r} is itself composed, chains are two levels"
            )
        text, open_points = compose_plot(base, plots)
        if not open_points:
            raise ValueError(f"{meta_path}: base {name!r} leaves no points open")
        return text, base
    raise ValueError(f"{meta_path}: base {name!r} not found — expected {base / 'plot.md'}")


def _fragments(plot_dir: Path, declaration: dict, markers: list[str]) -> dict[str, str]:
    fragments = {}
    open_points = declaration["plot"].get("open-points", [])
    for item in sorted(plot_dir.iterdir()):
        if item.name == "plot.toml" or item.name.startswith("."):
            continue
        if item.is_symlink():
            raise ValueError(f"{item}: symlinks are not allowed in plot sources")
        if item.is_dir() and item.name == "skills" and "target" in declaration:
            continue
        if item.is_dir() or item.suffix != ".md":
            raise ValueError(f"{item}: unexpected entry in a composed plot")
        if item.stem not in markers:
            raise ValueError(f"{item}: fragment has no {{{{FILL:{item.stem}}}}} marker")
        text = item.read_bytes().decode("utf-8")
        check_text(text, item, bool(open_points))
        headings = h1_lines(text)
        if headings:
            raise ValueError(
                f"{item}:{headings[0]}: fragment carries an H1 line — "
                "the base owns the document title"
            )
        fragments[item.stem] = text.rstrip()
    return fragments


def _compose(base: str, fragments: dict[str, str]) -> str:
    lines = []
    for line in base.splitlines():
        match = FILL_MARKER.fullmatch(line)
        if not match:
            lines.append(line)
        elif fragments[match.group(1)]:
            lines.append(fragments[match.group(1)])
    return "\n".join(lines).rstrip("\n") + "\n"


def compose_plot(plot_dir: Path, plots: Path) -> tuple[str, list[str]]:
    meta_path = plot_dir / "plot.toml"
    if (plot_dir / "plot.md").is_file():
        raise ValueError(f"{plot_dir}: carries both plot.md and plot.toml")
    declaration = load_file(meta_path)
    open_points = declaration["plot"].get("open-points", [])
    base, origin = _base_text(plots, declaration["plot"]["base"], (meta_path, not open_points))
    markers = base_markers(base, origin)
    fragments = _fragments(plot_dir, declaration, markers)
    missing = next((point for point in markers if point not in fragments), None)
    if missing:
        raise ValueError(
            f"{origin}: marker {{{{FILL:{missing}}}}} has no fragment — "
            f"expected {plot_dir / (missing + '.md')}"
        )
    composed = _compose(base, fragments)
    surviving = [
        match.group(1) for line in composed.splitlines() if (match := FILL_MARKER.fullmatch(line))
    ]
    if open_points and sorted(surviving) != sorted(open_points):
        raise ValueError(
            f"{meta_path}: open-points declares {' '.join(open_points)} but the fragments leave "
            f"{' '.join(surviving) or 'nothing'} open"
        )
    return composed, open_points


def render_plot(plot_dir: Path, paths: tuple[Path, Path], manifest: list) -> None:
    out, plots = paths
    composed, open_points = compose_plot(plot_dir, plots)
    if open_points:
        return
    for tool, _, label in HOME_RENDERINGS:
        destination = out / tool / "plots"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / f"{plot_dir.name}.md").write_text(composed.replace("{{TOOL}}", label))
    manifest.append(("plot", plot_dir.name, plot_dir.name))


def _target_source(paths: tuple[Path, Path], target: str, name: str) -> SkillRequest:
    """A folder with its own SKILL.md is the target's skill, any other folder patches the shared
    skill of that name. The folder's contents are the declaration, there is nothing else to read."""
    src, plots = paths
    folder = plots / target / "skills" / name
    if (folder / "SKILL.md").is_file():
        return SkillRequest(folder, Path(), [], target, None, True)
    source = src / "skills" / name
    if not (source / "SKILL.md").is_file():
        raise ValueError(f"{folder}: patches {name!r}, which is not a shared skill")
    return SkillRequest(source, Path(), [], target, folder)


def _missing_payload(skills_dir: Path, payloads: list, searchable: str) -> Path | None:
    return next(
        (
            skills_dir / name / path
            for name, path in payloads
            if path.as_posix() not in searchable and path.name not in searchable
        ),
        None,
    )


def render_target_skills(plot_dir: Path, paths: tuple[Path, Path, Path], manifest: list) -> None:
    out, src, plots = paths
    skills_dir, target = plot_dir / "skills", plot_dir.name
    reject_symlinks(skills_dir)
    payloads = []
    for folder in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
        source = _target_source((src, plots), target, folder.name)
        request = SkillRequest(source.source, out, manifest, target, source.overlay, source.local)
        payloads.extend((folder.name, path) for path in render_skill(request))
    searchable = (out / "codex" / "plots" / f"{target}.md").read_text()
    target_root = out / "claude" / "targets" / target / "skills"
    searchable += "\n".join(path.read_text(errors="replace") for path in target_root.rglob("*.md"))
    missing = _missing_payload(skills_dir, payloads, searchable)
    if missing:
        raise ValueError(f"{missing}: imported target payload has no rendered reference")
