"""Sign glab in with the token and host `op run` puts in the environment, printing a marker only."""

import os
import re
import subprocess

TOKEN = "SLOPMEISTER_GLAB_TOKEN"
HOST = "SLOPMEISTER_GLAB_HOST"
PLACEHOLDER = "REPLACE_WITH_TOKEN"
# The host comes from a 1Password field and becomes an argument, so it may not look like a flag.
HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")
# With CI or GITLAB_CI set, glab writes the token to its file as plaintext, not to the keychain.
DROPPED = (TOKEN, HOST, "CI", "GITLAB_CI")
TIMEOUT = 60
PASS, FAIL = "GLAB_LOGIN_PASS", "GLAB_LOGIN_FAIL"


def _unfilled(token: str, host: str) -> str | None:
    if not token or token == PLACEHOLDER or token.startswith("op://"):
        return "the 1Password item holds no token"
    if not HOSTNAME.fullmatch(host):
        return "the 1Password item holds no bare host name"
    return None


def login() -> int:
    token, host = os.environ.get(TOKEN, ""), os.environ.get(HOST, "")
    problem = _unfilled(token, host)
    if problem:
        print(f"{FAIL}: {problem}")
        return 1
    command = ["glab", "auth", "login", "--hostname", host, "--stdin"]
    env = {key: value for key, value in os.environ.items() if key not in DROPPED}
    try:
        # glab's own output names the host and may echo a rejected token, so none of it is kept.
        done = subprocess.run(
            command, input=token, text=True, capture_output=True, env=env, timeout=TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"{FAIL}: glab auth login did not finish, {type(error).__name__}")
        return 1
    if done.returncode:
        print(f"{FAIL}: glab auth login exited {done.returncode}")
        return 1
    print(PASS)
    return 0
