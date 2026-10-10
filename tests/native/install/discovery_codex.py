"""Drive Codex positive controls and exclusive prepared discovery."""

from tests.native.install.discovery_fixture import CODEX, git
from tests.support.standin import Command, put, require, run

CODEX_FOREIGN = (
    "FOREIGN_CODEX_ROOT",
    "FOREIGN_CODEX_OVERRIDE",
    "FOREIGN_CODEX_SETTINGS",
    "FOREIGN_CODEX_SKILL",
    "FOREIGN_CODEX_NESTED",
    "FOREIGN_NESTED_CODEX_SETTINGS",
    "FOREIGN_CODEX_FALLBACK",
    "FOREIGN_EXTRA_CODEX",
    "FOREIGN_EXTRA_CODEX_SKILL",
    "FOREIGN_EXTRA_CODEX_SETTINGS",
)

__all__ = ["verify_codex"]


def verify_codex(fixture):
    verify_controls(fixture)
    prepare_product(fixture)
    captured = prepared_output(fixture, "codex-replaced")
    for marker in CODEX_FOREIGN:
        require(marker not in captured, "Codex loaded competing configuration: " + marker)
    for marker in (
        "GLOBAL_CODEX_MARKER",
        "SLOPMEISTER_AGREEMENT_MARKER",
        "SLOPMEISTER_SKILL_MARKER",
    ):
        require(marker in captured, "Codex lost expected configuration: " + marker)
    require(str(fixture.extra) in captured, "Codex additional-directory grant missing")
    verify_late_configuration(fixture)
    require(git(fixture, ["rev-parse", "HEAD"]) == fixture.original, "upstream HEAD changed")
    print(
        "PASS codex-replaced: controlled prompt discovery and extra file grant, "
        "live daemon still requires separate proof",
        flush=True,
    )


def verify_controls(fixture):
    baseline = prompt_input(fixture, fixture.workspace, "codex-baseline")
    for marker in (
        "FOREIGN_CODEX_OVERRIDE",
        "FOREIGN_CODEX_SETTINGS",
        "FOREIGN_CODEX_SKILL",
        "GLOBAL_CODEX_MARKER",
    ):
        require(marker in baseline, "missing Codex positive control: " + marker)
    (fixture.workspace / "AGENTS.override.md").unlink()
    ordinary = prompt_input(fixture, fixture.workspace, "codex-agents-baseline")
    require("FOREIGN_CODEX_ROOT" in ordinary, "ordinary Codex root control was not loaded")
    put(fixture.workspace / "AGENTS.override.md", "FOREIGN_CODEX_OVERRIDE\n")
    nested = prompt_input(fixture, fixture.workspace / "nested", "codex-nested-baseline")
    require(
        "FOREIGN_CODEX_NESTED" in nested and "FOREIGN_NESTED_CODEX_SETTINGS" in nested,
        "nested Codex controls were not loaded",
    )
    fallback = prompt_input(fixture, fixture.workspace / "fallback", "codex-fallback-baseline")
    require("FOREIGN_CODEX_FALLBACK" in fallback, "alternate filename control was not loaded")
    extra = prompt_input(fixture, fixture.extra, "codex-extra-baseline")
    for marker in (
        "FOREIGN_EXTRA_CODEX",
        "FOREIGN_EXTRA_CODEX_SKILL",
        "FOREIGN_EXTRA_CODEX_SETTINGS",
    ):
        require(marker in extra, "extra Codex control was not loaded: " + marker)


def prompt_input(fixture, cwd, evidence):
    argv = [str(CODEX), "-C", str(cwd), "debug", "prompt-input"]
    return run(Command(argv, fixture.root, fixture.env, fixture.root / evidence))


def prepare_product(fixture):
    argv = [
        str(fixture.product / "bin/slopmeister"),
        "install",
        "--prepare",
        "probe",
        str(fixture.workspace),
        "--grant",
        str(fixture.repo),
        "--grant",
        str(fixture.extra),
    ]
    run(Command(argv, fixture.root, fixture.env, fixture.root / "prepare"))


def prepared_output(fixture, evidence):
    argv = [
        str(CODEX),
        "-C",
        str(fixture.workspace),
        "--add-dir",
        str(fixture.extra),
        "-c",
        'project_root_markers=["AGENTS.md"]',
        "-c",
        "project_doc_fallback_filenames=[]",
        "debug",
        "prompt-input",
    ]
    return run(Command(argv, fixture.root, fixture.env, fixture.root / evidence))


def verify_late_configuration(fixture):
    late = fixture.workspace / "late-product"
    put(late / "app.txt", "LATE_ORDINARY_READ_CONTENT\n")
    put(late / ".codex/config.toml", 'developer_instructions="FOREIGN_NESTED_CODEX_SETTINGS"\n')
    argv = [
        str(fixture.product / "bin/slopmeister"),
        "install",
        "--check",
        "probe",
        str(fixture.workspace),
        "--grant",
        str(fixture.repo),
        "--grant",
        str(fixture.extra),
    ]
    run(Command(argv, fixture.root, fixture.env, fixture.root / "late-config-check"))
    captured = prepared_output(fixture, "codex-late-config")
    require(
        "FOREIGN_NESTED_CODEX_SETTINGS" not in captured,
        "Codex loaded settings introduced after preparation",
    )
    for marker in (
        "GLOBAL_CODEX_MARKER",
        "SLOPMEISTER_AGREEMENT_MARKER",
        "SLOPMEISTER_SKILL_MARKER",
    ):
        require(marker in captured, "late Codex case lost expected configuration: " + marker)
