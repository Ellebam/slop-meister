"""The setup step installs the session op's files privately and prints names, never a value."""

import json
import os
from pathlib import Path
import stat

import pytest

from slopmeister.session import secret_approval, secret_tier
from slopmeister.workstation import op_setup
from tests.integration.workstation.test_install import machine, workstation
from tests.support.fakes import fake_binary

ONE, TWO = "ops_one-synthetic", "ops_two-synthetic"
# Each token lists its own vaults, as each service account does, and any other is rejected.
VAULTS = f"""env > "$HOME/op-env"
case "$OP_SERVICE_ACCOUNT_TOKEN" in
  {ONE}) echo '[{{"id":"a","name":"Everyday"}}]' ;;
  {TWO}) echo '[{{"id":"a","name":"Everyday"}},{{"id":"b","name":"Production"}}]' ;;
  *) echo 'token rejected' >&2; exit 1 ;;
esac"""
ROUTE = {
    op_setup.ROUTE["ask_url"]: "https://ha.example.invalid/api/webhook/synthetic",
    op_setup.ROUTE["answer_url"]: "https://ha.example.invalid/api/states/sensor.synthetic",
    op_setup.ROUTE["token"]: "read-synthetic",
}


def setup(tmp_path: Path, part: str, **env: str):
    home, bin_dir = machine(tmp_path)
    fake_binary(bin_dir, "op", VAULTS)
    return home, workstation(home, bin_dir, "op-setup", part, **env)


def tokens(one: str = ONE, two: str = TWO, **more: str) -> dict[str, str]:
    return {
        "SLOPMEISTER_OP_TIER_ONE": one,
        "SLOPMEISTER_OP_TIER_TWO": two,
        "SLOPMEISTER_OP_TOKEN_VAULT": "Agent Tokens",
        **more,
    }


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_tokens_land_in_private_files_and_only_names_are_printed(tmp_path):
    """Bug: a token is readable by others, printed, or handed to the other account's check."""
    home, run = setup(tmp_path, "tokens", **tokens())
    files = home / secret_tier.DIRECTORY
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout == "tier-one: Everyday\ntier-two: Everyday, Production\nOP_SETUP_PASS\n"
    assert "ops_" not in run.stdout + run.stderr
    assert (files / "tier-one.token").read_text() == ONE + "\n"
    assert (files / "tier-two.token").read_text() == TWO + "\n"
    assert mode(files) == 0o700
    assert {mode(path) for path in files.iterdir()} == {0o600}
    lists = json.loads((files / secret_tier.LISTS).read_text())
    assert [vault["name"] for vault in lists["tier-two"]] == ["Everyday", "Production"]
    assert ONE not in (home / "op-env").read_text()


@pytest.mark.parametrize(
    "env,reason",
    [
        (tokens(two="op://agent-tokens/TIER_TWO/credential"), "SLOPMEISTER_OP_TIER_TWO was not"),
        (tokens(one=""), "SLOPMEISTER_OP_TIER_ONE was not resolved"),
        (tokens(two="ops_revoked"), "did not accept the tier-two token"),
        (tokens(one="not-a-token"), "the tier-one value is not a service-account token"),
        (tokens(SLOPMEISTER_OP_TOKEN_VAULT="production"), "tier-two token lists the token vault"),
    ],
)
def test_nothing_is_written_unless_both_tokens_prove_themselves(tmp_path, env, reason):
    """Bug: a dismissed prompt, a revoked token or an account that reads the token vault leaves
    half an install, or replaces working files."""
    home, first = setup(tmp_path, "tokens", **tokens())
    assert first.returncode == 0
    kept = (home / secret_tier.DIRECTORY / "tier-one.token").read_bytes()
    run = workstation(home, tmp_path / "bin", "op-setup", "tokens", **env)
    assert run.returncode == 1
    assert run.stdout.startswith("OP_SETUP_FAIL: ") and reason in run.stdout
    assert "ops_" not in run.stdout + run.stderr
    assert (home / secret_tier.DIRECTORY / "tier-one.token").read_bytes() == kept


def test_first_run_without_a_value_creates_no_file(tmp_path):
    """Bug: a machine without the operator's desktop approval ends with empty token files."""
    home, run = setup(tmp_path, "tokens")
    assert run.returncode == 1 and "was not resolved" in run.stdout
    assert not (home / secret_tier.DIRECTORY).exists()


def test_rerun_replaces_a_rotated_token(tmp_path):
    """Bug: after a rotation the old token stays on the machine."""
    home, _ = setup(tmp_path, "tokens", **tokens())
    fake_binary(tmp_path / "bin", "op", VAULTS.replace(ONE, "ops_rotated"))
    run = workstation(home, tmp_path / "bin", "op-setup", "tokens", **tokens(one="ops_rotated"))
    assert run.returncode == 0, run.stdout
    assert (home / secret_tier.DIRECTORY / "tier-one.token").read_text() == "ops_rotated\n"


def test_route_lands_in_a_private_file(tmp_path):
    """Bug: the Home Assistant credential is readable by others or printed."""
    home, run = setup(tmp_path, "approval", **ROUTE)
    path = home / secret_tier.DIRECTORY / secret_approval.SETTINGS
    assert run.returncode == 0 and run.stdout == "OP_SETUP_PASS\n"
    assert mode(path) == 0o600 and json.loads(path.read_text())["token"] == "read-synthetic"


def test_route_over_plain_http_is_not_installed_and_keeps_a_working_route(tmp_path):
    """Bug: the read credential is installed for an address that sends it unencrypted, or a
    failed rotation deletes the route that worked."""
    plain = {**ROUTE, op_setup.ROUTE["answer_url"]: "http://ha.example.invalid/api/states/x"}
    home, run = setup(tmp_path, "approval", **plain)
    path = home / secret_tier.DIRECTORY / secret_approval.SETTINGS
    assert run.returncode == 1 and "does not hold the route" in run.stdout
    assert not path.exists()
    assert workstation(home, tmp_path / "bin", "op-setup", "approval", **ROUTE).returncode == 0
    kept = path.read_bytes()
    assert workstation(home, tmp_path / "bin", "op-setup", "approval", **plain).returncode == 1
    assert path.read_bytes() == kept


@pytest.mark.parametrize("name", ["", " \t "])
def test_token_vault_must_be_named_before_setup_writes(tmp_path, name):
    """Bug: an omitted custody vault silently skips the account access check."""
    home, run = setup(tmp_path, "tokens", **tokens(SLOPMEISTER_OP_TOKEN_VAULT=name))
    assert run.returncode == 1 and "SLOPMEISTER_OP_TOKEN_VAULT" in run.stdout
    assert not (home / secret_tier.DIRECTORY).exists()


def test_old_temporary_hardlink_cannot_overwrite_another_file(tmp_path):
    """Bug: opening a predictable staging path truncates an existing linked file."""
    home, bin_dir = machine(tmp_path)
    fake_binary(bin_dir, "op", VAULTS)
    directory = home / secret_tier.DIRECTORY
    directory.mkdir(parents=True)
    target = tmp_path / "kept"
    target.write_text("keep this file")
    os.link(target, directory / "tier-one.token.new")
    run = workstation(home, bin_dir, "op-setup", "tokens", **tokens())
    assert run.returncode == 0, run.stdout + run.stderr
    assert target.read_text() == "keep this file"


@pytest.mark.parametrize(
    "part", ["directory", "tier-one.token", "tier-two.token", secret_tier.LISTS]
)
def test_setup_refuses_symlinks_below_its_home(tmp_path, part):
    """Bug: setup writes outside its managed path or changes a linked directory's mode."""
    home, bin_dir = machine(tmp_path)
    fake_binary(bin_dir, "op", VAULTS)
    directory = home / secret_tier.DIRECTORY
    target = tmp_path / "kept"
    if part == "directory":
        target.mkdir(mode=0o755)
        directory.parent.mkdir(parents=True)
        directory.symlink_to(target, target_is_directory=True)
    else:
        target.write_text("keep this file")
        directory.mkdir(parents=True)
        (directory / "tier-one.token").write_text("previous token")
        (directory / part).unlink(missing_ok=True)
        (directory / part).symlink_to(target)
    before = target.stat().st_mode
    saved = {path.name: path.read_bytes() for path in directory.iterdir()}
    run = workstation(home, bin_dir, "op-setup", "tokens", **tokens())
    assert run.returncode == 1 and "symlink" in run.stdout
    assert target.stat().st_mode == before
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == saved
