"""Final review-result storage."""

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from slopmeister.review.schema import CrossToolReviewError
from slopmeister.session.launch_identity import private_json, state_home

RESULT_KEYS = {"gate", "exit_code"}


def _git_common(cwd: str) -> Path:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise CrossToolReviewError(
            "cannot establish repository review identity", category="START_PRECONDITION"
        ) from error
    if result.returncode:
        raise CrossToolReviewError(
            "cannot establish repository review identity", category="START_PRECONDITION"
        )
    return Path(result.stdout.strip()).resolve()


def result_path(args: argparse.Namespace, task: str) -> Path:
    name = f"{task}-{args.mode}.json"
    if getattr(args, "subject_manifest", None):
        git = Path.cwd() / ".git"
        if git.exists() or git.is_symlink():
            raise CrossToolReviewError(
                "directory subject requires a directory launcher workspace",
                category="START_PRECONDITION",
            )
        return state_home() / "cross-tool-review/results/directory" / name
    target = Path(args.cwd).resolve(strict=True)
    if target != Path.cwd().resolve():
        raise CrossToolReviewError(
            "repository review target must be the launcher workspace",
            category="START_PRECONDITION",
        )
    return _git_common(str(target)) / "slopmeister-config/reviews" / name


def _prepare_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if path.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("review result directory must be owned and private")


def save_result(path: Path, gate: str, outcome: tuple[int, str | None]) -> None:
    code, candidate = outcome
    _prepare_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".part")
    part = Path(temporary)
    try:
        os.chmod(part, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            value = {"gate": gate, "exit_code": code}
            if candidate is not None:
                value["candidate"] = candidate
            json.dump(value, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def read_result(path: Path) -> tuple[str, int, str | None]:
    value = private_json(path, "review result file")
    gate, code = value.get("gate"), value.get("exit_code")
    if (
        set(value) not in (RESULT_KEYS, RESULT_KEYS | {"candidate"})
        or not isinstance(gate, str)
        or not gate
    ):
        raise ValueError("invalid review result")
    if type(code) is not int or code not in (0, 1):
        raise ValueError("invalid review result exit code")
    candidate = value.get("candidate")
    if candidate is not None and not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise ValueError("invalid review result candidate")
    return gate, code, candidate
