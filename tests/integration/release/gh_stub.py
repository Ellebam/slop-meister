"""Local REST responses for release tests. This file makes no network requests."""

import json
import os
from pathlib import Path
import sys


def respond(status: int, value: dict) -> None:
    print(f"HTTP/2.0 {status} Synthetic\nContent-Type: application/json\n")
    print(json.dumps(value))
    if status >= 400:
        print(os.environ["GH_TOKEN"], file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    file = Path(os.environ["RELEASE_STATE"])
    state = json.loads(file.read_text())
    args = sys.argv
    method, path = args[args.index("--method") + 1], args[2]
    payload = json.load(sys.stdin) if "--input" in args else None
    call = {"method": method, "path": path, "body": payload}
    state["calls"].append(call)
    file.write_text(json.dumps(state))
    if state.get("fail") == f"{method} {path}":
        respond(state.get("status", 503), {"message": "Synthetic failure"})
    value = operate(state, call)
    file.write_text(json.dumps(state))
    respond(200 if value else 404, value or {"message": "Not Found"})


def operate(state: dict, call: dict) -> dict | None:
    path, payload = call["path"], call["body"]
    if call["method"] == "GET":
        key = "tag" if "/git/ref/" in path else "release"
        return state[key]
    if path.endswith("/git/refs"):
        assert state["tag"] is None, "Tag already exists"
        state["tag"] = {"ref": payload["ref"], "object": {"type": "commit", "sha": payload["sha"]}}
        return state["tag"]
    assert path.endswith("/releases"), path
    assert state["release"] is None, "Release already exists"
    state["release"] = payload | {
        "published_at": "2026-01-01T00:00:00Z",
        "target_commitish": "main",
    }
    return state["release"]


if __name__ == "__main__":
    main()
