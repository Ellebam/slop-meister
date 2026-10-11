"""The sandbox write check can run again on a sandbox that already holds its earlier pages."""

import json

from slopmeister.sandbox import writes


def test_repeat_runs_create_pages_with_titles_confluence_has_not_seen():
    titles = []

    def run(action, *args):
        if "--pages" in args:
            titles.extend(page["title"] for page in json.loads(args[args.index("--pages") + 1]))
            return {"written": [{"created": "11"}, {"created": "12"}]}
        if "--comment-page" in args:
            return {"written": [{"created": "13"}]}
        if action == "confluence-read":
            comment = {"id": "13", "body": {"storage": {"value": writes.COMMENT}}}
            return {"page": {"body_storage": writes.PAGE, "comments": [comment]}}
        return {"permissions": ["update:page"]}

    writes._confluence(run, "7")
    writes._confluence(run, "7")
    assert len(set(titles)) == 4
