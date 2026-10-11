"""Jira discovery: fixed JQL from typed filters, and project, board and sprint listings."""

import re

from .constants import SUCCESS
from .jira_issue import VISIBILITY, url
from .wire import bounded, issue_key, label, literal, term

SPRINT = "com.pyxis.greenhopper.jira:gh-sprint"
EPIC = "com.pyxis.greenhopper.jira:gh-epic-link"
RANK = "com.pyxis.greenhopper.jira:gh-lexo-rank"
PARENT_LINK = "com.atlassian.jpo:jpo-custom-field-parent"
CATEGORIES = {"todo": 2, "in-progress": 4, "done": 3}
ASSIGNEES = {"me": "assignee = currentUser()", "none": "assignee is EMPTY"}
ORDER = {
    "updated": "updated DESC, key DESC",
    "created": "created DESC, key DESC",
    "priority": "priority DESC, key DESC",
    "key": "key ASC",
}
CANDIDATE_FIELDS = ("summary", "issuetype", "status", "assignee", "priority", "labels")
CANDIDATE_FIELDS += ("components", "parent", "updated", "issuelinks")
NOT_FILTERS = ("mode", "order", "start", "limit")
COVERAGE = {
    "bodies_retrieved": False,
    "collection": "window",
    "visibility": VISIBILITY,
    "order": "windows can shift when tickets change between runs",
}


def custom_fields(client) -> dict[str, str]:
    """Numeric ids by schema type, only for types exactly one well-formed field carries."""
    fields = client.get("rest/api/2/field")
    if not isinstance(fields, list) or not all(isinstance(field, dict) for field in fields):
        raise ValueError("RESPONSE_INVALID")
    found: dict[object, list[object]] = {}
    for field in fields:
        schema = field.get("schema") if isinstance(field.get("schema"), dict) else {}
        found.setdefault(schema.get("custom"), []).append(field.get("id"))
    resolved = {}
    for kind in (SPRINT, EPIC, RANK, PARENT_LINK):
        ids = found.get(kind, [])
        text = ids[0] if len(ids) == 1 and isinstance(ids[0], str) else ""
        if match := re.fullmatch(r"customfield_([1-9][0-9]{0,18})", text):
            resolved[kind] = match[1]
    return resolved


def clause_name(fields: dict[str, str], kind: str) -> str:
    """The `cf[id]` clause, refusing rather than dropping a filter the instance cannot resolve."""
    if kind not in fields:
        raise ValueError("SELECTOR_UNAVAILABLE")
    return f"cf[{fields[kind]}]"


def _board_filter(client, board: str) -> str:
    config = client.get(f"rest/agile/1.0/board/{board}/configuration")
    found = config.get("filter") if isinstance(config, dict) else None
    value = str(found.get("id")) if isinstance(found, dict) else ""
    if not re.fullmatch(r"[1-9][0-9]{0,18}", value):
        raise ValueError("SELECTOR_UNAVAILABLE")
    return value


def _sprint(value: str, fields: dict) -> str:
    name = clause_name(fields, SPRINT)
    return f"{name} in openSprints()" if value == "open" else f"{name} = {value}"


CLAUSES = {
    "text": lambda client, value, fields: "text ~ " + term(value),
    "summary": lambda client, value, fields: "summary ~ " + term(value),
    "project": lambda client, value, fields: "project = " + literal(value),
    "component": lambda client, value, fields: "component = " + literal(value),
    "label": lambda client, value, fields: "labels = " + literal(value),
    "status-category": lambda client, value, fields: f"statusCategory = {CATEGORIES[value]}",
    "assignee": lambda client, value, fields: (
        ASSIGNEES.get(value) or "assignee = " + literal(value)
    ),
    "sprint": lambda client, value, fields: _sprint(value, fields),
    "epic": lambda client, value, fields: f"{clause_name(fields, EPIC)} = {literal(value)}",
    "parent": lambda client, value, fields: "parent = " + literal(value),
    "board": lambda client, value, fields: "filter = " + _board_filter(client, value),
    "filter": lambda client, value, fields: "filter = " + value,
    "keys": lambda client, value, fields: "key in (" + ", ".join(map(literal, value)) + ")",
    "linked-to": lambda client, value, fields: f"issue in linkedIssues({literal(value)})",
}


def jql(client, operation: dict, fields: dict) -> str:
    if operation["mode"] == "backlog":
        return backlog_query(client.backlog_jql)
    clauses = [
        CLAUSES[name](client, value, fields)
        for name, value in operation.items()
        if name not in NOT_FILTERS
    ]
    order = operation["order"]
    ordering = f"{clause_name(fields, RANK)} ASC" if order == "rank" else ORDER[order]
    return " AND ".join(clauses) + " ORDER BY " + ordering


def pagination(window: tuple[int, int], returned: int, has_more: bool) -> dict:
    start, limit = window
    next_start = start + returned if has_more else None
    return dict(
        start=start, limit=limit, returned=returned, has_more=has_more, next_start=next_start
    )


def search_window(page: dict, start: int, limit: int) -> dict:
    issues, total, size = page.get("issues"), page.get("total"), page.get("maxResults")
    invalid = not isinstance(issues, list) or page.get("startAt") != start
    invalid |= type(total) is not int or type(size) is not int or not 0 < size <= limit
    returned = len(issues) if isinstance(issues, list) else 0
    invalid |= not invalid and (returned > size or start + returned > total)
    invalid |= not invalid and returned < size and start + returned < total
    if invalid:
        raise ValueError("RESPONSE_INVALID")
    return {**pagination((start, limit), returned, start + returned < total), "total": total}


def backlog_query(value: object) -> str:
    if value is None:
        raise ValueError("BACKLOG_NOT_CONFIGURED")
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
        or not re.fullmatch(r".+\bORDER\s+BY\s+key\s+(?:ASC|DESC)\s*", value, re.IGNORECASE)
    ):
        raise ValueError("BACKLOG_QUERY_INVALID")
    return value


def _name(value) -> str | None:
    return value.get("name") if isinstance(value, dict) else None


def candidate(client, issue: dict, resolved: dict) -> dict:
    fields = issue.get("fields") if isinstance(issue, dict) else None
    key = issue.get("key") if isinstance(issue, dict) else None
    if not issue_key(key) or not isinstance(fields, dict):
        raise ValueError("RESPONSE_INVALID")
    parent = fields.get("parent")
    return {
        "key": key,
        "url": url(client, key),
        "summary": label(fields.get("summary", "")),
        "type": _name(fields.get("issuetype")),
        "status": _name(fields.get("status")),
        "status_category": fields.get("status", {}).get("statusCategory")
        if isinstance(fields.get("status"), dict)
        else None,
        "issuelinks": fields.get("issuelinks"),
        "assignee": _name(fields.get("assignee")),
        "priority": _name(fields.get("priority")),
        "labels": fields.get("labels"),
        "components": [_name(item) for item in fields.get("components") or []],
        "parent": parent.get("key") if isinstance(parent, dict) else None,
        "epic": fields.get("customfield_" + resolved[EPIC]) if EPIC in resolved else None,
        "sprint": fields.get("customfield_" + resolved[SPRINT]) if SPRINT in resolved else None,
        "updated": fields.get("updated"),
    }


def _find(client, operation: dict) -> tuple[list, dict]:
    resolved = {} if operation["mode"] == "backlog" else custom_fields(client)
    extra = tuple("customfield_" + resolved[kind] for kind in (EPIC, SPRINT) if kind in resolved)
    query = {
        "jql": jql(client, operation, resolved),
        "startAt": operation["start"],
        "maxResults": operation["limit"],
        "fields": ",".join(CANDIDATE_FIELDS + extra),
    }
    page = client.get("rest/api/2/search", query)
    window = search_window(page, operation["start"], operation["limit"])
    results = [candidate(client, issue, resolved) for issue in page["issues"]]
    if len({item["key"] for item in results}) != len(results):
        raise ValueError("RESPONSE_INVALID")
    return results, window


def agile_window(page: dict, start: int, limit: int) -> dict:
    values, last = page.get("values"), page.get("isLast")
    invalid = not isinstance(values, list) or page.get("startAt") != start
    invalid |= type(last) is not bool or isinstance(values, list) and len(values) > limit
    returned = len(values) if isinstance(values, list) else 0
    invalid |= not invalid and not last and not values
    if invalid:
        raise ValueError("RESPONSE_INVALID")
    # Jira Software's optional totals are not needed for paging, so none is reported.
    return {**pagination((start, limit), returned, not last), "total": None}


def _board(value) -> dict:
    location = value.get("location") if isinstance(value.get("location"), dict) else {}
    return {
        **{key: value.get(key) for key in ("id", "name", "type")},
        "project": location.get("projectKey"),
    }


def _sprint_item(value) -> dict:
    keys = ("id", "name", "state", "startDate", "endDate", "goal")
    return {key: value.get(key) for key in keys}


def _agile(client, operation: dict) -> tuple[list, dict]:
    query = {"startAt": operation["start"], "maxResults": operation["limit"]}
    if operation["mode"] == "boards":
        path, shape = "rest/agile/1.0/board", _board
        query.update({"projectKeyOrId": operation.get("project"), "name": operation.get("name")})
    else:
        path, shape = f"rest/agile/1.0/board/{operation['board']}/sprint", _sprint_item
        query["state"] = operation.get("state")
    page = client.get(path, {key: value for key, value in query.items() if value is not None})
    window = agile_window(page, operation["start"], operation["limit"])
    values = page["values"]
    ids = [value.get("id") if isinstance(value, dict) else None for value in values]
    if not all(type(item) is int and item > 0 for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("RESPONSE_INVALID")
    return [shape(value) for value in values], window


def _projects(client, operation: dict) -> tuple[list, dict]:
    projects = client.get("rest/api/2/project")
    if not isinstance(projects, list) or not all(isinstance(item, dict) for item in projects):
        raise ValueError("RESPONSE_INVALID")
    keys = [item.get("key") for item in projects]
    if not all(isinstance(key, str) and key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("RESPONSE_INVALID")
    start, limit = operation["start"], operation["limit"]
    window = projects[start : start + limit]
    results = [{"key": item["key"], "name": item.get("name")} for item in window]
    more = start + len(window) < len(projects)
    return results, {**pagination((start, limit), len(window), more), "total": len(projects)}


def discover(client, expected: str, operation: dict) -> dict:
    mode = operation["mode"]
    results, window = {"find": _find, "backlog": _find, "projects": _projects}.get(mode, _agile)(
        client, operation
    )
    result = {"result": SUCCESS["jira-read"], "user": expected, "operation": mode}
    return bounded({**result, "results": results, "pagination": window, "coverage": COVERAGE})
