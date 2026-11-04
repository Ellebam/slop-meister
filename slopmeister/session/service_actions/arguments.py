"""Parse only the declared Jira and Confluence operations."""

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
READ_ARG_LIMIT = 4096
ARG_COUNT = 64


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


def _arguments(action: str, args: list[str]) -> list[str]:
    if action not in TABLES or len(args) > ARG_COUNT:
        raise ValueError("ARGUMENTS_NOT_SUPPORTED")
    read = action in READ_ACTIONS
    limit = READ_ARG_LIMIT if read else BODY_LIMIT
    for arg in args:
        controls = (ord(c) < 32 and (read or c not in "\n\t") or 127 <= ord(c) <= 159 for c in arg)
        if len(arg) > limit or any(controls):
            raise ValueError("ARGUMENTS_NOT_SUPPORTED")
    return args


def operation(data: dict, args: list[str]) -> dict:
    selected = parse(data["action"], _arguments(data["action"], args))
    if selected["mode"] == "backlog":
        backlog_query(data.get("backlog_jql"))
    if selected["mode"] == "page":
        selected["id"] = _page(selected["id"], data["origin"])
    return selected
