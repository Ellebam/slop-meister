"""Resolve approved references as the service account. Values live in memory only."""

from pathlib import Path
import subprocess

READ_TIMEOUT = 60


def resolve(references: dict[str, str], credentials: tuple[Path, str, Path]) -> tuple[dict, str]:
    """The values by name and an empty string, or no values and the first name that failed."""
    op, token, state = credentials
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/var/empty",
        "XDG_CONFIG_HOME": str(state),
        "OP_BIOMETRIC_UNLOCK_ENABLED": "false",
        "OP_SERVICE_ACCOUNT_TOKEN": token,
    }
    values: dict[str, str] = {}
    for name, reference in references.items():
        try:
            done = subprocess.run(
                [str(op), "read", "--no-newline", reference],
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=READ_TIMEOUT,
            )
        except OSError, subprocess.TimeoutExpired:
            return {}, name
        if done.returncode:
            return {}, name
        values[name] = done.stdout.decode(errors="replace")
    return values, ""
