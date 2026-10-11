"""The sandbox write check: every write form on one target and a batch, read back afterwards."""

from collections.abc import Callable
from functools import partial
import json
import secrets

from slopmeister.sandbox import setup

BODY, PAGE = "live\ncomment", "<p>live update</p>"
COMMENT = "<p>live comment</p>"
CORRECTED = '{"summary":"live corrected"}'
RIGHTS = ("CREATE_ISSUES", "EDIT_ISSUES", "ADD_COMMENTS", "TRANSITION_ISSUES", "LINK_ISSUES")


class WriteCheckError(Exception):
    pass


def _expect(condition: bool, what: str) -> None:
    if not condition:
        raise WriteCheckError(f"write check failed: {what}")


def _runner(call: Callable[[str, list[str]], dict]):
    """Every success marker ends in _PASS, every failure code does not."""

    def run(action: str, *args: str) -> dict:
        result = call(action, list(args))
        _expect(str(result.get("result")).endswith("_PASS"), f"{action} {args[0]}: {result}")
        return result

    return run


def _issues(run, keys: list[str]) -> list[dict]:
    return sorted(run("jira-read", "--issues", ",".join(keys))["issues"], key=lambda i: i["key"])


def _created(run, call) -> tuple[list[str], list[str]]:
    """Create and comment a batch of two, and prove a stale guard is refused."""
    jira = partial(run, "jira-write")
    rights = jira("--permissions", setup.KEY)["permissions"]
    _expect(all(rights.get(name) for name in RIGHTS), "sandbox user lacks a Jira write right")
    task = {"summary": "live write", "issuetype": {"name": "Task"}}
    created = jira("--create", setup.KEY, "--fields", json.dumps([task, task]))["written"]
    keys, guards = [line["created"] for line in created], [line["updated"] for line in created]
    comment = jira("--comment", ",".join(keys), "--body", BODY, "--if-updated", ",".join(guards))
    stale = ["--comment", keys[0], "--body", "stale", "--if-updated", guards[0]]
    _expect(call("jira-write", stale).get("result") == "CONTENT_CHANGED", "stale guard accepted")
    return keys, [line["updated"] for line in comment["written"]]


def _jira(run, call) -> None:
    jira = partial(run, "jira-write")
    keys, (first, second) = _created(run, call)
    moved = jira("--transition", keys[0], "--to", "Start Progress", "--if-updated", first)
    now = moved["written"][0]["updated"]
    jira(
        "--link",
        keys[0],
        "--type",
        "Blocks",
        "--to-issue",
        keys[1],
        "--if-updated",
        f"{now},{second}",
    )
    # Correct the created batch as a unit from its record, re-reading its guards first.
    current = ",".join(issue["fields"]["updated"] for issue in _issues(run, keys))
    jira("--update", ",".join(keys), "--fields", CORRECTED, "--if-updated", current)
    issues = _issues(run, keys)
    _expect(all(i["fields"]["summary"] == "live corrected" for i in issues), "summaries")
    last = [i["fields"]["comment"]["comments"][-1]["body"] for i in issues]
    _expect(last == [BODY, BODY], "comments")
    _expect(issues[0]["fields"]["status"]["name"] == "In Progress", "transition")
    links = issues[0]["fields"]["issuelinks"]
    _expect(any(link.get("outwardIssue", {}).get("key") == keys[1] for link in links), "link")


def _confluence(run, page: str) -> None:
    confluence = partial(run, "confluence-write")
    rights = confluence("--permissions", page)["permissions"]
    _expect("update:page" in rights, "sandbox user cannot update the test page")
    # Confluence titles are unique per space and every run leaves its pages behind.
    run_id = secrets.token_hex(4)
    pages = [{"title": f"Live write {run_id} {n}", "body": f"<p>{n}</p>"} for n in ("one", "two")]
    ids = [
        line["created"]
        for line in confluence("--create-page", page, "--pages", json.dumps(pages))["written"]
    ]
    confluence("--update-page", ",".join(ids), "--body", PAGE, "--if-version", "1,1")
    note = confluence("--comment-page", ids[0], "--body", COMMENT, "--if-version", "2")
    read = [run("confluence-read", "--page", identity)["page"] for identity in ids]
    _expect([page["body_storage"] for page in read] == [PAGE, PAGE], "page bodies")
    comments = {c["id"]: c["body"]["storage"]["value"] for c in read[0]["comments"]}
    _expect(comments.get(note["written"][0]["created"]) == COMMENT, "page comment")


def check(call: Callable[[str, list[str]], dict], page: str) -> str:
    run = _runner(call)
    _jira(run, call)
    _confluence(run, page)
    return "SANDBOX_WRITE_PASS"
