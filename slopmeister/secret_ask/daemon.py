"""One service owns request lifetime, Home Assistant events and the resolution of approvals."""

from concurrent.futures import ThreadPoolExecutor
import os
import pwd
import signal
import socket
import threading
import time

from .broker import Broker
from .config import Config, private_token
from .home_assistant import Channel
from .local import handle
from .resolve import resolve


class Daemon:
    def __init__(self, config: Config):
        self.config = config
        self.broker = Broker(config.state, config.operator)
        self.token = private_token(config.op_token)
        self.stop = threading.Event()
        self.clients = ThreadPoolExecutor(max_workers=4, thread_name_prefix="secret-ask-client")
        self.resolvers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="secret-ask-resolve")
        self.slots = threading.BoundedSemaphore(16)
        self.channel = Channel(config, self.broker, self.approved)

    def approved(self, row: dict) -> None:
        self.resolvers.submit(self._resolve, row)

    def _resolve(self, row: dict) -> None:
        values, failed = resolve(row["env"], (self.config.op, self.token, self.config.state))
        if failed:
            self.broker.log.info("%s resolution_failed %s", row["id"], failed)
            self.broker.finish(row["id"], "failed")
        else:
            self.broker.ready(row["id"], values)

    def _client(self, client: socket.socket) -> None:
        try:
            handle(client, self.broker, self.config.agent_uid)
        finally:
            self.slots.release()

    def _listen(self, listener: socket.socket) -> None:
        while not self.stop.is_set():
            self.broker.expire(time.time())
            try:
                client, _ = listener.accept()
            except TimeoutError:
                continue
            if self.slots.acquire(blocking=False):
                self.clients.submit(self._client, client)
            else:
                client.close()

    def run(self) -> None:
        os.umask(0o077)
        path = self.config.socket
        path.unlink(missing_ok=True)
        thread = threading.Thread(target=self.channel.run, name="secret-ask-ha")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            os.chown(path, -1, pwd.getpwuid(self.config.agent_uid).pw_gid)
            path.chmod(0o660)
            listener.listen(16)
            listener.settimeout(0.25)
            thread.start()
            try:
                self._listen(listener)
            finally:
                self._close(thread)
                path.unlink(missing_ok=True)

    def _close(self, thread: threading.Thread) -> None:
        self.channel.stop.set()
        self.clients.shutdown(wait=True, cancel_futures=True)
        thread.join(timeout=15)
        self.channel.close()
        self.resolvers.shutdown(wait=True, cancel_futures=True)
        self.broker.close()


def serve(config: Config) -> int:
    daemon = Daemon(config)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: daemon.stop.set())
    daemon.run()
    return 0
