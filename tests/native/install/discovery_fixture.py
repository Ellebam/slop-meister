"""Build the native configuration-discovery test fixture."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil

from tests.support.standin import Command, put, require, run

ROOT = Path(__file__).resolve().parents[3]
CODEX = Path.home() / ".local/bin/codex"
CLAUDE = shutil.which("claude")


@dataclass
class Discovery:
    """Paths and process state for one native discovery test."""

    root: Path
    env: dict
    home: Path
    codehome: Path
    claudestore: Path
    repo: Path
    extra: Path
    product: Path
    workspace: Path | None = None
    original: str = ""


def prepare(root):
    require(CLAUDE and CODEX.is_file(), "installed Claude and standalone Codex are required")
    home, codehome, claudestore = root / "home", root / "codex", root / "claude"
    repo, extra, product = root / "project", root / "extra", root / "slopmeister"
    for path in (home, codehome, claudestore, repo, extra, product):
        path.mkdir()
    env = environment(root, (home, codehome, claudestore))
    fixture = Discovery(root, env, home, codehome, claudestore, repo, extra, product)
    write_global(fixture)
    write_repository(fixture)
    commit_repository(fixture)
    write_product(fixture)
    return fixture


def environment(root, homes):
    home, codehome, claudestore = homes
    prefixes = ("ANTHROPIC_", "CLAUDE_", "CODEX_", "OPENAI_", "GIT_", "PLOT_", "SLOPMEISTER_")
    env = {key: value for key, value in os.environ.items() if not key.startswith(prefixes)}
    env.update(
        HOME=str(home),
        CODEX_HOME=str(codehome),
        CLAUDE_CONFIG_DIR=str(claudestore),
        GIT_CONFIG_GLOBAL=str(root / "gitconfig"),
        GIT_CONFIG_NOSYSTEM="1",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        CLAUDE_CODE_DISABLE_AUTO_MEMORY="1",
        CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD="1",
    )
    return env


def write_global(fixture):
    put(fixture.codehome / "AGENTS.md", "GLOBAL_CODEX_MARKER\n")
    put(fixture.claudestore / "CLAUDE.md", "GLOBAL_CLAUDE_MARKER\n")
    put(fixture.claudestore / "agents/global.md", skill("global", "GLOBAL_AGENT_MARKER"))
    hook = {
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "echo GLOBAL_HOOK_MARKER"}]}]
        }
    }
    put(fixture.claudestore / "settings.json", json.dumps(hook))
    versions = {
        tool: run(
            Command(
                [str(binary), "--version"],
                fixture.root,
                fixture.env,
                fixture.root / (tool + "-version"),
            )
        ).strip()
        for tool, binary in (("codex", CODEX), ("claude", CLAUDE))
    }
    print(json.dumps(versions), flush=True)


def skill(name, marker):
    return f"---\nname: {name}\ndescription: {marker}\n---\nFixture.\n"


def write_repository(fixture):
    repo, extra = fixture.repo, fixture.extra
    files = {
        "AGENTS.md": "FOREIGN_CODEX_ROOT\n",
        "AGENTS.override.md": "FOREIGN_CODEX_OVERRIDE\n",
        "memory-source.md": "FOREIGN_CLAUDE_ROOT\nFOREIGN_LINK_AGREEMENT\n@imported.md\n",
        "imported.md": "FOREIGN_IMPORT\n",
        "CLAUDE.local.md": "FOREIGN_CLAUDE_LOCAL\n",
        "nested/CLAUDE.md": "FOREIGN_CLAUDE_NESTED\n",
        "nested/AGENTS.md": "FOREIGN_CODEX_NESTED\n",
        "nested/app.txt": "ORDINARY_READ_CONTENT\n",
        "nested/.claude/rules/nested.md": "FOREIGN_NESTED_RULE\n",
        "fallback/OTHER.md": "FOREIGN_CODEX_FALLBACK\n",
        ".claude/rules/rule.md": "FOREIGN_RULE\n",
    }
    for relative, content in files.items():
        put(repo / relative, content)
    (repo / "CLAUDE.md").symlink_to("memory-source.md")
    write_repository_settings(repo)
    write_extensions(repo, extra)


def write_repository_settings(repo):
    put(
        repo / "nested/.codex/config.toml",
        'developer_instructions="FOREIGN_NESTED_CODEX_SETTINGS"\n',
    )
    put(repo / ".codex/config.toml", 'developer_instructions="FOREIGN_CODEX_SETTINGS"\n')
    hooks = {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "echo FOREIGN_CLAUDE_HOOK"}]}
            ]
        }
    }
    put(repo / ".claude/settings.json", json.dumps(hooks))
    hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "echo FOREIGN_MAIN_LOCAL_HOOK"
    put(repo / ".claude/settings.local.json", json.dumps(hooks))
    put(repo / ".claude/commands/legacy.md", skill("legacy", "FOREIGN_LEGACY_COMMAND"))


def write_extensions(repo, extra):
    for base, marker in (
        (repo / ".agents", "FOREIGN_CODEX_SKILL"),
        (repo / ".claude", "FOREIGN_CLAUDE_SKILL"),
        (extra / ".claude", "FOREIGN_EXTRA_SKILL"),
        (extra / ".agents", "FOREIGN_EXTRA_CODEX_SKILL"),
    ):
        name = "extra" if base.parent == extra else "foreign"
        put(base / f"skills/{name}/SKILL.md", skill(name, marker))
    put(repo / ".claude/agents/foreign.md", skill("foreign", "FOREIGN_CLAUDE_AGENT"))
    put(extra / ".claude/agents/extra.md", skill("extra", "FOREIGN_EXTRA_AGENT"))
    put(extra / ".codex/config.toml", 'developer_instructions="FOREIGN_EXTRA_CODEX_SETTINGS"\n')
    put(extra / "CLAUDE.md", "FOREIGN_EXTRA_MEMORY\n")
    put(extra / "AGENTS.md", "FOREIGN_EXTRA_CODEX\n")
    put(extra / "app.txt", "EXTRA_READ_CONTENT\n")


def git(fixture, arguments):
    argv = ["git", "-C", str(fixture.repo), "-c", "core.hooksPath=/dev/null", *arguments]
    return run(Command(argv, fixture.root, fixture.env, fixture.root / "last-git")).strip()


def commit_repository(fixture):
    git(fixture, ["init", "-q", "-b", "main"])
    git(fixture, ["add", "-A"])
    commit = [
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Create fixture",
    ]
    git(fixture, commit)
    fixture.original = git(fixture, ["rev-parse", "HEAD"])
    fixture.workspace = fixture.repo / ".worktrees/session"
    git(fixture, ["worktree", "add", "-qb", "session", str(fixture.workspace)])
    projects = "".join(
        f'[projects.{json.dumps(str(path))}]\ntrust_level="trusted"\n'
        for path in (fixture.repo, fixture.workspace, fixture.extra)
    )
    put(
        fixture.codehome / "config.toml", 'project_doc_fallback_filenames=["OTHER.md"]\n' + projects
    )


def write_product(fixture):
    for name in ("permissions.toml", "native-permissions.toml"):
        put(fixture.product / "src" / name, (ROOT / "src" / name).read_text())
    for name in ("bin", "slopmeister"):
        shutil.copytree(ROOT / name, fixture.product / name)
    put(
        fixture.product / "plots/probe/plot.toml",
        '[plot]\nbase="code"\n[target]\ntasks="manual"\n[target.repository]\ncommit="allow"\n[slots]\nnone=true\n',
    )
    put(
        fixture.product / "dist/manifest.tsv",
        "kind\tname\tplot\nskill\tslopmeister-probe\tshared\n",
    )
    for tool in ("claude", "codex"):
        copy_skills(fixture, tool)
        put(fixture.product / f"dist/{tool}/plots/probe.md", "SLOPMEISTER_AGREEMENT_MARKER\n")
        put(
            fixture.product / f"dist/{tool}/skills/slopmeister-probe/SKILL.md",
            skill("slopmeister-probe", "SLOPMEISTER_SKILL_MARKER"),
        )
    shutil.copy2(ROOT / "dist/claude/settings.json", fixture.product / "dist/claude/settings.json")
    rules = ROOT / "dist/codex/rules/permissions.rules"
    put(fixture.product / "dist/codex/rules/permissions.rules", rules.read_text())


def copy_skills(fixture, tool):
    for name in ("execute-plan", "ship"):
        source = ROOT / f"dist/{tool}/skills/{name}"
        shutil.copytree(source, fixture.product / f"dist/{tool}/skills/{name}")
