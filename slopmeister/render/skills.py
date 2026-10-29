"""Render shared and plot-owned skills for Claude and Codex."""

from dataclasses import dataclass
from pathlib import Path
import shutil

from slopmeister.render.check import (
    check_meta_keys,
    frontmatter_value,
    parse_meta,
    reject_symlinks,
    resolve_tool_blocks,
    single_line,
    split_frontmatter,
    yaml_quote,
)

SHARED = "shared"
META_KEYS = {
    "codex_name",
    "codex_description",
    "codex_display_name",
    "codex_short_description",
    "codex_default_prompt",
}
INTERFACE_KEYS = (
    ("codex_display_name", "display_name"),
    ("codex_short_description", "short_description"),
    ("codex_default_prompt", "default_prompt"),
)


@dataclass(frozen=True)
class SkillRequest:
    source: Path
    out: Path
    manifest: list
    target: str | None = None
    overlay: Path | None = None
    local: bool = False


@dataclass(frozen=True)
class SkillContent:
    prefix: str
    body: str
    meta: dict
    frontmatter: str


def _copy_payload(source: Path, destination: Path, excluded: set[str]) -> list[Path]:
    copied = []
    for item in sorted(source.iterdir()):
        if item.name in excluded or item.name.startswith("."):
            continue
        target = destination / item.name
        if target.exists():
            raise ValueError(f"{item}: target payload collides with {target}")
        if item.is_dir():
            shutil.copytree(item, target)
            copied.extend(
                path.relative_to(destination) for path in target.rglob("*") if path.is_file()
            )
        else:
            shutil.copy2(item, target)
            copied.append(target.relative_to(destination))
    return copied


def _metadata(request: SkillRequest) -> dict:
    """Metadata is optional and carries Codex interface keys only. Location decides delivery."""
    meta_path = request.source / "skill.meta.yaml"
    meta = parse_meta(meta_path) if meta_path.is_file() else {}
    check_meta_keys(meta, META_KEYS, meta_path)
    for key, value in meta.items():
        single_line(value, meta_path, key)
    return meta


def _claude_prefix(prefix: str, frontmatter: str, request: SkillRequest) -> str:
    if request.overlay is None:
        return prefix
    path = request.overlay / "claude.frontmatter.yaml"
    if not path.exists():
        return prefix
    meta = parse_meta(path)
    check_meta_keys(meta, {"allowed-tools"}, path)
    if not meta.get("allowed-tools"):
        raise ValueError(f"{path}: must declare allowed-tools")
    allowed = single_line(meta["allowed-tools"], path, "allowed-tools")
    if frontmatter_value(frontmatter, "allowed-tools") is not None:
        raise ValueError(f"{path}: allowed-tools collides with shared skill frontmatter")
    closing = prefix.rfind("\n---")
    if closing < 0:
        raise ValueError(f"{request.source / 'SKILL.md'}: frontmatter has no closing --- line")
    return prefix[:closing] + f"\nallowed-tools: {allowed}" + prefix[closing:]


def _write_skill(request: SkillRequest, tool: str, content: SkillContent) -> list[Path]:
    parts = ("targets", request.target, "skills") if request.target else ("skills",)
    destination = request.out / tool / Path(*parts) / request.source.name
    destination.mkdir(parents=True)
    rendered = resolve_tool_blocks(
        content.body, tool, (request.source / "SKILL.md", content.prefix.count("\n"), request.local)
    )
    if tool == "codex":
        description = (
            content.meta.get("codex_description")
            or frontmatter_value(content.frontmatter, "description")
            or ""
        )
        rendered = (
            f"---\nname: {content.meta.get('codex_name', request.source.name)}\n"
            f"description: {description}\n---\n\n" + rendered.lstrip("\n")
        )
    else:
        rendered = content.prefix + rendered
    (destination / "SKILL.md").write_text(rendered)
    copied = _copy_payload(request.source, destination, {"SKILL.md", "skill.meta.yaml"})
    if request.overlay is not None:
        copied.extend(
            _copy_payload(
                request.overlay,
                destination,
                {"SKILL.md", "skill.meta.yaml", "claude.frontmatter.yaml"},
            )
        )
    return copied


def _write_interface(request: SkillRequest, meta: dict, gated: bool) -> None:
    interface = [(yaml, meta[key]) for key, yaml in INTERFACE_KEYS if meta.get(key)]
    if not gated and not interface:
        return
    chunks = []
    if interface:
        chunks.append(
            "interface:\n" + "".join(f"  {key}: {yaml_quote(value)}\n" for key, value in interface)
        )
    if gated:
        chunks.append("policy:\n  allow_implicit_invocation: false\n")
    parts = ("targets", request.target, "skills") if request.target else ("skills",)
    directory = request.out / "codex" / Path(*parts) / request.source.name / "agents"
    directory.mkdir()
    (directory / "openai.yaml").write_text("".join(chunks))


def render_skill(request: SkillRequest) -> list[Path]:
    reject_symlinks(request.source)
    if request.overlay is not None:
        reject_symlinks(request.overlay)
    source = request.source / "SKILL.md"
    text = source.read_text()
    frontmatter, body = split_frontmatter(text, source)
    if "{{" in frontmatter:
        raise ValueError(f"{source}: '{{{{' token in skill frontmatter")
    prefix = text[: len(text) - len(body)]
    meta = _metadata(request)
    claude = SkillContent(_claude_prefix(prefix, frontmatter, request), body, meta, frontmatter)
    copied = _write_skill(request, "claude", claude)
    _write_skill(request, "codex", SkillContent(prefix, body, meta, frontmatter))
    _write_interface(
        request, meta, frontmatter_value(frontmatter, "disable-model-invocation") == "true"
    )
    kind = "target-skill" if request.target else "skill"
    name = f"{request.target}/{request.source.name}" if request.target else request.source.name
    request.manifest.append((kind, name, request.target or SHARED))
    return copied
