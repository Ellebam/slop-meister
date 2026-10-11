"""Synthetic HA interfaces and requests shared by the approval handler tests."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

HOST = Path(__file__).resolve().parents[1]
OPERATOR = "0" * 32
OTHER = "f" * 32
IDENTIFIER = "a" * 32
CREDENTIAL = "c" * 64


def module(monkeypatch, name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    monkeypatch.setitem(sys.modules, name, result)
    return result


def identity(value):
    return value


@pytest.fixture
def schema(monkeypatch):
    module(
        monkeypatch,
        "voluptuous",
        Schema=lambda value, **kwargs: value,
        Required=identity,
        All=lambda *values: values,
        Length=lambda **kwargs: None,
        In=identity,
        ALLOW_EXTRA=True,
    )


@pytest.fixture
def framework(monkeypatch, schema):
    """Only the external HA interfaces are stand-ins. The route module runs unchanged."""
    web = SimpleNamespace(
        Response=lambda status: SimpleNamespace(status=status),
        json_response=lambda data: SimpleNamespace(status=200, data=data),
    )
    module(monkeypatch, "aiohttp", web=web)
    module(monkeypatch, "homeassistant")
    websocket = SimpleNamespace(
        websocket_command=lambda schema: identity,
        ERR_UNAUTHORIZED="unauthorized",
        ERR_NOT_FOUND="not_found",
        async_register_command=lambda *args: None,
    )
    webhook = SimpleNamespace(async_register=lambda *args, **kwargs: None)
    module(monkeypatch, "homeassistant.components", webhook=webhook, websocket_api=websocket)
    module(monkeypatch, "homeassistant.core", callback=identity)
    module(monkeypatch, "homeassistant.exceptions", HomeAssistantError=RuntimeError)
    module(
        monkeypatch,
        "homeassistant.helpers",
        config_validation=SimpleNamespace(string=str, ensure_list=identity, slug=str),
    )


@pytest.fixture
def route(monkeypatch, framework):
    path = HOST / "home-assistant/config/custom_components/secret_approval/__init__.py"
    spec = importlib.util.spec_from_file_location("approval_under_test", path)
    integration = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, integration)
    spec.loader.exec_module(integration)
    state = integration.Route(CREDENTIAL, OPERATOR, ["mobile_app_phone", "mobile_app_tablet"])
    hass = SimpleNamespace(
        data={integration.DOMAIN: state},
        services=SimpleNamespace(async_call=AsyncMock()),
        async_create_task=asyncio.create_task,
    )
    try:
        yield integration, hass, state
    finally:
        sys.modules.pop(spec.name + ".config", None)


def request(identifier=IDENTIFIER, message="Command: true", **values):
    body = json.dumps({"id": identifier, "title": "Secret approval: demo", "message": message})
    return SimpleNamespace(read=AsyncMock(return_value=body.encode()), headers={}, **values)


def connection(user=OPERATOR):
    results, errors = [], []
    return SimpleNamespace(
        user=SimpleNamespace(id=user),
        results=results,
        errors=errors,
        send_result=lambda *args: results.append(args),
        send_error=lambda *args: errors.append(args),
    )
