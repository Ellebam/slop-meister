"""Collect and validate Confluence comments and attachments."""

from .confluence_common import window
from .operations import ID
from .wire import bounded


def _child(value, kind: str, seen: set[str]) -> dict:
    identity = value.get("id") if isinstance(value, dict) else None
    invalid = (
        not isinstance(identity, str)
        or not ID.fullmatch(identity)
        or value.get("type") != kind
        or identity in seen
    )
    if kind == "comment":
        storage = value.get("body", {}).get("storage", {})
        invalid |= not isinstance(storage.get("value"), str)
        invalid |= storage.get("representation") != "storage"
    if invalid:
        raise ValueError("RESPONSE_INVALID")
    seen.add(identity)
    return value


def _query(kind: str, start: int) -> dict:
    query = {"start": start, "limit": 100, "expand": "body.storage,version,container,extensions"}
    if kind == "comment":
        query.update(
            depth="all",
            expand=query["expand"] + ",extensions.inlineProperties,extensions.resolution",
        )
    return query


def _consistent(pagination: dict, start: int, total) -> None:
    if total is not None and total != pagination["total"]:
        raise ValueError("CONTENT_CHANGED")
    end = start + pagination["returned"]
    current = pagination["total"]
    if current is not None and (
        not pagination["has_more"] and end != current or pagination["has_more"] and end >= current
    ):
        raise ValueError("RESPONSE_INVALID")


def _collection(client, request: tuple[str, str, dict]) -> list:
    identity, kind, current = request
    values, seen, start, total = [], set(), 0, None
    while True:
        response = client.get(f"rest/api/content/{identity}/child/{kind}", _query(kind, start))
        pagination = window(response, start, 100)
        _consistent(pagination, start, total)
        total = pagination["total"]
        values.extend(_child(value, kind, seen) for value in response["results"])
        bounded({"current": current, "values": values})
        if not pagination["has_more"]:
            return values
        start = pagination["next_start"]


def _missing(comment: dict) -> dict | None:
    extensions = comment.get("extensions", {})
    fields = [
        "extensions." + key for key in ("inlineProperties", "resolution") if key not in extensions
    ]
    return {"id": comment["id"], "fields": fields} if fields else None


def _comment_coverage(comments: list) -> dict:
    return {
        "complete": True,
        "returned": len(comments),
        "visibility": "configured account",
        "depth": "all",
        "location": "all exposed",
        "metadata_not_returned": [found for value in comments if (found := _missing(value))],
    }


def collect(client, identity: str, result: dict) -> None:
    comments = _collection(client, (identity, "comment", result))
    attachments = _collection(client, (identity, "attachment", result))
    result["page"].update(comments=comments, attachments=attachments)
    result["coverage"]["comments"] = _comment_coverage(comments)
    result["coverage"]["attachments"] = {
        "complete": True,
        "returned": len(attachments),
        "binary_retrieved": False,
    }
