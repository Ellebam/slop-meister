"""A fake opencode on PATH that answers from a JSON state file and records each call."""

import json
from pathlib import Path
import sys

SCRIPT = r"""#!/usr/bin/env python3
import json, os, sys
state_path = "@STATE@"
state = json.load(open(state_path))
args = sys.argv[1:]
seen = {name: bool(os.environ.get(name)) for name in state.get("watch", [])}
record = {"argv": args, "cwd": os.getcwd(), "env": seen,
          "config": os.environ.get("OPENCODE_CONFIG_CONTENT"),
          "claude_off": os.environ.get("OPENCODE_DISABLE_CLAUDE_CODE")}
with open("@LOG@", "a") as log:
    log.write(json.dumps(record) + "\n")
if args[:2] == ["session", "list"]:
    print(state["list_raw"] if "list_raw" in state else json.dumps(state.get("sessions", [])))
elif args[:2] == ["session", "delete"]:
    state.setdefault("deleted", []).append(args[2])
    json.dump(state, open(state_path, "w"))
    sys.exit(state.get("delete_exit", 0))
elif args[:1] == ["export"]:
    found = state.get("exports", {}).get(args[1])
    if found is None:
        sys.exit(1)
    print(json.dumps(found, indent=2)[: state.get("export_cut")])
elif args[:1] == ["run"]:
    prompt = sys.stdin.read()
    session = state.get("session", "ses_fake")
    for name in state.get("echo", []):
        sys.stderr.write("provider said " + os.environ.get(name, "") + "\n")
    for event in state.get("events", []):
        print(json.dumps(dict(event, sessionID=session)))
    exported = state.get("run_export")
    if exported is not None:
        exported["messages"][0]["parts"] = [{"type": "text", "text": prompt}]
        state.setdefault("exports", {})[session] = exported
        json.dump(state, open(state_path, "w"))
    sys.exit(state.get("run_exit", 0))
"""


def install(directory: Path, state: dict) -> dict[str, str]:
    """Write the fake and its state; the returned entries only document where they live."""
    directory.mkdir(parents=True, exist_ok=True)
    fake = directory / "opencode"
    # Paths are baked in because the tester hands OpenCode a projected environment.
    script = SCRIPT.replace("/usr/bin/env python3", sys.executable, 1)
    script = script.replace("@STATE@", str(directory / "state.json"))
    fake.write_text(script.replace("@LOG@", str(directory / "calls.jsonl")))
    fake.chmod(0o755)
    (directory / "state.json").write_text(json.dumps(state))
    return {
        "FAKE_OPENCODE_STATE": str(directory / "state.json"),
        "FAKE_OPENCODE_LOG": str(directory / "calls.jsonl"),
    }


def calls(directory: Path) -> list[dict]:
    log = directory / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def state(directory: Path) -> dict:
    return json.loads((directory / "state.json").read_text())


def exported(session: str, directory: str, prompt: str) -> dict:
    """An export shaped like OpenCode 1.18, one user prompt and one answer from prov/model-a."""
    answer = {"role": "assistant", "providerID": "prov", "modelID": "model-a", "finish": "stop"}
    return {
        "info": {"id": session, "directory": directory},
        "messages": [
            {"info": {"role": "user"}, "parts": [{"type": "text", "text": prompt}]},
            {"info": answer, "parts": [{"type": "text", "text": "done"}]},
        ],
    }
