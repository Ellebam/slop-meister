"""Every gate once, with its layer. Portable runs in CI, native only on a workstation."""

from dataclasses import dataclass

from slopmeister.check.jobs import Check
from slopmeister.paths import ROOT
from slopmeister.quality import inventory

PYTEST_FLAGS = ("-m", "pytest", "-q", "-p", "no:cacheprovider")


def python() -> str:
    """The interpreter in the repository's locked development environment."""
    return str(ROOT / ".venv" / "bin" / "python")


def tool(name: str) -> str:
    return str(ROOT / ".venv" / "bin" / name)


def pytest_layer(layer: str) -> tuple[str, ...]:
    # loadgroup keeps every xdist_group on one worker, so its tests never overlap.
    return (python(), *PYTEST_FLAGS, f"tests/{layer}", "-n", "auto", "--dist", "loadgroup")


def shell_files() -> tuple[str, ...]:
    return tuple(
        str(source.path.relative_to(ROOT))
        for source in inventory.sources(ROOT)
        if source.language == "bash"
    )


def first_phase() -> list[Check]:
    return [
        Check("ruff", (tool("ruff"), "check", "."), kind="lint", phase="first"),
        Check("format", (tool("ruff"), "format", "--check", "."), kind="lint", phase="first"),
        Check(
            "shellcheck",
            ("shellcheck", "--severity=warning", *shell_files()),
            kind="lint",
            phase="first",
        ),
        Check("quality", ("bin/slopmeister", "quality"), kind="quality", phase="first"),
        Check("render", ("bin/slopmeister", "render", "--check"), kind="quality", phase="first"),
    ]


def layered_pytest() -> list[Check]:
    return [
        Check("pytest-unit", pytest_layer("unit"), seconds=2),
        Check("pytest-integration", pytest_layer("integration"), seconds=20),
        Check("pytest-native", pytest_layer("native"), layer="native", seconds=10),
    ]


def native_extras(vault: str | None) -> list[Check]:
    drift = ("bin/slopmeister", "workstation", "drift", *((vault,) if vault else ()))
    return [Check("drift", drift, layer="native", phase="last")]


@dataclass(frozen=True)
class Selection:
    layer: str = "all"
    kind: str = "all"
    vault: str | None = None

    def keeps(self, check: Check) -> bool:
        return (self.layer in ("all", check.layer)) and (self.kind in ("all", check.kind))


def catalogue(selection: Selection | None = None) -> list[Check]:
    selection = selection or Selection()
    checks = first_phase() + layered_pytest()
    checks += native_extras(selection.vault)
    return [check for check in checks if selection.keeps(check)]


def describe(checks: list[Check]) -> list[str]:
    return [f"{check.layer:<9} {check.kind:<8} {check.phase:<9} {check.id}" for check in checks]
