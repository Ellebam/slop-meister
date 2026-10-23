"""The on-host doctor reads reviewed snapshot bytes and probes only a test-owned endpoint."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import subprocess
import tarfile
import threading

import pytest

from host.tests.test_deploy import PAYLOADS, ROOT
from host.tests.test_deploy import deployment as deployment
from tests.support.repos import git

MEMBERS = [name for name in PAYLOADS if name.startswith("slopmeister/")]
CADDY = "host/ansible/roles/grove/templates/Caddyfile.j2"
pytestmark = pytest.mark.xdist_group("grove-doctor")


def executable(path, text):
    path.write_text("#!/bin/sh\n" + text)
    path.chmod(0o700)


def snapshot(repo, revision, parent):
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", revision, *MEMBERS],
        capture_output=True,
        check=True,
    ).stdout
    root = parent / hashlib.sha256(archive).hexdigest()
    root.mkdir(parents=True)
    saved = parent / "reviewed.tar"
    saved.write_bytes(archive)
    with tarfile.open(saved) as stream:
        stream.extractall(root, filter="data")
    return root


def standins(binary, headers, policy):
    executable(binary / "uname", 'printf "%s\\n" "${DOCTOR_OS:-Linux}"\n')
    executable(
        binary / "systemctl",
        'case "$1" in\n show) printf "%s\\n" "${DOCTOR_LOAD:-loaded}";;\n'
        ' is-active) exit "${DOCTOR_INACTIVE:-0}";;\n *) exit 99;;\nesac\n',
    )
    executable(
        binary / "curl", 'test "${DOCTOR_TRANSPORT:-ok}" = ok || exit 7\ncat "$DOCTOR_HEADERS"\n'
    )
    expected = re.findall(
        r"^\s*(Content-Security-Policy|X-Content-Type-Options|Referrer-Policy|Cache-Control) (.+)$",
        policy.read_text(),
        re.M,
    )
    headers.write_text(
        "HTTP/1.1 404 Not Found\nServer: Caddy\n"
        + "\n".join(name + ": " + value.strip('"') for name, value in expected)
        + "\n\n"
    )


@pytest.fixture
def doctor(deployment, tmp_path, monkeypatch):
    repo = deployment[0]
    policy = repo / CADDY
    policy.parent.mkdir(parents=True)
    policy.write_bytes((ROOT / CADDY).read_bytes())
    git(repo, "add", CADDY)
    git(repo, "commit", "-qm", "Review response policy")
    revision = git(repo, "rev-parse", "HEAD").strip()
    installed = snapshot(repo, revision, tmp_path / "custom grove root")
    entry = tmp_path / "grove"
    entry.write_text(
        'from pathlib import Path\nimport sys\nsys.path[:0] = [str(Path("'
        + str(installed)
        + '"))]\nraise RuntimeError("DO_NOT_EXECUTE_ENTRY")\n'
    )
    binary, headers = tmp_path / "bin", tmp_path / "headers"
    standins(binary, headers, policy)
    monkeypatch.setenv("DOCTOR_HEADERS", str(headers))
    for key in ("GROVE_ENTRY", "GROVE_BACKEND_PORT", "HOST_REVISION"):
        monkeypatch.delenv(key, raising=False)
    return dict(
        repo=repo,
        revision=revision,
        installed=installed,
        entry=entry,
        binary=binary,
        headers=headers,
    )


def inspect(world, port=54321):
    return subprocess.run(
        [
            "task",
            "host:grove:doctor",
            f"HOST_REVISION={world['revision']}",
            f"GROVE_ENTRY={world['entry']}",
            f"GROVE_BACKEND_PORT={port}",
        ],
        cwd=world["repo"],
        capture_output=True,
        text=True,
        timeout=20,
    )


def assert_cleaned(world):
    assert not list((world["repo"] / "host/.scratch").glob("grove-doctor.*"))


def test_clean_custom_root_is_verified_without_running_installed_code(doctor):
    result = inspect(doctor)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "units and loopback checks passed" in result.stdout
    assert "DO_NOT_EXECUTE_ENTRY" not in result.stdout + result.stderr
    assert_cleaned(doctor)


@pytest.mark.parametrize("damage", ["altered", "missing", "extra", "linked", "entry-digest"])
def test_snapshot_damage_is_reported_without_printing_installed_contents(doctor, damage):
    root = doctor["installed"]
    leaf = root / "slopmeister/session/bloom.py"
    if damage == "altered":
        leaf.write_text("PRIVATE_CONTENT_SENTINEL")
    elif damage == "missing":
        leaf.unlink()
    elif damage == "extra":
        (root / "extra").write_text("PRIVATE_CONTENT_SENTINEL")
    if damage == "linked":
        outside = root.parent / "outside"
        outside.write_text("PRIVATE_CONTENT_SENTINEL")
        leaf.unlink()
        leaf.symlink_to(outside)
    if damage == "entry-digest":
        renamed = root.with_name("0" * 64)
        root.rename(renamed)
        doctor["entry"].write_text(doctor["entry"].read_text().replace(str(root), str(renamed)))
    result = inspect(doctor)
    assert result.returncode != 0 and "grove:doctor: FAIL" in result.stderr
    assert "PRIVATE_CONTENT_SENTINEL" not in result.stdout + result.stderr
    assert_cleaned(doctor)


@pytest.mark.parametrize(
    "name,value,reason",
    [
        ("DOCTOR_OS", "Darwin", "prerequisite: run on the Grove Linux host"),
        ("DOCTOR_LOAD", "not-found", "prerequisite: grove.service is not installed"),
        ("DOCTOR_INACTIVE", "1", "service or timer is inactive"),
        ("DOCTOR_TRANSPORT", "failed", "loopback transport failed"),
    ],
)
def test_missing_prerequisites_and_transport_are_failures(doctor, monkeypatch, name, value, reason):
    monkeypatch.setenv(name, value)
    result = inspect(doctor)
    assert result.returncode != 0 and reason in result.stderr, result.stdout + result.stderr
    assert_cleaned(doctor)


@pytest.mark.parametrize("change", ["status", "server", "csp", "duplicate"])
def test_response_boundaries_must_match_the_reviewed_policy(doctor, change):
    headers = doctor["headers"].read_text()
    if change == "status":
        headers = headers.replace("404 Not Found", "200 OK")
    elif change == "server":
        headers = headers.replace("Server: Caddy", "Server: other")
    elif change == "csp":
        headers = headers.replace(
            "sandbox allow-scripts", "sandbox allow-scripts allow-same-origin"
        )
    else:
        headers += "Cache-Control: public\n"
    doctor["headers"].write_text(headers)
    result = inspect(doctor)
    assert result.returncode != 0 and "grove:doctor: FAIL" in result.stderr
    assert_cleaned(doctor)


def test_loopback_requests_keep_traversal_paths_and_use_the_selected_port(doctor):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.paths.append(self.path)
            self.send_response_only(404)
            for line in doctor["headers"].read_text().splitlines()[1:]:
                if ":" in line:
                    name, value = line.split(":", 1)
                    self.send_header(name, value.strip())
            self.end_headers()

        def log_message(self, *args):
            pass

    (doctor["binary"] / "curl").unlink()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.paths = []
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        result = inspect(doctor, server.server_port)
        assert result.returncode == 0, result.stdout + result.stderr
        assert server.paths == ["/", "/../etc/passwd", "/%2e%2e/etc/passwd", "/..%2fetc%2fpasswd"]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert_cleaned(doctor)


def test_doctor_ignores_ambient_tar_options(doctor, monkeypatch):
    monkeypatch.setenv("TAR_OPTIONS", "--exclude=*")
    result = inspect(doctor)
    assert result.returncode == 0, result.stdout + result.stderr
    assert_cleaned(doctor)
