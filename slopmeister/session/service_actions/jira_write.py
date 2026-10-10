"""Jira writes: the permission probe and fixed changes to at most three named tickets."""

import json

from .constants import SUCCESS
from .jira import PROJECT
from .operations import BODY, ISSUE, JSON, KEY, NAME, Form, Rejected, Table, guards, targets
from .writes import Write, apply, items, requires

UPDATED = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}[+-][0-9]{4}"
KEYS = targets(KEY, "issue keys")


def _update(operation: dict) -> None:
    requires("fields", guard="if-updated", targets="keys")(operation)
    if isinstance(json.loads(operation["fields"]), list):
        raise Rejected("--update expects one JSON object applied to every key")


def _link(operation: dict) -> None:
    requires("type", "to-issue")(operation)
    if len(operation.get("if-updated", [])) != 2:
        raise Rejected("--link expects --if-updated for the issue and --to-issue")
    if operation["to-issue"] == operation["key"]:
        raise Rejected("--to-issue expects another issue")


def _guarded(name: str):
    return requires(name, guard="if-updated", targets="keys")


TABLE = Table(
    {
        "--permissions": Form("project", PROJECT),
        "--create": Form("project", PROJECT, ("--fields",), check=requires("fields")),
        "--update": Form("keys", KEYS, ("--fields", "--if-updated"), check=_update),
        "--comment": Form("keys", KEYS, ("--body", "--if-updated"), check=_guarded("body")),
        "--transition": Form("keys", KEYS, ("--to", "--if-updated"), check=_guarded("to")),
        "--link": Form("key", ISSUE, ("--type", "--to-issue", "--if-updated"), check=_link),
    },
    {
        "--fields": JSON,
        "--body": BODY,
        "--to": NAME,
        "--type": NAME,
        "--to-issue": ISSUE,
        "--if-updated": guards(UPDATED, "Jira updated values"),
    },
)


def updated(client, key: str) -> str:
    issue = client.get(f"rest/api/2/issue/{key}", {"fields": "updated"})
    value = issue.get("fields", {}).get("updated") if isinstance(issue, dict) else None
    if issue.get("key") != key or not isinstance(value, str):
        raise ValueError("RESPONSE_INVALID")
    return value


def _seconds(value: str) -> str:
    """Search returns `updated` truncated to whole seconds, so guards compare at that precision."""
    return value[:19] + value[23:]


def _after(key: str):
    def read(_response, client, line: dict) -> None:
        line["updated"] = updated(client, key)

    return read


def _created(response, client, line: dict) -> None:
    key = response.get("key") if isinstance(response, dict) else None
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError("RESPONSE_INVALID")
    line["created"] = key
    line["updated"] = updated(client, key)


def _transition(client, key: str, name: str) -> str:
    found = client.get(f"rest/api/2/issue/{key}/transitions").get("transitions")
    ids = [item.get("id") for item in found or [] if item.get("name") == name]
    if len(ids) != 1 or not isinstance(ids[0], str):
        raise ValueError("SELECTOR_UNAVAILABLE")
    return ids[0]


def _existing(client, operation: dict, key: str) -> Write:
    mode, path = operation["mode"], f"rest/api/2/issue/{key}"
    if mode == "update":
        return Write(key, "PUT", path, {"fields": json.loads(operation["fields"])}, _after(key))
    if mode == "comment":
        return Write(key, "POST", path + "/comment", {"body": operation["body"]}, _after(key))
    transition = {"transition": {"id": _transition(client, key, operation["to"])}}
    return Write(key, "POST", path + "/transitions", transition, _after(key))


def _planned(client, operation: dict) -> list[Write]:
    mode = operation["mode"]
    if mode == "create":
        project = {"project": {"key": operation["project"]}}
        post = [{"fields": fields | project} for fields in items(operation["fields"])]
        return [Write(operation["project"], "POST", "rest/api/2/issue", p, _created) for p in post]
    keys = [operation["key"], operation["to-issue"]] if mode == "link" else operation["keys"]
    for key, value in zip(keys, operation["if-updated"], strict=True):
        if _seconds(updated(client, key)) != _seconds(value):
            raise ValueError("CONTENT_CHANGED")
    if mode == "link":
        link = {"type": {"name": operation["type"]}}
        link |= {"inwardIssue": {"key": keys[0]}, "outwardIssue": {"key": keys[1]}}
        return [Write(keys[0], "POST", "rest/api/2/issueLink", link, _after(keys[0]))]
    return [_existing(client, operation, key) for key in keys]


def write(client, expected: str, operation: dict) -> dict:
    user = client.get("rest/api/2/myself")
    if user.get("name") != expected:
        raise ValueError("IDENTITY_MISMATCH")
    result = {"result": SUCCESS["jira-write"], "user": expected, "operation": operation["mode"]}
    if operation["mode"] != "permissions":
        return apply(client, result, _planned(client, operation))
    found = client.get("rest/api/2/mypermissions", {"projectKey": operation["project"]})
    permissions = found.get("permissions") if isinstance(found, dict) else None
    if not isinstance(permissions, dict):
        raise ValueError("RESPONSE_INVALID")
    have = {name: value.get("havePermission") is True for name, value in permissions.items()}
    return dict(result, project=operation["project"], permissions=have)
