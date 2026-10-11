"""Jira read operations: discovery windows, one ticket, related tickets and key batches."""

from .jira_find import discover
from .jira_issue import read_issue, read_issues
from .jira_related import read_related
from .operations import (
    ISSUE,
    ISSUES,
    NAME,
    NUMERIC,
    TEXT,
    WINDOW,
    Form,
    Kind,
    Table,
    choice,
    matching,
    subset,
    windowed,
)

PROJECT = Kind(matching(r"[A-Z][A-Z0-9_]{0,254}"), "a project key such as PROJ")
USER = Kind(matching(r"[A-Za-z0-9._@-]{1,255}"), "me, none or a username")
SPRINT = Kind(matching(r"open|[1-9][0-9]{0,19}"), "a numeric sprint id or open")
FILTERS = {
    "--text": TEXT,
    "--summary": TEXT,
    "--project": PROJECT,
    "--component": NAME,
    "--label": NAME,
    "--status-category": choice("todo", "in-progress", "done"),
    "--assignee": USER,
    "--sprint": SPRINT,
    "--epic": ISSUE,
    "--parent": ISSUE,
    "--board": NUMERIC,
    "--filter": NUMERIC,
    "--keys": ISSUES,
    "--linked-to": ISSUE,
}
TABLE = Table(
    {
        "--issue": Form("key", ISSUE, ("--related",)),
        "--issues": Form("keys", ISSUES),
        "--find": windowed(options=(*FILTERS, "--order"), order="updated"),
        "--backlog": windowed(),
        "--projects": windowed(),
        "--boards": windowed(options=("--project", "--name")),
        "--sprints": windowed("board", NUMERIC, ("--state",)),
    },
    {
        **FILTERS,
        **WINDOW,
        "--related": subset("links", "children", "parent"),
        "--order": choice("updated", "created", "priority", "rank", "key"),
        "--name": NAME,
        "--state": choice("active", "future", "closed"),
    },
)


def read(client, expected: str, operation: dict) -> dict:
    user = client.get("rest/api/2/myself")
    if user.get("name") != expected:
        raise ValueError("IDENTITY_MISMATCH")
    mode = operation["mode"]
    if mode == "issue" and "related" in operation:
        return read_related(client, expected, operation)
    if mode == "issue":
        return read_issue(client, expected, operation["key"])
    if mode == "issues":
        return read_issues(client, expected, operation["keys"])
    return discover(client, expected, operation)
