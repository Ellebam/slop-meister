"""Validate and bound values crossing the provider process boundary."""

import json
import re

from .constants import ISSUE_KEY, LIMIT


def label(value) -> str:
    if not isinstance(value, str) or len(value) > 10000:
        raise ValueError("RESPONSE_INVALID")
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", value)


def issue_key(value) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(ISSUE_KEY, value))


def encode(value) -> bytes:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = re.sub(r"[\x7f-\x9f]", lambda match: f"\\u{ord(match[0]):04x}", text)
    raw = (text + "\n").encode()
    if len(raw) > LIMIT:
        raise ValueError("ACTION_OUTPUT_LIMIT")
    return raw


def bounded(value):
    encode(value)
    return value


def literal(text: str) -> str:
    """A double-quoted JQL or CQL string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def term(text: str) -> str:
    """A text-search literal whose search syntax characters match as plain text."""
    return literal(re.sub(r'([+\-!(){}\[\]^"~*?:\\/&|])', r"\\\1", text))
