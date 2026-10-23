"""Approval question reads are bounded before notifications and acknowledge acceptance."""

import asyncio

import pytest

from host.tests.approval_support import framework as framework
from host.tests.approval_support import request
from host.tests.approval_support import route as route
from host.tests.approval_support import schema as schema


@pytest.mark.parametrize("body", [b"{", b"[]", b"x" * 3801])
def test_malformed_or_oversized_request_is_refused_before_notification(route, body):
    integration, hass, _ = route
    given = request(raw=body)
    assert asyncio.run(integration._ask(hass, None, given)).status == 400
    hass.services.async_call.assert_not_called()


def test_acceptance_receipt_and_exact_body_limit(route):
    integration, hass, _ = route
    body = request().read.return_value
    given = request(raw=body + b" " * (integration.BODY_BYTES - len(body)))
    answer = asyncio.run(integration._ask(hass, None, given))
    assert answer.status == 200 and answer.data == {"accepted": True}
    assert hass.services.async_call.await_count == 2


def test_declared_oversize_is_refused_without_reading(route):
    integration, hass, _ = route
    given = request(raw=b"x" * (integration.BODY_BYTES + 1))
    given.read.side_effect = AssertionError("unbounded request read")
    answer = asyncio.run(integration._ask(hass, None, given))
    assert answer.status == 400
    given.content.read.assert_not_called()
    hass.services.async_call.assert_not_called()


def test_unfinished_chunked_oversize_stops_at_the_first_excess_byte(route):
    integration, hass, _ = route
    given = request()
    given.content_length = None
    given.read.side_effect = AssertionError("unbounded request read")
    given.content.read.side_effect = [
        b"x" * integration.BODY_BYTES,
        b"x",
        AssertionError("read beyond limit"),
    ]
    answer = asyncio.run(integration._ask(hass, None, given))
    assert answer.status == 400
    assert [c.args for c in given.content.read.await_args_list] == [
        (integration.BODY_BYTES + 1,),
        (1,),
    ]
    hass.services.async_call.assert_not_called()
