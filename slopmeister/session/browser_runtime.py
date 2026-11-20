"""Run page commands in a session's own tab of a named, persistent Chrome profile."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from slopmeister.session import browser_display as display
from slopmeister.session import browser_state as state
from slopmeister.session.browser_state import (
    PREFIX,
    SECONDS,
    TEMP_ROOT,
    data_home,
    environment,
    hide,
    https_url,
    locked,
    metadata,
    node,
    private_directory,
    save,
    workspace,
)
from slopmeister.session.browser_state import (
    configuration as _configuration,
)
from slopmeister.session.browser_state import owned as owned
from slopmeister.session.browser_state import request as protocol_request

PAGE_TOOL = data_home() / "playwright"
PAGE_ENTRY = PAGE_TOOL / "node_modules/@playwright/cli/playwright-cli.js"
LIBRARY = PAGE_TOOL / "node_modules/playwright-core"
SESSION = "job"
# The page tool session that holds the profile's Chrome while any state uses it.
KEEPER = "keep"
VIEWPORT = ("1280", "800")
# Files the page tool creates inside the state, all removed at close.
OWNED = ("playwright",)
SNAPSHOTS = "playwright/.playwright-cli"
# The owner-only state has a size limit, so a long address must not reach it.
ADDRESS_LIMIT = 1024
# Page work only. Cookie, storage, saved state, network bodies, routing, code running,
# recording and session commands stay out, because they reach credentials or other browsers.
# A new tab would belong to no session, so tab-new stays out too.
COMMANDS = frozenset(
    {
        "goto", "click", "dblclick", "fill", "type", "press", "keydown", "keyup", "hover",
        "select", "check", "uncheck", "drag", "upload", "snapshot", "find", "eval",
        "dialog-accept", "dialog-dismiss", "resize", "go-back", "go-forward", "reload",
        "mousemove", "mousedown", "mouseup", "mousewheel", "screenshot", "tab-list",
        "tab-close", "tab-select",
    }
)  # fmt: skip
TAB_COMMANDS = frozenset({"tab-list", "tab-close", "tab-select"})
# Output names stay generated inside the state, so no option may choose a file or a session.
# JSON output carries the tab list as one string, which the per-line tab filter cannot cut.
OPTIONS = frozenset(
    {"--modifiers", "--submit", "--depth", "--boxes", "--type", "--full-page", "--hires",
     "--regex", "--raw"}
)  # fmt: skip
# The command line forces a full snapshot after actions. Console capture can be stopped: no known
# level matches "none", so the pinned tool records no console message. Recheck on a version change.
CONFIG = {"console": {"level": "none"}}
# One line of the page tool's tab list, such as "- 2: (current) [Title](https://...)".
TAB_LINE = re.compile(r"^- (\d+):( \(current\))? .*$", re.MULTILINE)
# Every reply lists all tabs of the profile, and another session's titles and addresses stay out.
OPEN_TABS = re.compile(r"^### Open tabs\n(?:- .*\n?)*", re.MULTILINE)
ATTACHED = re.compile(r"^- [^\n]+:\n  - status: open\n  - browser-type: \w+ \(attached\)$", re.M)
FILLED = "BROWSER_PAGE_REFUSED: a credential field holds a value"
UNANSWERED = "BROWSER_PAGE_REFUSED: the page does not answer"
FOREIGN = (
    "BROWSER_PAGE_REFUSED: the current tab is not this session's own page, so the output is "
    "withheld and the command may have reached another session's page. Find an own tab with "
    "tab-list and select it with tab-select"
)
TAB_LOST = "BROWSER_TAB_LOST: this session's own tab is gone. Close the state and start again"


def start(url: str, profile: str, private_display: bool = False) -> dict:
    origin, path = https_url(url)
    if not PAGE_ENTRY.is_file():
        raise ValueError("BROWSER_PREREQUISITE: run task browser:install")
    node()
    runtime = state.runtime(profile)
    with locked(runtime):
        # Two first starts of one profile would otherwise seed it at the same time.
        folder = state.profile(profile)
        root = Path(tempfile.mkdtemp(prefix=PREFIX, dir=TEMP_ROOT)).resolve()
        address = (origin + path)[:ADDRESS_LIMIT]
        save(root, {"worktree": str(workspace()), "address": address, "profile": profile})
        try:
            open_keeper(runtime, folder, private_display)
            attach(root, url)
        except (ValueError, OSError) as error:
            try:
                teardown(root, metadata(root), runtime)
            except ValueError, OSError:
                raise ValueError(f"{error}; retain state {root} for cleanup") from None
            finally:
                # The attach, tab and teardown output can name another session's page.
                shutil.rmtree(root / SNAPSHOTS, ignore_errors=True)
            raise ValueError(f"{error}; the state is closed") from None
    return {
        "result": "BROWSER_READY",
        "state": str(root),
        "profile": profile,
        "url": metadata(root)["address"],
    }


def open_keeper(runtime: Path, folder: Path, private_display: bool) -> None:
    if keeper_open(runtime):
        return
    # A display an interrupted session left behind has no Chrome any more.
    display.stop(runtime)
    display.check(private_display)
    env = display.start(runtime) if private_display else {}
    arguments = ["open", "--persistent", f"--profile={folder}", "--browser=chrome", "--headed"]
    done = keeper(runtime, [*arguments, "about:blank"], env)
    if done.returncode:
        raise ValueError(f"BROWSER_START_FAILED: Chrome did not open the profile: {failure(done)}")


def attach(root: Path, url: str) -> None:
    done = page_tool(root, ["attach", KEEPER, "--session=" + SESSION])
    if done.returncode:
        raise ValueError(f"BROWSER_START_FAILED: {failure(done)}")
    data = {**metadata(root), "tab_unproven": True}
    save(root, data)
    done = session(root, ["tab-new", url])
    current = current_tab(session(root, ["tab-list"]))
    if done.returncode or current is None:
        raise ValueError(f"BROWSER_START_FAILED: {failure(done)}")
    data["own"] = request(root, {"action": "own", "index": current})["target"]
    del data["tab_unproven"]
    save(root, data)
    done = session(root, ["resize", *VIEWPORT])
    if done.returncode:
        raise ValueError(f"BROWSER_START_FAILED: {failure(done)}")
    shutil.rmtree(root / SNAPSHOTS, ignore_errors=True)
    try:
        guard(root, data)
    except ValueError as error:
        raise ValueError(f"BROWSER_PAGE_NOT_REACHED: {error}") from None


def current_tab(done: subprocess.CompletedProcess) -> int | None:
    found = [int(m.group(1)) for m in TAB_LINE.finditer(done.stdout) if m.group(2)]
    return found[0] if not done.returncode and len(found) == 1 else None


def socket(root: Path) -> str:
    found = list((runtime_of(root) / "sockets/browser").glob("*.sock"))
    if len(found) != 1:
        raise ValueError("BROWSER_CONNECTION_LOST: close the state and start again")
    return str(found[0])


def runtime_of(root: Path) -> Path:
    name = metadata(root).get("profile")
    if not isinstance(name, str):
        raise ValueError("BROWSER_STATE_REFUSED")
    return state.runtime(name)


def request(root: Path, payload: dict) -> dict:
    """Ask the page helper, which acts only on the state's own tab and its popups."""
    full = {"own": metadata(root).get("own"), **payload}
    full.update(socket=socket(root), library=str(LIBRARY))
    return protocol_request(root, node(), full)


def tool(
    work: Path, runtime: Path, arguments: list[str], extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    """Run the pinned page tool with the profile's sockets and lists and output in work."""
    if not PAGE_ENTRY.is_file():
        raise ValueError("BROWSER_PREREQUISITE: run task browser:install")
    for directory in (work, work / "tmp", work / ".playwright"):
        private_directory(directory)
    _configuration(work / ".playwright/cli.config.json", CONFIG)
    env = {
        **environment(work),
        "TMPDIR": str(work / "tmp"),
        # Each profile has its own sockets and session lists, so two keepers never meet.
        "PWTEST_SOCKETS_DIR": str(runtime / "sockets"),
        "PWTEST_DAEMON_SESSION_DIR": str(runtime / "daemon"),
        "PWTEST_SERVER_REGISTRY": str(runtime / "registry"),
        # Chrome discovery needs the real HOME, so its global page tool settings are replaced.
        "PWTEST_CLI_GLOBAL_CONFIG": str(work),
        "NO_UPDATE_NOTIFIER": "1",
    }
    if extra:
        env.pop("WAYLAND_DISPLAY", None)
        env.update(extra)
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


def keeper(
    runtime: Path, arguments: list[str], extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return tool(runtime / "keeper", runtime, ["-s=" + KEEPER, *arguments], extra)


def keeper_open(runtime: Path) -> bool:
    listed = tool(runtime / "keeper", runtime, ["list"])
    return f"- {KEEPER}:\n  - status: open" in listed.stdout


def page_tool(root: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    return tool(root / "playwright", runtime_of(root), arguments)


def session(root: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    return page_tool(root, ["-s=" + SESSION, *arguments])


def allowed(arguments: list[str]) -> str:
    if not arguments or arguments[0] not in COMMANDS:
        raise ValueError("BROWSER_COMMAND_REFUSED")
    # A leading dash followed by a digit is a negative number, such as a scroll distance.
    switches = [a for a in arguments[1:] if a.startswith("-") and not a[1:2].isdigit()]
    if any(a.split("=")[0] not in OPTIONS for a in switches):
        raise ValueError("BROWSER_OPTION_REFUSED")
    if arguments[0] == "goto" and len(arguments) > 1:
        https_url(arguments[1])
    return arguments[0]


def page(root: Path, arguments: list[str]) -> subprocess.CompletedProcess:
    command = allowed(arguments)
    # The page tool saves a snapshot after every action, so it never runs while a credential
    # field holds a value. The check uses the page helper, not the page tool.
    data = metadata(root)
    # A tab command reads no page and shows only own tabs, so it finds the way back to one.
    reply = guard(root, data, foreign=command in TAB_COMMANDS)
    if command == "tab-close":
        done = close_tab(root, data, reply, arguments[1:])
    else:
        if command == "tab-select" and tab_index(arguments[1:]) not in reply["owned"]:
            raise ValueError("BROWSER_COMMAND_REFUSED: select one of this session's own tabs")
        done = session(root, arguments)
    # An action can make Chrome reveal a saved password or move to another session's tab, so
    # its snapshot and output are withheld.
    try:
        reply = guard(root, data, foreign=command == "tab-list")
    except ValueError, OSError:
        shutil.rmtree(root / SNAPSHOTS, ignore_errors=True)
        raise
    text = OPEN_TABS.sub("", done.stdout)
    if command in TAB_COMMANDS:
        text = TAB_LINE.sub(lambda m: m.group() if int(m.group(1)) in reply["owned"] else "", text)
    done.stdout = hide(text)
    if done.returncode:
        done.stdout += hide(OPEN_TABS.sub("", done.stderr))
    return done


def tab_index(arguments: list[str]) -> int | None:
    return int(arguments[0]) if arguments and arguments[0].isdigit() else None


def close_tab(
    root: Path, data: dict, reply: dict, arguments: list[str]
) -> subprocess.CompletedProcess:
    """Close an own popup by its Chrome target, so a shifted tab index cannot reach a peer's tab."""
    index = tab_index(arguments) if arguments else reply["current"]
    if index not in reply["owned"] or index == reply["main"]:
        raise ValueError("BROWSER_COMMAND_REFUSED: close one of this session's own popups")
    request(root, {"action": "close", "index": index})
    # The page tool moves its current tab to a neighbour, which can be another session's tab.
    main = guard(root, data, foreign=True)["main"]
    return session(root, ["tab-select", str(main)])


def failure(done: subprocess.CompletedProcess) -> str:
    """The page tool's own error line, with no address tail and no other session's tab."""
    text = hide(OPEN_TABS.sub("", f"{done.stdout}\n{done.stderr}"))
    # A navigation failure names Chrome's network error with no error type before it.
    found = (line for line in text.splitlines() if re.match(r"\w*Error: |net::ERR_", line))
    return next(found, "the page tool gave no error")


def guard(root: Path, data: dict, foreign: bool = False) -> dict:
    """Refuse the page tool unless its current tab is an own live page with no credential value."""
    tabs = session(root, ["tab-list"])
    current = current_tab(tabs)
    if current is None and not foreign:
        raise ValueError(UNANSWERED)
    selectors = [
        "input[type=password]",
        'input[autocomplete="one-time-code"]',
        *data.get("credential_fields", []),
    ]
    payload = {"action": "filled", "selectors": selectors}
    try:
        reply = request(root, {**payload, "current": None if foreign else current})
    except ValueError as error:
        if "OPERATION_FAILED" in str(error):
            raise ValueError(UNANSWERED) from None
        raise
    result = reply.get("result")
    if result == "PAGE_LOST":
        raise ValueError(TAB_LOST)
    if result == "FOREIGN":
        raise ValueError(FOREIGN)
    if result != "EMPTY":
        raise ValueError(FILLED if result == "FILLED" else UNANSWERED)
    if "address" in reply:
        data["address"] = reply["address"]
        save(root, data)
    return {**reply, "current": current}


def attached(runtime: Path) -> int | None:
    """How many states of the profile hold a page tool session, or None when the list failed."""
    listed = tool(runtime / "keeper", runtime, ["list", "--all"])
    if listed.returncode:
        return None
    return len(ATTACHED.findall(listed.stdout.split("### Browser servers")[0]))


def teardown(root: Path, data: dict, runtime: Path) -> bool:
    """Close the state's pages and session, and Chrome and its display after the last state.

    Runs under the profile lock. Returns whether own tabs may remain in a Chrome still open.
    """
    listed = page_tool(root, ["list"])
    if listed.returncode:
        raise ValueError("BROWSER_CLOSE_UNCONFIRMED")
    left = bool(data.get("tab_unproven"))
    # The helper reaches Chrome through the keeper, so own tabs close even without the session.
    if data.get("own"):
        try:
            request(root, {"action": "close"})
        except ValueError:
            left = True
    joined = f"- {SESSION}:\n  - status: open" in listed.stdout
    if joined and session(root, ["detach"]).returncode:
        raise ValueError("BROWSER_CLOSE_UNCONFIRMED")
    if attached(runtime) == 0:
        closed = not keeper_open(runtime) or not keeper(runtime, ["close"]).returncode
        # The display holds the Chrome, so it stops even when the keeper did not answer.
        display.stop(runtime)
        if not closed:
            raise ValueError("BROWSER_CLOSE_UNCONFIRMED: the profile's Chrome did not close")
        left = False
    remove(root)
    return left


def remove(root: Path) -> None:
    if any(p.name not in {*OWNED, "owner.json"} for p in root.iterdir()):
        raise ValueError("BROWSER_STATE_REFUSED")
    if any((root / name).is_symlink() for name in OWNED):
        raise ValueError("BROWSER_STATE_REFUSED")
    for name in OWNED:
        if (root / name).exists():
            shutil.rmtree(root / name)
    (root / "owner.json").unlink()
    root.rmdir()


def close(root: Path) -> dict:
    data = metadata(root)
    runtime = runtime_of(root)
    with locked(runtime):
        left = teardown(root, data, runtime)
    if not left:
        return {"result": "BROWSER_CLOSED"}
    tab = data.get("address", "A tab of this state")
    return {
        "result": "BROWSER_CLOSED",
        "tabs_left": f"{tab} may still be open in the profile's Chrome. Tell the operator",
    }
