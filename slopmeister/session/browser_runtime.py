"""Own browser lifecycle and dispatch page operations without native keyboard focus."""

import os
from pathlib import Path
import shutil
import sys
import tempfile

from slopmeister.session.browser_state import (
    MARKER,
    PREFIX,
    TEMP_ROOT,
    credential_state,
    execute,
    https_url,
    identifier,
    metadata,
    save,
)
from slopmeister.session.browser_state import environment as environment
from slopmeister.session.browser_state import owned as owned
from slopmeister.session.browser_state import request as protocol_request


def binaries() -> tuple[Path, Path]:
    if sys.platform == "darwin":
        roots = (Path("/Applications"), Path.home() / "Applications")
        choices = [
            (p / "Orca.app/Contents/Resources/bin/orca", p / "Orca.app/Contents/MacOS/Orca")
            for p in roots
        ]
    elif sys.platform == "linux":
        cli = Path(shutil.which("orca-ide") or "/opt/Orca/resources/bin/orca-ide").resolve()
        choices = [(cli, cli.parents[2] / name) for name in ("orca-ide", "orca", "Orca")]
    else:
        choices = []
    for pair in choices:
        if all(p.is_file() and os.access(p, os.X_OK) for p in pair):
            return pair
    raise ValueError("BROWSER_PREREQUISITE: install and start Orca")


def cli(root: Path, command: list[str]) -> dict:
    program, _ = binaries()
    response = execute(root, [str(program), *command, "--json"])
    if response.get("ok") is not True or not isinstance(response.get("result"), dict):
        raise ValueError("BROWSER_ORCA_OPERATION_FAILED")
    return response["result"]


def allocate(root: Path, url: str, data: dict) -> None:
    profile = cli(root, ["tab", "profile", "create", "--label", root.name, "--scope", "isolated"])
    data["profile"] = identifier(profile["profile"]["id"])
    save(root, data)
    owner = "path:" + data["worktree"]
    command = ["tab", "create", "--url", "about:blank", "--worktree", owner]
    tab = cli(root, [*command, "--profile", data["profile"]])
    data["page"] = identifier(tab["browserPageId"])
    save(root, data)
    cli(root, ["exec", "--page", data["page"], "--command", "open " + url])


def start(url: str, browser: str = "orca") -> dict:
    https_url(url)
    if browser == "orca":
        binaries()
    elif browser != "chrome":
        raise ValueError("BROWSER_ROUTE_REFUSED")
    worktree = str(Path.cwd().resolve())
    root = Path(tempfile.mkdtemp(prefix=PREFIX, dir=TEMP_ROOT)).resolve()
    data = {"worktree": worktree, "browser": browser}
    save(root, data)
    try:
        if browser == "chrome":
            from slopmeister.session import browser_chrome

            browser_chrome.allocate(root, url, data)
        else:
            allocate(root, url, data)
    except (KeyError, ValueError) as error:
        raise ValueError(f"BROWSER_START_FAILED: retain state {root} for cleanup") from error
    return {
        "result": "BROWSER_READY",
        "state": str(root),
        "page": data["page"],
        "route": "Installed Google Chrome" if browser == "chrome" else "Orca integrated browser",
    }


def page_command(root: Path, action: str, url: str | None = None) -> dict:
    if action == "snapshot":
        if credential_state(root):
            raise ValueError("BROWSER_SNAPSHOT_REFUSED")
        command = ["snapshot", "--page", metadata(root)["page"]]
    elif action == "open" and url is not None:
        https_url(url)
        command = ["exec", "--page", metadata(root)["page"], "--command", "open " + url]
    else:
        raise ValueError("BROWSER_COMMAND_REFUSED")
    try:
        if metadata(root).get("browser") == "chrome":
            return request(root, {"action": action, "url": url})
        return cli(root, command)
    except ValueError:
        if action == "snapshot":
            raise ValueError("BROWSER_READ_FAILED: use narrow page inspection") from None
        raise


def request(root: Path, payload: dict) -> dict:
    data = metadata(root)
    if data.get("browser") == "chrome":
        from slopmeister.session import browser_chrome

        engine, endpoint = browser_chrome.connection(root, data, payload["action"])
    else:
        if not data.get("page"):
            raise ValueError("BROWSER_STATE_INCOMPLETE: close the saved state")
        endpoint = cli(root, ["exec", "--page", data["page"], "--command", "get cdp-url"])["cdpUrl"]
        _, engine = binaries()
    return protocol_request(root, engine, {**payload, "endpoint": endpoint})


def close(root: Path) -> dict:
    data = metadata(root)
    if data.get("browser") == "chrome":
        from slopmeister.session import browser_chrome

        return browser_chrome.close(root, data)
    return close_orca(root, data)


def close_orca(root: Path, data: dict) -> dict:
    owner = "path:" + data["worktree"]
    pages = {data["page"]} if data.get("page") else set()
    if data.get("profile"):
        tabs = cli(root, ["tab", "list", "--worktree", owner, "--show-profile"])["tabs"]
        pages.update(
            identifier(t["browserPageId"]) for t in tabs if t.get("profileId") == data["profile"]
        )
    for page in sorted(pages):
        data["page"] = page
        save(root, data)
        result = cli(root, ["tab", "close", "--page", page, "--worktree", owner])
        if result.get("closed") is not True:
            raise ValueError("BROWSER_CLOSE_UNCONFIRMED")
        del data["page"]
        save(root, data)
    if data.get("profile"):
        result = cli(root, ["tab", "profile", "delete", "--profile", data["profile"]])
        if result.get("deleted") is not True:
            raise ValueError("BROWSER_CLOSE_UNCONFIRMED")
        del data["profile"]
        save(root, data)
    if any(p.name not in {"owner.json", MARKER} for p in root.iterdir()):
        raise ValueError("BROWSER_STATE_REFUSED")
    if credential_state(root):
        (root / MARKER).unlink()
    (root / "owner.json").unlink()
    root.rmdir()
    return {"result": "BROWSER_CLOSED"}
