"""The dispatcher guidance source carries the rules a dispatcher must follow."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUIDANCE = ("src/skills/plot-session/SKILL.md", "src/skills/plot-session/dispatcher.md")
REQUIRED = (
    "only when the operator says dispatch",
    "Mode: spine",
    "Mode: freeform",
    "Freeform is the default",
    "ticket-shaped repository implementation with acceptance criteria",
    "pipes the declared body over stdin by default",
    "line three of the final Codex kickoff",
    "never from a running process",
    "<plot>-<ticket>-<one or two words>",
    "task plot-session -- <slopmeister root> slopmeister slopmeister-<ticket>-<slug> "
    "--issue-id <ticket> --tool <tool> --model <model> -- --effort high < kickoff.md",
    "model requested",
    "model observed",
    "model comparison",
    "model evidence",
    "worker running, model unconfirmed",
    "A different name succeeds",
    "~/.slopmeister/sessions/<name>",
    "<name>-NOTES.md",
    "`writable_roots` of the workspace `.codex/config.toml`",
    "docs/contracts.md",
    "task kickoff:check",
    "Contents/Resources/bin/orca worktree ps --json",
    "older than ten minutes is unknown",
    "never copy status output",
    "only when the operator asks you to in this conversation",
)


def test_dispatcher_guidance_carries_rules():
    """Bug: a dispatch, mode, delivery, naming, model or directory rule ships missing."""
    text = "\n".join((ROOT / path).read_text() for path in GUIDANCE)
    assert [phrase for phrase in REQUIRED if phrase not in text] == []


def test_slot_dispatch_guidance_has_one_rule_and_consistent_pointers():
    """Bug: a dispatcher or slot skill still chooses plain launch for a resource plot."""
    dispatcher = (ROOT / GUIDANCE[1]).read_text()
    skill = (ROOT / GUIDANCE[0]).read_text()
    slots = (ROOT / "src/skills/slot/SKILL.md").read_text()
    settings = (ROOT / "src/claude/settings.json").read_text()
    assert "## Choose the worker command" in dispatcher
    assert "task plot -- --slots <plot>" in dispatcher
    assert "task slot:up -- <repo> <plot> <name>" in dispatcher
    assert "dispatcher.md#choose-the-worker-command" in skill
    assert "dispatcher.md#choose-the-worker-command" in slots
    assert "default when unsure is no slot" not in slots
    assert "task slot:up" in settings


def test_status_is_filtered_before_entering_dispatcher_context():
    """Bug: raw Orca previews enter context before a prose-only projection instruction."""
    text = (ROOT / GUIDANCE[1]).read_text()
    assert "Contents/Resources/bin/orca worktree ps --json | jq -c '" in text
    assert "minutes: ((now * 1000" in text
    assert "hostScope: .result.hostScope" in text
