"""Shared scalar and table checks for plot declarations."""

from pathlib import Path
from typing import Any


def safe(text: object) -> str:
    """Make diagnostics one printable line."""
    return str(text).encode("unicode_escape").decode("ascii")


def fail(path: Path, key: str, reason: str) -> None:
    raise ValueError(f"{safe(path)}: {safe(key)}: {safe(reason)}")


def table(value: Any, keys: set[str] | None, context: tuple[Path, str]) -> dict:
    path, key = context
    if not isinstance(value, dict):
        fail(path, key, "expected a table")
    unknown = set(value) - keys if keys is not None else set()
    if unknown:
        field = sorted(unknown)[0]
        fail(path, f"{key}.{field}" if key != "<document>" else field, "unknown key")
    return value


def enum(value: Any, values: tuple[str, ...], context: tuple[Path, str]) -> None:
    if not isinstance(value, str) or value not in values:
        fail(*context, "required string, expected " + ", ".join(values))


def integer(value: Any, bounds: tuple[int, int], context: tuple[Path, str]) -> None:
    low, high = bounds
    if type(value) is not int or not low <= value <= high:
        fail(*context, f"expected an integer in {low} to {high}")
