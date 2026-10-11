"""Publish a new project version at the commit that passed the main workflow."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib


def context() -> tuple[str, str, str]:
    version = tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"]
    if not isinstance(version, str) or not re.fullmatch(
        r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version
    ):
        raise ValueError("project.version must be X.Y.Z without leading zeroes")
    sha = os.environ.get("GITHUB_SHA", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    allowed = (
        os.environ.get("GITHUB_EVENT_NAME") in ("push", "workflow_dispatch")
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and re.fullmatch(r"[0-9a-f]{40}", sha)
        and sha == head
        and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
    )
    if not allowed:
        raise ValueError("release requires the tested main commit from push or workflow_dispatch")
    return f"repos/{repository}", f"v{version}", sha


def api(path: str, payload: dict | None = None, missing_ok: bool = False) -> dict | None:
    method = "GET" if payload is None else "POST"
    command = ["gh", "api", path, "--hostname", "github.com", "--include", "--method", method]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command,
        input=json.dumps(payload) if payload is not None else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    headers, _, body = result.stdout.partition("\n\n")
    status = re.match(r"HTTP/\S+ (\d{3})\b", headers)
    code = int(status[1]) if status else 0
    if code == 404 and missing_ok:
        return None
    if result.returncode or not 200 <= code < 300:
        raise ValueError(f"GitHub request failed: {method} {path} (HTTP {code})")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("GitHub returned an unexpected response")
    return value


def tag_commit(reference: dict | None, tag: str) -> str | None:
    if reference is None:
        return None
    target = reference.get("object", {})
    sha = target.get("sha", "")
    if (
        reference.get("ref") != f"refs/tags/{tag}"
        or target.get("type") != "commit"
        or not re.fullmatch(r"[0-9a-f]{40}", sha)
    ):
        raise ValueError(f"conflicting tag {tag}: expected a direct commit reference")
    return sha


def verify_release(release: dict, tag: str, sha: str | None) -> None:
    if (
        not sha
        or release.get("tag_name") != tag
        or release.get("draft") is not False
        or release.get("prerelease") is not False
        or not release.get("published_at")
    ):
        raise ValueError(f"conflicting tag or release {tag}: publication identity does not match")


def publish() -> None:
    base, tag, sha = context()
    release = api(f"{base}/releases/tags/{tag}", missing_ok=True)
    existing = tag_commit(api(f"{base}/git/ref/tags/{tag}", missing_ok=True), tag)
    if release is not None:
        verify_release(release, tag, existing)
        print(f"{tag} already published at {existing}; skipping")
        return
    if existing is not None and existing != sha:
        raise ValueError(f"conflicting tag {tag}: it does not name the tested commit")
    if existing is None:
        api(f"{base}/git/refs", {"ref": f"refs/tags/{tag}", "sha": sha})
    confirmed = tag_commit(api(f"{base}/git/ref/tags/{tag}"), tag)
    if confirmed != sha:
        raise ValueError(f"conflicting tag {tag}: it changed before publication")
    payload = {"tag_name": tag, "target_commitish": sha, "name": tag}
    payload.update(draft=False, prerelease=False, generate_release_notes=True)
    created = api(f"{base}/releases", payload)
    verify_release(created, tag, sha)
    print(f"Published {tag} at {sha}")


if __name__ == "__main__":
    try:
        publish()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"release: {error}", file=sys.stderr)
        raise SystemExit(1) from None
