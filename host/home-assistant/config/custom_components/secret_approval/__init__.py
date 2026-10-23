"""Ask the operator one approval question per request and serve the decisions to the requester."""

import asyncio
from dataclasses import dataclass, field
import functools
import hmac
import logging
import re
import secrets
import time

from aiohttp import web
from homeassistant.components import webhook, websocket_api
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .config import CONFIG_SCHEMA as CONFIG_SCHEMA
from .config import DECIDE_COMMAND, DOMAIN, OPEN_COMMAND, protect_logs
from .question import BODY_BYTES as BODY_BYTES
from .question import read as read_question

LOGGER = logging.getLogger(__name__)
ACTION = re.compile(r"SECRET_APPROVAL_(APPROVE|DENY)_([0-9a-f]{32})_([0-9a-f]{32})")
TAG = "secret-approval-"
# A tap on the notification opens the page of ../../www/secret-approval.js on this question.
PAGE = "/secret-approval?request="
OPEN_QUESTIONS = 16
PRESS_SECONDS = 600
# A decision made in the last second stays readable for five more minutes.
KEEP_SECONDS = 900
# An address part and the credential are the only protection of their webhook.
SECRET_LENGTH = 32
# The requester waits five seconds. One slow device must not hold the other back.
SEND_SECONDS = 4


@dataclass
class Question:
    """One sent question. The token binds its two actions to this sending of the ID."""

    token: str
    title: str
    message: str
    asked: float = field(default_factory=time.monotonic)
    decision: str | None = None


@dataclass
class Route:
    credential: str
    operator: str
    devices: list[str]
    questions: dict[str, Question] = field(default_factory=dict)


def _retained(route):
    """Drop every question past the retention time and return the rest."""
    limit = time.monotonic() - KEEP_SECONDS
    for identifier in [key for key, question in route.questions.items() if question.asked < limit]:
        del route.questions[identifier]
    return route.questions


def _waiting(route):
    """The retained questions that the operator can still decide."""
    limit = time.monotonic() - PRESS_SECONDS
    return {
        key: question
        for key, question in _retained(route).items()
        if question.decision is None and question.asked > limit
    }


async def _send(hass, device, payload):
    try:
        async with asyncio.timeout(SEND_SECONDS):
            await hass.services.async_call("notify", device, payload, blocking=True)
    # The error text can name a companion registration, so it stays out of the log.
    except HomeAssistantError, TimeoutError:
        LOGGER.warning("%s took no notification", device)
        return False
    return True


async def _notify(hass, route, payload):
    """Send one payload to every device at once and return how many took it."""
    return sum(await asyncio.gather(*(_send(hass, device, payload) for device in route.devices)))


def _notification(data, token):
    suffix = f"{data['id']}_{token}"
    actions = [
        {"action": "SECRET_APPROVAL_APPROVE_" + suffix, "title": "Approve"},
        {"action": "SECRET_APPROVAL_DENY_" + suffix, "title": "Deny", "destructive": True},
    ]
    extra = {"tag": TAG + data["id"], "url": PAGE + data["id"], "actions": actions}
    return {"title": data["title"], "message": data["message"], "data": extra}


async def _ask(hass, _webhook_id, request):
    route = hass.data[DOMAIN]
    data = await read_question(request)
    if data is None:
        return web.Response(status=400)
    questions = _retained(route)
    # A retained ID keeps its first text, so a press never decides a text the operator did not see.
    if data["id"] in questions:
        return web.Response(status=409)
    if len(_waiting(route)) >= OPEN_QUESTIONS:
        return web.Response(status=429)
    question = questions[data["id"]] = Question(
        secrets.token_hex(16), data["title"], data["message"]
    )
    accepted = await _notify(hass, route, _notification(data, question.token))
    if not accepted:
        del questions[data["id"]]
    return web.json_response({"accepted": True}) if accepted else web.Response(status=502)


async def _answer(hass, _webhook_id, request):
    route = hass.data[DOMAIN]
    given = request.headers.get("Authorization", "").encode()
    if not hmac.compare_digest(given, b"Bearer " + route.credential.encode()):
        return web.Response(status=401)
    decided = {
        key: question.decision for key, question in _retained(route).items() if question.decision
    }
    return web.json_response({"decisions": decided})


def _decide(hass, shown, decision):
    """Record the first decision for (ID, token). Return whether it counted."""
    identifier, token = shown
    route = hass.data[DOMAIN]
    question = _waiting(route).get(identifier)
    # A token names one sending. A stale notification or page cannot decide a later text.
    if question is None or question.token != token:
        return False
    question.decision = decision
    clear = {"message": "clear_notification", "data": {"tag": TAG + identifier}}
    hass.async_create_task(_notify(hass, route, clear))
    return True


def _listener(hass, route):
    @callback
    def press(event):
        match = ACTION.fullmatch(str(event.data.get("action")))
        # The companion app fires the event as the user of its registration.
        if match is None or event.context.user_id != route.operator:
            return
        verb, identifier, token = match.groups()
        _decide(hass, (identifier, token), "approved" if verb == "APPROVE" else "denied")

    return press


def _operator_only(command):
    """Answer a page command only on a connection of the operator's own Home Assistant user."""

    @functools.wraps(command)
    def guarded(hass, connection, msg):
        if connection.user.id != hass.data[DOMAIN].operator:
            connection.send_error(
                msg["id"],
                websocket_api.ERR_UNAUTHORIZED,
                "Only the operator decides secret approvals",
            )
            return
        command(hass, connection, msg)

    return guarded


@websocket_api.websocket_command(OPEN_COMMAND)
@_operator_only
@callback
def _page_open(hass, connection, msg):
    waiting = _waiting(hass.data[DOMAIN]).items()
    rows = [
        {"id": key, "token": question.token, "title": question.title, "message": question.message}
        for key, question in waiting
    ]
    connection.send_result(msg["id"], rows)


@websocket_api.websocket_command(DECIDE_COMMAND)
@_operator_only
@callback
def _page_decide(hass, connection, msg):
    if _decide(hass, (msg["request"], msg["token"]), msg["decision"]):
        connection.send_result(msg["id"])
    else:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "The request is decided or expired"
        )


async def async_setup(hass, config):
    values = config[DOMAIN]
    ask_id, answer_id = (
        values[key].rstrip("/").rpartition("/")[2] for key in ("ask_url", "answer_url")
    )
    if min(map(len, (ask_id, answer_id, values["credential"], values["operator"]))) < SECRET_LENGTH:
        LOGGER.error(
            "An address part, the credential or the operator is shorter than %d characters",
            SECRET_LENGTH,
        )
        return False
    route = hass.data[DOMAIN] = Route(values["credential"], values["operator"], values["devices"])
    protect_logs(ask_id, answer_id, route)
    # A tailnet address is not local to Home Assistant. The proxy bounds the admitted sources.
    for name, identifier, handler, method in (
        ("Secret approval question", ask_id, _ask, "POST"),
        ("Secret approval answer", answer_id, _answer, "GET"),
    ):
        webhook.async_register(
            hass, DOMAIN, name, identifier, handler, local_only=False, allowed_methods=[method]
        )
    hass.bus.async_listen("mobile_app_notification_action", _listener(hass, route))
    websocket_api.async_register_command(hass, _page_open)
    websocket_api.async_register_command(hass, _page_decide)
    return True
