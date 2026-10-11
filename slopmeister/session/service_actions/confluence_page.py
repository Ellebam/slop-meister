"""Confluence complete page and latest-user-edit reads."""

from dataclasses import dataclass, field
from datetime import datetime

from . import confluence_children
from .confluence_common import version
from .constants import SUCCESS
from .operations import ID
from .wire import bounded

CQL = "type = page AND contributor = currentUser() ORDER BY lastmodified DESC"
PAGE_SIZE = 25


def _timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise ValueError("RESPONSE_INVALID") from None


def _older(search, page: dict, candidate: dict):
    while True:
        if search.best and _timestamp(candidate["when"]) <= _timestamp(search.best["when"]):
            return None
        if candidate["author"] == search.expected:
            return candidate
        if candidate["number"] == 1:
            return None
        number = candidate["number"] - 1
        response = search.client.get(
            f"rest/api/content/{page['id']}",
            {"status": "historical", "version": number, "expand": "version"},
        )
        prior = version(response, page["id"], number)
        if _timestamp(prior["when"]) > _timestamp(candidate["when"]):
            raise ValueError("CONTENT_CHANGED")
        candidate = prior


@dataclass
class LatestSearch:
    client: object
    expected: str
    best: dict | None = None
    selected: str | None = None
    selected_current: int | None = None
    seen: set[str] = field(default_factory=set)
    start: int = 0
    previous: float = float("inf")

    def response(self) -> dict:
        response = self.client.get(
            "rest/api/content/search",
            {"cql": CQL, "expand": "version", "start": self.start, "limit": PAGE_SIZE},
        )
        results = response.get("results")
        if (
            not isinstance(results, list)
            or response.get("start") != self.start
            or len(results) > PAGE_SIZE
            or response.get("_links", {}).get("next")
            and not results
        ):
            raise ValueError("RESPONSE_INVALID")
        return response

    def consider(self, page: dict) -> bool:
        identity = page.get("id") if isinstance(page, dict) else None
        if (
            not isinstance(identity, str)
            or not ID.fullmatch(identity)
            or identity in self.seen
            or page.get("status") != "current"
        ):
            raise ValueError("RESPONSE_INVALID")
        self.seen.add(identity)
        current = version(page, identity)
        timestamp = _timestamp(current["when"])
        if timestamp > self.previous:
            raise ValueError("CONTENT_CHANGED")
        self.previous = timestamp
        if self.best and timestamp <= _timestamp(self.best["when"]):
            return True
        candidate = _older(self, page, current)
        if candidate:
            self.best, self.selected = candidate, identity
            self.selected_current = current["number"]
        return False

    def result(self) -> tuple[str, int, dict]:
        if self.best is None or self.selected is None or self.selected_current is None:
            raise ValueError("NO_EDITED_PAGES")
        return self.selected, self.selected_current, self.best


def _latest(client, expected: str) -> tuple[str, int, dict]:
    search = LatestSearch(client, expected)
    while True:
        response = search.response()
        complete = any(search.consider(page) for page in response["results"])
        search.start += len(response["results"])
        if complete or not response.get("_links", {}).get("next"):
            break
    return search.result()


@dataclass(frozen=True)
class Selection:
    identity: str
    current: int | None
    best: dict | None


def _selection(client, expected: str, operation: dict) -> Selection:
    if operation["mode"] == "latest-edited":
        return Selection(*_latest(client, expected))
    return Selection(operation["id"], None, None)


def _page(content: dict, selection: Selection) -> dict:
    storage = content.get("body", {}).get("storage", {})
    title = content.get("title")
    if (
        content.get("status") != "current"
        or not isinstance(title, str)
        or len(title) > 10000
        or not isinstance(storage.get("value"), str)
        or storage.get("representation") != "storage"
    ):
        raise ValueError("RESPONSE_INVALID")
    return {
        "id": selection.identity,
        "title": title,
        "url": None,
        "version": version(content, selection.identity),
        "body_storage": storage["value"],
        "space": content.get("space"),
        "ancestors": content.get("ancestors"),
    }


def _result(content: dict, expected: str, selection: Selection) -> dict:
    page = _page(content, selection)
    if selection.current is not None and page["version"]["number"] != selection.current:
        raise ValueError("CONTENT_CHANGED")
    if selection.best:
        page["latest_user_edit"] = selection.best
    return {
        "result": SUCCESS["confluence-read"],
        "user": expected,
        "page": page,
        "coverage": {
            "atomic_snapshot": False,
            "body": "current storage",
            "macros": "unexpanded",
            "historical_bodies": "not retrieved",
            "missing_metadata": [key for key in ("space", "ancestors") if key not in content],
        },
    }


def _unchanged(client, selection: Selection, result: dict) -> dict:
    latest = client.get(f"rest/api/content/{selection.identity}", {"expand": "version"})
    if version(latest, selection.identity)["number"] != result["page"]["version"]["number"]:
        raise ValueError("CONTENT_CHANGED")
    return bounded(result)


def read_page(client, expected: str, operation: dict) -> dict:
    selection = _selection(client, expected, operation)
    content = client.get(
        f"rest/api/content/{selection.identity}",
        {"expand": "body.storage,version,space,ancestors"},
    )
    result = _result(content, expected, selection)
    result["page"]["url"] = client.url("pages/viewpage.action", {"pageId": selection.identity})
    bounded(result)
    confluence_children.collect(client, selection.identity, result)
    return _unchanged(client, selection, result)
