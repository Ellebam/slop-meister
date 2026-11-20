"""A recorded page tool and page helper for one Chrome profile, shared by the browser tests."""

import subprocess

from slopmeister.session.browser_runtime import KEEPER, SESSION

OWN_TAB = "- 1: (current) [Page](https://a.example/)\n"
OPEN = "  - status: open\n"
HELPER = {
    "own": {"target": "T1"},
    "close": {"result": "CLOSED"},
    "filled": {"result": "EMPTY", "main": 1, "owned": [1], "address": "https://a.example/"},
}


class Chrome:
    """Answers page tool runs, systemd runs and helper requests like one profile's Chrome.

    A command in replies answers with that exit code and output and changes nothing. An action in
    answers replies with that value, the next item of a list or raises an exception.
    """

    def __init__(self):
        self.calls = []
        self.units = []
        self.helper = []
        self.replies = {}
        self.answers = {}
        self.unit_codes = {"stop": 0, "is-active": 3}
        self.keeper = False
        self.attached = set()
        self.tabs = OWN_TAB

    def run(self, argv, **options):
        if not str(argv[0]).endswith("node"):
            self.units.append((argv, options))
            verb = next(a for a in argv[1:] if not a.startswith("-"))
            return subprocess.CompletedProcess(argv, self.unit_codes.get(verb, 0), "", "")
        arguments = argv[2:]
        self.calls.append((arguments, options))
        command = next((a for a in arguments if not a.startswith("-")), "")
        if command in self.replies:
            code, output = self.replies[command]
            return subprocess.CompletedProcess(argv, code, output, "")
        return subprocess.CompletedProcess(argv, 0, self.act(command, arguments, options), "")

    def act(self, command, arguments, options):
        work = str(options["cwd"])
        keeper = work.endswith("keeper")
        if command in {"open", "close"} and keeper:
            self.keeper = command == "open"
        if command in {"attach", "detach"}:
            (self.attached.add if command == "attach" else self.attached.discard)(work)
        if command == "tab-list":
            return self.tabs
        if command == "list" and "--all" in arguments:
            return self.everyone()
        if command == "list":
            mine = self.keeper if keeper else work in self.attached
            return f"- {KEEPER if keeper else SESSION}:\n{OPEN}" if mine else "(no browsers)\n"
        return "### Result\nok\n"

    def everyone(self):
        joined = f"- {SESSION}:\n{OPEN}  - browser-type: chrome (attached)\n"
        kept = f"- {KEEPER}:\n{OPEN}  - browser-type: chrome\n" if self.keeper else ""
        return f"### Browsers\n{kept}{joined * len(self.attached)}### Browser servers\n"

    def request(self, _root, payload):
        self.helper.append(payload)
        answer = self.answers.get(payload["action"], HELPER.get(payload["action"]))
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer or {"result": "EMPTY"}


def commands(calls):
    return [next(a for a in argv if not a.startswith("-")) for argv, _ in calls]
