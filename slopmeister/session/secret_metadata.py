"""List a fixed item metadata projection through the session's vault approval route."""

import json
from pathlib import Path
import subprocess
import sys

TIMEOUT = 60
OUTPUT_LIMIT = 8 * 1024 * 1024
TEXT_LIMIT = 256
USAGE = "use op metadata --vault NAME [--search TEXT]"


def parse(args: list[str]) -> tuple[str, str]:
    valid = len(args) in (2, 4) and args[0] == "--vault"
    if not valid or len(args) == 4 and args[2] != "--search":
        raise ValueError(USAGE)
    vault, search = args[1], args[3] if len(args) == 4 else ""
    if (
        not vault
        or vault != vault.strip()
        or vault.startswith("-")
        or any(char in vault for char in "/?#")
        or any(
            not value.isprintable() or len(value) > TEXT_LIMIT for value in (vault, search) if value
        )
    ):
        raise ValueError("invalid metadata vault or search text")
    return vault, search


def projected(item: object, vault: str) -> tuple[dict, list[str]]:
    """Check scope even for incomplete rows; diagnostics use only fixed field names."""
    item = item if isinstance(item, dict) else {}
    identity = item.get("vault")
    identity = identity if isinstance(identity, dict) else {}
    fields = {key: item.get(key) for key in ("id", "title", "category")}
    scope = {key: identity.get(key) for key in ("id", "name")}
    names = {value.casefold() for value in scope.values() if isinstance(value, str) and value}
    if names and vault.casefold() not in names:
        raise ValueError("1Password returned metadata outside the requested vault")
    missing = [
        key
        for key, value in (fields | {f"vault.{key}": value for key, value in scope.items()}).items()
        if not isinstance(value, str) or not value
    ]
    return {**fields, "vault": scope}, missing


def listing(binary: Path, vault: str, env: dict[str, str]) -> list[dict]:
    """The upstream receives no arbitrary flags and cannot print its own diagnostics."""
    done = subprocess.run(
        [str(binary), "item", "list", f"--vault={vault}", "--format=json"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        timeout=TIMEOUT,
    )
    if done.returncode or len(done.stdout) > OUTPUT_LIMIT:
        raise ValueError("1Password metadata listing failed or exceeded its response limit")
    try:
        data = json.loads(done.stdout)
    except ValueError, UnicodeError:
        raise ValueError("1Password returned invalid metadata JSON") from None
    if not isinstance(data, list):
        raise ValueError("1Password returned invalid item metadata")
    items, missing, skipped = [], set(), 0
    for item in data:
        row, absent = projected(item, vault)
        if absent:
            skipped += 1
            missing.update(absent)
        else:
            items.append(row)
    if skipped:
        warning = f"skipped {skipped} item(s); missing fields: {', '.join(sorted(missing))}"
        print(f"op metadata: {warning}", file=sys.stderr)
    return items


def output(scope: tuple[str, str], binary: Path, env: dict[str, str]) -> None:
    vault, search = scope
    try:
        items = listing(binary, vault, env)
    except OSError, subprocess.SubprocessError:
        raise ValueError("metadata command failed") from None
    result = [item for item in items if search.casefold() in item["title"].casefold()]
    print(json.dumps(result, ensure_ascii=True))
