"""Declared operations, parsed from agent arguments and revalidated at the provider."""

from collections.abc import Callable
import dataclasses
from dataclasses import dataclass
import json
import re

from .constants import ISSUE_KEY

KEY = re.compile(ISSUE_KEY)
ID = re.compile(r"[1-9][0-9]{0,19}")
MAX_KEYS = 50
MAX_TARGETS = 3
BODY_LIMIT = 32768
# A tuple, not `except A, B:`, so the supervisor's import chain still parses before its floor check.
MALFORMED = (ValueError, TypeError, KeyError, AttributeError)


class Rejected(ValueError):
    """Fixed text naming a refused option and what it expects, never the supplied value."""

    def __init__(self, detail: str):
        super().__init__("ARGUMENTS_NOT_SUPPORTED: " + detail)
        self.detail = detail


@dataclass(frozen=True)
class Kind:
    parse: Callable[[str], object]
    expects: str
    default: object = None


@dataclass(frozen=True)
class Form:
    field: str | None = None
    kind: Kind | None = None
    options: tuple[str, ...] = ()
    defaults: dict = dataclasses.field(default_factory=dict)
    check: Callable[[dict], None] | None = None


@dataclass(frozen=True)
class Table:
    forms: dict[str, Form]
    options: dict[str, Kind]


def matching(pattern: re.Pattern | str) -> Callable[[str], str]:
    def parse(value: str) -> str:
        if not re.fullmatch(pattern, value):
            raise ValueError
        return value

    return parse


def _text(limit: int) -> Callable[[str], str]:
    def parse(value: str) -> str:
        if not value.strip() or len(value) > limit or value.startswith("--"):
            raise ValueError
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
            raise ValueError
        return value

    return parse


def _number(maximum: int, minimum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        if not re.fullmatch(r"0|[1-9][0-9]{0,9}", value) or not minimum <= int(value) <= maximum:
            raise ValueError
        return int(value)

    return parse


def _body(value: str) -> str:
    if not value.strip() or len(value) > BODY_LIMIT or value.startswith("--"):
        raise ValueError
    if any(ord(char) < 32 and char not in "\n\t" or 127 <= ord(char) <= 159 for char in value):
        raise ValueError
    return value


def _json(value: str) -> str:
    """One JSON object or 1 to 3 of them, kept as text so revalidation compares like for like."""
    parsed = json.loads(_body(value))
    items = parsed if isinstance(parsed, list) else [parsed]
    if not 1 <= len(items) <= MAX_TARGETS or not all(isinstance(item, dict) for item in items):
        raise ValueError
    return value


def targets(pattern: re.Pattern | str, expects: str) -> Kind:
    """1 to 3 unique comma-separated targets of one write."""

    def parse(value: str) -> list[str]:
        items = value.split(",")
        if len(items) > MAX_TARGETS or len(set(items)) != len(items):
            raise ValueError
        if not all(re.fullmatch(pattern, item) for item in items):
            raise ValueError
        return items

    return Kind(parse, f"1 to {MAX_TARGETS} unique comma-separated {expects}")


def guards(pattern: re.Pattern | str, expects: str) -> Kind:
    """The values each target must still have, in target order."""

    def parse(value: str) -> list[str]:
        items = value.split(",")
        if len(items) > MAX_TARGETS + 1 or not all(re.fullmatch(pattern, item) for item in items):
            raise ValueError
        return items

    return Kind(parse, f"comma-separated {expects}, one per target")


def _keys(value: str) -> list[str]:
    keys = value.split(",")
    if len(keys) > MAX_KEYS or len(set(keys)) != len(keys) or not all(map(KEY.fullmatch, keys)):
        raise ValueError
    return keys


def choice(*values: str, default: object = None) -> Kind:
    def parse(value: str) -> str:
        if value not in values:
            raise ValueError
        return value

    return Kind(parse, " or ".join(values), default)


def subset(*values: str) -> Kind:
    def parse(value: str) -> list[str]:
        items = value.split(",")
        if len(set(items)) != len(items) or not set(items) <= set(values):
            raise ValueError
        return items

    return Kind(parse, "a comma list of " + ", ".join(values), list(values))


ISSUE = Kind(matching(KEY), "an issue key such as PROJ-7")
ISSUES = Kind(_keys, f"1 to {MAX_KEYS} unique comma-separated issue keys")
NUMERIC = Kind(matching(ID), "a positive numeric id")
TEXT = Kind(_text(1024), "1 to 1024 characters without control characters")
NAME = Kind(_text(255), "1 to 255 characters without control characters")
BODY = Kind(_body, f"1 to {BODY_LIMIT} characters, newline and tab allowed, not starting with --")
JSON = Kind(_json, "one JSON object, or a JSON array of 1 to 3 objects")
WINDOW = {
    "--start": Kind(_number(2147483647, 0), "a number from 0"),
    "--limit": Kind(_number(100, 1), "a number from 1 to 100"),
}


def windowed(field: str | None = None, kind: Kind | None = None, options=(), **defaults) -> Form:
    """A listing form taking --start and --limit, defaulting to the first 25 results."""
    return Form(field, kind, (*options, *WINDOW), {"start": 0, "limit": 25, **defaults})


def _convert(name: str, kind: Kind, value: str) -> object:
    try:
        return kind.parse(value)
    except ValueError:
        raise Rejected(f"{name} expects {kind.expects}") from None


def _option(name: str, kind: Kind, rest: list[str]) -> tuple[object, list[str]]:
    if rest and not rest[0].startswith("--"):
        return _convert(name, kind, rest[0]), rest[1:]
    if kind.default is None:
        raise Rejected(f"{name} expects {kind.expects}")
    return kind.default, rest


def parse(table: Table, args: list[str]) -> dict:
    if not args or args[0] not in table.forms:
        raise Rejected("expected one of " + ", ".join(table.forms))
    flag, form, rest = args[0], table.forms[args[0]], args[1:]
    operation = {"mode": flag[2:]}
    if form.kind:
        operation[form.field], rest = _option(flag, form.kind, rest)
    given = {}
    while rest:
        name = rest[0]
        if name not in form.options:
            accepted = ", ".join(form.options) or "no options"
            raise Rejected(f"{flag} accepts {accepted}")
        if name[2:] in given:
            raise Rejected(f"{name} may appear once")
        given[name[2:]], rest = _option(name, table.options[name], rest[1:])
    result = {**operation, **form.defaults, **given}
    if form.check:
        form.check(result)
    return result


def _text_of(value: object) -> str:
    if isinstance(value, list):
        return ",".join(value)
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        return value
    raise TypeError


def valid(table: Table, operation: object) -> bool:
    """The provider-side check, rebuilding the arguments so both sides share one definition."""
    try:
        flag = "--" + operation["mode"]
        form = table.forms[flag]
        args = [flag] + ([_text_of(operation[form.field])] if form.kind else [])
        for name, value in operation.items():
            if name not in ("mode", form.field):
                args += ["--" + name, _text_of(value)]
        return parse(table, args) == operation
    except MALFORMED:
        return False
