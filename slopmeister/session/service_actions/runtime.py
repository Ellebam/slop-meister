"""Validate the fixed local executables before credentials or provider access."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

from .constants import (
    CURL,
    KNOWN_FAILURES,
    OP,
    OPENSSL,
    OPENSSL_CONFIG,
    PYTHON,
    PYTHON_FLAGS,
    SUCCESS,
)
from .process import Run, invoke

PROBE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C"}
# The TLS library the transport's client-certificate and pinning flow is proven with.
TLS_LIBRARY = {"darwin": "SecureTransport", "linux": "OpenSSL"}
NO_ANSWER = "PROVIDER_NO_ANSWER"


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _probe(argv, *, text=False, check=False):
    return subprocess.run(
        argv, capture_output=True, text=text, timeout=5, check=check, env=PROBE_ENV
    )


def _curl_capabilities() -> bool:
    try:
        version = _probe([CURL, "--version"], text=True, check=True).stdout
        help_text = _probe([CURL, "--help", "all"], text=True, check=True).stdout
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return False
    backend = re.search(r"\blibcurl/\S+\s+(\S+)", version)
    library = backend[1].split("/", 1)[0] if backend else ""
    protocols = next(
        (
            line.partition(":")[2].split()
            for line in version.splitlines()
            if line.startswith("Protocols:")
        ),
        [],
    )
    return (
        sys.platform in TLS_LIBRARY
        and TLS_LIBRARY[sys.platform] == library.strip("()")
        and (sys.platform == "darwin" or "(" not in library)
        and "https" in protocols
        and "--cert-type" in help_text
        and "P12" in help_text
        and "--config" in help_text
    )


def _python_capabilities() -> bool:
    try:
        result = _probe(
            [
                PYTHON,
                *PYTHON_FLAGS,
                "-c",
                "import sys; raise SystemExit(sys.version_info < (3,14))",
            ]
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return False
    return result.returncode == 0


def _provider_starts(root: Path) -> bool:
    """A started provider answers empty input with a code, so silence is a local launch defect."""
    argv = [str(PYTHON), *PYTHON_FLAGS, "-m", "service_actions.provider"]
    try:
        output = invoke(Run(argv, PROBE_ENV, timeout=5, failure=NO_ANSWER, cwd=root))
    except OSError:
        return False
    except ValueError as error:
        return str(error) not in (NO_ANSWER, "ACTION_TIMEOUT", "ACTION_OUTPUT_LIMIT")
    try:
        parsed = json.loads(output)
    except ValueError:
        return False
    code = parsed.get("result") if isinstance(parsed, dict) else None
    return isinstance(code, str) and (code in KNOWN_FAILURES or code in SUCCESS.values())


def _foreign_interpreter() -> bool:
    return Path(sys.executable).resolve() != PYTHON.resolve()


def _openssl_capabilities() -> bool:
    try:
        result = subprocess.run(
            [OPENSSL, "list", "-providers"],
            env=PROBE_ENV | {"OPENSSL_CONF": str(OPENSSL_CONFIG)},
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return False
    active = re.findall(
        r"^  (default|legacy)\n(?:    [^\n]*\n)*?    status: active(?:\n|$)",
        result.stdout,
        re.MULTILINE,
    )
    return result.returncode == 0 and set(active) == {"default", "legacy"}


def missing(
    check_current: bool = False, module_root: Path | None = None, cert: bool = False
) -> list[str]:
    found = []
    if not _executable(PYTHON) or not _python_capabilities():
        found.append(str(PYTHON) + " at Python 3.14 or newer")
    elif module_root and not _provider_starts(module_root):
        found.append("provider module")
    if not _executable(OP):
        found.append(str(OP))
    if not _executable(CURL) or not _curl_capabilities():
        library = TLS_LIBRARY.get(sys.platform, "a supported TLS library")
        found.append(str(CURL) + f" with {library}, HTTPS and PKCS#12")
    if cert and sys.platform == "linux":
        if not _executable(OPENSSL) or not _openssl_capabilities():
            found.append(str(OPENSSL) + " with default and legacy providers")
    if check_current and _foreign_interpreter():
        found.append(str(PYTHON) + " selected by the fixed consumer")
    return found


def require(
    check_current: bool = False, module_root: Path | None = None, cert: bool = False
) -> None:
    if absent := missing(check_current, module_root, cert):
        raise ValueError("LOCAL_PREREQUISITE_MISSING:" + ",".join(absent))


def require_interpreter() -> None:
    """The supervisor has probed the tools, so its provider proves only its own interpreter."""
    if _foreign_interpreter():
        raise ValueError("LOCAL_PREREQUISITE_MISSING:" + str(PYTHON))
