"""Own one bounded native-client protocol session and its unreaped process group."""

from contextlib import suppress
import json
import os
import selectors
import subprocess
import time

from slopmeister.check import jobs
from slopmeister.launch.model import Launch

CHUNK = 65536
MAX_FRAME_BYTES = 1024 * 1024
EXIT_WAIT = 5


class Refused(Exception):
    """The client did not establish the required native tool connection."""


class Client:
    def __init__(self, argv: list[str], launch: Launch, seconds: float) -> None:
        self.launch, self.deadline = launch, time.monotonic() + seconds
        self.process = subprocess.Popen(
            argv,
            cwd=launch.wt,
            env=_environment(launch),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        launch.native_pending = True
        try:
            self.poll = selectors.DefaultSelector()
            self.poll.register(self.process.stdout, selectors.EVENT_READ)
        except BaseException:
            if hasattr(self, "poll"):
                self.poll.close()
            jobs.stop_group(self.process, anchored=True)
            launch.native_pending = False
            raise
        self.pending = b""

    def send(self, message: dict) -> None:
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def ask(self, message: dict, matches) -> dict:
        self.send(message)
        while (left := self.deadline - time.monotonic()) > 0:
            line, newline, rest = self.pending.partition(b"\n")
            if newline:
                self.pending = rest
                try:
                    answer = json.loads(line)
                except ValueError, RecursionError:
                    raise Refused("invalid native-client reply") from None
                if not isinstance(answer, dict):
                    raise Refused("invalid native-client reply")
                if matches(answer):
                    return answer
                continue
            if not self.poll.select(left):
                continue
            chunk = os.read(self.process.stdout.fileno(), CHUNK)
            if not chunk:
                raise Refused("the client exited")
            self.pending += chunk
            if len(self.pending) > MAX_FRAME_BYTES:
                raise Refused("native-client frame exceeds the size limit")
        raise Refused("native-client response deadline exceeded")

    def close(self) -> None:
        self.poll.close()
        with suppress(OSError):
            self.process.stdin.close()
        with suppress(subprocess.TimeoutExpired):
            jobs.wait_unreaped(self.process, EXIT_WAIT)
        # The unreaped leader keeps the group identity owned until all children are stopped.
        jobs.stop_group(self.process, anchored=True)
        self.launch.native_pending = False


def _environment(launch: Launch) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("ORCA_")}
    if launch.tool == "codex":
        env["CODEX_HOME"] = str(launch.codex_home)
    elif launch.claude_root:
        env["CLAUDE_CONFIG_DIR"] = str(launch.claude_root)
    else:
        env.pop("CLAUDE_CONFIG_DIR", None)
    return env
