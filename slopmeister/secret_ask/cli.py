"""The broker service and its relay, the entry the Mac reaches over the dedicated SSH route."""

import argparse
import json
import os
from pathlib import Path
import select
import sys

from slopmeister.session import secret_transport as transport

from .config import CONFIG, load


def connected(source) -> bool:
    """Whether the SSH client is still there: its stdin reads EOF once it has gone."""
    try:
        readable, _, _ = select.select([source], [], [], 0)
        return not readable or bool(os.read(source.fileno(), 1))
    except OSError, ValueError:
        return False


def relay(source=sys.stdin, sink=sys.stdout) -> int:
    """Settle one request read as a JSON line, printing every broker reply as a line."""
    try:
        request = json.loads(source.readline())
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        report = lambda receipt: print(json.dumps(receipt), file=sink, flush=True)  # noqa: E731
        final = transport.settle(transport.SOCKET, request, (report, lambda: connected(source)))
    except transport.Refused as error:
        print(json.dumps({"error": "request refused", "detail": str(error)}), file=sink, flush=True)
        return 1
    except (OSError, ValueError, KeyError) as error:
        detail = {"error": "broker unavailable", "detail": str(error)}
        print(json.dumps(detail), file=sink, flush=True)
        return 1
    print(json.dumps(final), file=sink, flush=True)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    modes = result.add_subparsers(dest="operation", required=True)
    daemon = modes.add_parser("serve", help="run the system service")
    daemon.add_argument("--config", type=Path, default=CONFIG)
    modes.add_parser("relay", help="settle one request from stdin for a client on another machine")
    return result


def main(argv: list[str]) -> int:
    args = parser().parse_args(argv)
    try:
        if args.operation == "serve":
            from .daemon import serve

            return serve(load(args.config))
        return relay()
    except KeyboardInterrupt:
        return 130
