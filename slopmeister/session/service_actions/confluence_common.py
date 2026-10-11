"""Confluence operation and response validation shared by its readers."""

import re

from .operations import NUMERIC, TEXT, WINDOW, Form, Kind, Table, matching, windowed

SPACE = re.compile(r"~?[A-Za-z0-9][A-Za-z0-9_.@-]{0,253}")
SPACE_KIND = Kind(matching(SPACE), "a space key such as TEST or ~user")
PAGE = Kind(
    matching(r"[1-9][0-9]{0,19}|https://\S+"), "a numeric page id or a same-application page URL"
)
TABLE = Table(
    {
        "--page": Form("id", PAGE),
        "--latest-edited": Form(),
        "--search": windowed("text", TEXT, ("--space",)),
        "--title": windowed("text", TEXT, ("--space",)),
        "--spaces": windowed(),
        "--pages-in-space": windowed("space", SPACE_KIND),
        "--children": windowed("id", NUMERIC),
    },
    {"--space": SPACE_KIND, **WINDOW},
)


def window(response: dict, start: int, limit: int) -> dict:
    results = response.get("results")
    links = response.get("_links") or {}
    next_link = links.get("next")
    if (
        not isinstance(results, list)
        or response.get("start") != start
        or len(results) > limit
        or response.get("size") != len(results)
        or next_link
        and not results
        or next_link is not None
        and (not isinstance(next_link, str) or not next_link)
    ):
        raise ValueError("RESPONSE_INVALID")
    total = response.get("totalSize", response.get("totalCount"))
    if total is not None and (type(total) is not int or total < start + len(results)):
        raise ValueError("RESPONSE_INVALID")
    next_start = start + len(results) if next_link else None
    if next_start is not None and next_start > 2147483647:
        raise ValueError("SEARCH_LIMIT")
    return {
        "start": start,
        "limit": limit,
        "returned": len(results),
        "has_more": next_start is not None,
        "next_start": next_start,
        "total": total,
    }


def version(content: dict, identity: str, number: int | None = None) -> dict:
    value = content.get("version") if isinstance(content, dict) else None
    actual = value.get("number") if isinstance(value, dict) else None
    author = value.get("by", {}).get("username") if isinstance(value, dict) else None
    when = value.get("when") if isinstance(value, dict) else None
    if (
        content.get("id") != identity
        or content.get("type") != "page"
        or type(actual) is not int
        or actual < 1
        or number is not None
        and actual != number
        or not isinstance(author, str)
        or not author
        or not isinstance(when, str)
        or not when
    ):
        raise ValueError("RESPONSE_INVALID")
    return {"number": actual, "when": when, "author": author}
