"""Own approval transitions and durable outcomes under one lock, resolved values in memory only."""

import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import secrets
import threading
import time

from .config import line

DECISION_SECONDS = 600
PENDING_LIMIT = 16
RECORD_LIMIT = 1024
REFERENCE_LIMIT = 32
ARGV_LIMIT = 64
STATES = {"pending", "approved", "delivered", "denied", "timed out", "failed", "interrupted"}
ACTIVE = {"pending", "approved"}
FIELDS = {"env", "argv", "cwd", "reason", "session", "host"}
VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
# Vault, item, section and field names may hold spaces, never separators or control characters.
SEGMENT = r"[^/?\x00-\x1f]+"
REFERENCE = re.compile(rf"op://{SEGMENT}/{SEGMENT}(?:/{SEGMENT}){{1,2}}(?:\?[\w=.,-]+)?\Z")


def references(data: object) -> dict[str, str]:
    if not isinstance(data, dict) or not 1 <= len(data) <= REFERENCE_LIMIT:
        raise ValueError(f"a request names one to {REFERENCE_LIMIT} references")
    for key, value in data.items():
        if not isinstance(key, str) or not VARIABLE.fullmatch(key):
            raise ValueError("invalid environment variable name")
        if not isinstance(value, str) or not REFERENCE.fullmatch(value):
            raise ValueError("a reference must be a literal op://vault/item/field")
    return dict(data)


def argument(value: object) -> str:
    """One shell argument: text up to the limit, newlines and tabs allowed for inline scripts."""
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("invalid command argument")
    if any(not c.isprintable() and c not in "\n\t" for c in value):
        raise ValueError("invalid command argument")
    return value


def command(data: object) -> list[str]:
    if not isinstance(data, list) or not 1 <= len(data) <= ARGV_LIMIT:
        raise ValueError(f"a command has one to {ARGV_LIMIT} arguments")
    return [argument(item) for item in data]


def request(data: dict) -> dict:
    """The validated request fields, the only caller text that enters a record."""
    if set(data) != FIELDS:
        raise ValueError("request accepts env, argv, cwd, reason, session and host only")
    cwd = line(data["cwd"], 4096)
    if not cwd.startswith("/"):
        raise ValueError("the working directory must be absolute")
    return {
        "env": references(data["env"]),
        "argv": command(data["argv"]),
        "cwd": cwd,
        "reason": line(data["reason"], 512, empty=True),
        "session": line(data["session"], 128),
        "host": line(data["host"], 64),
    }


class Broker:
    def __init__(self, root: Path, operator: str):
        self.root, self.operator = root, operator
        self.lock = threading.RLock()
        self.values: dict[str, dict[str, str]] = {}
        self.records: dict[str, dict] = {}
        self.log = logging.Logger("secret-ask", logging.INFO)
        handler = RotatingFileHandler(root / "audit.log", maxBytes=1048576, backupCount=3)
        os.chmod(root / "audit.log", 0o600)
        self.log.addHandler(handler)
        self._restore()

    def _restore(self) -> None:
        path = self.root / "requests.json"
        if path.exists():
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("request history exceeds limit")
            self.records = json.loads(path.read_text())
            for row in self.records.values():
                if row["state"] in ACTIVE:
                    row["state"] = "interrupted"
                    row["retract"] = True
                row.pop("approve", None)
                row.pop("deny", None)
        self._save()

    def _save(self) -> None:
        path = self.root / "requests.json.new"
        # Decisions die with the process, so the live action tokens never touch the disk.
        saved = {
            key: {k: v for k, v in row.items() if k not in ("approve", "deny")}
            for key, row in self.records.items()
        }
        with open(path, "w", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            json.dump(saved, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(path, self.root / "requests.json")

    def _capacity(self) -> None:
        if len([r for r in self.records.values() if r["state"] in ACTIVE]) >= PENDING_LIMIT:
            raise ValueError("broker is busy")
        if len(self.records) >= RECORD_LIMIT:
            key = next(k for k, r in self.records.items() if r["state"] not in ACTIVE)
            del self.records[key]

    def _attached(self, uid: int, fields: dict) -> dict | None:
        """The caller's active request with the same references, command, directory and origin."""
        same = ("env", "argv", "cwd", "host", "session")
        return next(
            (
                r
                for r in self.records.values()
                if r["uid"] == uid
                and r["state"] in ACTIVE
                and all(r[key] == fields[key] for key in same)
            ),
            None,
        )

    def submit(self, uid: int, data: dict) -> dict:
        fields = request(data)
        with self.lock:
            existing = self._attached(uid, fields)
            if existing:
                return {"id": existing["id"], "state": existing["state"]}
            self._capacity()
            row = dict(
                fields,
                id=secrets.token_hex(16),
                uid=uid,
                state="pending",
                expires=time.time() + DECISION_SECONDS,
                approve="secret_ask_" + secrets.token_hex(32),
                deny="secret_ask_" + secrets.token_hex(32),
            )
            self.records[row["id"]] = row
            self._save()
            self.log.info(
                json.dumps({k: v for k, v in row.items() if k not in {"approve", "deny"}})
            )
            return {"id": row["id"], "state": "pending"}

    def collect(self, identifier: str, uid: int) -> dict:
        """The request's state, with its values exactly once when they are ready."""
        with self.lock:
            row = self.records.get(identifier)
            if row is None or row["uid"] != uid:
                raise ValueError("request is unavailable")
            if row["state"] == "approved" and identifier in self.values:
                values = self.values.pop(identifier)
                self.finish(identifier, "delivered")
                return {"id": identifier, "state": "delivered", "values": values}
            return {"id": identifier, "state": row["state"]}

    def pending(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.records.values() if r["state"] == "pending"]

    def decide(self, event: dict) -> dict | None:
        """The approved request to resolve, or None when the event decides nothing."""
        with self.lock:
            self.expire(time.time())
            action = event.get("data", {}).get("action")
            user = event.get("context", {}).get("user_id")
            row = next(
                (
                    r
                    for r in self.records.values()
                    if isinstance(action, str) and action in (r.get("approve"), r.get("deny"))
                ),
                None,
            )
            if user != self.operator or row is None or row["state"] != "pending":
                self.log.info("decision_refused")
                return None
            if action != row["approve"]:
                self.finish(row["id"], "denied")
                return None
            row["expires"] = time.time() + DECISION_SECONDS
            self.finish(row["id"], "approved")
            return {"id": row["id"], "env": dict(row["env"])}

    def restore(self, identifier: str, values: dict[str, str]) -> None:
        """A delivery whose reply failed to send never happened, the values wait again."""
        with self.lock:
            if self.records.get(identifier, {}).get("state") == "delivered":
                self.records[identifier]["state"] = "approved"
                self.values[identifier] = values
                self._save()
                self.log.info("%s delivery_failed", identifier)

    def ready(self, identifier: str, values: dict[str, str]) -> None:
        """Hold resolved values for collection while the request is still approved."""
        with self.lock:
            if self.records.get(identifier, {}).get("state") == "approved":
                self.values[identifier] = values

    def expire(self, now: float) -> None:
        with self.lock:
            for row in self.records.values():
                if row["state"] in ACTIVE and row["expires"] <= now:
                    self.finish(row["id"], "timed out")

    def finish(self, identifier: str, state: str) -> None:
        if state not in STATES:
            raise ValueError("invalid terminal state")
        with self.lock:
            self.records[identifier]["state"] = state
            self.records[identifier]["retract"] = state != "pending"
            self._save()
            self.log.info("%s %s", identifier, state)
            if state != "approved":
                self.values.pop(identifier, None)

    def retracted(self, identifier: str) -> None:
        with self.lock:
            self.records[identifier]["retract"] = False
            self._save()

    def close(self) -> None:
        self.values.clear()
        for handler in self.log.handlers:
            handler.close()
