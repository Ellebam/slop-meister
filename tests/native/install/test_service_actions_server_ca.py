"""Installed curl must enforce the selected server CA without system-store fallback."""

import sys

import pytest

from slopmeister.session.service_actions import transport
from tests.support.service_actions import https_server, identity


def test_real_curl_refuses_a_server_outside_the_pinned_ca(tmp_path):
    """Bug: a request succeeds against a server whose CA differs from the selected pin."""
    credentials = identity()
    wrong_pin = tmp_path / "other-ca.pem"
    wrong_pin.write_bytes(identity("Other Test CA").ca)

    def reply(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(b'{"pinned":true}')))
        handler.end_headers()
        handler.wfile.write(b'{"pinned":true}')

    with https_server(credentials, reply, require_client=False) as server:
        request = transport.CurlRequest(
            server.origin, "disposable-pat", 5, server_ca=server.ca_path
        )
        assert transport.send(request) == {"pinned": True}
        server.requests.clear()
        request = transport.CurlRequest(server.origin, "disposable-pat", 5, server_ca=wrong_pin)
        with pytest.raises(ValueError, match="^NETWORK_OR_TLS_FAILED$"):
            transport.send(request)
        assert server.requests == []


@pytest.mark.skipif(sys.platform != "linux", reason="OpenSSL's extra CA directory is Linux-only")
def test_real_curl_pin_excludes_an_otherwise_trusted_ca_directory(tmp_path, monkeypatch):
    """Bug: OpenSSL's default CA directory admits a server outside the explicit pin."""
    import subprocess

    credentials = identity()
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    ca = trusted / "ca.pem"
    ca.write_bytes(credentials.ca)
    subprocess.run(["openssl", "rehash", str(trusted)], check=True, capture_output=True)
    wrong_pin = tmp_path / "other-ca.pem"
    wrong_pin.write_bytes(identity("Other Test CA").ca)
    command = transport._command

    # Supply a disposable default trust directory without changing the machine's store.
    def default_trust(request, fd):
        argv = command(request, fd)
        return [argv[0], "--capath", str(trusted), *argv[1:]]

    monkeypatch.setattr(transport, "_command", default_trust)
    with https_server(credentials, lambda handler: handler.send_error(200), False) as server:
        unpinned = transport.CurlRequest(server.origin, "disposable-pat", 5)
        assert transport._run(unpinned).status == 0
        server.requests.clear()
        pinned = transport.CurlRequest(server.origin, "disposable-pat", 5, server_ca=wrong_pin)
        with pytest.raises(ValueError, match="^NETWORK_OR_TLS_FAILED$"):
            transport.send(pinned)
        assert server.requests == []
