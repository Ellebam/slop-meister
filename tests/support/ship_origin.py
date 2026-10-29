"""Origin and GitHub as the ship helper sees them, for tests/integration/session/test_ship.py."""

import json
import sys

from slopmeister.session import ship

BODY = "Task proof\n\nIndependent review: PENDING - awaiting diff review\n"
REMOTE = "git@github.com:owner/subject.git"
PINNED = "github.com/owner/subject"
URL = "https://github.com/owner/subject/pull/1"
PR = dict(
    number=1, url=URL, state="OPEN", title="Task", body=BODY, baseRefName="main",
    headRefName="task", headRefOid="", mergedAt="2026-01-01T00:00:00Z",
    headRepository={"nameWithOwner": "owner/subject"},
)  # fmt: skip
OTHER = "git@github.com:other/repo.git"
WRITES = (("gh", "pr", "create"), ("gh", "pr", "edit"))
REAL_COMMAND = ship.command


class Origin:
    """Origin and GitHub as the helper sees them, recording every call."""

    def __init__(self):
        self.sha = None
        self.prs = []
        self.calls = []
        self.mergeable = ["MERGEABLE"]
        self.default = "main"
        self.push_lands = True
        self.fail = None

    def command(self, repo, *argv):
        self.calls.append(argv)
        if self.fail and argv[: len(self.fail)] == self.fail:
            raise ValueError(f"{' '.join(argv[:3])} failed (1): boom")
        if argv[0] == "gh":
            return self.gh(argv[1:])
        if argv[:2] == ("git", "push") and self.push_lands:
            self.sha = REAL_COMMAND(repo, "git", "rev-parse", "HEAD")
        heads = f"{self.sha}\trefs/heads/task" if self.sha else ""
        fake = {sys.executable: "verified", "git push": "", "git ls-remote": heads}
        key = argv[0] if argv[0] == sys.executable else " ".join(argv[:2])
        return fake[key] if key in fake else REAL_COMMAND(repo, *argv)

    def gh(self, args):
        assert args[-2:] == ("--repo", PINNED) or args[-1] == PINNED, args
        texts = [arg[2:].split("=", 1) for arg in args if arg.startswith(("--title=", "--body="))]
        if args[1] == "create":
            number = max((pr["number"] for pr in self.prs), default=0) + 1
            self.prs.append(
                dict(
                    PR,
                    number=number,
                    url=URL.rsplit("/", 1)[0] + f"/{number}",
                    headRefOid=self.sha,
                    **dict(texts),
                )
            )
            return self.prs[-1]["url"]
        if args[1] == "edit":
            index = next(i for i, pr in enumerate(self.prs) if pr["number"] == int(args[2]))
            self.prs[index].update(dict(texts))
            return self.prs[index]["url"]
        if args[:2] == ("pr", "view"):
            state = self.mergeable.pop(0) if len(self.mergeable) > 1 else self.mergeable[0]
            return json.dumps({"mergeable": state})
        repository = {"nameWithOwner": "owner/subject", "defaultBranchRef": {"name": self.default}}
        return json.dumps(repository if args[0] == "repo" else self.prs)

    def writes(self):
        return [call for call in self.calls if call[:3] in WRITES or call[:2] == ("git", "push")]
