#!/usr/bin/env python3
"""Only disposable fake GitHub and fake native-session commands are accepted here."""

import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

root = Path(os.environ["CLAIMS_FIXTURE"])
name = os.environ.get("CLAIMS_FAKE_NAME", Path(sys.argv[0]).name)
HANDLE = json.dumps({"ok": True, "result": {"terminal": {"handle": "term_fixture"}}})
args = sys.argv[1:]
case = json.loads((root / "case.json").read_text())
workers = [json.loads(p.read_text()) for p in root.glob("worker-*.json")]


def live(worker):
    return (root / (str(worker["pid"]) + ".started")).exists() and subprocess.run(
        ["/bin/ps", "-p", str(worker["pid"]), "-o", "stat="], capture_output=True, text=True
    ).stdout.strip() not in ("", "Z")


if name == "gh":
    with (root / "remote.json").open("r+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        remote = json.load(stream)
        if args[:2] == ["issue", "view"]:
            assert "--repo" in args and args[args.index("--repo") + 1] == "owner/project", args
            print("Mode: spine\nFixture work.")
        else:
            assert args[:3] == ["api", "--hostname", "github.com"], args
            method = args[args.index("-X") + 1]
            endpoint = args[args.index("-X") + 2]
            assert endpoint.startswith("repos/owner/project/"), endpoint
            endpoint = endpoint[len("repos/owner/project/") :].split("?")[0]
            payload = json.load(sys.stdin) if "--input" in args else None
            event = dict(
                method=method,
                endpoint=endpoint,
                payload=payload,
                native=(root / "native.json").exists(),
            )
            with (root / "github.log").open("a") as log:
                log.write(json.dumps(event) + "\n")
            if case.get("write_failure") and method != "GET":
                sys.exit(1)
            if endpoint == "labels":
                result = (
                    payload
                    if method == "POST"
                    else []
                    if case.get("label_absent")
                    else [{"name": "agent:claimed"}]
                )
            elif endpoint.endswith("dependencies/blocked_by"):
                if case.get("dependency_failure"):
                    sys.exit(1)
                result = case.get("dependencies", [])
            elif endpoint == "issues":
                result = [remote]
            elif endpoint == f"issues/{remote['number']}":
                if method == "PATCH":
                    remote["state"] = payload["state"]
                result = remote
            elif endpoint == f"issues/{remote['number']}/labels" and method == "POST":
                assert event["native"], "claim before native delivery"
                native = json.loads((root / "native.json").read_text())
                assert native["model"] or not native["requested"], (
                    "claim before requested model observation"
                )
                remote["labels"] = [{"name": "agent:claimed"}]
                result = remote["labels"]
            elif (
                endpoint == f"issues/{remote['number']}/labels/agent%3Aclaimed"
                and method == "DELETE"
            ):
                remote["labels"] = []
                result = remote["labels"]
            else:
                raise AssertionError(args)
            stream.seek(0)
            json.dump(remote, stream)
            stream.truncate()
            print(json.dumps(result))
elif name == "pgrep":
    selected = [
        w
        for w in workers
        if live(w)
        and (
            "codex --no-daemon" in " ".join(args)
            and w["tool"] == "codex"
            or "remote-control=" + w["name"] in " ".join(args)
            and w["tool"] == "claude"
        )
    ]
    for worker in selected:
        print(worker["pid"])
    sys.exit(0 if selected else 1)
elif name == "ps":
    if "-axo" in args:
        for w in workers:
            if live(w):
                if any("ppid=" in field for field in args):
                    print(w["pid"], 1)
                else:
                    print(w["pid"], "??", w["tool"])
    else:
        pid = int(args[args.index("-p") + 1])
        worker = next((w for w in workers if w["pid"] == pid), None)
        if worker is None:
            sys.exit(subprocess.run(["/bin/ps", *args]).returncode)
        if not live(worker):
            sys.exit(1)
        if any("args=" in x for x in args):
            print(
                "codex --no-daemon -C " + worker["workspace"]
                if worker["tool"] == "codex"
                else "claude --remote-control=" + worker["name"]
            )
        else:
            prefix = "S " if any("stat=" in field for field in args) else ""
            print(prefix + "fixture-start " + worker["tool"])
elif name == "lsof":
    worker = next(w for w in workers if str(w["pid"]) == args[args.index("-p") + 1])
    print("n" + worker["workspace"])
elif name == "claude":
    assert args == ["agents", "--json"], args
    print(json.dumps([{"pid": w["pid"]} for w in workers if live(w)]))
elif name == "orca" and args[:2] != ["terminal", "create"]:
    status = {"app": {"running": True}, "runtime": {"reachable": True}}
    listed = {"terminals": [], "truncated": False}
    reply = status if args[0] == "status" else listed if args[:2] == ["terminal", "list"] else {}
    print(json.dumps({"ok": True, "result": reply}))
elif name == "orca":
    title = args[args.index("--title") + 1]
    worker = next(
        w
        for w in workers
        if w["name"] == title and not (root / (str(w["pid"]) + ".started")).exists()
    )
    if case.get("hold"):
        (root / "held").touch()
        while not (root / "continue").exists():
            time.sleep(0.01)
    (root / (str(worker["pid"]) + ".started")).touch()
    if case.get("undelivered"):
        print(HANDLE)
        sys.exit(0)
    state = Path(os.environ["PLOT_SESSION_STATE_DIR"])
    kickoff = (state / (worker["name"] + ".md")).read_text().rstrip("\n")
    command = (state / (worker["name"] + ".command")).read_text()
    session = (
        re.search(r"--session-id ([a-f0-9-]+)", command)[1]
        if worker["tool"] == "claude"
        else worker["session"]
    )
    model = None if case.get("model_absent") else "observed-native"
    if worker["tool"] == "claude":
        folder = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects/fixture"
        path = folder / (session + ".jsonl")
        rows = [
            {
                "type": "user",
                "sessionId": session,
                "cwd": worker["workspace"],
                "message": {"content": kickoff},
            }
        ]
        if model:
            rows.append({"type": "assistant", "message": {"model": model}})
    else:
        folder = Path(os.environ["CODEX_HOME"]) / "sessions"
        path = folder / ("rollout-2026-09-13T00-00-00-" + session + ".jsonl")
        # A real Codex first turn records its turn_context before the kickoff message.
        rows = [
            {"type": "session_meta", "payload": {"cwd": worker["workspace"], "id": session}},
            *([{"type": "turn_context", "payload": {"model": model}}] if model else []),
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": kickoff}],
                },
            },
        ]
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    (root / "native.json").write_text(
        json.dumps(
            dict(
                model=model,
                session=session,
                path=str(path),
                requested="--model " in command or "model=" in command,
            )
        )
    )
    print(HANDLE)
elif name == "sleep":
    pass
else:
    raise AssertionError(name)
