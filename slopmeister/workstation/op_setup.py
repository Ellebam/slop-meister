"""Install what the session's op needs on this machine, from the environment `op run` fills.

`tokens` writes the two service-account tokens and the vault names each one lists. `approval`
writes the Home Assistant route. Both read their values through the 1Password desktop app, so
they run only with the operator present, print names and a marker, and never a value.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from slopmeister.session import secret_approval, secret_run, secret_tier
from slopmeister.workstation import state

TOKENS = {
    secret_tier.TIER_ONE: "SLOPMEISTER_OP_TIER_ONE",
    secret_tier.TIER_TWO: "SLOPMEISTER_OP_TIER_TWO",
}
ROUTE = {
    "ask_url": "SLOPMEISTER_OP_ASK_URL",
    "answer_url": "SLOPMEISTER_OP_ANSWER_URL",
    "token": "SLOPMEISTER_OP_ANSWER_TOKEN",
}
# The vault that holds the tokens. No token may list it.
TOKEN_VAULT = "SLOPMEISTER_OP_TOKEN_VAULT"
SERVICE_TOKEN = re.compile(r"ops_[A-Za-z0-9_-]+={0,2}")
TIMEOUT = 60
PASS, FAIL = "OP_SETUP_PASS", "OP_SETUP_FAIL"


class Problem(Exception):
    """Nothing was written, the message names the cause without a value."""


def filled(names: dict[str, str]) -> dict[str, str]:
    """The named values from the environment, each resolved by `op run`."""
    values = {key: os.environ.get(variable, "") for key, variable in names.items()}
    for key, value in values.items():
        if not value or value.startswith("op://"):
            raise Problem(f"{names[key]} was not resolved, run this through op run")
    return values


def vaults(tier: str, token: str) -> list[dict[str, str]]:
    """The vaults this token lists, which proves the token and defines its tier."""
    if not SERVICE_TOKEN.fullmatch(token):
        raise Problem(f"the {tier} value is not a service-account token")
    carried = (*TOKENS.values(), *ROUTE.values())
    env = {k: v for k, v in secret_run.normalized(token).items() if k not in carried}
    try:
        done = subprocess.run(
            ["op", "vault", "list", "--format=json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=TIMEOUT,
        )
        listed = json.loads(done.stdout) if done.returncode == 0 else None
    except OSError, subprocess.TimeoutExpired, json.JSONDecodeError:
        listed = None
    if not isinstance(listed, list) or not listed:
        raise Problem(f"1Password did not accept the {tier} token or it lists no vault")
    return [{"id": str(vault["id"]), "name": str(vault["name"])} for vault in listed]


def write(path: Path, text: str) -> None:
    """Replace the file in one step, readable by its owner only from its first byte."""
    if state.link_in(Path.home(), path.relative_to(Path.home())):
        raise Problem("op configuration path contains a symlink")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    fresh = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(text)
        os.replace(fresh, path)
    finally:
        fresh.unlink(missing_ok=True)


def tokens() -> None:
    values = filled(TOKENS)
    kept = os.environ.get(TOKEN_VAULT, "").strip().casefold()
    if not kept or kept.startswith("op://"):
        raise Problem(f"{TOKEN_VAULT} must name the vault that holds the tokens")
    lists = {tier: vaults(tier, token) for tier, token in values.items()}
    for tier, listed in lists.items():
        if kept in {vault["name"].casefold() for vault in listed}:
            raise Problem(f"the {tier} token lists the token vault, change the account's access")
    directory = secret_tier.directory()
    names = [f"{tier}.token" for tier in values] + [secret_tier.LISTS]
    if any(state.link_in(Path.home(), Path(secret_tier.DIRECTORY) / name) for name in names):
        raise Problem("op configuration path contains a symlink")
    for tier, token in values.items():
        write(directory / f"{tier}.token", token + "\n")
    write(directory / secret_tier.LISTS, json.dumps(lists, indent=1) + "\n")
    for tier, listed in lists.items():
        print(f"{tier}: " + ", ".join(sorted(vault["name"] for vault in listed)))


def approval() -> None:
    path = secret_tier.directory() / secret_approval.SETTINGS
    values = filled(ROUTE)
    if not secret_approval.valid(values):
        raise Problem("the 1Password item does not hold the route's two HTTPS addresses and token")
    write(path, json.dumps(values, indent=1) + "\n")


def setup(part: str) -> int:
    try:
        {"tokens": tokens, "approval": approval}[part]()
    except Problem as error:
        print(f"{FAIL}: {error}")
        return 1
    print(PASS)
    return 0
