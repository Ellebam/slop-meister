"""A machine with the session op's files, for tests that drive the op without a real exec."""

import json
from pathlib import Path

from slopmeister.session import secret_approval, secret_tier

ONE, TWO = "ops_tier-one-synthetic", "ops_tier-two-synthetic"
LISTS = {
    "tier-one": [{"id": "idone", "name": "Everyday"}],
    "tier-two": [{"id": "idone", "name": "Everyday"}, {"id": "idtwo", "name": "Production"}],
}


def private(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o600)


def env_file(tmp_path: Path, text: str) -> list[str]:
    (tmp_path / "x.env").write_text(text)
    return ["run", "--env-file", str(tmp_path / "x.env"), "--", "deploy", "now"]


def approve(monkeypatch, state: str) -> list[dict]:
    """Home Assistant takes the question and answers every wait with the given state."""
    asked = []
    private(
        Path.home() / secret_tier.DIRECTORY / secret_approval.SETTINGS,
        json.dumps(
            {"ask_url": "https://ha.invalid/a", "answer_url": "https://ha.invalid/b", "token": "t"}
        ),
    )
    monkeypatch.setattr(secret_approval, "ask", lambda settings, body: asked.append(body))
    monkeypatch.setattr(secret_approval, "decision", lambda settings, identifier: state)
    return asked
