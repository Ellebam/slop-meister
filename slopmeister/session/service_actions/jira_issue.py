"""Complete Jira ticket bodies, for one key or a bounded batch."""

from .constants import SUCCESS
from .wire import bounded, literal

VISIBILITY = "tickets this account can see; an absent ticket is not proven to be missing"


def url(client, key: str) -> str:
    return client.origin.rstrip("/") + "/browse/" + key


def _coverage(issue: dict) -> dict:
    fields = issue["fields"]
    log = fields.get("worklog")
    worklogs = log.get("worklogs") if isinstance(log, dict) else None
    total = log.get("total") if isinstance(log, dict) else None
    return {
        "fields": "all exposed fields; unreturned fields may be unavailable",
        "unmapped_fields": [
            key for key in fields if not isinstance(issue.get("names", {}).get(key), str)
        ],
        "missing_metadata": [key for key in ("names", "schema") if key not in issue],
        "changelog": {"retrieved": False},
        "attachments": {
            "metadata_returned": isinstance(fields.get("attachment"), list),
            "binary_retrieved": False,
        },
        "atomic_snapshot": False,
        "worklog": {
            "retrieved": log is not None,
            "returned": len(worklogs) if isinstance(worklogs, list) else None,
            "total": total if type(total) is int and total >= 0 else None,
            "complete": len(worklogs) == total
            if isinstance(worklogs, list) and type(total) is int
            else None,
        },
    }


def _comments(client, key: str, embedded_total) -> list:
    comments, seen, total = [], set(), None
    while True:
        page = client.get(
            f"rest/api/2/issue/{key}/comment",
            {"startAt": len(comments), "maxResults": 100, "orderBy": "created"},
        )
        values, current = page.get("comments"), page.get("total")
        invalid = type(current) is not int or current < 0 or page.get("startAt") != len(comments)
        invalid |= not isinstance(values, list) or len(values) > 100
        invalid |= total is not None and total != current
        invalid |= type(embedded_total) is int and embedded_total != current
        invalid |= isinstance(values, list) and len(comments) + len(values) > current
        invalid |= isinstance(values, list) and not values and len(comments) < current
        if invalid:
            raise ValueError("RESPONSE_INVALID")
        total = current
        for comment in values:
            identity = comment.get("id") if isinstance(comment, dict) else None
            if not isinstance(identity, str) or not identity or identity in seen:
                raise ValueError("RESPONSE_INVALID")
            seen.add(identity)
            comments.append(comment)
        if len(comments) == total:
            return comments


def _body(client, issue: dict, key: str) -> dict:
    fields = issue.get("fields")
    if (
        issue.get("key") != key
        or not isinstance(issue.get("id"), str)
        or not isinstance(fields, dict)
    ):
        raise ValueError("RESPONSE_INVALID")
    links = client.get(f"rest/api/2/issue/{key}/remotelink")
    if not isinstance(links, list) or not all(isinstance(link, dict) for link in links):
        raise ValueError("RESPONSE_INVALID")
    return dict(id=issue["id"], key=key, url=url(client, key), fields=fields, remote_links=links)


def _complete_comments(client, body: dict, always: bool) -> dict:
    embedded = body["fields"].get("comment")
    embedded = embedded if isinstance(embedded, dict) else {}
    total, present = embedded.get("total"), embedded.get("comments")
    if always or not isinstance(present, list) or type(total) is not int or len(present) < total:
        present = _comments(client, body["key"], total)
    body["fields"]["comment"] = {"comments": present, "total": len(present)}
    return {"complete": True, "returned": len(present), "total": len(present)}


def _check_update(client, issue: dict, updated) -> str:
    key = issue["key"]
    latest = client.get(f"rest/api/2/issue/{key}", {"fields": "updated"})
    if (
        latest.get("id") != issue["id"]
        or latest.get("key") != key
        or latest.get("fields", {}).get("updated") != updated
    ):
        raise ValueError("CONTENT_CHANGED")
    return "unchanged" if isinstance(updated, str) else "not returned"


def read_issue(client, expected: str, key: str) -> dict:
    issue = client.get(f"rest/api/2/issue/{key}", {"fields": "*all", "expand": "names,schema"})
    body = _body(client, issue, key)
    body.update(names=issue.get("names"), schema=issue.get("schema"))
    coverage = _coverage(issue)
    coverage["comments"] = _complete_comments(client, body, always=True)
    coverage["comments"]["visibility"] = "configured account"
    coverage["remote_links"] = {"retrieved": True, "returned": len(body["remote_links"])}
    result = {"result": SUCCESS["jira-read"], "user": expected, "operation": "issue"}
    result.update(issue=body, coverage=coverage)
    bounded(result)
    coverage["update_check"] = _check_update(client, issue, body["fields"].get("updated"))
    return bounded(result)


def bodies(client, keys: list[str]) -> dict:
    """Every visible ticket of `keys` in one search, with complete comments."""
    jql = "key in (" + ", ".join(map(literal, keys)) + ") ORDER BY key ASC"
    query = {"jql": jql, "startAt": 0, "maxResults": 100, "fields": "*all"}
    page = client.get(
        "rest/api/2/search", {**query, "expand": "names,schema", "validateQuery": "warn"}
    )
    found = page.get("issues")
    if not isinstance(found, list) or page.get("startAt") != 0:
        raise ValueError("RESPONSE_INVALID")
    found = {issue.get("key") if isinstance(issue, dict) else None: issue for issue in found}
    if len(found) != page["total"] or not all(key in keys for key in found):
        raise ValueError("RESPONSE_INVALID")
    issues = []
    for key, issue in found.items():
        body = _body(client, issue, key)
        body["coverage"] = {**_coverage(issue), "comments": _complete_comments(client, body, False)}
        issues.append(body)
    missing = [key for key in keys if key not in found]
    names, schema = page.get("names") or {}, page.get("schema") or {}
    return {"names": names, "schema": schema, "issues": issues, "not_returned": missing}


def read_issues(client, expected: str, keys: list[str]) -> dict:
    result = {"result": SUCCESS["jira-read"], "user": expected, "operation": "issues"}
    result.update(bodies(client, keys))
    result["coverage"] = {"visibility": VISIBILITY, "atomic_snapshot": False}
    return bounded(result)
