"""Deliver inspected credential steps and bounded page commands to a connected Chrome tab."""

import argparse
import json
import os
from pathlib import Path

from slopmeister.session import browser_runtime as runtime

VARIABLES = {"BROWSER_LOGIN_USERNAME", "BROWSER_LOGIN_PASSWORD", "BROWSER_LOGIN_OTP"}
TYPES = {
    "BROWSER_LOGIN_USERNAME": ["text", "email"],
    "BROWSER_LOGIN_PASSWORD": ["password"],
    "BROWSER_LOGIN_OTP": ["text", "tel", "number"],
}
MAX_STEPS = 4


def fields(values: list[list[str]], resolved: bool = True) -> list[list[str]]:
    result = []
    for selector, variable in values:
        if variable not in VARIABLES or not selector or len(selector) > 1024:
            raise ValueError("BROWSER_FIELD_REFUSED")
        if not resolved:
            result.append([selector, ""])
            continue
        value = os.environ.get(variable, "")
        if not value or value.startswith("op://") or len(value) > 16384:
            raise ValueError("BROWSER_CREDENTIAL_UNRESOLVED")
        if variable == "BROWSER_LOGIN_OTP" and (
            len(value) not in (6, 8) or not value.isascii() or not value.isdecimal()
        ):
            raise ValueError("BROWSER_OTP_REFUSED: require a generated numeric code, never a seed")
        result.append([selector, value])
    if not result or len(result) > 2:
        raise ValueError("BROWSER_FIELD_REFUSED")
    return result


def step(raw: str, resolved: bool = True) -> dict:
    """One inspected page: its exact URL, the fields to fill there and the control to press."""
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise ValueError("BROWSER_STEP_REFUSED") from None
    if not isinstance(parsed, dict) or set(parsed) != {"url", "fields", "submit"}:
        raise ValueError("BROWSER_STEP_REFUSED")
    url, pairs, submit = parsed["url"], parsed["fields"], parsed["submit"]
    if not isinstance(url, str) or not isinstance(submit, str) or not isinstance(pairs, list):
        raise ValueError("BROWSER_STEP_REFUSED")
    if not submit or len(submit) > 1024:
        raise ValueError("BROWSER_STEP_REFUSED")
    if not all(
        isinstance(p, list) and len(p) == 2 and all(isinstance(v, str) for v in p) for p in pairs
    ):
        raise ValueError("BROWSER_STEP_REFUSED")
    origin, path = runtime.https_url(url)
    inputs = [
        {"selector": selector, "value": value, "types": TYPES[variable]}
        for (selector, variable), (_, value) in zip(pairs, fields(pairs, resolved), strict=True)
    ]
    return {"origin": origin, "path": path, "fields": inputs, "submit": submit}


def fill(root: Path, args: argparse.Namespace) -> dict:
    if len(args.step) > MAX_STEPS:
        raise ValueError("BROWSER_STEP_REFUSED")
    steps = [step(raw) for raw in args.step]
    data = runtime.metadata(root)
    # A site keeps a rejected username in its form, and a username is no secret.
    secret = [
        f for s in steps for f in s["fields"] if f["types"] != TYPES["BROWSER_LOGIN_USERNAME"]
    ]
    data["credential_fields"] = [f["selector"] for f in secret]
    runtime.save(root, data)
    return runtime.request(root, {"action": "fill", "steps": steps})


def check(root: Path, args: argparse.Namespace) -> dict:
    """Test the session and the first page with no secret, because approval comes before fill."""
    if len(args.step) > MAX_STEPS:
        raise ValueError("BROWSER_STEP_REFUSED")
    steps = [step(raw, resolved=False) for raw in args.step]
    return runtime.request(root, {"action": "check", "steps": steps[:1]})


def arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    start = sub.add_parser("start")
    start.add_argument("url")
    for name in ("run", "check", "fill", "close"):
        p = sub.add_parser(name)
        p.add_argument("state")
        if name == "run":
            p.add_argument("command", nargs=argparse.REMAINDER)
        elif name in {"check", "fill"}:
            p.add_argument("--step", action="append", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = arguments(argv)
    try:
        root = runtime.owned(args.state) if hasattr(args, "state") else None
        match args.action:
            case "start":
                result = runtime.start(args.url)
            case "check":
                result = check(root, args)
            case "fill":
                result = fill(root, args)
            case "close":
                result = runtime.close(root)
            case "run":
                done = runtime.page(root, args.command)
                print(done.stdout, end="")
                return done.returncode
        print(json.dumps(result))
        return int(args.action in {"check", "fill"} and result.get("result") == "BROWSER_BLOCKED")
    except (OSError, ValueError) as error:
        message = (
            str(error)
            if isinstance(error, ValueError)
            else "BROWSER_STATE_OR_CONNECTION_UNAVAILABLE"
        )
        if isinstance(error, TimeoutError):
            message = "BROWSER_TIMEOUT: outcome unknown; do not retry submission"
        print(json.dumps({"result": "BROWSER_BLOCKED", "reason": message}))
        return 1
