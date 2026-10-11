"""Whether the live allow-rule files carry the rules the home templates declare, by status only.

The report never prints live content. The live files hold approvals the operator added for
field work, and a textual diff would put those identifiers into agent output and from there
into a notes file or a pull request. It only reads, the operator edits both files.
"""

import ast
from collections.abc import Callable
import json
from pathlib import Path

from slopmeister.paths import ROOT

CLAUDE_TEMPLATE = "plots/home/claude/settings.json.tmpl"
CODEX_TEMPLATE = "plots/home/codex/rules/default.rules"
CLAUDE_LIVE = ".claude/settings.json"
CODEX_LIVE = ".codex/rules/default.rules"
# The Codex template is mostly a reference seed, only the rules it justifies are Slopmeister's.
CODEX_OWNED = "Slopmeister"
CLAUDE_DECISIONS = ("allow", "deny", "ask")
PRESENT = "present"
ABSENT = "absent"
DIFFERS = "decision differs"


def _expand(text: str, home: Path) -> str:
    # Codex reads a variable as opaque text, so the live file spells the path out.
    return text.replace("$HOME", str(home))


def _claude(text: str) -> dict[str, str]:
    permissions = json.loads(text).get("permissions", {})
    return {
        rule: decision
        for decision in CLAUDE_DECISIONS
        for rule in permissions.get(decision, [])
        if isinstance(rule, str)
    }


def _codex(text: str, owned_only: bool = False) -> dict[str, str]:
    rules = {}
    for node in ast.walk(ast.parse(text)):
        is_rule = isinstance(node, ast.Call) and getattr(node.func, "id", "") == "prefix_rule"
        if not is_rule:
            continue
        fields = {k.arg: ast.literal_eval(k.value) for k in node.keywords if k.arg}
        if owned_only and not str(fields.get("justification", "")).startswith(CODEX_OWNED):
            continue
        pattern = fields.get("pattern")
        if isinstance(pattern, list):
            rules[" ".join(map(str, pattern))] = str(fields.get("decision", "allow"))
    return rules


def _status(rule: str, wanted: str, live: dict[str, str]) -> str:
    if rule not in live:
        return ABSENT
    return PRESENT if live[rule] == wanted else DIFFERS


def _compare(live: tuple[str, str, Callable], template: dict[str, str], home: Path) -> list[str]:
    """Matched with $HOME expanded, printed in the template's own spelling."""
    tool, relative, parse = live
    rules: dict[str, str] = {}
    if (home / relative).is_file():
        try:
            rules = parse((home / relative).read_text())
        except ValueError, SyntaxError, AttributeError, TypeError:
            # The parser's message can quote the live line, so none of it is repeated.
            return [f"  unreadable: ~/{relative}, compared nothing"]
    return [
        f"  {_status(_expand(rule, home), decision, rules)}: {tool} {decision} {rule}"
        for rule, decision in template.items()
    ]


def report(home: Path, root: Path = ROOT) -> list[str]:
    """One line per template rule, its status, tool, decision and the template's own text."""
    claude = _claude((root / CLAUDE_TEMPLATE).read_text())
    codex = _codex((root / CODEX_TEMPLATE).read_text(), owned_only=True)
    return [
        *_compare(("claude", CLAUDE_LIVE, _claude), claude, home),
        *_compare(("codex", CODEX_LIVE, _codex), codex, home),
    ]
