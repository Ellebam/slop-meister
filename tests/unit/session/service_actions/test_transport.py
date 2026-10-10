"""Curl transport keeps all provider credentials out of argv."""

from pathlib import Path
import sys

import pytest

from slopmeister.session.service_actions import transport


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("pfx", [None, b"p12"])
def test_legacy_provider_config_is_fixed_and_only_reaches_linux_certificate_curl(
    monkeypatch, platform, pfx
):
    """Bug: old certificates fail, or parent OpenSSL settings alter other requests."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("OPENSSL_CONF", "/untrusted/config")
    monkeypatch.setenv("OPENSSL_MODULES", "/untrusted/modules")
    request = transport.CurlRequest("https://example.invalid", "pat", 10, pfx=pfx)
    expected = {"PATH": "/usr/bin:/bin", "LANG": "C"}
    if platform == "linux" and pfx is not None:
        expected["OPENSSL_CONF"] = str(Path(transport.__file__).with_name("openssl.cnf"))
    assert transport._environment(request) == expected


def test_certificate_and_password_reach_curl_only_through_pipes():
    request = transport.CurlRequest(
        "https://example.invalid/rest",
        "disposable-pat",
        10,
        pfx=b"disposable-p12",
        password='quote" newline\n slash\\',
    )
    command = transport._command(request, 9)
    config = transport._config(request)
    joined = " ".join(command)
    assert "disposable-pat" not in joined
    assert "disposable-password" not in joined
    assert "disposable-p12" not in joined
    assert "/dev/stdin" in config.decode()
    assert "disposable-pat" in config.decode()
    assert 'quote\\" newline\\n slash\\\\' in config.decode()


def test_redirect_proxy_and_client_ca_cannot_change_server_trust(monkeypatch):
    request = transport.CurlRequest("https://example.invalid", "pat", 10, server_ca=None)
    command = transport._command(request, 7)
    assert command[0:2] == ["/usr/bin/curl", "--disable"]
    assert "--location" not in command
    assert command[command.index("--noproxy") + 1] == "*"
    assert "--cacert" not in command
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy.invalid")
    captured = {}

    class Process:
        returncode = 0

        def __init__(self, config_fd):
            self.config_fd = transport.os.dup(config_fd)

        def communicate(self, _payload, timeout):
            captured["config"] = transport.os.read(self.config_fd, 4096)
            transport.os.close(self.config_fd)
            return b"{}\nSLOPMEISTER_HTTP_STATUS:200", b""

    def popen(argv, **kwargs):
        captured.update(argv=argv, kwargs=kwargs)
        return Process(kwargs["pass_fds"][0])

    monkeypatch.setattr(transport.subprocess, "Popen", popen)
    assert transport.send(request) == {}
    assert "HTTPS_PROXY" not in captured["kwargs"]["env"]


@pytest.mark.parametrize(
    "platform,pfx,arguments,backend",
    [
        ("linux", None, ["--cacert", "/pin.pem", "--capath", "/dev/null"], None),
        ("linux", b"p12", ["--cacert", "/pin.pem", "--capath", "/dev/null"], None),
        ("darwin", None, ["--cacert", "/pin.pem"], "secure-transport"),
        ("darwin", b"p12", ["--cacert", "/pin.pem"], None),
    ],
)
def test_pinned_server_certificate_replaces_system_trust(
    monkeypatch, platform, pfx, arguments, backend
):
    """Bug: a pinned server certificate still accepts every certificate the system trusts."""
    monkeypatch.setattr(sys, "platform", platform)
    request = transport.CurlRequest(
        "https://example.invalid", "pat", 10, pfx=pfx, server_ca=Path("/pin.pem")
    )
    command = transport._command(request, 7)
    assert command[-len(arguments) - 1 : -1] == arguments
    assert transport._environment(request).get("CURL_SSL_BACKEND") == backend
    unpinned = transport.CurlRequest("https://example.invalid", "pat", 10)
    assert "--capath" not in transport._command(unpinned, 7)
    assert transport._environment(unpinned) == {"PATH": "/usr/bin:/bin", "LANG": "C"}


def test_write_body_reaches_curl_only_through_the_config_pipe():
    body = b'{"fields":{"summary":"SENTINEL_BODY \\"quoted\\""}}'
    request = transport.CurlRequest(
        "https://example.invalid/rest", "pat", 10, method="PUT", body=body
    )
    command = transport._command(request, 9)
    config = transport._config(request).decode()
    assert command[command.index("--request") + 1] == "PUT"
    assert "SENTINEL_BODY" not in " ".join(command)
    assert 'header = "Content-Type: application/json"' in config
    assert 'data-binary = "{\\"fields\\":{\\"summary\\":\\"SENTINEL_BODY \\\\\\"quoted' in config


@pytest.mark.parametrize(
    ("method", "status", "body", "expected"),
    [
        ("GET", 200, b"{}", {}),
        ("POST", 201, b'{"id":"1"}', {"id": "1"}),
        ("POST", 201, b"", None),
        ("PUT", 204, b"", None),
        ("PUT", 200, b'{"version":{"number":2}}', {"version": {"number": 2}}),
    ],
)
def test_writes_accept_created_and_empty_success(method, status, body, expected):
    request = transport.CurlRequest("https://example.invalid", "pat", 10, method=method, body=b"{}")
    output = body + transport.MARKER + str(status).encode()
    assert transport._result(transport.CurlResponse(0, output, b""), request) == expected


@pytest.mark.parametrize(("method", "status"), [("GET", 201), ("GET", 204), ("POST", 302)])
def test_reads_stay_200_only_and_writes_refuse_other_codes(method, status):
    request = transport.CurlRequest("https://example.invalid", "pat", 10, method=method)
    output = b"" + transport.MARKER + str(status).encode()
    with pytest.raises(ValueError, match=f"HTTP_{status}"):
        transport._result(transport.CurlResponse(0, output, b""), request)


def test_a_body_curl_would_read_as_a_file_is_refused():
    request = transport.CurlRequest(
        "https://example.invalid", "pat", 10, method="POST", body=b"@/etc/x"
    )
    with pytest.raises(ValueError, match="REQUEST_INVALID"):
        transport._config(request)
