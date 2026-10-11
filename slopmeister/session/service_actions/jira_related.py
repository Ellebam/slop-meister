"""One ticket with the complete bodies of its direct neighbours, one hop and bounded."""

import dataclasses
from dataclasses import dataclass

from .jira_find import EPIC, PARENT_LINK, custom_fields, search_window
from .jira_issue import VISIBILITY, bodies, read_issue
from .operations import MAX_KEYS
from .wire import bounded, issue_key, literal


@dataclass
class Neighbours:
    key: str
    fields: dict
    resolved: dict
    found: dict = dataclasses.field(default_factory=dict)
    searched: list = dataclasses.field(default_factory=list)

    def add(self, key, relationship: str) -> None:
        if not issue_key(key):
            raise ValueError("RESPONSE_INVALID")
        self.found.setdefault(key, []).append(relationship)


def _links(near: Neighbours) -> None:
    near.searched.append("links")
    for link in near.fields.get("issuelinks") or []:
        kind = link.get("type") if isinstance(link, dict) else None
        for side in ("inward", "outward"):
            other = link.get(side + "Issue") if isinstance(kind, dict) else None
            if isinstance(other, dict):
                near.add(other.get("key"), f"{side}: {kind.get(side)}")


def _parents(near: Neighbours) -> None:
    parent = near.fields.get("parent")
    if isinstance(parent, dict):
        near.add(parent.get("key"), "parent")
    near.searched.append("parent")
    for kind, relationship in ((EPIC, "epic"), (PARENT_LINK, "parent link")):
        if kind in near.resolved:
            near.searched.append(relationship)
            value = near.fields.get("customfield_" + near.resolved[kind])
            if isinstance(value, dict):
                value = (value.get("data") or {}).get("key")
            if value is not None:
                near.add(value, relationship)


def _children(client, near: Neighbours) -> None:
    clauses = ["parent = " + literal(near.key)]
    near.searched.append("subtasks")
    for kind, relationship in ((EPIC, "epic children"), (PARENT_LINK, "parent link children")):
        if kind in near.resolved:
            clauses.append(f"cf[{near.resolved[kind]}] = {literal(near.key)}")
            near.searched.append(relationship)
    query = {"jql": " OR ".join(clauses) + " ORDER BY key ASC", "startAt": 0}
    query.update(maxResults=MAX_KEYS + 1, fields="parent")
    page = client.get("rest/api/2/search", query)
    if search_window(page, 0, MAX_KEYS + 1)["has_more"]:
        raise ValueError("RELATED_LIMIT")
    for issue in page["issues"]:
        near.add(issue.get("key") if isinstance(issue, dict) else None, "child")


def read_related(client, expected: str, operation: dict) -> dict:
    key, relations = operation["key"], operation["related"]
    result = read_issue(client, expected, key)
    near = Neighbours(key, result["issue"]["fields"], custom_fields(client))
    if "links" in relations:
        _links(near)
    if "parent" in relations:
        _parents(near)
    if "children" in relations:
        _children(client, near)
    near.found.pop(key, None)
    if len(near.found) > MAX_KEYS:
        raise ValueError("RELATED_LIMIT")
    related = bodies(client, sorted(near.found)) if near.found else {"issues": []}
    related.setdefault("not_returned", [])
    for body in related["issues"]:
        body["relationships"] = near.found[body["key"]]
    result.update(operation="related", related=related)
    result["coverage"]["related"] = {"relations_searched": near.searched, "visibility": VISIBILITY}
    return bounded(result)
