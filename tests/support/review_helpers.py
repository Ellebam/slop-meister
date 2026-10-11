"""Shared fixtures and values for review unit and integration tests."""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path

import slopmeister.review.cli as review_cli
from slopmeister.review.config import DEFAULT_CONFIG_PATH, ReviewerConfig
from slopmeister.review.run import CommandResult, project_child_env
from slopmeister.review.schema import ReviewResult, SecurityLens

REPO_DIR = Path(__file__).resolve().parents[2]
DEFAULTS = __import__("tomllib").loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
CONFIG = ReviewerConfig("codex-model-x", "medium", "claude-model-x", "low")
CLEAN_LENS = {
    "finding": None,
    "checks": ["secrets", "trust-boundary inputs"],
    "evidence": "Nothing crosses a boundary.",
}
CLEAN_LENS_JSON = json.dumps(CLEAN_LENS)
CLEAN_REVIEW_JSON = json.dumps({"findings": [], "security_lens": CLEAN_LENS})
CLEAN_RESULT = ReviewResult((), SecurityLens(None, ("secrets",), "Nothing found."))
VALID_REVIEW_JSON = """{
  "findings": [{
    "severity": "MUST-FIX", "file": "scripts/lib/example.py", "line": 12,
    "title": "Missing guard", "rationale": "The reviewer boundary trusts external JSON.",
    "suggested_action": "Validate all fields before rendering.", "confidence": "high"
  }],
  "security_lens": {
    "finding": 1,
    "checks": ["secrets", "trust-boundary inputs", "injection vectors", "data leaks"],
    "evidence": "The unvalidated JSON is a trust-boundary defect."
  }
}"""


class FakeReviewRuntime:
    def __init__(self) -> None:
        self.worktrees: list = []
        self.review_results = deque([CommandResult(0, CLEAN_REVIEW_JSON)])
        self.commands: list[list[str]] = []
        self.envs: list[dict[str, str]] = []
        self.stdin_texts: list[str | None] = []

    def worktree(self, cwd: str) -> tuple[str, bool]:
        """Stand in for `review.run._worktree`: the queued states, then an unchanged clean tree."""
        state = self.worktrees.pop(0) if self.worktrees else ("tree", False)
        if isinstance(state, BaseException):
            raise state
        return state

    def set_review_output(self, stdout: str, *, stderr: str = "", returncode: int = 0) -> None:
        self.review_results = deque([CommandResult(returncode, stdout, stderr)])

    def set_review_exception(self, error: BaseException) -> None:
        self.review_results = deque([error])

    def __call__(self, argv, **options):
        command = list(argv)
        self.commands.append(command)
        self.envs.append(dict(options.get("env") or {}))
        self.stdin_texts.append(options.get("stdin_text"))
        result = (
            self.review_results.popleft()
            if len(self.review_results) > 1
            else self.review_results[0]
        )
        if isinstance(result, BaseException):
            raise result
        return result


SCRUBBED_PARENT = {
    "OPENAI_API_KEY": "sk-" + "openai-test-key-1234567890abcdef",
    "ANTHROPIC_API_KEY": "sk-" + "anthropic-test-key-1234567890abcdef",
    "ANTHROPIC_AUTH_TOKEN": "anthropic-auth-token",
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "CLAUDE_CODE_USE_VERTEX": "1",
    "AWS_PROFILE": "billing-profile",
    "AWS_REGION": "eu-central-1",
    "AWS_DEFAULT_REGION": "eu-central-1",
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "aws-secret",
    "AWS_SESSION_TOKEN": "aws-session",
    "AWS_BILLING_CHANNEL": "aws-billing",
    "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/google.json",
    "GOOGLE_CLOUD_PROJECT": "example-prod",
    "CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE": "/tmp/cloudsdk.json",
    "GCLOUD_PROJECT": "example-prod",
    "GCP_PROJECT": "example-prod",
    "ANTHROPIC_BASE_URL": "https://anthropic-proxy.example",
    "OPENAI_BASE_URL": "https://openai-proxy.example",
    "HTTPS_PROXY": "https://proxy.example",
    "PATH": "/usr/bin",
    "HOME": "/Users/tester",
    "USER": "tester",
    "SAFE_VALUE": "removed",
    "TMPDIR": "/tmp/tester",
    "LANG": "de_DE.UTF-8",
    "LC_ALL": "C.UTF-8",
    "LC_CTYPE": "UTF-8",
    "TRACKER_TOKEN": "secret_trackershape123456789",
}


def env_with_scrubbed_api_keys() -> tuple[dict[str, str], dict[str, str]]:
    parent = dict(SCRUBBED_PARENT)
    return parent, project_child_env(parent)


def finding(file: str, line: int, severity: str = "NITPICK") -> dict[str, object]:
    return {
        "severity": severity,
        "file": file,
        "line": line,
        "title": "t",
        "rationale": "r",
        "suggested_action": "a",
        "confidence": "low",
    }


def lens_line(gate: str) -> str:
    lines = [line for line in gate.splitlines() if line.startswith("**Security Lens:**")]
    assert len(lines) == 1, gate
    return lines[0]


def load_cli_module():
    return review_cli


def canned_cli(monkeypatch, tmp_path: Path, output: str = CLEAN_REVIEW_JSON):
    """The review CLI with a confirmed launcher task and a reviewer that answers `output`."""
    identity = {"task": tmp_path.name, "tool": "claude", "workspace": str(tmp_path)}
    monkeypatch.setattr(review_cli.launch_identity, "read", lambda *args: identity)
    monkeypatch.setattr(review_cli, "result_path", lambda *args: tmp_path / "result.json")
    monkeypatch.setattr(
        review_cli, "owned_reviewer_runner", lambda argv, **options: CommandResult(0, output)
    )
    return review_cli
