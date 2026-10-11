"""Authorize one fixed provider read without exposing the service-account token."""

import base64
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time

from . import runtime
from .arguments import operation
from .constants import BASE_PATH, INCOMPLETE, OP, PYTHON, PYTHON_FLAGS, SUCCESS
from .operations import Rejected
from .process import Run, invoke
from .wire import encode

ROOT = Path(__file__).resolve().parents[1]


def service_token(value: str) -> str:
    path = Path(value)
    if not path.is_absolute() or any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("LOCAL_CREDENTIAL_FILE_UNSAFE")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            safe = stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            safe &= stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 16384
            if not safe:
                raise ValueError("LOCAL_CREDENTIAL_FILE_UNSAFE")
            match = re.fullmatch(
                r"OP_SERVICE_ACCOUNT_TOKEN=(ops_[A-Za-z0-9_-]+={0,2})\n", stream.read(16385)
            )
            if not match:
                raise ValueError("LOCAL_CREDENTIAL_NOT_PROVISIONED")
            return match[1]
    except OSError:
        raise ValueError("LOCAL_CREDENTIAL_NOT_PROVISIONED") from None


def server_ca(value: str) -> str:
    """A trust anchor another local user could replace would redirect the PAT."""
    path = Path(value)
    if not path.is_absolute() or any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("LOCAL_CREDENTIAL_FILE_UNSAFE")
    try:
        info = path.stat()
    except OSError:
        raise ValueError("LOCAL_CREDENTIAL_FILE_UNSAFE") from None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("LOCAL_CREDENTIAL_FILE_UNSAFE")
    return value


def _environment(data: dict) -> dict[str, str]:
    return {
        "PATH": BASE_PATH,
        # op checks the desktop app's settings under HOME/Library/Group Containers at every start,
        # which macOS guards with a per-process app-data prompt. An empty HOME skips that check.
        "HOME": "/var/empty" if sys.platform == "darwin" else str(Path.home()),
        "XDG_CONFIG_HOME": str(Path.home() / ".config"),
        "OP_BIOMETRIC_UNLOCK_ENABLED": "false",
        "OP_SERVICE_ACCOUNT_TOKEN": service_token(data["token_file"]),
    }


def _identity(data: dict, env: dict[str, str], deadline: float) -> None:
    output = invoke(
        Run(
            [str(OP), "user", "get", "--me", "--format", "json"],
            env,
            deadline=deadline,
            failure="SERVICE_ACCOUNT_ACCESS_FAILED",
        )
    )
    user = json.loads(output)
    if (
        user.get("id", "").upper() != data["account_id"].upper()
        or user.get("type") != "SERVICE_ACCOUNT"
        or user.get("state") != "ACTIVE"
    ):
        raise ValueError("SERVICE_ACCOUNT_IDENTITY_MISMATCH")


def _vault(data: dict, env: dict[str, str], deadline: float) -> None:
    output = invoke(
        Run(
            [str(OP), "vault", "list", "--format", "json"],
            env,
            deadline=deadline,
            failure="VAULT_ACCESS_FAILED",
        )
    )
    vaults = json.loads(output)
    valid = isinstance(vaults, list) and len(vaults) == 1
    valid &= valid and vaults[0].get("id", "").lower() == data["vault_id"].lower()
    valid &= valid and vaults[0].get("name") == data["vault_name"]
    if not valid:
        raise ValueError("VAULT_SCOPE_MISMATCH")


def _certificate(data: dict, env: dict[str, str], deadline: float) -> str:
    output = invoke(
        Run(
            [str(OP), "document", "get", data["certificate_document"], "--vault", data["vault_id"]],
            env,
            deadline=deadline,
            failure="CERTIFICATE_ACCESS_FAILED",
        )
    )
    if not output or len(output) > 1024 * 1024:
        raise ValueError("CERTIFICATE_SIZE_INVALID")
    return base64.b64encode(output).decode()


def _provider_payload(data: dict, selected, execution: tuple[dict, float]) -> dict:
    env, deadline = execution
    payload = {
        "origin": data["origin"],
        "expected_user": data["expected_user"],
        "action": data["action"],
        "operation": selected,
    }
    if selected["mode"] == "backlog":
        payload["backlog_jql"] = data["backlog_jql"]
    env["JIRA_PAT"] = data["pat_ref"]
    if "server_ca" in data:
        payload["server_ca"] = server_ca(data["server_ca"])
    if "certificate_document" in data:
        payload["pfx"] = _certificate(data, env, deadline)
        env["JIRA_CERT_PASSWORD"] = data["password_ref"]
    payload["remaining_ms"] = max(0, int((deadline - time.monotonic() - 1) * 1000))
    return payload


def _provider(data: dict, selected, execution: tuple[dict, float]) -> bytes:
    env, deadline = execution
    payload = _provider_payload(data, selected, execution)
    command = [
        str(OP),
        "run",
        "--",
        "/usr/bin/env",
        "-u",
        "OP_SERVICE_ACCOUNT_TOKEN",
        str(PYTHON),
        *PYTHON_FLAGS,
        "-m",
        "service_actions.provider",
    ]
    return invoke(
        Run(
            command,
            env,
            json.dumps(payload).encode(),
            300,
            "FIELD_OR_PROVIDER_ACCESS_FAILED",
            deadline=deadline,
            # With -m, Python resolves the provider package from the working directory.
            cwd=ROOT,
        )
    )


def fetch(direct_args: list[str] | None = None) -> bytes:
    data = json.loads((ROOT / "config.json").read_bytes())
    runtime.require(check_current=True, module_root=ROOT, cert="certificate_document" in data)
    deadline = time.monotonic() + 300
    native = data.pop("native", None)
    if data.get("action") not in SUCCESS:
        raise ValueError("CONFIG_INVALID")
    if sys.platform == "darwin" and {"server_ca", "certificate_document"} <= data.keys():
        raise ValueError("CONFIG_INVALID")
    if data["action"].endswith("-write"):
        from .native_gate import require_consumer

        require_consumer(ROOT, native)
        # Effective flags alone would admit spellings that miss the native command rule.
        entry = (
            [str(ROOT / "entry.py")]
            if direct_args is not None
            else ["-m", "service_actions.supervisor"]
        )
        prefix = [*PYTHON_FLAGS, *entry]
        if sys.executable != str(PYTHON) or sys.orig_argv[1 : len(prefix) + 1] != prefix:
            raise ValueError("ARGUMENTS_NOT_SUPPORTED")
    selected = operation(data, direct_args)
    env = _environment(data)
    _identity(data, env, deadline)
    _vault(data, env, deadline)
    result = _provider(data, selected, (env, deadline))
    if json.loads(result).get("result") not in (SUCCESS[data["action"]], INCOMPLETE):
        raise ValueError("ACTION_FAILED")
    return result


def _terminate(signum, _frame) -> None:
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None, *, direct: bool = False) -> int:
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _terminate)
    try:
        if argv and not direct:
            raise ValueError("ARGUMENTS_NOT_SUPPORTED")
        result = json.loads(fetch(argv) if direct else fetch())
        sys.stdout.buffer.write(encode(result))
        return 1 if result.get("result") == INCOMPLETE else 0
    except Exception as error:
        raw = str(error) if isinstance(error, ValueError) else "ACTION_FAILED"
        code, _, component = raw.partition(":")
        if not re.fullmatch(r"[A-Z_]{3,64}|HTTP_[0-9]{3}", code):
            code, component = "ACTION_FAILED", ""
        result = {"result": code}
        if code == "LOCAL_PREREQUISITE_MISSING" and component:
            result.update(component=component, provider_contacted=False)
        if isinstance(error, Rejected):
            result["detail"] = error.detail
        print(json.dumps(result))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
