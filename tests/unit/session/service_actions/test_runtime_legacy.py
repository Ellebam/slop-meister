"""Certificate admission proves the fixed OpenSSL providers before credentials."""

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from slopmeister.session.service_actions import runtime

ACTIVE = (
    "Providers:\n  default\n    name: OpenSSL Default Provider\n"
    "    version: 3.0.13\n    status: active\n"
    "  legacy\n    name: OpenSSL Legacy Provider\n"
    "    version: 3.0.13\n    status: active\n"
)


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(runtime, "_executable", lambda _: True)
    monkeypatch.setattr(runtime, "_python_capabilities", lambda: True)
    monkeypatch.setattr(runtime, "_curl_capabilities", lambda: True)


@pytest.mark.parametrize("failure", ["executable", "module", "inactive", "exit", "timeout", "os"])
def test_missing_legacy_provider_is_a_local_prerequisite(monkeypatch, tools, failure):
    """Bug: missing or unusable legacy support is misreported as a bad customer certificate."""
    monkeypatch.setattr(sys, "platform", "linux")
    if failure == "executable":
        monkeypatch.setattr(runtime, "_executable", lambda path: path != Path("/usr/bin/openssl"))

    def run(argv, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 5)
        if failure == "os":
            raise OSError("missing")
        output = ACTIVE.replace("  legacy", "  absent") if failure == "module" else ACTIVE
        if failure == "inactive":
            output = output.replace("status: active", "status: inactive")
        return SimpleNamespace(stdout=output, returncode=1 if failure == "exit" else 0)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(ValueError, match="^LOCAL_PREREQUISITE_MISSING:.*legacy"):
        runtime.require(cert=True)


def test_provider_probe_loads_both_providers_without_parent_openssl_settings(monkeypatch, tools):
    """Bug: an inherited module path changes the probe, or only default support is checked."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("OPENSSL_CONF", "/untrusted/config")
    monkeypatch.setenv("OPENSSL_MODULES", "/untrusted/modules")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout=ACTIVE, returncode=0)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    assert runtime.missing(cert=True) == []
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [Path("/usr/bin/openssl"), "list", "-providers"]
    assert kwargs["env"] == {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "OPENSSL_CONF": str(Path(runtime.__file__).with_name("openssl.cnf")),
    }
    assert kwargs["timeout"] == 5 and kwargs["capture_output"] and kwargs["text"]


@pytest.mark.parametrize("platform,certificate", [("linux", False), ("darwin", True)])
def test_requests_without_linux_certificates_do_not_require_legacy(
    monkeypatch, tools, platform, certificate
):
    """Bug: a missing Linux module blocks PAT-only actions or Mac certificate actions."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **kw: pytest.fail("OpenSSL probed"))
    assert runtime.missing(cert=certificate) == []
