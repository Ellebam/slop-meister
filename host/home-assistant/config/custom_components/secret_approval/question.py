"""Bound and validate one approval question before it reaches a notification service."""

import json
import re

BODY_BYTES = 3800
QUESTION_ID = re.compile(r"[0-9a-f]{32}")


def _parse(body):
    if len(body) > BODY_BYTES:
        return None
    try:
        data = json.loads(body)
    except ValueError, RecursionError:
        return None
    if not isinstance(data, dict) or not all(
        isinstance(data.get(key), str) for key in ("id", "title", "message")
    ):
        return None
    # Companion apps run a one-word message as a device command instead of showing it.
    return data if QUESTION_ID.fullmatch(data["id"]) and len(data["message"].split()) > 1 else None


async def read(request):
    if request.content_length is not None and request.content_length > BODY_BYTES:
        return None
    body = bytearray()
    while len(body) <= BODY_BYTES:
        chunk = await request.content.read(BODY_BYTES + 1 - len(body))
        if not chunk:
            break
        body.extend(chunk)
    return _parse(body)
