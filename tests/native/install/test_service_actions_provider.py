"""Real macOS curl proves service-action TLS and provider behavior."""

import json
import sys
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from slopmeister.session.service_actions import confluence, jira, provider, transport
from tests.support.service_actions import https_server, identity


def _reply(handler, value, status=200):
    body = json.dumps(value).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


@pytest.mark.skipif(sys.platform != "linux", reason="Legacy OpenSSL provider is Linux-only")
@pytest.mark.parametrize("legacy", [False, True])
def test_linux_client_certificates_need_legacy_config_only_for_old_format(monkeypatch, legacy):
    """Bug: RC2-40 certificates fail in the same stdin flow that accepts modern bundles."""
    credentials = identity(legacy=legacy)
    with https_server(
        credentials, lambda handler: _reply(handler, {"authenticated": True})
    ) as server:
        request = transport.CurlRequest(
            server.origin,
            "disposable-pat",
            5,
            pfx=credentials.client_p12,
            password=credentials.password,
            server_ca=server.ca_path,
        )
        assert transport.send(request) == {"authenticated": True}
        assert server.requests[0]["peer"]
        environment = transport._environment
        monkeypatch.setattr(
            transport,
            "_environment",
            lambda request: {k: v for k, v in environment(request).items() if k != "OPENSSL_CONF"},
        )
        if legacy:
            with pytest.raises(ValueError, match="CERTIFICATE_INVALID"):
                transport.send(request)
            assert len(server.requests) == 1
        else:
            assert transport.send(request) == {"authenticated": True}
            assert len(server.requests) == 2


def _client(server, credentials, pat_only, *, password=None, server_ca=True):
    return provider.Client(
        server.origin,
        "disposable-pat",
        time.monotonic() + 30,
        None if pat_only else credentials.client_p12,
        None if pat_only else password or credentials.password,
        server.ca_path if server_ca else None,
    )


def _search(version):
    page = {"id": "1", "type": "page", "status": "current", "version": version}
    return {"start": 0, "results": [page], "_links": {"next": None}}


def _children(kind: str):
    child = {"id": "3", "type": "attachment"}
    if kind == "comment":
        child = {
            "id": "2",
            "type": "comment",
            "body": {"storage": {"value": "Note", "representation": "storage"}},
            "extensions": {"inlineProperties": {}, "resolution": {}},
        }
    return {"start": 0, "size": 1, "totalSize": 1, "results": [child], "_links": {}}


def _page(version):
    return {
        "id": "1",
        "type": "page",
        "status": "current",
        "title": "Runbook",
        "version": version,
        "body": {"storage": {"value": "<p>Body</p>", "representation": "storage"}},
        "space": {"key": "TEST"},
        "ancestors": [],
    }


def _confluence_response(path: str, query: dict, version) -> tuple[dict, int]:
    responses = {
        "/rest/api/user/current": {"type": "known", "username": "reader"},
        "/rest/api/content/search": _search(version),
        "/rest/api/content/1/child/comment": _children("comment"),
        "/rest/api/content/1/child/attachment": _children("attachment"),
    }
    if path == "/rest/api/content/1":
        compact = {"id": "1", "type": "page", "version": version}
        responses[path] = compact if query.get("expand") == ["version"] else _page(version)
    value = responses.get(path)
    return (value, 200) if value else ({"redirect": "https://other.invalid"}, 302)


def _confluence_callback(version):
    def callback(handler):
        parsed = urlsplit(handler.path)
        value, status = _confluence_response(parsed.path, parse_qs(parsed.query), version)
        _reply(handler, value, status)

    return callback


def _tickets():
    return [
        {"key": f"TEST-{number}", "fields": {"summary": f"Ticket {number}"}}
        for number in range(1, 102)
    ]


def _jira_callback(tickets):
    def callback(handler):
        parsed = urlsplit(handler.path)
        if parsed.path == "/rest/api/2/myself":
            _reply(handler, {"name": "reader"})
        elif parsed.path == "/rest/api/2/field":
            _reply(handler, [])
        else:
            query = parse_qs(parsed.query)
            start, size = int(query["startAt"][0]), int(query["maxResults"][0])
            page = tickets[start : start + size]
            _reply(
                handler,
                {"startAt": start, "maxResults": size, "total": len(tickets), "issues": page},
            )

    return callback


def _find(start):
    return {"mode": "find", "start": start, "limit": 100, "order": "key", "assignee": "me"}


@pytest.mark.parametrize("pat_only", [False, True])
def test_provider_does_not_leak_credentials_trust_client_ca_or_return_partial_tickets(pat_only):
    credentials = identity()
    tickets = _tickets()
    with https_server(credentials, _jira_callback(tickets), require_client=not pat_only) as server:
        client = _client(server, credentials, pat_only)
        first, second = (jira.read(client, "reader", _find(start)) for start in (0, 100))
        assert (
            first["pagination"]["next_start"] == 100 and second["pagination"]["has_more"] is False
        )
        assert len(first["results"]) + len(second["results"]) == 101
        assert all(
            request["authorization"] == "Bearer disposable-pat" for request in server.requests
        )
        assert all(bool(request["peer"]) == (not pat_only) for request in server.requests)
        if not pat_only:
            with pytest.raises(ValueError, match="NETWORK_OR_TLS_FAILED"):
                jira.read(
                    _client(server, credentials, pat_only, server_ca=False), "reader", _find(0)
                )
            with pytest.raises(ValueError, match="CERTIFICATE_INVALID"):
                jira.read(
                    _client(server, credentials, pat_only, password="wrong-password"),
                    "reader",
                    _find(0),
                )


@pytest.mark.parametrize("pat_only", [False, True])
def test_confluence_reader_proves_user_latest_edit_and_never_follows_other_origins(pat_only):
    credentials = identity()
    version = {
        "number": 2,
        "by": {"username": "reader"},
        "when": "2026-09-15T10:00:00Z",
    }

    with https_server(
        credentials, _confluence_callback(version), require_client=not pat_only
    ) as server:
        client = _client(server, credentials, pat_only)
        result = confluence.read(client, "reader", {"mode": "latest-edited"})
        assert result["page"]["latest_user_edit"]["author"] == "reader"
        assert result["page"]["comments"][0]["id"] == "2"
        assert result["page"]["attachments"][0]["id"] == "3"
        assert all(
            urlsplit(request["path"]).path.startswith("/rest/api/") for request in server.requests
        )


def test_curl_config_quoting_blocks_injected_url_with_real_curl():
    credentials = identity()

    with https_server(credentials, lambda handler: _reply(handler, {}), False) as server:
        injected_password = credentials.password + '"\nurl = "' + server.origin + "/injected"
        request = transport.CurlRequest(
            "https://127.0.0.1:9",
            "disposable-pat",
            5,
            pfx=credentials.client_p12,
            password=injected_password,
            server_ca=server.ca_path,
        )
        response = transport._run(request)

        assert response.status != 0
        assert server.requests == []


@pytest.mark.parametrize("pat_only", [False, True])
def test_backlog_query_reaches_real_curl_as_get_with_link_status(pat_only):
    """Bug: the new read changes the method, drops its fixed query, or loses dependency evidence."""
    credentials = identity()
    status = {"name": "Open", "statusCategory": {"id": 2}}
    link = {
        "type": {"inward": "is blocked by", "outward": "blocks"},
        "inwardIssue": {"key": "TEST-9", "fields": {"status": status}},
    }
    tickets = [
        {
            "key": "TEST-1",
            "fields": {"summary": "Dependent", "status": status, "issuelinks": [link]},
        }
    ]
    query = 'project = "TEST" AND statusCategory != Done ORDER BY key ASC'
    with https_server(credentials, _jira_callback(tickets), require_client=not pat_only) as server:
        client = _client(server, credentials, pat_only)
        client.backlog_jql = query
        result = jira.read(client, "reader", {"mode": "backlog", "start": 0, "limit": 25})
        assert result["results"][0]["issuelinks"] == [link]
        assert result["results"][0]["status_category"]["id"] == 2
        assert len(server.requests) == 2
        assert parse_qs(urlsplit(server.requests[-1]["path"]).query)["jql"] == [query]
