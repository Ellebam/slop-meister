"""Runtime admission keeps missing local tools out of provider diagnosis."""

import ast
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from slopmeister.install import service_actions
from slopmeister.session.service_actions import runtime


def test_runtime_probes_exclude_resolved_credentials(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[0] == runtime.CURL and argv[1:] == ["--version"]:
            return SimpleNamespace(stdout=MAC_CURL, returncode=0)
        if argv[0] == runtime.CURL:
            return SimpleNamespace(
                stdout="--cert-type <type> Certificate type (DER/PEM/ENG/P12)\n--config <file>\n",
                returncode=0,
            )
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert runtime._python_capabilities() and runtime._curl_capabilities()
    assert calls
    assert all(kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C"} for _, kwargs in calls)


P12_HELP = "--cert-type <type> Certificate type (DER/PEM/ENG/P12)\n--config <file>\n"
MAC_CURL = "curl 8.7.1 libcurl/8.7.1 (SecureTransport) LibreSSL/3.3.6\nProtocols: http https\n"
LINUX_CURL = "curl 8.5.0 libcurl/8.5.0 OpenSSL/3.0.13\nProtocols: http https\n"


@pytest.mark.parametrize(
    "platform,version,help_text,expected",
    [
        ("darwin", MAC_CURL, P12_HELP, True),
        ("darwin", "curl SecureTransport https\nProtocols: http\n", P12_HELP, False),
        ("darwin", MAC_CURL, "--cert-type <type>\n--config <file>\n", False),
        ("linux", LINUX_CURL, P12_HELP, True),
        ("linux", MAC_CURL, P12_HELP, False),
        (
            "linux",
            "curl 8.5.0 libcurl/8.5.0 (OpenSSL/3.0.13) GnuTLS/3.8.3\nProtocols: http https\n",
            P12_HELP,
            False,
        ),
        (
            "linux",
            "curl 8.5.0 libcurl/8.5.0 GnuTLS/3.8.3 libssh2/1.11.0 OpenSSL/3.0.13\n"
            "Protocols: http https\n",
            P12_HELP,
            False,
        ),
        (
            "linux",
            "curl 8.5.0 libcurl/8.5.0 GnuTLS/3.8.3\nProtocols: http https\n",
            P12_HELP,
            False,
        ),
        ("darwin", LINUX_CURL, P12_HELP, False),
        ("freebsd", LINUX_CURL, P12_HELP, False),
    ],
)
def test_curl_capability_probe_proves_https_protocol_and_p12(
    monkeypatch, platform, version, help_text, expected
):
    """Bug: Linux curl is refused for lacking the Mac's TLS library, or a wrong one passes."""
    monkeypatch.setattr(sys, "platform", platform)
    outputs = iter((version, help_text))
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=next(outputs), returncode=0),
    )
    assert runtime._curl_capabilities() is expected


def test_runtime_entry_modules_parse_before_python_floor_check():
    root = Path(runtime.__file__).parent
    entry_modules = (
        "supervisor.py",
        "runtime.py",
        "process.py",
        "arguments.py",
        "operations.py",
        "jira.py",
        "jira_find.py",
        "jira_issue.py",
        "jira_related.py",
        "confluence_common.py",
        "wire.py",
        "constants.py",
    )
    for name in entry_modules:
        path = root / name
        tree = ast.parse(path.read_text(), filename=str(path), feature_version=(3, 13))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                dependency = root / (node.module + ".py")
                ast.parse(dependency.read_text(), filename=str(dependency), feature_version=(3, 13))


@pytest.mark.parametrize("platform,library", [("darwin", "SecureTransport"), ("linux", "OpenSSL")])
def test_missing_python_or_curl_is_a_local_prerequisite(monkeypatch, tmp_path, platform, library):
    monkeypatch.setattr(sys, "platform", platform)
    missing = tmp_path / "missing"
    monkeypatch.setattr(runtime, "PYTHON", missing / "python3")
    monkeypatch.setattr(runtime, "OP", missing / "op")
    monkeypatch.setattr(runtime, "CURL", missing / "curl")
    assert runtime.missing() == [
        str(missing / "python3") + " at Python 3.14 or newer",
        str(missing / "op"),
        str(missing / "curl") + f" with {library}, HTTPS and PKCS#12",
    ]
    with pytest.raises(ValueError, match="before session creation.*provider was not contacted"):
        service_actions.admit()


def test_runtime_accepts_only_executable_declared_paths(monkeypatch, tmp_path):
    paths = [tmp_path / name for name in ("python3", "op", "curl")]
    for path in paths:
        path.write_text("fixture")
        path.chmod(0o700)
    monkeypatch.setattr(runtime, "PYTHON", paths[0])
    monkeypatch.setattr(runtime, "OP", paths[1])
    monkeypatch.setattr(runtime, "CURL", paths[2])
    monkeypatch.setattr(runtime, "_python_capabilities", lambda: True)
    monkeypatch.setattr(runtime, "_curl_capabilities", lambda: True)
    assert runtime.missing() == []


def test_runtime_accepts_the_fixed_homebrew_symlink_shape(monkeypatch, tmp_path):
    target = tmp_path / "python-target"
    target.write_text("fixture")
    target.chmod(0o700)
    link = tmp_path / "python3"
    link.symlink_to(target)
    monkeypatch.setattr(runtime, "PYTHON", link)
    monkeypatch.setattr(runtime, "OP", Path("/bin/sh"))
    monkeypatch.setattr(runtime, "CURL", Path("/usr/bin/curl"))
    monkeypatch.setattr(runtime, "_python_capabilities", lambda: True)
    monkeypatch.setattr(runtime, "_curl_capabilities", lambda: True)
    assert runtime.missing() == []


def test_runtime_rejects_python_below_the_declared_floor(monkeypatch, tmp_path):
    paths = [tmp_path / name for name in ("python3", "op", "curl")]
    for path in paths:
        path.write_text("fixture")
        path.chmod(0o700)
    monkeypatch.setattr(runtime, "PYTHON", paths[0])
    monkeypatch.setattr(runtime, "OP", paths[1])
    monkeypatch.setattr(runtime, "CURL", paths[2])
    monkeypatch.setattr(runtime, "_python_capabilities", lambda: False)
    monkeypatch.setattr(runtime, "_curl_capabilities", lambda: True)
    assert runtime.missing() == [str(paths[0]) + " at Python 3.14 or newer"]


@pytest.mark.parametrize("broken", ["op", "curl_capabilities"])
def test_admit_refuses_each_missing_or_incapable_prerequisite(monkeypatch, tmp_path, broken):
    paths = {name: tmp_path / name for name in ("python3", "op", "curl")}
    for path in paths.values():
        path.write_text("fixture")
        path.chmod(0o700)
    monkeypatch.setattr(runtime, "PYTHON", paths["python3"])
    monkeypatch.setattr(runtime, "OP", paths["op"])
    monkeypatch.setattr(runtime, "CURL", paths["curl"])
    monkeypatch.setattr(runtime, "_python_capabilities", lambda: True)
    monkeypatch.setattr(runtime, "_curl_capabilities", lambda: broken != "curl_capabilities")
    if broken == "op":
        paths["op"].chmod(0o600)

    expected = str(paths["op"] if broken == "op" else paths["curl"])
    with pytest.raises(ValueError, match=expected + ".*provider was not contacted"):
        service_actions.admit()


def _present_tools(monkeypatch):
    monkeypatch.setattr(runtime, "PYTHON", Path(sys.executable))
    monkeypatch.setattr(runtime, "OP", Path("/bin/sh"))
    monkeypatch.setattr(runtime, "CURL", Path("/usr/bin/curl"))
    monkeypatch.setattr(runtime, "_python_capabilities", lambda: True)
    monkeypatch.setattr(runtime, "_curl_capabilities", lambda: True)


def test_provider_that_cannot_start_is_a_local_prerequisite(monkeypatch, tmp_path):
    """Bug: a provider that loads and dies silently is reported as a credential failure."""
    _present_tools(monkeypatch)
    package = tmp_path / "service_actions"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "provider.py").write_text('if __name__ == "__main__":\n    raise SystemExit(1)\n')
    assert runtime.missing(module_root=tmp_path) == ["provider module"]
    (package / "provider.py").unlink()
    assert runtime.missing(module_root=tmp_path) == ["provider module"]
    (package / "provider.py").write_text("pass\n")
    assert runtime.missing(module_root=tmp_path) == ["provider module"]
    (package / "provider.py").write_text("print()\n")
    assert runtime.missing(module_root=tmp_path) == ["provider module"]
    (package / "provider.py").write_text("print('not a result')\n")
    assert runtime.missing(module_root=tmp_path) == ["provider module"]


def test_loadable_provider_adds_nothing(monkeypatch):
    """Bug: the start check reports every healthy reader as broken."""
    _present_tools(monkeypatch)
    root = Path(runtime.__file__).resolve().parents[1]
    assert runtime.missing(module_root=root) == []


def test_probe_environment_carries_no_credentials(monkeypatch, tmp_path):
    """Bug: the start check inherits the service token, or never runs."""
    _present_tools(monkeypatch)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", "PARENT_CANARY")
    runs = []
    monkeypatch.setattr(
        runtime, "invoke", lambda run: runs.append(run) or b'{"result":"INPUT_INVALID"}'
    )
    assert runtime.missing(module_root=tmp_path) == []
    assert len(runs) == 1
    assert runs[0].argv[-2:] == ["-m", "service_actions.provider"]
    assert (runs[0].env, runs[0].cwd, runs[0].payload) == (runtime.PROBE_ENV, tmp_path, b"")
