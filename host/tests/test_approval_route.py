"""Drive real route handlers with synthetic requests and events, without a login or server."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from host.tests.approval_support import (
    CREDENTIAL,
    IDENTIFIER,
    OPERATOR,
    OTHER,
    connection,
    request,
)
from host.tests.approval_support import (
    framework as framework,
)
from host.tests.approval_support import (
    route as route,
)
from host.tests.approval_support import (
    schema as schema,
)


def test_question_is_sent_once_and_first_matching_operator_press_wins(route):
    integration, hass, state = route

    async def drive():
        assert (await integration._ask(hass, None, request())).status == 200
        assert hass.services.async_call.await_count == 2
        sent = hass.services.async_call.await_args_list[0].args[2]
        assert sent["data"]["url"] == "/secret-approval?request=" + IDENTIFIER
        assert (await integration._ask(hass, None, request(message="Command: other"))).status == 409
        assert state.questions[IDENTIFIER].message == "Command: true"
        listener = integration._listener(hass, state)
        approve, deny = (action["action"] for action in sent["data"]["actions"])
        for user, action in [
            (OTHER, approve),
            (None, approve),
            (OPERATOR, approve[:-32] + "9" * 32),
        ]:
            listener(
                SimpleNamespace(data={"action": action}, context=SimpleNamespace(user_id=user))
            )
        assert state.questions[IDENTIFIER].decision is None
        for action in (deny, approve):
            listener(
                SimpleNamespace(data={"action": action}, context=SimpleNamespace(user_id=OPERATOR))
            )
        assert state.questions[IDENTIFIER].decision == "denied"
        await asyncio.sleep(0)

    asyncio.run(drive())


def test_expired_and_reused_questions_refuse_old_actions(route):
    integration, hass, state = route

    async def drive():
        assert (await integration._ask(hass, None, request())).status == 200
        token = state.questions[IDENTIFIER].token
        state.questions[IDENTIFIER].asked -= integration.PRESS_SECONDS
        assert not integration._decide(hass, (IDENTIFIER, token), "approved")
        state.questions[IDENTIFIER].asked -= integration.KEEP_SECONDS
        assert (await integration._ask(hass, None, request(message="Command: other"))).status == 200
        assert not integration._decide(hass, (IDENTIFIER, token), "approved")
        assert integration._decide(
            hass, (IDENTIFIER, state.questions[IDENTIFIER].token), "approved"
        )
        await asyncio.sleep(0)

    asyncio.run(drive())


@pytest.mark.parametrize("authorization", ["", "Bearer wrong", CREDENTIAL])
def test_answer_requires_exact_bearer_credential(route, authorization):
    integration, hass, _ = route
    given = SimpleNamespace(headers={"Authorization": authorization})
    assert asyncio.run(integration._answer(hass, None, given)).status == 401


def test_answer_contains_only_decisions_and_never_question_text_or_action_tokens(route):
    integration, hass, state = route
    state.questions[IDENTIFIER] = integration.Question(
        "private-action", "title", "question text", decision="denied"
    )
    given = SimpleNamespace(headers={"Authorization": "Bearer " + CREDENTIAL})
    answer = asyncio.run(integration._answer(hass, None, given))
    assert answer.data == {"decisions": {IDENTIFIER: "denied"}}


@pytest.mark.parametrize("body", [b"{", b"[]", b"x" * 3801])
def test_malformed_or_oversized_request_is_refused_before_notification(route, body):
    integration, hass, _ = route
    given = request()
    given.read.return_value = body
    assert asyncio.run(integration._ask(hass, None, given)).status == 400
    hass.services.async_call.assert_not_called()


@pytest.mark.parametrize(
    "identifier,message",
    [("A" * 32, "m m"), ("a" * 31, "m m"), (IDENTIFIER, "request_location_update")],
)
def test_invalid_id_or_device_command_is_refused(route, identifier, message):
    integration, hass, _ = route
    assert asyncio.run(integration._ask(hass, None, request(identifier, message))).status == 400
    hass.services.async_call.assert_not_called()


def test_open_question_limit_and_notification_failure(route):
    integration, hass, state = route

    async def drive():
        statuses = [
            (await integration._ask(hass, None, request(f"{number:032x}"))).status
            for number in range(17)
        ]
        assert statuses == [200] * 16 + [429]
        state.questions.clear()
        hass.services.async_call.side_effect = RuntimeError("synthetic registration detail")
        assert (await integration._ask(hass, None, request())).status == 502
        assert not state.questions

    asyncio.run(drive())


def test_page_is_operator_only_and_decides_the_displayed_token_once(route):
    integration, hass, state = route

    async def drive():
        assert (await integration._ask(hass, None, request())).status == 200
        token = state.questions[IDENTIFIER].token
        decide = {"id": 1, "request": IDENTIFIER, "token": token, "decision": "denied"}
        other, operator = connection(OTHER), connection()
        integration._page_open(hass, other, {"id": 1})
        integration._page_decide(hass, other, decide)
        assert len(other.errors) == 2 and not other.results
        integration._page_open(hass, operator, {"id": 1})
        assert operator.results[0][1][0]["token"] == token
        integration._page_decide(hass, operator, decide | {"token": "stale"})
        integration._page_decide(hass, operator, decide)
        integration._page_decide(hass, operator, decide | {"decision": "approved"})
        assert len(operator.errors) == 2
        assert state.questions[IDENTIFIER].decision == "denied"
        await asyncio.sleep(0)

    asyncio.run(drive())


def settings():
    return {
        "ask_url": "https://home.example.invalid/api/webhook/" + "1" * 32,
        "answer_url": "https://home.example.invalid/api/webhook/" + "2" * 32,
        "credential": CREDENTIAL,
        "operator": OPERATOR,
        "devices": ["mobile_app_phone"],
    }


@pytest.mark.parametrize("key", ["ask_url", "answer_url", "credential", "operator"])
def test_weak_route_settings_refuse_registration(route, monkeypatch, key):
    integration, hass, _ = route
    register = Mock()
    monkeypatch.setattr(integration.webhook, "async_register", register)
    assert not asyncio.run(
        integration.async_setup(
            hass,
            {
                integration.DOMAIN: settings() | {key: "short"},
            },
        )
    )
    register.assert_not_called()


def test_setup_exposes_only_the_two_webhook_methods_and_masks_route_logs(route, monkeypatch):
    integration, hass, _ = route
    register = Mock()
    monkeypatch.setattr(integration.webhook, "async_register", register)
    hass.bus = SimpleNamespace(async_listen=Mock())
    hook_log = logging.getLogger("homeassistant.components.webhook")
    page_log = logging.getLogger("homeassistant.components.websocket_api.http.connection")
    for logger in (hook_log, page_log):
        monkeypatch.setattr(logger, "filters", [])
    assert asyncio.run(integration.async_setup(hass, {integration.DOMAIN: settings()}))
    assert [call.kwargs for call in register.call_args_list] == [
        {"local_only": False, "allowed_methods": ["POST"]},
        {"local_only": False, "allowed_methods": ["GET"]},
    ]
    assert [call.args[4] for call in register.call_args_list] == [
        integration._ask,
        integration._answer,
    ]
    state = hass.data[integration.DOMAIN]
    state.questions[IDENTIFIER] = integration.Question("action-token", "title", "question text")
    assert not hook_log.filter(logging.makeLogRecord({"msg": "webhook " + "1" * 32}))
    assert not hook_log.filter(logging.makeLogRecord({"msg": "webhook " + "2" * 32}))
    assert not page_log.filter(logging.makeLogRecord({"msg": "question text action-token"}))
    assert hook_log.filter(logging.makeLogRecord({"msg": "ordinary log"}))


def test_slow_device_cannot_hold_back_another_and_registration_errors_are_not_logged(
    route, monkeypatch, caplog
):
    integration, hass, state = route
    monkeypatch.setattr(integration, "SEND_SECONDS", 0.01)

    async def notify(domain, device, payload, **kwargs):
        if device == state.devices[1]:
            await asyncio.sleep(1)

    async def drive():
        hass.services.async_call.side_effect = notify
        assert (await asyncio.wait_for(integration._ask(hass, None, request()), 0.5)).status == 200
        hass.services.async_call.side_effect = RuntimeError("synthetic registration detail")
        assert (await integration._ask(hass, None, request("b" * 32))).status == 502
        assert "synthetic registration detail" not in caplog.text

    asyncio.run(drive())
