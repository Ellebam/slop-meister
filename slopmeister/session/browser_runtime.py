"""Connect to the operator's Chrome through the Playwright Extension and run page commands."""

import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

from slopmeister.session.browser_state import (
    PREFIX,
    SECONDS,
    TEMP_ROOT,
    data_home,
    environment,
    https_url,
    metadata,
    private_directory,
    save,
    workspace,
)
from slopmeister.session.browser_state import owned as owned
from slopmeister.session.browser_state import request as protocol_request

PAGE_TOOL = data_home() / "playwright"
PAGE_ENTRY = PAGE_TOOL / "node_modules/@playwright/cli/playwright-cli.js"
LIBRARY = PAGE_TOOL / "node_modules/playwright-core"
TOKEN = "PLAYWRIGHT_MCP_EXTENSION_TOKEN"
SESSION = "job"
VIEWPORT = ("1280", "800")
# Files the page tool creates inside the state, all removed at close.
OWNED = ("playwright", "sockets")
# The extension's connect page carries the token in its address.
CONNECT_ADDRESS = re.compile(r"chrome-extension://[^\s)\]\"']+")
HIDDEN = "chrome-extension://hidden"
# The owner-only state has a size limit, so a long address must not reach it.
ADDRESS_LIMIT = 1024
# Page work only. Cookie, storage, saved state, network bodies, routing, code running,
# recording and session commands stay out, because they reach credentials or other browsers.
COMMANDS = frozenset(
    {
        "goto", "click", "dblclick", "fill", "type", "press", "keydown", "keyup", "hover",
        "select", "check", "uncheck", "drag", "upload", "snapshot", "find", "eval",
        "dialog-accept", "dialog-dismiss", "resize", "go-back", "go-forward", "reload",
        "mousemove", "mousedown", "mouseup", "mousewheel", "screenshot", "tab-list", "tab-new",
        "tab-close", "tab-select",
    }
)  # fmt: skip
# Output names stay generated inside the state, so no option may choose a file or a session.
OPTIONS = frozenset(
    {"--modifiers", "--submit", "--depth", "--boxes", "--type", "--full-page", "--hires",
     "--regex", "--raw", "--json"}
)  # fmt: skip
# The command line forces a full snapshot after actions. Console capture can be stopped: no known
# level matches "none", so the pinned tool records no console message. Recheck on a version change.
CONFIG = {"console": {"level": "none"}}
# Chrome drops an extension's debugger from any tab holding another extension's frame and refuses
# to reattach while that frame exists, and 1Password adds one to login pages. With shadow roots
# disabled on its elements, its attachShadow call throws, even from its isolated world, so no frame
# appears. Recheck these names after a 1Password update.
FRAME_BLOCK = """\
for (const name of ['menu', 'uso', 'notification', 'modal'])
  customElements.define(`com-1password-${name}`, class extends HTMLElement {
    static disabledFeatures = ['shadow'];
  });
"""
FILLED = "BROWSER_PAGE_REFUSED: a credential field holds a value"
UNANSWERED = "BROWSER_PAGE_REFUSED: the page does not answer"
TAB_LOST = (
    "BROWSER_TAB_LOST: Chrome took the task tab away from this session. The usual cause is another "
    "extension's frame in the page, such as a 1Password prompt. Close the state and report this"
)


def node() -> Path:
    found = shutil.which("node")
    if found is None:
        raise ValueError("BROWSER_PREREQUISITE: Node required")
    engine = Path(found).resolve()
    cwd = workspace()
    inside = cwd not in {Path.home().resolve(), Path(cwd.anchor)} and engine.is_relative_to(cwd)
    if inside or engine.is_relative_to(TEMP_ROOT):
        raise ValueError(
            "BROWSER_PREREQUISITE: use installed Node outside the workspace and temp root"
        )
    return engine


def start(url: str) -> dict:
    origin, path = https_url(url)
    token = os.environ.get(TOKEN, "")
    if not token or token.startswith("op://"):
        raise ValueError("BROWSER_TOKEN_UNRESOLVED: start under op run with this machine's token")
    if not PAGE_ENTRY.is_file():
        raise ValueError("BROWSER_PREREQUISITE: run task browser:install")
    node()
    root = Path(tempfile.mkdtemp(prefix=PREFIX, dir=TEMP_ROOT)).resolve()
    save(root, {"worktree": str(workspace()), "address": (origin + path)[:ADDRESS_LIMIT]})
    # The address of the connect tab and the attach snapshot never leave this function.
    if page_tool(root, ["attach", "--extension=chrome", "--session=" + SESSION], token).returncode:
        raise ValueError(
            f"BROWSER_EXTENSION_UNAVAILABLE: check Chrome, its extension and the token; "
            f"retain state {root} for cleanup"
        )
    for command in (["tab-new", url], ["tab-close", "0"], ["resize", *VIEWPORT]):
        done = session(root, command)
        if done.returncode:
            save(root, {**metadata(root), "tab_unproven": True})
            raise ValueError(
                f"BROWSER_START_FAILED: {failure(done)}; retain state {root} for cleanup"
            )
    shutil.rmtree(root / "playwright/.playwright-cli", ignore_errors=True)
    data = metadata(root)
    try:
        guard(root, data)
    except ValueError as error:
        save(root, {**data, "tab_unproven": True})
        raise ValueError(
            f"BROWSER_PAGE_NOT_REACHED: {error}; retain state {root} for cleanup"
        ) from None
    return {
        "result": "BROWSER_READY",
        "state": str(root),
        "route": "Playwright Extension",
        "url": data["address"],
    }


def socket(root: Path) -> str:
    found = list((root / "sockets/browser").glob("*.sock"))
    if len(found) != 1:
        raise ValueError("BROWSER_CONNECTION_LOST: close the state and start again")
    return str(found[0])


def request(root: Path, payload: dict) -> dict:
    metadata(root)
    full = {**payload, "socket": socket(root), "library": str(LIBRARY)}
    return protocol_request(root, node(), full)


def page_tool(root: Path, arguments: list[str], token: str = "") -> subprocess.CompletedProcess:
    """Run the pinned page tool with its sockets and output inside the owned state."""
    if not PAGE_ENTRY.is_file():
        raise ValueError("BROWSER_PREREQUISITE: run task browser:install")
    work = root / "playwright"
    for directory in (work, work / "tmp", work / ".playwright", root / "sockets"):
        private_directory(directory)
    block = work / "frame-block.js"
    block.write_text(FRAME_BLOCK)
    config = {**CONFIG, "browser": {"initScript": [str(block)]}}
    _configuration(work / ".playwright/cli.config.json", config)
    env = {
        **environment(root),
        "TMPDIR": str(work / "tmp"),
        "PWTEST_SOCKETS_DIR": str(root / "sockets"),
        # Chrome discovery needs the real HOME, so its global page tool settings are replaced.
        "PWTEST_CLI_GLOBAL_CONFIG": str(work),
        "NO_UPDATE_NOTIFIER": "1",
    }
    if token:
        env[TOKEN] = token
    try:
        done = subprocess.run(
            [str(node()), str(PAGE_ENTRY), *arguments],
            capture_output=True,
            text=True,
            cwd=work,
            env=env,
            timeout=SECONDS,
            umask=0o077,
        )
    except OSError, subprocess.TimeoutExpired:
        raise ValueError("BROWSER_PAGE_TOOL_FAILED: the page outcome is unknown") from None
    if len(done.stdout) > 1024 * 1024:
        raise ValueError("BROWSER_PAGE_TOOL_FAILED: output exceeds the limit")
    return done


def session(root: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    return page_tool(root, ["-s=" + SESSION, *arguments])


def page(root: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    if not arguments or arguments[0] not in COMMANDS:
        raise ValueError("BROWSER_COMMAND_REFUSED")
    # A leading dash followed by a digit is a negative number, such as a scroll distance.
    switches = [a for a in arguments[1:] if a.startswith("-") and not a[1:2].isdigit()]
    if any(a.split("=")[0] not in OPTIONS for a in switches):
        raise ValueError("BROWSER_OPTION_REFUSED")
    if arguments[0] in {"goto", "tab-new"} and len(arguments) > 1:
        https_url(arguments[1])
    # The page tool saves a snapshot after every action, so it never runs while a credential
    # field holds a value. The check uses the page helper, not the page tool.
    data = metadata(root)
    guard(root, data)
    done = session(root, arguments)
    if arguments[0] == "tab-close":
        data["pages"] = data.get("pages", 1) - 1
    # An action can make Chrome reveal a saved password, so its snapshot and output are withheld.
    try:
        guard(root, data)
    except ValueError, OSError:
        shutil.rmtree(root / "playwright/.playwright-cli", ignore_errors=True)
        raise
    done.stdout = CONNECT_ADDRESS.sub(HIDDEN, done.stdout)
    if done.returncode:
        done.stdout += CONNECT_ADDRESS.sub(HIDDEN, done.stderr)
    return done


def failure(done: subprocess.CompletedProcess) -> str:
    """The page tool's own error line, with no address that carries the extension token."""
    text = CONNECT_ADDRESS.sub(HIDDEN, f"{done.stdout}\n{done.stderr}")
    found = (line for line in text.splitlines() if re.match(r"\w*Error: ", line))
    return next(found, "the page tool gave no error")


def guard(root: Path, data: dict) -> None:
    """Refuse the page tool unless the helper finds a live page with no credential value."""
    selectors = [
        "input[type=password]",
        'input[autocomplete="one-time-code"]',
        *data.get("credential_fields", []),
    ]
    try:
        reply = request(root, {"action": "filled", "selectors": selectors})
    except ValueError as error:
        if "OPERATION_FAILED" in str(error):
            raise ValueError(UNANSWERED) from None
        raise
    result = reply.get("result")
    if result == "PAGE_LOST":
        data["tab_unproven"] = True
        save(root, data)
        raise ValueError(TAB_LOST)
    if result != "EMPTY":
        raise ValueError(FILLED if result == "FILLED" else UNANSWERED)
    # A surviving popup hides a lost tab from the blank check, so a drop in live pages counts too.
    # A popup may also close itself, which is why this reports at close and refuses nothing.
    count = reply.get("pages", 0)
    if count < data.get("pages", 0):
        data["tab_unproven"] = True
    if "address" in reply and not data.get("tab_unproven"):
        data["address"] = reply["address"]
    data["pages"] = count
    save(root, data)


def close_tabs(root: Path, data: dict) -> None:
    tabs = session(root, ["tab-list"])
    listed = re.findall(r"^- \d+:.*$", tabs.stdout, re.MULTILINE)
    # A tab can vanish after the last guard, and a surviving popup keeps the session attached.
    if sum("](about:blank)" not in tab for tab in listed) < data.get("pages", 0):
        data["tab_unproven"] = True
    steps = [["tab-close", "0"] for _ in listed]
    if tabs.returncode or any(session(root, step).returncode for step in [*steps, ["detach"]]):
        raise ValueError("BROWSER_CLOSE_UNCONFIRMED")


def close(root: Path) -> dict:
    data = metadata(root)
    # The session ends with Chrome, so a gone session leaves only this state to remove.
    listed = page_tool(root, ["list"])
    if listed.returncode:
        raise ValueError("BROWSER_CLOSE_UNCONFIRMED")
    attached = SESSION in listed.stdout
    if attached:
        close_tabs(root, data)
    if any(p.name not in {*OWNED, "owner.json"} for p in root.iterdir()):
        raise ValueError("BROWSER_STATE_REFUSED")
    if any((root / name).is_symlink() for name in OWNED):
        raise ValueError("BROWSER_STATE_REFUSED")
    for name in OWNED:
        if (root / name).exists():
            shutil.rmtree(root / name)
    (root / "owner.json").unlink()
    root.rmdir()
    if attached and not data.get("tab_unproven"):
        return {"result": "BROWSER_CLOSED"}
    tab = data.get("address", "A tab of this state")
    return {
        "result": "BROWSER_CLOSED",
        "tabs_left": f"{tab} may still be open in Chrome. Tell the operator, this route lost it",
    }


def _configuration(config: Path, data: dict) -> None:
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "w") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise ValueError("BROWSER_PAGE_CONFIG_REFUSED")
        stream.truncate(0)
        stream.write(json.dumps(data))
