"""Parse only the declared Jira and Confluence operations."""

import json
import os
import re
from urllib.parse import parse_qs, urlsplit

from . import confluence_common, confluence_write, jira, jira_write
from .jira_find import backlog_query
from .operations import BODY_LIMIT, Rejected
from .operations import parse as parse_table

TABLES = {
    "jira-read": jira.TABLE,
    "confluence-read": confluence_common.TABLE,
    "jira-write": jira_write.TABLE,
    "confluence-write": confluence_write.TABLE,
}
READ_ACTIONS = ("jira-read", "confluence-read")
DIRECT_ARG_LIMIT = 4096
DIRECT_ARG_COUNT = 64


def _page(value: str, origin: str) -> str:
    if re.fullmatch(r"[1-9][0-9]{0,19}", value):
        return value
    url, base = urlsplit(value), urlsplit(origin)
    if url.scheme != "https" or url.netloc != base.netloc or url.username or url.password:
        raise Rejected("--page expects a page URL on the configured application")
    prefix = base.path.rstrip("/")
    if not url.path.startswith(prefix + "/"):
        raise Rejected("--page expects a page URL on the configured application")
    page_path = url.path[len(prefix) :]
    match = re.fullmatch(r"/spaces/[^/]+/pages/([1-9][0-9]{0,19})(?:/[^/]*)?", page_path)
    ids = parse_qs(url.query).get("pageId", []) if page_path == "/pages/viewpage.action" else []
    result = match[1] if match else ids[0] if len(ids) == 1 else ""
    if not re.fullmatch(r"[1-9][0-9]{0,19}", result):
        raise Rejected("--page expects a page URL on the configured application")
    return result


def parse(action: str, args: list[str]) -> dict:
    """The operation `args` select, revalidated by the provider."""
    if action not in TABLES:
        raise Rejected("action expects " + " or ".join(TABLES))
    return parse_table(TABLES[action], args)


def _arguments(action: str, direct_args: list[str] | None = None) -> list[str]:
    structured = os.environ.get("SLOPMEISTER_SERVICE_ACTION_INPUT")
    direct = direct_args is not None
    read_direct = direct and action in READ_ACTIONS
    if direct:
        if structured is not None or action not in TABLES:
            raise ValueError("ARGUMENTS_NOT_SUPPORTED")
        args = direct_args
    else:
        try:
            args = json.loads(structured or "[]")
        except ValueError:
            raise ValueError("ARGUMENTS_NOT_SUPPORTED") from None
    limit = DIRECT_ARG_LIMIT if read_direct else BODY_LIMIT
    if (
        not isinstance(args, list)
        or any(
            not isinstance(arg, str)
            or len(arg) > limit
            or any(
                ord(char) < 32 and (read_direct or char not in "\n\t") or 127 <= ord(char) <= 159
                for char in arg
            )
            for arg in args
        )
        or (direct and len(args) > DIRECT_ARG_COUNT)
    ):
        raise ValueError("ARGUMENTS_NOT_SUPPORTED")
    return args


def operation(data: dict, direct_args: list[str] | None = None) -> dict:
    selected = parse(data["action"], _arguments(data["action"], direct_args))
    if selected["mode"] == "backlog":
        backlog_query(data.get("backlog_jql"))
    if selected["mode"] == "page":
        selected["id"] = _page(selected["id"], data["origin"])
    return selected
