"""Confluence discovery and page-read dispatch."""

from urllib.parse import quote

from .confluence_common import SPACE, window
from .confluence_page import read_page
from .constants import SUCCESS
from .operations import ID
from .wire import literal, term


def _query(operation: dict) -> tuple[str, dict]:
    mode = operation["mode"]
    query = {"start": operation["start"], "limit": operation["limit"]}
    if mode == "spaces":
        return "rest/api/space", query
    if mode == "pages-in-space":
        return f"rest/api/space/{quote(operation['space'], safe='')}/content/page", query
    if mode == "children":
        return f"rest/api/content/{operation['id']}/child/page", query
    field = "title" if mode == "title" else "text"
    cql = f"type = page AND {field} ~ {term(operation['text'])}"
    if operation.get("space"):
        cql += " AND space = " + literal(operation["space"])
    query.update(cql=cql + " ORDER BY created ASC, title ASC", expand="space,version")
    return "rest/api/content/search", query


def _candidate(value: dict, operation: dict, client) -> dict:
    mode = operation["mode"]
    identity = value.get("key") if mode == "spaces" else value.get("id")
    pattern = SPACE if mode == "spaces" else ID
    if not isinstance(identity, str) or not pattern.fullmatch(identity):
        raise ValueError("RESPONSE_INVALID")
    if mode == "spaces":
        return {
            "key": identity,
            "name": value.get("name"),
            "type": value.get("type"),
            "homepage": (value.get("homepage") or {}).get("id"),
        }
    if (
        value.get("type") != "page"
        or value.get("status") != "current"
        or not isinstance(value.get("title"), str)
    ):
        raise ValueError("RESPONSE_INVALID")
    return {
        "id": identity,
        "title": value["title"],
        "url": client.url("pages/viewpage.action", {"pageId": identity}),
        "space": value.get("space"),
        "version": value.get("version"),
        "metadata_not_returned": [field for field in ("space", "version") if field not in value],
    }


def discover(client, expected: str, operation: dict) -> dict:
    path, query = _query(operation)
    response = client.get(path, query)
    pagination, seen, results = window(response, operation["start"], operation["limit"]), set(), []
    total = pagination["total"]
    end = operation["start"] + pagination["returned"]
    if total is not None and (
        not pagination["has_more"] and end != total or pagination["has_more"] and end >= total
    ):
        raise ValueError("RESPONSE_INVALID")
    for value in response["results"]:
        candidate = _candidate(value, operation, client)
        identity = candidate.get("key", candidate.get("id"))
        if identity in seen:
            raise ValueError("RESPONSE_INVALID")
        seen.add(identity)
        results.append(candidate)
    return {
        "result": SUCCESS["confluence-read"],
        "user": expected,
        "operation": operation["mode"],
        "results": results,
        "pagination": pagination,
        "coverage": {
            "bodies_retrieved": False,
            "collection": "window",
            "atomic_snapshot": False,
            "search": "indexed matching; absence is not proven",
        },
    }


def read(client, expected: str, operation: dict) -> dict:
    user = client.get("rest/api/user/current")
    if user.get("username") != expected or user.get("type") != "known":
        raise ValueError("IDENTITY_MISMATCH")
    if operation["mode"] not in ("page", "latest-edited"):
        return discover(client, expected, operation)
    return read_page(client, expected, operation)
