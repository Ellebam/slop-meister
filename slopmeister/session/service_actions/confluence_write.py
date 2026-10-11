"""Confluence writes: the permission probe and fixed changes to at most three named pages."""

from .confluence_common import version
from .constants import SUCCESS
from .operations import BODY, ID, JSON, NUMERIC, Form, Rejected, Table, guards, targets
from .writes import Write, apply, items, requires

PAGES = targets(ID, "page ids")


def _pages(operation: dict) -> None:
    requires("pages")(operation)
    for page in items(operation["pages"]):
        if set(page) != {"title", "body"} or not all(isinstance(v, str) for v in page.values()):
            raise Rejected("--pages expects objects with exactly a title and a body")


GUARDED = requires("body", guard="if-version", targets="ids")
TABLE = Table(
    {
        "--permissions": Form("id", NUMERIC),
        "--create-page": Form("id", NUMERIC, ("--pages",), check=_pages),
        "--update-page": Form("ids", PAGES, ("--body", "--if-version"), check=GUARDED),
        "--comment-page": Form("ids", PAGES, ("--body", "--if-version"), check=GUARDED),
    },
    {"--pages": JSON, "--body": BODY, "--if-version": guards(r"[1-9][0-9]{0,9}", "page versions")},
)


def _storage(text: str) -> dict:
    return {"storage": {"value": text, "representation": "storage"}}


def _current(client, identity: str) -> dict:
    page = client.get(f"rest/api/content/{identity}", {"expand": "version,space"})
    space = page.get("space", {}).get("key") if isinstance(page, dict) else None
    if not isinstance(page.get("title"), str) or not isinstance(space, str):
        raise ValueError("RESPONSE_INVALID")
    return {"version": version(page, identity)["number"], "title": page["title"], "space": space}


def _created(response, _client, line: dict) -> None:
    identity = response.get("id") if isinstance(response, dict) else None
    if not isinstance(identity, str) or not ID.fullmatch(identity):
        raise ValueError("RESPONSE_INVALID")
    line["created"] = identity
    line["version"] = response.get("version", {}).get("number")


def _updated(identity: str):
    def read(response, _client, line: dict) -> None:
        line["version"] = version(response, identity)["number"]

    return read


def _existing(operation: dict, identity: str, page: dict) -> Write:
    if operation["mode"] == "comment-page":
        comment = {"type": "comment", "container": {"id": identity, "type": "page"}}
        return Write(
            identity,
            "POST",
            "rest/api/content",
            comment | {"body": _storage(operation["body"])},
            _created,
        )
    update = {"id": identity, "type": "page", "title": page["title"]}
    update |= {"version": {"number": page["version"] + 1}, "body": _storage(operation["body"])}
    return Write(identity, "PUT", f"rest/api/content/{identity}", update, _updated(identity))


def _planned(client, operation: dict) -> list[Write]:
    if operation["mode"] == "create-page":
        parent = _current(client, operation["id"])
        common = {
            "type": "page",
            "space": {"key": parent["space"]},
            "ancestors": [{"id": operation["id"]}],
        }
        posts = [
            common | {"title": p["title"], "body": _storage(p["body"])}
            for p in items(operation["pages"])
        ]
        return [
            Write(operation["id"], "POST", "rest/api/content", post, _created) for post in posts
        ]
    pages = {identity: _current(client, identity) for identity in operation["ids"]}
    if [str(page["version"]) for page in pages.values()] != operation["if-version"]:
        raise ValueError("CONTENT_CHANGED")
    return [_existing(operation, identity, page) for identity, page in pages.items()]


def write(client, expected: str, operation: dict) -> dict:
    user = client.get("rest/api/user/current")
    if user.get("username") != expected or user.get("type") != "known":
        raise ValueError("IDENTITY_MISMATCH")
    result = {
        "result": SUCCESS["confluence-write"],
        "user": expected,
        "operation": operation["mode"],
    }
    if operation["mode"] != "permissions":
        return apply(client, result, _planned(client, operation))
    # Data Center reports the account's operations per page, the space form has none.
    page = client.get(f"rest/api/content/{operation['id']}", {"expand": "operations"})
    found = page.get("operations") if isinstance(page, dict) else None
    if not isinstance(found, list) or not all(isinstance(item, dict) for item in found):
        raise ValueError("RESPONSE_INVALID")
    allowed = sorted({f"{item.get('operation')}:{item.get('targetType')}" for item in found})
    return dict(result, page=operation["id"], permissions=allowed)
