"""Find OpenCode, the provider variables its configuration names, and its session evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from slopmeister.review.process import project_child_env

PERMISSION = Path(__file__).resolve().parents[2] / "dist/opencode/permission.json"
ENV_REFERENCE = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")
COMMAND_SECONDS = 60
# Shorter values would rewrite ordinary text, the provider keys this guards are far longer.
MIN_SECRET_LENGTH = 8


class Blocked(ValueError):
    """An OpenCode run that cannot start or cannot be proven, never a verdict on the subject."""

    def __init__(self, reason: str, cause: str, fix: str) -> None:
        super().__init__(f"{reason}: {cause}. Fix: {fix}.")
        self.reason = reason


@dataclass(frozen=True)
class Store:
    """The OpenCode executable, the directory its sessions belong to and its environment."""

    binary: str
    directory: Path
    env: Mapping[str, str]


def binary(path: str | None = None) -> str:
    found = shutil.which("opencode", path=path)
    if not found:
        raise Blocked(
            "opencode not found",
            "no opencode executable on PATH",
            "install OpenCode or add it to PATH",
        )
    return found


def _config_files(env: Mapping[str, str]) -> list[Path]:
    if env.get("OPENCODE_CONFIG"):
        return [Path(env["OPENCODE_CONFIG"])]
    base = Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME", "~")) / ".config")
    return [base.expanduser() / "opencode" / name for name in ("opencode.json", "opencode.jsonc")]


def provider_names(env: Mapping[str, str]) -> list[str]:
    """Variable names only, the values stay in the environment and never pass through here."""
    names: set[str] = set()
    for path in _config_files(env):
        if path.is_file():
            names.update(ENV_REFERENCE.findall(path.read_text(errors="replace")))
    return sorted(names)


def require_provider(env: Mapping[str, str]) -> list[str]:
    names = provider_names(env)
    for name in names:
        if not env.get(name):
            raise Blocked(
                f"provider variable {name} unset",
                f"the OpenCode configuration references {{env:{name}}} and it is empty here",
                f"export {name} in ~/.zshenv so non-interactive shells and agents see it",
            )
    return names


def permission(edit: bool = True) -> dict:
    rules = json.loads(PERMISSION.read_text())
    return rules if edit else {**rules, "edit": "deny"}


def child_env(source: Mapping[str, str], names: list[str], rules: dict) -> dict:
    env = project_child_env(source)
    env.update({name: source[name] for name in names if source.get(name)})
    env["OPENCODE_DISABLE_CLAUDE_CODE"] = "1"
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"permission": rules}, separators=(",", ":"))
    return env


def _json(store: Store, *args: str, empty: object = None) -> object:
    """Read through a file, not a pipe, so a large export never depends on pipe flushing at exit."""
    label = "opencode " + " ".join(args[:2])
    try:
        with tempfile.TemporaryFile() as output:
            done = subprocess.run(
                [store.binary, *args], cwd=store.directory, env=dict(store.env), stdout=output,
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=COMMAND_SECONDS,
            )  # fmt: skip
            output.seek(0)
            text = output.read().decode(errors="replace")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Blocked(
            "no native evidence", f"{label} did not complete: {error}", "retry"
        ) from error
    if done.returncode:
        cause = f"{label} exited {done.returncode}"
        raise Blocked("no native evidence", cause, "check that the OpenCode store is readable")
    if not text.strip() and empty is not None:
        return empty
    try:
        return json.loads(text)
    except ValueError as error:
        cause = f"{label} returned incomplete JSON ({len(text)} characters): {error}"
        raise Blocked("no native evidence", cause, "rerun it by hand and compare") from error


def sessions(store: Store) -> list[dict]:
    listed = _json(store, "session", "list", "--format", "json", empty=[])
    real = os.path.realpath(store.directory)
    return [row for row in listed if isinstance(row, dict) and row.get("directory") == real]


def export(store: Store, session: str) -> dict:
    return _json(store, "export", session)


def first_prompt(exported: dict) -> str | None:
    for message in exported.get("messages", []):
        if message.get("info", {}).get("role") == "user":
            parts = message.get("parts", [])
            texts = (
                p.get("text", "")
                for p in parts
                if p.get("type") == "text" and not p.get("synthetic")
            )
            return "".join(texts)
    return None


def receipt(exported: dict) -> dict:
    """The fields that prove the session, never the conversation itself."""
    info = exported.get("info", {})
    replies = [
        m.get("info", {})
        for m in exported.get("messages", [])
        if m.get("info", {}).get("role") == "assistant"
    ]
    prompt = first_prompt(exported) or ""
    last = replies[-1] if replies else {}
    error = last.get("error") or {}
    return {
        "session": info.get("id"),
        "directory": info.get("directory"),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "models": sorted(
            {
                f"{r['providerID']}/{r['modelID']}"
                for r in replies
                if r.get("providerID") and r.get("modelID")
            }
        ),
        "finish": last.get("finish"),
        "error": error.get("name"),
    }


def find(store: Store, prompt: str, since_ms: int) -> tuple[dict, dict]:
    """The one session in this directory, created after the launch, whose first prompt is ours."""
    matches = []
    for row in sessions(store):
        if int(row.get("created", 0)) < since_ms:
            continue
        exported = export(store, row["id"])
        if first_prompt(exported) == prompt:
            matches.append(exported)
    if len(matches) != 1:
        raise Blocked(
            "no native evidence",
            f"{len(matches)} sessions in {store.directory} carry the exact prompt since the launch",
            "inspect with opencode session list in that directory, never relaunch over a worker",
        )
    return matches[0], receipt(matches[0])


def scrub(root: Path, values: list[str], subject: Path) -> None:
    """Remove exact provider values from run files, never from the subject under test."""
    secrets = [value.encode() for value in values if len(value) >= MIN_SECRET_LENGTH]
    if not secrets:
        return
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink() and not path.is_relative_to(subject):
            data = path.read_bytes()
            cleaned = data
            for secret in secrets:
                cleaned = cleaned.replace(secret, b"[REDACTED provider value]")
            if cleaned != data:
                path.write_bytes(cleaned)
