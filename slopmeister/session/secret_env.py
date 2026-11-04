"""Read `op run` env files the way the real command does, dotenv style, with expansion."""

import os
from pathlib import Path
import re
import stat
import sys

# Refuse known env-file controls of executable lookup, startup code, transport and trust roots.
EXECUTION_NAMES = frozenset(
    [
        "PATH",
        "BASH_ENV",
        "ENV",
        "SHELLOPTS",
        "BASHOPTS",
        "IFS",
        "CDPATH",
        "GLOBIGNORE",
        "ZDOTDIR",
        "FPATH",
        "NODE_OPTIONS",
        "NODE_PATH",
        "PERL5OPT",
        "PERL5LIB",
        "PERLLIB",
        "NODE_EXTRA_CA_CERTS",
        "NODE_TLS_REJECT_UNAUTHORIZED",
        "GIT_SSL_NO_VERIFY",
        "GIT_SSL_CAINFO",
        "GIT_SSH_COMMAND",
        "GIT_EXEC_PATH",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
        "GIT_PROXY_COMMAND",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "GCONV_PATH",
        "LUA_INIT",
        "FTP_PROXY",
        "RUBYOPT",
        "RUBYLIB",
        "JAVA_TOOL_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "_JAVA_OPTIONS",
        "CLASSPATH",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "OPENSSL_CONF",
        "OPENSSL_MODULES",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    ]
)
EXECUTION_PREFIXES = ("LD_", "DYLD_", "PYTHON")


def validate_names(names: tuple[str, ...], reserved: tuple[str, ...]) -> None:
    owned = next((name for name in names if name in reserved), None)
    if owned:
        raise ValueError(f"{owned} is set by the session's op and cannot come from an env file")
    for name in names:
        if name.upper() in EXECUTION_NAMES or name.startswith(EXECUTION_PREFIXES):
            raise ValueError(f"{name} can alter execution and cannot come from an env file")


# Apple's _CS_DARWIN_USER_TEMP_DIR key is not named in Python's confstr table.
DARWIN_USER_TEMP_DIR = 65537


def cli_environment(env: dict[str, str]) -> dict[str, str]:
    """Use the private OS root, independent of the session's workspace TMPDIR."""
    try:
        root = (
            os.confstr(DARWIN_USER_TEMP_DIR)
            if sys.platform == "darwin"
            else env.get("XDG_RUNTIME_DIR")
        )
        if not root:
            raise ValueError("private temporary root is unavailable; Linux needs XDG_RUNTIME_DIR")
        path = Path(root)
        info = path.lstat()
    except OSError:
        raise ValueError("private temporary root is unavailable") from None
    workspace = env.get("SLOPMEISTER_SESSION_WORKSPACE")
    safe = path.is_absolute() and stat.S_ISDIR(info.st_mode)
    safe &= info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700
    if not safe or workspace and path.resolve().is_relative_to(Path(workspace).resolve()):
        raise ValueError("private temporary root must be outside the workspace, owned, mode 700")
    return env | {"TMPDIR": str(path), "XDG_RUNTIME_DIR": str(path)}


def command_environment(argv: list[str], env: dict[str, str], token: str) -> list[str]:
    """Restore the command's original roots after op resolves and masks its environment."""
    if argv[:1] != ["run"] or "--" not in argv:
        return argv
    split = argv.index("--") + 1
    if split == len(argv):
        return argv
    names = ("TMPDIR", "XDG_RUNTIME_DIR")
    unset = [arg for name in names for arg in ("-u", name)]
    values = [f"{name}={env[name]}" for name in names if name in env]
    return [*argv[:split], "/usr/bin/env", "-u", token, *unset, *values, *argv[split:]]


NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
# Vault, item, section and field names may hold spaces, never separators or control characters.
SEGMENT = r"[^/?\x00-\x1f]+"
REFERENCE = re.compile(rf"op://{SEGMENT}/{SEGMENT}(?:/{SEGMENT}){{1,2}}(?:\?[\w=.,-]+)?\Z")
EXPANSION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
# A placeholder for an escaped dollar sign while the other dollars expand.
ESCAPED_DOLLAR = "\x00dollar\x00"
# One pass over the escapes a double-quoted value may carry, as the real op reads them.
ESCAPE = re.compile(r"\\([\\\"n$])")
UNESCAPED = {"\\": "\\", '"': '"', "n": "\n", "$": ESCAPED_DOLLAR}


def _closing(raw: str, quote: str) -> int:
    """The index of the closing quote, skipping backslash-escaped ones, or -1."""
    index = 1
    while index < len(raw):
        if raw[index] == "\\":
            index += 2
            continue
        if raw[index] == quote:
            return index
        index += 1
    return -1


def _value(raw: str, known: dict[str, str], where: str) -> str:
    """One dotenv value: quoted on one line, or unquoted up to an inline comment, then expanded."""
    if raw and raw[0] in "'\"":
        quote = raw[0]
        end = _closing(raw, quote)
        if end < 0:
            raise ValueError(f"{where}: multi-line quoted values are not supported")
        if raw[end + 1 :].split(" #", 1)[0].strip():
            raise ValueError(f"{where}: text after the closing quote")
        value = raw[1:end]
        if quote == "'":
            return value
        value = ESCAPE.sub(lambda m: UNESCAPED[m.group(1)], value)
    else:
        value = raw.split(" #", 1)[0].rstrip()
    expanded = EXPANSION.sub(lambda m: known.get(m.group(1) or m.group(2), ""), value)
    return expanded.replace(ESCAPED_DOLLAR, "$")


def read_env_file(path: str, known: dict[str, str]) -> dict[str, str]:
    """The file's variables, dotenv style, with ${NAME} expanded from earlier values."""
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text().splitlines()
    except OSError as error:
        raise ValueError(f"env file {path}: {error.strerror}") from None
    for number, line in enumerate(lines, 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        name, equals, raw = text.removeprefix("export ").partition("=")
        name = name.strip()
        if not equals:
            raise ValueError(f"env file {path}:{number}: missing '='")
        if not NAME.fullmatch(name):
            raise ValueError(f"env file {path}:{number}: {name!r} is not a variable name")
        values[name] = _value(raw.strip(), {**known, **values}, f"env file {path}:{number}")
    return values


def environment(files: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Literal variables to set and references to resolve, env files over the shell environment."""
    merged = {name: value for name, value in os.environ.items() if value.startswith("op://")}
    for path in files:
        merged.update(read_env_file(path, {**os.environ, **merged}))
    literals = {name: value for name, value in merged.items() if not value.startswith("op://")}
    references = {name: value for name, value in merged.items() if value.startswith("op://")}
    # The real op trims a value before it looks for a reference, so a padded one is one too.
    for name, value in {**os.environ, **merged}.items():
        if value.strip().startswith("op://") and not REFERENCE.fullmatch(value):
            raise ValueError(f"{name} is not a secret reference: {value.strip()}")
    return literals, references


ENV_FILE, NO_MASKING = "--env-file", "--no-masking"


def _flag(args: list[str], index: int, files: list[str]) -> int:
    """Consume one `op run` flag at index into files, returning the next index."""
    arg = args[index]
    if arg == ENV_FILE and index + 1 < len(args):
        files.append(args[index + 1])
        return index + 2
    if arg.startswith(ENV_FILE + "="):
        files.append(arg.partition("=")[2])
        return index + 1
    if arg == NO_MASKING:
        raise ValueError(f"{NO_MASKING} is refused, values stay masked")
    raise ValueError(f"{arg} is not supported by the session's op")


def parse(args: list[str]) -> tuple[list[str], list[str]]:
    """The env files and the command of an `op run` line."""
    files: list[str] = []
    index = 0
    while index < len(args) and args[index] != "--":
        index = _flag(args, index, files)
    command = args[index + 1 :]
    if not command:
        raise ValueError("op run needs -- followed by the command")
    return files, command
