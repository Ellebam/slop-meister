"""Render shared agent definitions for Claude and Codex."""

from dataclasses import dataclass
from pathlib import Path

from slopmeister.render.check import (
    check_meta_keys,
    frontmatter_value,
    parse_meta,
    split_frontmatter,
    toml_string,
)

META_KEYS = {"description", "nickname_candidates", "developer_instructions"}


@dataclass(frozen=True)
class AgentRequest:
    source: Path
    tier: str
    out: Path
    manifest: list


def _toml(meta: dict, frontmatter: str, name: str) -> str:
    description = meta.get("description") or frontmatter_value(frontmatter, "description") or ""
    nicknames = [
        item.strip() for item in meta.get("nickname_candidates", "").split(",") if item.strip()
    ]
    instructions = meta.get("developer_instructions", "")
    if not instructions:
        raise ValueError("developer_instructions is required for the Codex .toml stub")
    values = (
        toml_string(name),
        toml_string(description),
        ", ".join(map(toml_string, nicknames)),
        toml_string(instructions),
    )
    template = (
        "name = {}\ndescription = {}\nnickname_candidates = [{}]\ndeveloper_instructions = {}\n"
    )
    return template.format(*values)


def render_agent(request: AgentRequest) -> None:
    source, tier, out = request.source, request.tier, request.out
    name = source.stem
    meta_path = source.with_name(f"{name}.meta.yaml")
    meta = parse_meta(meta_path)
    check_meta_keys(meta, META_KEYS, meta_path)
    text = source.read_text()
    frontmatter, _ = split_frontmatter(text, source)
    for tool in ("claude", "codex"):
        destination = out / tool / "agents" / tier
        destination.mkdir(parents=True, exist_ok=True)
        (destination / f"{name}.md").write_text(text)
    try:
        rendered = _toml(meta, frontmatter, name)
    except ValueError as error:
        raise ValueError(f"{meta_path}: {error}") from error
    (out / "codex" / "agents" / tier / f"{name}.toml").write_text(rendered)
    request.manifest.append(("agent", f"{tier}/{name}", "all", False, False))
