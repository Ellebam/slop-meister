"""Deliver inspected credential steps to an owned browser page without keyboard focus."""

import argparse
import json
import os
from pathlib import Path

from slopmeister.session import browser_runtime as runtime

VARIABLES = {"BROWSER_LOGIN_USERNAME", "BROWSER_LOGIN_PASSWORD", "BROWSER_LOGIN_OTP"}


def fields(values: list[list[str]]) -> list[list[str]]:
    result = []
    for selector, variable in values:
        if variable not in VARIABLES or not selector or len(selector) > 1024:
            raise ValueError("BROWSER_FIELD_REFUSED")
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


def fill(root: Path, args: argparse.Namespace) -> dict:
    values = fields(args.field)
    origin, path = runtime.https_url(args.url)
    types = {
        "BROWSER_LOGIN_USERNAME": ["text", "email"],
        "BROWSER_LOGIN_PASSWORD": ["password"],
        "BROWSER_LOGIN_OTP": ["text", "tel", "number"],
    }
    inputs = [
        {"selector": selector, "value": value, "types": types[variable]}
        for (selector, variable), (_, value) in zip(args.field, values, strict=True)
    ]
    runtime.credential_state(root, create=True)
    return runtime.request(
        root,
        {
            "action": "fill",
            "step": {"origin": origin, "path": path, "fields": inputs, "submit": args.submit},
        },
    )


def observe(root: Path, expression: str) -> dict:
    try:
        return runtime.request(root, {"action": "eval", "expression": expression})
    except ValueError:
        raise ValueError(
            "BROWSER_READ_FAILED: check the expression; never repeat a submission"
        ) from None


def run(root: Path, command: list[str]) -> dict:
    if command == ["get", "url"]:
        command = ["eval", "location.href"]
    match command:
        case ["snapshot"] | ["snapshot", "-i"]:
            return runtime.page_command(root, "snapshot")
        case ["open", url]:
            return runtime.page_command(root, "open", url)
        case ["eval", expression]:
            return observe(root, expression)
        case [action, target] if action in {"click", "click-text"}:
            current = runtime.request(
                root, {"action": "eval", "expression": "location.origin+location.pathname"}
            )["result"]
            origin, path = runtime.https_url(current)
            step = {
                "origin": origin,
                "path": path,
                "text" if action == "click-text" else "selector": target,
            }
            return runtime.request(root, {"action": action, "step": step})
        case _:
            raise ValueError("BROWSER_COMMAND_REFUSED")


def arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    start = sub.add_parser("start")
    start.add_argument("url")
    start.add_argument("--browser", choices=("orca", "chrome"), default="orca")
    for name in ("run", "fill", "close"):
        p = sub.add_parser(name)
        p.add_argument("state")
        if name == "run":
            p.add_argument("command", nargs=argparse.REMAINDER)
        elif name == "fill":
            p.add_argument("--url", required=True)
            p.add_argument("--field", nargs=2, action="append", required=True)
            p.add_argument("--submit", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = arguments(argv)
    try:
        root = runtime.owned(args.state) if hasattr(args, "state") else None
        match args.action:
            case "start":
                result = runtime.start(args.url, args.browser)
            case "fill":
                result = fill(root, args)
            case "close":
                result = runtime.close(root)
            case "run":
                result = run(root, args.command)
        print(json.dumps(result))
        return int(args.action == "fill" and result.get("result") == "BROWSER_BLOCKED")
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
