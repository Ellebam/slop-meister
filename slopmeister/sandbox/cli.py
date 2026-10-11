"""The opt-in local Jira and Confluence sandbox: up, status, stop, down and live."""

from collections.abc import Sequence
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import tempfile

from slopmeister.sandbox import setup, writes
from slopmeister.session.service_actions.constants import OP, PYTHON, PYTHON_FLAGS, SUCCESS

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[1]
STATE = Path.home() / ".local/state/slopmeister/sandbox"
ACCESS = Path.home() / ".config/slopmeister/access"
PLOT = "sandbox"
JIRA, CONFLUENCE = "https://localhost:18443", "https://localhost:18444"
ORIGINS = {"jira-read": JIRA, "confluence-read": CONFLUENCE}
ORIGINS |= {"jira-write": JIRA, "confluence-write": CONFLUENCE}
# Writes run as the same sandbox user, so they reuse the read PAT items.
ITEMS = {"jira-read": "slopmeister-sandbox-jira-pat"}
ITEMS |= {"confluence-read": "slopmeister-sandbox-confluence-pat"}
ITEMS |= {"jira-write": ITEMS["jira-read"], "confluence-write": ITEMS["confluence-read"]}
ROUTING = ("account_id", "vault_id", "vault_name", "token_file")
APPS = ["jira", "confluence"]
OPENSSL = "/usr/bin/openssl"


class SandboxError(Exception):
    pass


def compose(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(PACKAGE / "compose.yml"), *args]


def certificate() -> list[str]:
    """A localhost leaf that is never a CA, profiles pin it through `server_ca`."""
    tls = STATE / "tls"
    argv = [OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "825"]
    argv += ["-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"]
    argv += ["-addext", "basicConstraints=critical,CA:FALSE"]
    argv += ["-addext", "extendedKeyUsage=serverAuth"]
    return argv + ["-keyout", str(tls / "key.pem"), "-out", str(tls / "cert.pem")]


def op_item(action: str, routing: dict, create: bool) -> list[str]:
    """The PAT reaches `op` only on stdin as an item template, never as an argument."""
    verb = ["create", "-"] if create else ["delete", ITEMS[action]]
    return [str(OP), "item", *verb, "--vault", routing["vault_id"], "--format", "json"]


def _write(path: Path, text: str) -> None:
    path.unlink(missing_ok=True)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        stream.write(text)


def _environment() -> dict[str, str]:
    licences = json.loads((PACKAGE / "timebomb.json").read_text())
    return dict(os.environ, SANDBOX_STATE=str(STATE), CONFLUENCE_LICENSE=licences["confluence"])


def _run(argv: list[str], stdin: str | None = None) -> str:
    result = subprocess.run(argv, input=stdin, capture_output=True, text=True, env=_environment())
    if result.returncode:
        raise SandboxError(f"{Path(argv[0]).name} {argv[1]} failed: {result.stderr.strip()[-400:]}")
    return result.stdout


def prepare_state() -> None:
    (STATE / "tls").mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE.chmod(0o700)
    if not (STATE / "tls/cert.pem").exists():
        _run(certificate())
        (STATE / "tls/key.pem").chmod(0o600)
    (STATE / "tls/cert.pem").chmod(0o644)
    if not (STATE / "db.env").exists():
        password = secrets.token_urlsafe(24)
        lines = [f"POSTGRES_USER={PLOT}", f"ATL_JDBC_USER={PLOT}"]
        lines += [f"POSTGRES_PASSWORD={password}", f"ATL_JDBC_PASSWORD={password}"]
        _write(STATE / "db.env", "\n".join(lines) + "\n")


def routing(root: Path = ACCESS) -> dict:
    """Every existing profile shares one service account and vault, the sandbox joins it."""
    found = {
        tuple(json.loads(path.read_text())[key] for key in ROUTING)
        for action in ORIGINS
        for path in sorted(root.glob(f"*/{action}.json"))
        if path.parent.name != PLOT
    }
    if len(found) != 1:
        raise SandboxError("existing profiles must share exactly one account, vault and token file")
    return dict(zip(ROUTING, found.pop(), strict=True))


def _store(action: str, token: str, route: dict) -> None:
    subprocess.run(op_item(action, route, create=False), capture_output=True, env=_environment())
    field = {"id": "credential", "type": "CONCEALED", "label": "credential", "value": token}
    template = {"title": ITEMS[action], "category": "API_CREDENTIAL", "fields": [field]}
    _run(op_item(action, route, create=True), json.dumps(template))


def _profile(action: str, route: dict) -> None:
    data = dict(route, action=action, plot=PLOT, origin=ORIGINS[action], expected_user=setup.USER)
    data["pat_ref"] = f"op://{route['vault_name']}/{ITEMS[action]}/credential"
    data["server_ca"] = str(STATE / "tls/cert.pem")
    if action == "jira-read":
        data["backlog_jql"] = f'project = "{setup.KEY}" AND statusCategory != Done ORDER BY key ASC'
    (ACCESS / PLOT).mkdir(mode=0o700, parents=True, exist_ok=True)
    _write(ACCESS / PLOT / f"{action}.json", json.dumps(data, indent=2) + "\n")


def _context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=STATE / "tls/cert.pem")


def _apps() -> dict[str, setup.App]:
    return {
        action: setup.App(ORIGINS[action], _context())
        for action in ("jira-read", "confluence-read")
    }


def _build(route: dict) -> None:
    apps = _apps()
    licence = json.loads((PACKAGE / "timebomb.json").read_text())["jira"]
    confluence, page = setup.confluence(apps["confluence-read"])
    tokens = {"jira-read": setup.jira(apps["jira-read"], licence), "confluence-read": confluence}
    for action, token in tokens.items():
        _store(action, token, route)
    _write(STATE / "ids.json", json.dumps({"page": page}) + "\n")


def up() -> int:
    route = routing()
    prepare_state()
    running = _run(compose("ps", "--status", "running", "-q", *APPS)).split()
    _run(compose("up", "-d"))
    if running:
        _run(compose("restart", *APPS))
    states = [setup.wait(app) for app in _apps().values()]
    if states == ["FIRST_RUN", "FIRST_RUN"]:
        _build(route)
    elif states != ["RUNNING", "RUNNING"] or not (STATE / "ids.json").exists():
        raise SandboxError("sandbox is half set up, run task sandbox:down and then task sandbox:up")
    for action in ("jira-read", "confluence-read"):
        _profile(action, route)
    print(f"sandbox ready: jira {JIRA} confluence {CONFLUENCE}")
    return 0


def status() -> int:
    ready = True
    for name, app in zip(APPS, _apps().values(), strict=True):
        state = setup.state(app)
        ready &= state == "RUNNING"
        print(f"{name} {'ready' if state == 'RUNNING' else state.lower()}")
    return 0 if ready else 1


def _call(tree: Path, action: str, argument: list[str]) -> dict:
    """Run the fixed sandbox consumer with structured input on the environment."""
    argv = [str(PYTHON), *PYTHON_FLAGS, "-m", "service_actions.supervisor"]
    directory = tree / ".claude/service-actions" / action
    env = dict(os.environ, SLOPMEISTER_SERVICE_ACTION_INPUT=json.dumps(argument))
    result = subprocess.run(
        argv, capture_output=True, text=True, timeout=330, env=env, cwd=directory
    )
    # op run masks any injected secret that reaches output, so the mask itself is a leak.
    if "concealed by 1Password" in result.stdout + result.stderr:
        raise SandboxError(f"{action} output carried a secret")
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except ValueError, IndexError:
        output = (result.stdout + result.stderr).strip()[-400:]
        raise SandboxError(f"{action} failed: {output}") from None


def _fetch(tree: Path, action: str, argument: list[str]) -> str:
    result = _call(tree, action, argument)
    if result.get("result") != SUCCESS[action]:
        raise SandboxError(f"{action} failed: {result}")
    return SUCCESS[action]


def live() -> int:
    from slopmeister.install.service_actions import ActionContext, action_payload

    page = json.loads((STATE / "ids.json").read_text())["page"]
    with tempfile.TemporaryDirectory() as workspace:
        tree = Path(workspace)
        context = ActionContext(REPO, PLOT, {"service_actions": list(ORIGINS)}, tree, native=False)
        for relative, (content, mode) in action_payload(context)[0].items():
            (tree / relative).parent.mkdir(parents=True, exist_ok=True)
            (tree / relative).write_bytes(content)
            (tree / relative).chmod(mode)
        print(_fetch(tree, "jira-read", ["--issue", f"{setup.KEY}-1"]))
        print(_fetch(tree, "jira-read", ["--backlog"]))
        print(_fetch(tree, "confluence-read", ["--page", str(page)]))
        print(writes.check(lambda action, argument: _call(tree, action, argument), str(page)))
    return 0


def stop() -> int:
    _run(compose("stop"))
    return 0


def down() -> int:
    _run(compose("down", "--volumes", "--remove-orphans"))
    (STATE / "ids.json").unlink(missing_ok=True)
    return 0


def main(argv: Sequence[str]) -> int:
    commands = {"up": up, "status": status, "stop": stop, "down": down, "live": live}
    if len(argv) != 1 or argv[0] not in commands:
        sys.stderr.write("usage: slopmeister sandbox up|status|stop|down|live\n")
        return 2
    try:
        return commands[argv[0]]()
    except (
        SandboxError,
        setup.SetupError,
        writes.WriteCheckError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        sys.stderr.write(f"sandbox: {error}\n")
        return 1
