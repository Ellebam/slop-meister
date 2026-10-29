"""Shared service-action fixtures for installer integration tests."""

import json
from pathlib import Path
import shutil

from slopmeister.install.service_actions import CONSUMER_FILES, ActionContext
from slopmeister.session.service_actions import supervisor

ROOT = Path(__file__).resolve().parents[3]


def profile(plot="example"):
    return dict(
        action="jira-read",
        plot=plot,
        origin="https://jira.example.invalid",
        expected_user="reader",
        account_id="A" * 26,
        vault_id="b" * 26,
        vault_name="Automation",
        pat_ref="op://Automation/JIRA_PAT/credential",
        password_ref="op://Automation/CLIENT_CERT/password",
        certificate_document="CLIENT_CERT",
        token_file="/private/credentials/service.env",
    )


def action_context(tmp_path, actions, profile_root=None):
    return ActionContext(
        tmp_path, "example", {"service_actions": actions}, tmp_path / "session", profile_root
    )


def fixture(tmp_path):
    root = tmp_path / "slopmeister"
    (root / "src").mkdir(parents=True)
    for name in ("permissions.toml", "native-permissions.toml"):
        shutil.copyfile(ROOT / "src" / name, root / "src" / name)
    source = root / "slopmeister/session/service_actions"
    source.mkdir(parents=True)
    for name in CONSUMER_FILES:
        path = source / name.removeprefix("service_actions/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic " + name)
    instructions = root / "src/service-actions/instructions.md"
    instructions.parent.mkdir(parents=True)
    instructions.write_text("Use only the approved action.")
    profiles = tmp_path / "profiles"
    directory = profiles / "example"
    directory.mkdir(parents=True)
    path = directory / "jira-read.json"
    path.write_text(json.dumps(profile()))
    path.chmod(0o600)
    return root, profiles, path


def selected_context(tmp_path, actions=("jira-read",)):
    root, profiles, _ = fixture(tmp_path)
    return ActionContext(
        root, "example", {"service_actions": list(actions)}, tmp_path / "session", profiles
    )


def consumer(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "ROOT", tmp_path)
    monkeypatch.setattr(supervisor.runtime, "require", lambda **_kwargs: None)
    monkeypatch.setenv("SLOPMEISTER_SERVICE_ACTION_INPUT", json.dumps(["--issue", "TEST-7"]))
    data = profile()
    data["native"] = False
    token = tmp_path / "service.env"
    token.write_text("OP_SERVICE_ACCOUNT_TOKEN=ops_SYNTHETIC_CANARY\n")
    token.chmod(0o600)
    data["token_file"] = str(token)
    (tmp_path / "config.json").write_text(json.dumps(data))
    return supervisor, data, token


def unlock_deliveries(tmp_path):
    for root in tmp_path.rglob("service-actions"):
        if root.parent.name in (".codex", ".claude") and root.is_dir():
            _unlock(root)


def _unlock(root):
    for path in [root, *root.rglob("*")]:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o755)
