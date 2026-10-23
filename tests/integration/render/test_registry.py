"""Repository renders cover every declared plot, skill, and native setting."""

import ast
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT))

from slopmeister.render.settings import permission_contract, render_settings  # noqa: E402


def test_check_registry_coverage_cases():
    listed = subprocess.run(
        ["bin/slopmeister", "plots", "--list"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    names = [row[0] for line in listed if (row := line.split("\t"))[1] != "template"]
    assert names
    assert all(
        (DIST / tool / "plots" / f"{name}.md").is_file()
        for name in names
        for tool in ("claude", "codex")
    )


def test_check_render_is_current():
    result = subprocess.run(
        ["bin/slopmeister", "render", "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.rstrip().endswith("dist/ is up to date")


def test_check_home_parity():
    claude = (DIST / "claude/CLAUDE.md").read_bytes()
    codex = (DIST / "codex/AGENTS.md").read_bytes()
    assert _normalize(claude) == _normalize(codex)


def _normalize(raw: bytes) -> bytes:
    return raw.replace(b"Claude Code", b"__TOOL__").replace(b"Codex", b"__TOOL__")


def _rules(path: Path) -> dict[tuple[str, ...], tuple[str, str]]:
    found = {}
    for node in ast.parse(path.read_text()).body:
        fields = {field.arg: ast.literal_eval(field.value) for field in node.value.keywords}
        found[tuple(fields["pattern"])] = (fields["decision"], fields.get("justification", ""))
    return found


def _contract() -> list[dict]:
    return permission_contract(ROOT / "src/permissions.toml")["command"]


def test_check_contract_renders_to_every_tool():
    codex = _rules(DIST / "codex/rules/permissions.rules")
    claude = json.loads((DIST / "claude/settings.json").read_text())["permissions"]
    opencode = json.loads((DIST / "opencode/permission.json").read_text())["bash"]
    native = {"allow": "allow", "needs_intent": "prompt", "deny": "forbidden"}
    asked = {"allow": "allow", "needs_intent": "ask", "deny": "deny"}
    for entry in _contract():
        prefix, decision = entry["prefix"], entry["decision"]
        assert codex[tuple(prefix.split())] == (native[decision], entry["why"])
        assert opencode[prefix] == opencode[prefix + " *"] == asked[decision]
        rules = [f"Bash({form})" for form in (prefix, prefix + " *")]
        destination = decision
        everywhere = [rule for kind in ("allow", "ask", "deny") for rule in claude.get(kind, [])]
        carried = [rule for rule in rules if rule in everywhere]
        assert carried == (rules if destination in ("allow", "ask", "deny") else [])
        assert all(rule in claude.get(destination, []) for rule in carried)


def test_check_home_template_carries_the_contract_denies():
    """Bug: the contract gains or loses a deny and the operator's home template drifts from it."""
    home = json.loads((ROOT / "plots/home/claude/settings.json.tmpl").read_text())
    denied = [entry["prefix"] for entry in _contract() if entry["decision"] == "deny"]
    assert home["permissions"]["deny"] == [f"Bash({prefix} *)" for prefix in denied]


def test_check_contract_leaves_github_out_of_claude_ask():
    claude = json.loads((DIST / "claude/settings.json").read_text())["permissions"]
    assert [rule for rule in claude.get("ask", []) if "gh " in rule] == []


def test_check_needs_intent_reaches_the_claude_classifier():
    """Bug: needs_intent renders nothing for Claude, so an unasked merge has no guard at all."""
    auto = json.loads((DIST / "claude/settings.json").read_text())["autoMode"]
    assert auto["soft_deny"][0] == "$defaults"
    rule = auto["soft_deny"][1]
    for entry in _contract():
        if entry["decision"] == "needs_intent":
            assert entry["prefix"] in rule
    assert "unless the operator's own message names that exact action" in rule


def test_check_representative_commands_keep_their_decision():
    """Bug: a write is quietly downgraded to allow, or a read upgraded, and only data changed."""
    expected = {
        "gh issue view": "allow",
        "gh pr list": "allow",
        "gh run view": "allow",
        "gh pr merge": "needs_intent",
        "gh issue create": "needs_intent",
        "gh pr comment": "needs_intent",
        "gh repo create": "needs_intent",
        "gh gist": "needs_intent",
        "gh ssh-key": "needs_intent",
        "gh api": "needs_intent",
        "gh auth token": "deny",
        "glab issue view": "allow",
        "glab issue list": "allow",
        "glab work-items list": "allow",
        "glab issue note": "needs_intent",
        "glab mr merge": "needs_intent",
        "glab ci trigger": "needs_intent",
        "glab repo update": "needs_intent",
        "glab mr for": "needs_intent",
        "glab issue board create": "needs_intent",
        "glab api": "needs_intent",
        "glab auth": "deny",
        "glab config": "deny",
        "op read": "deny",
    }
    decisions = {entry["prefix"]: entry["decision"] for entry in _contract()}
    assert {prefix: decisions.get(prefix) for prefix in expected} == expected


def test_check_contract_covers_helper_commands():
    decisions = {entry["prefix"]: entry["decision"] for entry in _contract()}
    for prefix in ("gh pr create", "gh pr edit", "gh issue comment"):
        assert decisions[prefix] == "needs_intent"


def test_write_intent_has_one_central_policy_and_reaches_opencode():
    """Bug: delivered Atlassian writes have no central intent policy or OpenCode gate."""
    contract = permission_contract(ROOT / "src/permissions.toml")
    policies = {entry["action"]: entry for entry in contract.get("service_action", [])}
    assert set(policies) == {"jira-write", "confluence-write"}
    bash = json.loads((DIST / "opencode/permission.json").read_text())["bash"]
    for action, entry in policies.items():
        assert entry["decision"] == "needs_intent" and entry["why"]
        pattern = f"*/service-actions/{action}/entry.py"
        assert bash[pattern] == bash[pattern + " *"] == "ask"


def test_check_contract_refusals(tmp_path):
    base = (ROOT / "src/permissions.toml").read_text()
    cases = (
        base + '\n[[command]]\nprefix = "gh pr view"\ndecision = "deny"\nwhy = "clash"\n',
        base + '\n[[command]]\nprefix = "gh gist create"\ndecision = "sometimes"\nwhy = "x"\n',
        base + '\n[[command]]\nprefix = "gh gist create"\ndecision = "deny"\nwhy = ""\n',
        base + '\n[[command]]\nprefix = "gh gist *"\ndecision = "deny"\nwhy = "wild"\n',
        base + '\n[[command]]\nprefixes = ["glab api"]\ndecision = "deny"\nwhy = "clash"\n',
        base + '\n[[command]]\nprefixes = "glab x"\ndecision = "deny"\nwhy = "no list"\n',
        base + '\n[[command]]\nprefixes = []\ndecision = "deny"\nwhy = "an empty group vanishes"\n',
        base + '\n[[command]]\nprefix = "a"\nprefixes = ["b"]\ndecision = "deny"\nwhy = "both"\n',
    )
    for index, text in enumerate(cases):
        source = tmp_path / f"case{index}"
        source.mkdir()
        (source / "permissions.toml").write_text(text)
        shutil.copy2(ROOT / "src/native-permissions.toml", source / "native-permissions.toml")
        shutil.copy2(ROOT / "src/claude/settings.json", source / "settings.json")
        (source / "claude").mkdir()
        shutil.copy2(ROOT / "src/claude/settings.json", source / "claude/settings.json")
        with pytest.raises(ValueError):
            render_settings(source, tmp_path / f"out{index}", [])


@pytest.mark.parametrize(
    "broken",
    ["duplicate", "unknown", "decision", "missing_allow"],
)
def test_service_write_policy_refuses_missing_or_unprompted_authority(tmp_path, broken):
    """Bug: malformed policies render standing writes or omit their credential boundary."""
    base = (ROOT / "src/native-permissions.toml").read_text()
    extra = '\n[[service_action]]\naction="jira-write"\ndecision="needs_intent"\n'
    extra += 'why="x"\ncredential_allow="x"\n'
    cases = {
        "duplicate": base + extra,
        "unknown": base + extra.replace("jira-write", "jira-delete"),
        "decision": base.replace(
            'decision = "needs_intent"\nwhy = "Every invocation',
            'decision = "allow"\nwhy = "Every invocation',
        ),
        "missing_allow": base.replace("credential_allow =", "missing_allow =", 1),
    }
    source = tmp_path / "src"
    (source / "claude").mkdir(parents=True)
    (source / "native-permissions.toml").write_text(cases[broken])
    shutil.copyfile(ROOT / "src/permissions.toml", source / "permissions.toml")
    shutil.copyfile(ROOT / "src/claude/settings.json", source / "claude/settings.json")
    with pytest.raises(ValueError):
        render_settings(source, tmp_path / "dist", [])


def test_check_no_placeholder():
    needles = (b"{{TOOL}}", b"{{FILL:", b"{{TOOL:", b"{{/TOOL}}")
    offenders = [
        path
        for path in DIST.rglob("*")
        if path.is_file() and any(needle in path.read_bytes() for needle in needles)
    ]
    assert offenders == []


def test_check_skill_renderings():
    for skill in sorted(path for path in (ROOT / "src/skills").iterdir() if path.is_dir()):
        claude = DIST / "claude/skills" / skill.name / "SKILL.md"
        codex = DIST / "codex/skills" / skill.name / "SKILL.md"
        assert claude.is_file() and codex.is_file()
        if b"{{TOOL:" not in (skill / "SKILL.md").read_bytes():
            assert claude.read_bytes() == (skill / "SKILL.md").read_bytes()
        assert codex.read_text().startswith(f"---\nname: {skill.name}\n")


def test_check_manifest():
    with (DIST / "manifest.tsv").open() as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    skills = {path.name for path in (ROOT / "src/skills").iterdir() if path.is_dir()}
    rendered = {row["name"] for row in rows if row["kind"] == "skill"}
    assert rendered == skills
    assert sum(row["kind"] == "rules" and row["name"] == "permissions.rules" for row in rows) == 1
