"""Service-action profiles cannot expand the selected trust boundary."""

import json

import pytest

from slopmeister.install.service_actions import (
    ActionContext,
    action_payload,
    validate_profile,
)
from tests.integration.install.helpers import consumer, fixture, profile


@pytest.mark.parametrize(
    "args",
    [
        ["--page", "https://other.invalid/pages/viewpage.action?pageId=123"],
        ["--page", "../123"],
        ["--write", "123"],
        [],
    ],
)
def test_bad_confluence_inputs_fail_before_reading_credentials(tmp_path, monkeypatch, args):
    module, data, _ = consumer(tmp_path, monkeypatch)
    data["action"] = "confluence-read"
    (tmp_path / "config.json").write_text(json.dumps(data))
    monkeypatch.setenv("SLOPMEISTER_SERVICE_ACTION_INPUT", json.dumps(args))
    monkeypatch.setattr(module, "service_token", lambda *args: pytest.fail("no credential access"))
    with pytest.raises(ValueError, match="ARGUMENTS_NOT_SUPPORTED"):
        module.fetch()


@pytest.mark.parametrize(
    "page",
    [
        "123",
        "https://jira.example.invalid/pages/viewpage.action?pageId=123",
        "https://jira.example.invalid/spaces/TEST/pages/123/Document",
    ],
)
def test_page_input_is_normalized_to_an_id_on_the_private_origin(tmp_path, monkeypatch, page):
    module, data, _ = consumer(tmp_path, monkeypatch)
    data["action"] = "confluence-read"
    monkeypatch.setenv("SLOPMEISTER_SERVICE_ACTION_INPUT", json.dumps(["--page", page]))
    assert module.operation(data) == {"mode": "page", "id": "123"}


@pytest.mark.parametrize(
    "key,value",
    [
        ("origin", "http://jira.example.invalid"),
        ("origin", "https://user@jira.example.invalid"),
        ("origin", "https://jira.example.invalid/../other"),
        ("origin", "https://jira.example.invalid?x=1"),
        ("plot", "other"),
        ("action", "arbitrary-command"),
        ("token_file", "relative.env"),
        ("pat_ref", "op://Other/JIRA_PAT/credential"),
        ("pat_ref", "secret-value"),
        ("certificate_document", "--help"),
        ("expected_user", "reader\n"),
        ("password_ref", "op://Automation/JIRA_PAT/password"),
    ],
)
def test_profile_cannot_change_origin_plot_vault_or_command_arguments(key, value):
    data = profile()
    data[key] = value
    with pytest.raises(ValueError):
        validate_profile(data, "example", "jira-read")


def test_unknown_profile_fields_cannot_supply_jql_or_an_executable():
    for key in ("jql", "command", "method", "proxy", "ca"):
        with pytest.raises(ValueError):
            validate_profile(dict(profile(), **{key: "untrusted"}), "example", "jira-read")


@pytest.mark.parametrize("prefix", ["", "/", "/jira", "/confluence/", "/apps/wiki"])
def test_pat_only_profile_accepts_application_prefix_without_certificate(prefix):
    data = profile()
    del data["password_ref"], data["certificate_document"]
    data["origin"] = "https://jira.example.invalid" + prefix
    assert validate_profile(data, "example", "jira-read") == data


@pytest.mark.parametrize(
    "prefix", ["/a/../b", "/%2e%2e/b", "//other", "/a//b", "/a\\b", "/a;param"]
)
def test_application_prefix_cannot_redirect_or_normalize_outside_its_path(prefix):
    with pytest.raises(ValueError):
        validate_profile(
            dict(profile(), origin="https://jira.example.invalid" + prefix),
            "example",
            "jira-read",
        )


@pytest.mark.parametrize("missing", ["password_ref", "certificate_document"])
def test_partial_certificate_profile_is_rejected(missing):
    data = profile()
    del data[missing]
    with pytest.raises(ValueError):
        validate_profile(data, "example", "jira-read")


def test_confluence_prefixed_urls_stay_inside_the_configured_application(tmp_path, monkeypatch):
    module, data, _ = consumer(tmp_path, monkeypatch)
    data.update(action="confluence-read", origin="https://jira.example.invalid/confluence")
    for suffix in ["/pages/viewpage.action?pageId=123", "/spaces/TEST/pages/123/Document"]:
        monkeypatch.setenv(
            "SLOPMEISTER_SERVICE_ACTION_INPUT", json.dumps(["--page", data["origin"] + suffix])
        )
        assert module.operation(data) == {"mode": "page", "id": "123"}
        monkeypatch.setenv(
            "SLOPMEISTER_SERVICE_ACTION_INPUT",
            json.dumps(["--page", "https://jira.example.invalid" + suffix]),
        )
        with pytest.raises(ValueError):
            module.operation(data)


def test_unselected_plot_never_opens_private_profiles(tmp_path):
    context = ActionContext(tmp_path, "example", {}, tmp_path / "session", tmp_path / "absent")
    assert action_payload(context) == ({}, {}, "")


def test_unknown_action_cannot_become_a_generic_runner(tmp_path):
    context = ActionContext(tmp_path, "example", {"service_actions": ["unknown"]}, tmp_path)
    with pytest.raises(ValueError, match="consumer"):
        action_payload(context)


def _write_profile(profiles, action, **changes):
    data = dict(profile(), action=action, **changes)
    path = profiles / f"example/{action}.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)


def test_selected_actions_share_code_but_keep_separate_profiles_and_commands(tmp_path):
    root, profiles, _ = fixture(tmp_path)
    _write_profile(profiles, "confluence-read", origin="https://docs.example.invalid")
    selected = {"service_actions": ["jira-read", "confluence-read"]}
    context = ActionContext(root, "example", selected, tmp_path / "session", profiles)
    entries, _, instructions = action_payload(context)
    for native in (".codex", ".claude"):
        jira = native + "/service-actions/jira-read/"
        docs = native + "/service-actions/confluence-read/"
        assert (
            entries[jira + "service_actions/provider.py"]
            == entries[docs + "service_actions/provider.py"]
        )
        assert (
            json.loads(entries[docs + "config.json"][0])["origin"] == "https://docs.example.invalid"
        )
        assert (
            json.loads(entries[jira + "config.json"][0])["origin"] == "https://jira.example.invalid"
        )
    assert (
        "confluence-read/entry.py --output <PRIVATE_RESULT_FILE> --page <PAGE_ID_OR_URL>"
        in instructions
    )
    assert "jira-read/entry.py --output <PRIVATE_RESULT_FILE> --issue <KEY>" in instructions


def test_profile_naming_its_plot_in_the_pre_rename_field_is_refused(tmp_path):
    """Escaping bug: the exact-key-set check is widened and a profile carrying no plot field is
    delivered, so the selected plot is never checked against the profile's own claim."""
    root, profiles, _ = fixture(tmp_path)
    data = profile()
    data["lane"] = data.pop("plot")
    path = profiles / "example/jira-read.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    selected = {"service_actions": ["jira-read"]}
    context = ActionContext(root, "example", selected, tmp_path / "session", profiles)
    with pytest.raises(ValueError, match="fields"):
        action_payload(context)


def test_default_profile_root_resolves_to_the_current_documented_path(tmp_path, monkeypatch):
    """The only coverage of an uninjected profile root. Escaping bug: the root constant or its
    resolution is wrong, so every real launch looks in a directory no profile is written to, which
    no test supplying its own profile root can catch."""
    root, _, _ = fixture(tmp_path)
    home = tmp_path / "home"
    path = home / ".config/slopmeister/access/example/jira-read.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(profile()))
    path.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    selected = {"service_actions": ["jira-read"]}
    entries, _, _ = action_payload(ActionContext(root, "example", selected, tmp_path / "session"))
    delivered = json.loads(entries[".codex/service-actions/jira-read/config.json"][0])
    assert delivered == profile()


def test_profile_reached_through_a_symlinked_parent_is_refused(tmp_path):
    """Escaping bug: the ancestry half of the symlink guard is dropped, and a swapped parent
    directory silently redirects the credential lookup to a profile the operator never provisioned.
    The leaf-file case is covered by test_service_actions_delivery, this covers only the parent."""
    root, profiles, _ = fixture(tmp_path)
    real = tmp_path / "elsewhere"
    profiles.rename(real)
    profiles.symlink_to(real)
    selected = {"service_actions": ["jira-read"]}
    context = ActionContext(root, "example", selected, tmp_path / "session", profiles)
    with pytest.raises(ValueError, match="symlink"):
        action_payload(context)
