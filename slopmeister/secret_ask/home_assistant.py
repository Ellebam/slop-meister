"""Home Assistant notification and authenticated event transport."""

from concurrent.futures import ThreadPoolExecutor
import json
import shlex
import threading
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from websockets.sync.client import connect

from .broker import Broker
from .config import Config, private_token

PUSH_LIMIT = 3800
RESPONSE_LIMIT = 1048576


def notification(row: dict) -> dict:
    references = ", ".join(f"{name}={value}" for name, value in row["env"].items())
    text = (
        f"Command: {shlex.join(row['argv'])}\nReferences: {references}\n"
        f"Why: {row['reason'] or 'no reason given'}\nHost: {row['host']}\n"
        f"Session: {row['session']}\nDirectory: {row['cwd']}"
    )
    body = {
        "title": "Secret approval: " + row["session"],
        "message": text,
        "data": {
            "tag": "secret-ask-" + row["id"],
            "url": "/secret-ask?request=" + row["id"],
            "actions": [
                {"action": row["approve"], "title": "Approve"},
                {"action": row["deny"], "title": "Deny", "destructive": True},
            ],
        },
    }
    if len(json.dumps(body).encode()) > PUSH_LIMIT:
        raise ValueError("request text exceeds notification limit")
    return body


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Home Assistant redirect refused")


class Channel:
    def __init__(self, config: Config, broker: Broker, execute):
        self.config, self.broker, self.execute = config, broker, execute
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.sent: set[str] = set()
        self.deliveries: dict[tuple[str, str], tuple[float, int]] = {}
        self.clear_attempts: dict[str, tuple[float, int]] = {}
        self.last_view = ""
        self.token = private_token(config.ha_token)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.pool = ThreadPoolExecutor(
            max_workers=len(config.devices), thread_name_prefix="secret-ask-notify"
        )

    def http(self, route: str, body: dict) -> None:
        request = Request(
            self.config.url + route,
            json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(request, timeout=3) as response:
            if len(response.read(RESPONSE_LIMIT + 1)) > RESPONSE_LIMIT:
                raise ValueError("Home Assistant response exceeds limit")

    def _notify(self, device: str, body: dict) -> bool:
        try:
            self.http("/api/services/notify/" + device, body)
            return True
        except OSError, ValueError:
            self.broker.log.info("notification_delivery_failed")
            return False

    def fanout(self, body: dict) -> bool:
        futures = [self.pool.submit(self._notify, d, body) for d in self.config.devices]
        return all([future.result() for future in futures])

    def _publish(self) -> None:
        with self.broker.lock:
            rows = [dict(r) for r in self.broker.records.values()]
        pending = [r for r in rows if r["state"] == "pending"]
        visible = pending + [
            {"id": r["id"], "state": r["state"]} for r in rows[-16:] if r["state"] != "pending"
        ]
        for row in visible:
            row.pop("uid", None)
        rendered = json.dumps(visible)
        if rendered != self.last_view:
            self.http(
                "/api/states/sensor.secret_ask",
                {
                    "state": str(len(pending)),
                    "attributes": {"friendly_name": "Secret approvals", "requests": visible},
                },
            )
            self.last_view = rendered
        # A body tap can arrive before another device finishes receiving its push.
        for row in pending:
            if row["id"] not in self.sent:
                self._send_request(row)
        self._clear_finished(rows)

    def _send_request(self, row: dict) -> None:
        try:
            body = notification(row)
        except ValueError:
            self.broker.finish(row["id"], "failed")
            return
        now = time.monotonic()
        futures = {}
        for device in self.config.devices:
            key = (row["id"], device)
            previous, attempts = self.deliveries.get(key, (-3, 0))
            if attempts < 3 and now - previous >= 3:
                futures[key] = (self.pool.submit(self._notify, device, body), attempts)
        for key, (future, attempts) in futures.items():
            self.deliveries[key] = (now, 3 if future.result() else attempts + 1)
        if all(self.deliveries.get((row["id"], d), (0, 0))[1] >= 3 for d in self.config.devices):
            self.sent.add(row["id"])

    def _clear_finished(self, rows: list[dict]) -> None:
        for row in rows:
            previous, attempts = self.clear_attempts.get(row["id"], (0, 0))
            if (
                row["state"] == "pending"
                or not row.get("retract")
                or time.monotonic() - previous < 3
            ):
                continue
            body = {"message": "clear_notification", "data": {"tag": "secret-ask-" + row["id"]}}
            cleared = self.fanout(body)
            self.clear_attempts[row["id"]] = (time.monotonic(), attempts + 1)
            if cleared or attempts >= 2:
                self.broker.retracted(row["id"])
                if not cleared:
                    self.broker.log.info("notification_retraction_failed")
        known = {r["id"] for r in rows}
        self.sent.intersection_update(known)
        self.deliveries = {k: v for k, v in self.deliveries.items() if k[0] in known}
        self.clear_attempts = {k: v for k, v in self.clear_attempts.items() if k in known}

    def _subscribe(self, websocket) -> None:
        if json.loads(websocket.recv(timeout=5)).get("type") != "auth_required":
            raise ValueError("Home Assistant authentication unavailable")
        websocket.send(json.dumps({"type": "auth", "access_token": self.token}))
        if json.loads(websocket.recv(timeout=5)).get("type") != "auth_ok":
            raise ValueError("Home Assistant authentication failed")
        for identifier, kind in enumerate(
            ("mobile_app_notification_action", "secret_ask_decision"), 1
        ):
            websocket.send(
                json.dumps({"id": identifier, "type": "subscribe_events", "event_type": kind})
            )
            reply = json.loads(websocket.recv(timeout=5))
            if reply.get("id") != identifier or reply.get("success") is not True:
                raise ValueError("Home Assistant event subscription failed")

    def _listen(self, websocket) -> None:
        self._subscribe(websocket)
        self.ready.set()
        self.last_view = ""
        while not self.stop.is_set():
            self.broker.expire(time.time())
            self._publish()
            try:
                message = json.loads(websocket.recv(timeout=0.25))
            except TimeoutError:
                continue
            if message.get("type") == "event" and message.get("id") in (1, 2):
                self._decision(message.get("event", {}))

    def _decision(self, event: dict) -> None:
        if not isinstance(event, dict) or not isinstance(event.get("context"), dict):
            self.broker.log.info("decision_refused")
            return
        if not isinstance(event.get("data"), dict):
            self.broker.log.info("decision_refused")
            return
        approved = self.broker.decide(event)
        if approved:
            self.execute(approved)

    def run(self) -> None:
        url = self.config.url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        while not self.stop.is_set():
            try:
                with connect(
                    url + "/api/websocket",
                    proxy=None,
                    open_timeout=5,
                    close_timeout=2,
                    max_size=RESPONSE_LIMIT,
                ) as websocket:
                    self._listen(websocket)
            except Exception:
                self.broker.log.info("home_assistant_unavailable")
            finally:
                self.ready.clear()
            self.stop.wait(3)

    def close(self) -> None:
        self.stop.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
