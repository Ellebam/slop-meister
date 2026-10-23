"""One worker session as timed events. The classifiers here keep log text out of them."""

from dataclasses import dataclass, field
from datetime import datetime
import re

REVIEW = re.compile(r"slopmeister\s+review\s+review\b[\s\S]{0,400}?--mode[ =](plan|diff)\b")
# Only where a shell runs it. Notes, commit messages and searches mention the gate far more often.
GATE = re.compile(
    r"(?:^|[;&|({\n])\s*(?:(?:do|then|timeout\s+\S+|\S*time(?:\s+-\w+)*)\s+)*"
    r"(?:task\s+check\b(?!:)|\S*bin/slopmeister[\"']?\s+check\b)([^;&|)\n]*)"
)
# A full gate that ended sooner was refused at once or only looked like a command.
GATE_SECONDS = 30
# These options make the gate run a part of its catalogue, or nothing.
# What a heredoc holds is written to a file or a program, it is not a command of this shell.
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n[\s\S]*?\n\s*\2\b")
GATE_SUBSET = re.compile(r"--(?:layer|ci|kind|list|clean|help)\b")
COMMAND_KINDS = (
    ("tester-launch", re.compile(r"slopmeister\s+tester\s+launch\b")),
    ("tester-collect", re.compile(r"slopmeister\s+tester\s+collect\b")),
    ("ship", re.compile(r"scripts/ship\.py\b")),
    ("ci-watch", re.compile(r"\bgh\s+(pr\s+checks|run\s+(watch|view|list))\b")),
    ("pr-merge", re.compile(r"\bgh\s+pr\s+merge\b")),
    ("commit", re.compile(r"\bgit\s+(-C\s+\S+\s+)?commit\b")),
    (
        "test-run",
        re.compile(
            r"\b(pytest|task\s+test\S*|scripts/test-\S+\.sh|npm\s+(run\s+)?test|"
            r"mvn\b[^\n;|&]*\b(test|verify)|gradlew?\b[^\n;|&]*\b(test|check)|"
            r"go\s+test|cargo\s+test|make\s+(test|check))\b"
        ),
    ),
    ("checksum", re.compile(r"\b(shasum|sha256sum|cmp)\b")),
    ("sleep", re.compile(r"^\s*sleep\s+\d+\s*$")),
)
# Time inside these is waiting on another process, not work.
WAIT_KINDS = frozenset(
    {"review-plan", "review-diff", "tester-collect", "tester-run", "ci-watch", "sleep"}
)
TEST_KINDS = frozenset({"test-run", "gate-focused", "gate-full"})
DELIVERED_SKILL = re.compile(r"\.(?:claude|agents)/skills/([a-z][a-z-]*)/SKILL\.md")
REPORT = re.compile(
    r"\*\*Result\*\*[\s\S]*\*\*Your move\*\*|\*\*What changed\*\*[\s\S]*\*\*Next\*\*"
)
EXPLAIN = re.compile(
    r"\?|explain|understand|unclear|confus|what do you mean|plain|dummy|"
    r"versteh|erkl[aä]r|was meinst|warum|wieso",
    re.I,
)
FINALIZE = re.compile(
    r"(?:^|\s)[/$](?:finalize|harvest)\b|^\s*finalize\b|<command-name>/(?:finalize|harvest)", re.I
)
RELAY = re.compile(r"^\s*Dispatcher here", re.I)
KICKOFF_MODE = re.compile(r"^Mode:\s*(spine|freeform)\s*$", re.M)
VALIDATION = "## Validation"
TEST_GUIDE = re.compile(r"TEST-GUIDE[^/]*\.md$")
NOT_SOURCE = re.compile(r"-NOTES\.md$|/memory/|/tmp/|/scratchpad/|/\.slopmeister/vault/|/My Drive/")


def epoch(stamp: str) -> float:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def command_kind(text: str) -> str:
    text = HEREDOC.sub("", text)
    review = REVIEW.search(text)
    if review:
        return "review-" + review.group(1)
    gate = GATE.search(text)
    if gate:
        return "gate-focused" if GATE_SUBSET.search(gate.group(1)) else "gate-full"
    return next((kind for kind, pattern in COMMAND_KINDS if pattern.search(text)), "other")


def user_kind(text: str, first: bool) -> str:
    if text.startswith("[Request interrupted"):
        return "interrupt"
    if RELAY.search(text):
        return "relay"
    if FINALIZE.search(text):
        return "finalize"
    return "kickoff" if first else "operator"


@dataclass
class Command:
    start: float
    end: float
    kind: str
    failed: bool


@dataclass
class Turn:
    end: float
    seconds: float
    report: bool


@dataclass
class User:
    when: float
    kind: str
    explains: bool = False


@dataclass
class Session:
    """What one session did and when, with no text from its log."""

    tool: str
    session_id: str = ""
    cwd: str = ""
    model: str = ""
    effort: str = ""
    mode: str = "unknown"
    resumed: bool = False
    users: list[User] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    skills: list[tuple[float, str]] = field(default_factory=list)
    edits: list[tuple[float, str]] = field(default_factory=list)
    tokens: list[tuple[float, int, int]] = field(default_factory=list)
    approvals: list[tuple[float, float]] = field(default_factory=list)
    tester_runs: list[str] = field(default_factory=list)
    activity: list[float] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    compactions: int = 0
    cost_usd: float = 0.0
    lines: int = 0

    def add_user(self, when: float, text: str) -> None:
        first = not any(user.kind in ("kickoff", "operator") for user in self.users)
        kind = user_kind(text, first)
        if kind == "kickoff":
            mode = KICKOFF_MODE.search(text)
            self.mode = mode.group(1) if mode else "unknown"
            self.resumed = "## Resume" in text
        explains = kind == "operator" and bool(EXPLAIN.search(text))
        self.users.append(User(when, kind, explains))

    def add_command(self, span: tuple[float, float], text: str, failed: bool) -> None:
        kind = command_kind(text)
        if kind == "gate-full" and span[1] - span[0] < GATE_SECONDS:
            kind = "gate-focused"
        self.commands.append(Command(span[0], span[1], kind, failed))
        self.skills.extend((span[0], name) for name in DELIVERED_SKILL.findall(text))

    def add_edit(self, when: float, path: str, body: str) -> None:
        if TEST_GUIDE.search(path):
            kind = "guide"
        elif VALIDATION in body:
            kind = "validation"
        elif NOT_SOURCE.search(path):
            return
        else:
            kind = "source"
            self.sources.add(path)
        self.edits.append((when, kind))
