"""The write token can publish only after every public check succeeds on main."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]


def jobs() -> dict[str, str]:
    workflow = (ROOT / ".github/workflows/check.yml").read_text()
    chunks = re.split(r"^  ([a-z_]+):\n", workflow.split("jobs:\n", 1)[1], flags=re.MULTILINE)
    return dict(zip(chunks[1::2], chunks[2::2], strict=True))


def test_publisher_is_gated_and_has_the_only_write_token() -> None:
    blocks = jobs()
    assert "release" in blocks, "No automatic release after passing checks"
    release = blocks["release"]
    assert "needs: [lint, quality, tests, host]" in release
    assert "github.ref == 'refs/heads/main'" in release
    assert "github.event_name == 'push' || github.event_name == 'workflow_dispatch'" in release
    assert "contents: write" in release
    assert all(
        "contents: write" not in block for name, block in blocks.items() if name != "release"
    )
    assert "group: release-${{ github.repository }}" in release
    assert "cancel-in-progress: false" in release
    assert "ref: ${{ github.sha }}" in release
    assert "persist-credentials: false" in release
    assert "GH_TOKEN: ${{ github.token }}" in release
    assert "python .github/scripts/release.py" in release


def test_host_job_runs_all_synthetic_host_gates() -> None:
    blocks = jobs()
    assert "host" in blocks, "Release gates omit the optional host layer"
    host = blocks["host"]
    for command in ("host:lint", "host:syntax", "host:test", "host:ha:check"):
        assert f"run: task {command}" in host
    assert "uv sync --locked --group host" in host
    assert "node-version-file: host/.node-version" in host
    assert "npm --prefix host ci --ignore-scripts" in host
    assert "npx playwright install --with-deps chromium" in host
    assert "task check" not in host and "test:live" not in host
