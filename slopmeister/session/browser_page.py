"""Bound the optional page tool and verify that its listeners stop before credential input."""

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from slopmeister.session import browser_chrome as chrome
from slopmeister.session import browser_state as state

COMMANDS = {
    "goto": (1, 1, ()), "click": (1, 2, ("--modifiers",)),
    "dblclick": (1, 2, ("--modifiers",)), "fill": (2, 2, ("--submit",)),
    "type": (1, 1, ("--submit",)), "press": (1, 1, ()), "keydown": (1, 1, ()),
    "keyup": (1, 1, ()), "hover": (1, 1, ()), "select": (2, 2, ()),
    "check": (1, 1, ()), "uncheck": (1, 1, ()), "drag": (2, 2, ()),
    "snapshot": (0, 1, ("--depth", "--boxes")), "find": (1, 1, ("--regex",)),
    "dialog-accept": (0, 1, ()), "dialog-dismiss": (0, 0, ()), "resize": (2, 2, ()),
    "go-back": (0, 0, ()), "go-forward": (0, 0, ()), "reload": (0, 0, ()),
    "mousemove": (2, 2, ()), "mousedown": (0, 1, ()), "mouseup": (0, 1, ()),
    "mousewheel": (2, 2, ()), "screenshot": (0, 1, ("--type", "--full-page", "--hires")),
    "tab-list": (0, 0, ()), "tab-new": (0, 1, ()), "tab-close": (0, 1, ()),
    "tab-select": (1, 1, ()),
}  # fmt: skip
VALUE_OPTIONS = {"--modifiers", "--depth", "--type"}
OUTPUT_LIMIT = 1024 * 1024
MAX_PAGES = 32
EXIT_SECONDS = 5


def validate(arguments: list[str]) -> None:
    if not arguments or arguments[0] not in COMMANDS:
        raise ValueError("BROWSER_COMMAND_REFUSED")
    minimum, maximum, options = COMMANDS[arguments[0]]
    positional = _positionals(arguments[1:], options)
    if not minimum <= len(positional) <= maximum:
        raise ValueError("BROWSER_ARGUMENTS_REFUSED")
    if arguments[0] in {"goto", "tab-new"} and positional:
        state.https_url(positional[0])


def _positionals(values: list[str], options: tuple[str, ...]) -> list[str]:
    positional, seen, pending = [], set(), list(values)
    while pending:
        value = pending.pop(0)
        if not value.startswith("-") or re.fullmatch(r"-\d+(?:\.\d+)?", value):
            positional.append(value)
            continue
        name, equals, argument = value.partition("=")
        if name not in options or name in seen:
            raise ValueError("BROWSER_OPTION_REFUSED")
        seen.add(name)
        if name in VALUE_OPTIONS:
            argument = argument if equals else pending.pop(0) if pending else ""
            if not argument or argument.startswith("-"):
                raise ValueError("BROWSER_OPTION_REFUSED")
        elif equals:
            raise ValueError("BROWSER_OPTION_REFUSED")
    return positional


def tool(root: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    entry = state.data_home() / "playwright/node_modules/@playwright/cli/playwright-cli.js"
    if not entry.is_file():
        raise ValueError("BROWSER_PREREQUISITE: run task browser:install")
    work = root / "playwright"
    for path in (work, work / "home", work / "tmp", work / ".playwright"):
        state.private_directory(path)
    config = work / ".playwright/cli.config.json"
    _configuration(config)
    env = {
        **state.environment(root),
        "HOME": str(work / "home"),
        "TMPDIR": str(work / "tmp"),
        "NO_UPDATE_NOTIFIER": "1",
    }
    try:
        done = subprocess.run(
            [str(chrome.binaries()[1]), str(entry), *arguments],
            capture_output=True,
            text=True,
            cwd=work,
            env=env,
            timeout=state.SECONDS,
            umask=0o077,
        )
    except OSError, subprocess.TimeoutExpired:
        raise ValueError("BROWSER_PAGE_TOOL_FAILED: page outcome is unknown") from None
    if done.returncode or len(done.stdout) > OUTPUT_LIMIT:
        raise ValueError("BROWSER_PAGE_TOOL_FAILED: page outcome is unknown")
    return done


def _configuration(config: Path) -> None:
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "w") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError("BROWSER_PAGE_CONFIG_REFUSED")
        stream.truncate(0)
        stream.write(json.dumps({"console": {"level": "none"}}))


def process(root: Path, data: dict) -> str | None:
    owner = data.get("page_owner", {})
    if not isinstance(owner, dict) or type(owner.get("pid")) is not int or owner["pid"] <= 1:
        raise ValueError("BROWSER_PAGE_OWNER_REFUSED")
    pid = owner["pid"]
    done = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "stat=", "-o", "command="],
        capture_output=True,
        text=True,
        timeout=5,
        env=state.environment(root),
    )
    if done.returncode == 1 and not done.stdout and not done.stderr:
        return None
    if done.returncode:
        raise ValueError("BROWSER_PAGE_OWNER_REFUSED")
    words, born = done.stdout.split(), " ".join(done.stdout.split()[:5])
    config = "--config=" + str(root / "playwright/.playwright/cli.config.json")
    matches = all(
        re.search(re.escape(value) + r"(?:\s|$)", done.stdout)
        for value in (config, "--cdp=" + data["endpoint"])
    )
    reused = bool(owner.get("born")) and born != owner["born"]
    zombie = len(words) > 5 and words[5].startswith("Z") and born == owner.get("born")
    if (reused and not matches) or zombie:
        return None
    if reused or not matches or "cliDaemon.js" not in done.stdout:
        raise ValueError("BROWSER_PAGE_OWNER_REFUSED")
    return born


def credentials_visible(root: Path, data: dict) -> bool:
    engine, endpoint = chrome.connection(root, data, "pages")
    listing = state.request(root, engine, {"action": "pages", "endpoint": endpoint})
    pages = listing.get("pages")
    if (
        listing.get("frames") is not False
        or not isinstance(pages, list)
        or not 0 < len(pages) <= MAX_PAGES
    ):
        return True
    selectors = [
        "input[type=password]",
        'input[autocomplete="one-time-code"]',
        *data.get("credential_fields", []),
    ]
    for page in pages:
        if not isinstance(page, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", page):
            return True
        address = endpoint.split("/devtools/")[0] + "/devtools/page/" + page
        found = state.request(
            root, engine, {"action": "filled", "endpoint": address, "selectors": selectors}
        )
        if found.get("result") != "EMPTY":
            return True
    return False


def attach(root: Path, data: dict) -> None:
    data["page_pending"] = True
    state.save(root, data)
    config = root / "playwright/.playwright/cli.config.json"
    response = tool(
        root, ["attach", "--json", "--cdp=" + data["endpoint"], "--config=" + str(config)]
    )
    result = json.loads(response.stdout)
    if not isinstance(result, dict):
        raise ValueError("BROWSER_PAGE_OWNER_REFUSED")
    data["page_owner"] = {"pid": result.get("pid")}
    data["page_owner"]["born"] = process(root, data)
    if not data["page_owner"]["born"]:
        raise ValueError("BROWSER_PAGE_OWNER_REFUSED")
    data.pop("page_pending")
    state.save(root, data)


def page(root: Path, arguments: list[str]) -> dict:
    validate(arguments)
    data = state.metadata(root)
    if data.get("browser") != "chrome":
        raise ValueError("BROWSER_PAGE_REQUIRES_CHROME")
    if data.get("page_pending"):
        raise ValueError("BROWSER_PAGE_OWNER_UNCERTAIN: retain state for cleanup")
    if credentials_visible(root, data):
        raise ValueError("BROWSER_PAGE_REFUSED: populated credential fields or uninspected frames")
    if not data.get("page_owner"):
        attach(root, data)
    elif process(root, data) is None:
        raise ValueError("BROWSER_PAGE_EXITED: close the saved state")
    return {"result": "BROWSER_PAGE", "output": tool(root, arguments).stdout}


def detach(root: Path, data: dict) -> None:
    if data.get("page_pending"):
        raise ValueError("BROWSER_PAGE_OWNER_UNCERTAIN: no credential was entered")
    if not data.get("page_owner"):
        return
    if process(root, data) is not None:
        response = json.loads(tool(root, ["detach", "--json"]).stdout)
        if not isinstance(response, dict) or response.get("status") not in {
            "detached",
            "not-attached",
        }:
            raise ValueError("BROWSER_PAGE_DETACH_UNCONFIRMED")
        deadline = time.monotonic() + EXIT_SECONDS
        while process(root, data) is not None:
            if time.monotonic() >= deadline:
                raise ValueError("BROWSER_PAGE_DETACH_UNCONFIRMED: no credential was entered")
            time.sleep(0.1)
    del data["page_owner"]
    state.save(root, data)
