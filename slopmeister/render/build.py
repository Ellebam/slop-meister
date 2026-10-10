"""Build the complete deterministic dist/ tree."""

import argparse
from collections.abc import Sequence
from pathlib import Path
import shutil
import subprocess
import tempfile

from slopmeister.paths import DIST, ROOT
from slopmeister.plots import load_all
from slopmeister.render.agents import AgentRequest, render_agent
from slopmeister.render.check import trees_differ
from slopmeister.render.plots import render_plot, render_target_skills
from slopmeister.render.service_actions import render_service_actions
from slopmeister.render.settings import render_home, render_settings
from slopmeister.render.skills import SkillRequest, render_skill


def _render_skills(src: Path, out: Path, manifest: list) -> None:
    root = src / "skills"
    for skill in sorted(path for path in root.iterdir() if path.is_dir()):
        if not (skill / "SKILL.md").is_file():
            raise ValueError(f"{skill}: no SKILL.md")
        render_skill(SkillRequest(skill, out, manifest))


def _render_agents(src: Path, out: Path, manifest: list) -> None:
    root = src / "agents"
    tiers = sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    seen: dict[str, str] = {}
    for tier in tiers:
        for agent in sorted(tier.glob("*.md")):
            if agent.stem in seen:
                raise ValueError(
                    f"agent name collision: {tier.name}/{agent.stem} "
                    f"vs {seen[agent.stem]}/{agent.stem}"
                )
            seen[agent.stem] = tier.name
            render_agent(AgentRequest(agent, tier.name, out, manifest))


def _render_plots(paths: tuple[Path, Path, Path, dict], manifest: list) -> None:
    out, src, plots, declarations = paths
    for name in declarations:
        plot_dir = plots / name
        render_plot(plot_dir, (out, plots), manifest)
        if (plot_dir / "skills").is_dir():
            render_target_skills(plot_dir, (out, src, plots), manifest)


def _write_manifest(out: Path, manifest: list) -> None:
    lines = ["kind\tname\tplot\tclaude_gate\tcodex_gate"]
    lines.extend(
        f"{kind}\t{name}\t{plot}\t{str(claude).lower()}\t{str(codex).lower()}"
        for kind, name, plot, claude, codex in manifest
    )
    (out / "manifest.tsv").write_text("\n".join(lines) + "\n")


def build(out: Path, root: Path = ROOT) -> None:
    src, plots = root / "src", root / "plots"
    declarations = load_all(plots) if plots.exists() or plots.is_symlink() else {}
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    manifest: list = []
    _render_skills(src, out, manifest)
    _render_agents(src, out, manifest)
    _render_plots((out, src, plots, declarations), manifest)
    render_home(plots, out, manifest)
    render_settings(src, out, manifest)
    render_service_actions(src, out, manifest)
    _write_manifest(out, manifest)


def _counts(out: Path) -> tuple[int, int, int]:
    skills = (
        len(list((out / "claude" / "skills").iterdir()))
        if (out / "claude" / "skills").is_dir()
        else 0
    )
    agents = (
        len(list((out / "codex" / "agents").rglob("*.toml")))
        if (out / "codex" / "agents").is_dir()
        else 0
    )
    plots = (
        len(list((out / "claude" / "plots").glob("*.md")))
        if (out / "claude" / "plots").is_dir()
        else 0
    )
    return skills, agents, plots


def _check(root: Path, destination: Path) -> int:
    with tempfile.TemporaryDirectory() as temporary:
        fresh = Path(temporary) / "dist"
        build(fresh, root)
        if not destination.is_dir() or trees_differ(fresh, destination):
            print("dist/ is stale — run bin/slopmeister render")
            subprocess.run(["diff", "-rq", str(destination), str(fresh)], check=False)
            return 1
    print("dist/ is up to date")
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="slopmeister render")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        return _check(ROOT, DIST)
    build(DIST)
    skills, agents, plots = _counts(DIST)
    print(f"materialized {skills} skill(s), {agents} agent(s), {plots} plot(s) -> {DIST}")
    return 0
