"""Metadata search uses the approved vault account and never emits item values."""

import json
import subprocess

import pytest

from slopmeister.session import secret_run
from tests.support.op_session import TWO, approve

ITEM = {
    "id": "item-id",
    "title": "SERVICE_ADMIN_PASSWORD",
    "category": "PASSWORD",
    "vault": {"id": "idtwo", "name": "Production", "extra": "PRIVATE"},
    "fields": [{"value": "SECRET_VALUE"}],
    "notesPlain": "PRIVATE_NOTE",
    "urls": [{"href": "https://private.invalid/SECRET_URL"}],
}
ARGS = ["metadata", "--vault", "Production", "--search", "service_admin"]


@pytest.fixture
def metadata_approval(monkeypatch, session):
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    monkeypatch.setenv("SECRET_ASK_REASON", "Find item metadata")
    return approve(monkeypatch, "approved")


@pytest.fixture
def listing(monkeypatch):
    calls = []

    def listed(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps([ITEM]).encode(), b"")

    monkeypatch.setattr(subprocess, "run", listed)
    return calls


def test_metadata_without_tier_two_intent_never_reaches_desktop(session, capsys):
    """Bug: metadata listing passes through to desktop instead of the HA approval route."""
    assert secret_run.main(ARGS) == 1
    assert "op tier-two" in capsys.readouterr().err
    assert session == []


def test_approval_precedes_projected_output(monkeypatch, session, listing, capsys):
    """Bug: listing uses desktop, skips HA or prints fields outside the metadata allowlist."""
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    monkeypatch.setenv("SECRET_ASK_REASON", "Find owner item metadata")
    asked = approve(monkeypatch, "approved")
    assert secret_run.main(ARGS) == 0
    out, err = capsys.readouterr()
    assert (
        len(asked) == 1
        and "metadata --vault Production --search service_admin" in asked[0]["message"]
    )
    assert "VAULT_METADATA=op://Production" in asked[0]["message"]
    assert json.loads(out) == [
        {key: ITEM[key] for key in ("id", "title", "category")}
        | {"vault": {"id": "idtwo", "name": "Production"}}
    ]
    argv, options = listing[0]
    assert argv[1:] == ["item", "list", "--vault=Production", "--format=json"]
    assert options["env"][secret_run.TOKEN] == TWO
    assert options["env"]["OP_BIOMETRIC_UNLOCK_ENABLED"] == "false"
    assert session == []
    assert all(value not in out + err for value in (TWO, "SECRET_VALUE", "PRIVATE", "SECRET_URL"))


@pytest.mark.parametrize("decision", ["denied", "timed out"])
def test_no_list_after_denial(monkeypatch, session, listing, capsys, decision):
    """Bug: a rejected HA request still reaches the metadata API."""
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    monkeypatch.setenv("SECRET_ASK_REASON", "Find owner metadata")
    approve(monkeypatch, decision)
    assert secret_run.main(ARGS) == 1
    assert listing == [] and session == [] and capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--vault", "Production", "--format=json"],
        ["--vault", "Production/Other"],
        ["--vault", "Production\nOther"],
        ["--vault", "--all"],
        ["--vault", " Production"],
        ["--vault", "Production", "--vault", "Everyday"],
        ["--vault", "Production?x"],
    ],
)
def test_invalid_scope_never_asks_or_lists(args, session, listing, capsys):
    """Bug: an argument widens or obscures the vault named in the approval."""
    assert secret_run.main(["metadata", *args]) == 1
    assert listing == [] and session == [] and capsys.readouterr().out == ""


@pytest.mark.parametrize("vault", ["Unknown", "Personal"])
def test_unknown_vault_has_no_desktop_fallback(vault, session, listing, capsys):
    """Bug: a vault with no tier silently opens the desktop app."""
    assert secret_run.main(["metadata", "--vault", vault]) == 1
    assert "no tier" in capsys.readouterr().err
    assert listing == [] and session == []


def test_desktop_route_does_not_bypass_metadata_contract(monkeypatch, session, listing, capsys):
    monkeypatch.setenv(secret_run.ROUTE, secret_run.DESKTOP)
    assert secret_run.main(ARGS) == 1
    assert listing == [] and session == [] and capsys.readouterr().out == ""


@pytest.mark.parametrize("payload", [b"PRIVATE_ERROR", b"{}"])
def test_malformed_upstream_output_is_not_printed(monkeypatch, metadata_approval, capsys, payload):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, payload)
    )
    assert secret_run.main(["metadata", "--vault", "Everyday"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "PRIVATE_ERROR" not in err and "SECRET" not in err


def test_upstream_failure_does_not_print_diagnostics(monkeypatch, metadata_approval, capsys):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, b"PRIVATE_OUTPUT", b"PRIVATE_ERROR"),
    )
    assert secret_run.main(["metadata", "--vault", "Everyday"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "PRIVATE" not in err


def test_search_is_case_insensitive_and_no_matches_are_empty(monkeypatch, session, listing, capsys):
    monkeypatch.setenv(secret_run.ROUTE, secret_run.TIER_TWO)
    monkeypatch.setenv("SECRET_ASK_REASON", "Find item metadata")
    approve(monkeypatch, "approved")
    assert secret_run.main(["metadata", "--vault", "Production", "--search", "missing"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert len(listing) == 1


def test_excessive_response_is_suppressed(monkeypatch, metadata_approval, capsys):
    from slopmeister.session import secret_metadata

    monkeypatch.setattr(secret_metadata, "OUTPUT_LIMIT", 10)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, b"PRIVATE_RESPONSE_TOO_LARGE"),
    )
    assert secret_run.main(["metadata", "--vault", "Everyday"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "PRIVATE" not in err and "response limit" in err


def test_timeout_does_not_expose_partial_output(monkeypatch, metadata_approval, capsys):
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args, 60, output=b"PRIVATE", stderr=b"SECRET")

    monkeypatch.setattr(subprocess, "run", timed_out)
    assert secret_run.main(["metadata", "--vault", "Everyday"]) == 1
    out, err = capsys.readouterr()
    assert out == "" and "PRIVATE" not in err and "SECRET" not in err


def test_tier_one_metadata_also_requires_the_ha_approval(session, listing, capsys):
    assert secret_run.main(["metadata", "--vault", "Everyday"]) == 1
    assert "op tier-two" in capsys.readouterr().err
    assert listing == [] and session == []


def test_tier_one_uses_its_own_token_after_approval(metadata_approval, monkeypatch, capsys):
    from tests.support.op_session import ONE

    calls = []
    item = ITEM | {"vault": {"id": "idone", "name": "Everyday"}}

    def listed(argv, **kwargs):
        calls.append(kwargs["env"][secret_run.TOKEN])
        return subprocess.CompletedProcess(argv, 0, json.dumps([item]).encode())

    monkeypatch.setattr(subprocess, "run", listed)
    assert secret_run.main(["metadata", "--vault", "Everyday"]) == 0
    assert len(metadata_approval) == 1 and calls == [ONE]
    assert ONE not in capsys.readouterr().out


def test_unusual_title_does_not_block_the_vault_and_is_json_escaped(
    metadata_approval, monkeypatch, capsys
):
    unusual = ITEM | {"id": "other-id", "title": "Other\u00a0title\t\x1b"}
    payload = json.dumps([ITEM, unusual]).encode()
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, payload)
    )
    assert secret_run.main(ARGS) == 0
    assert [item["id"] for item in json.loads(capsys.readouterr().out)] == ["item-id"]
    assert secret_run.main(["metadata", "--vault", "Production"]) == 0
    out = capsys.readouterr().out
    assert len(json.loads(out)) == 2 and "\\u00a0" in out and "\\u001b" in out
    assert "\x1b" not in out and "\t" not in out


@pytest.mark.parametrize("field", ["id", "title", "category", "vault.id", "vault.name"])
@pytest.mark.parametrize("invalid", [None, "", 42])
def test_incomplete_item_preserves_matches(metadata_approval, monkeypatch, capsys, field, invalid):
    malformed = ITEM | {"id": "PRIVATE_ID", "title": "PRIVATE_TITLE", "vault": dict(ITEM["vault"])}
    target = malformed["vault"] if field.startswith("vault.") else malformed
    key = field.rsplit(".", 1)[-1]
    if invalid is None:
        target.pop(key)
    else:
        target[key] = invalid
    payload = json.dumps([malformed, ITEM]).encode()
    done = subprocess.CompletedProcess([], 0, payload)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)
    vault = "idtwo" if field == "vault.name" else "Production"
    assert secret_run.main(["metadata", "--vault", vault, "--search", "service_admin"]) == 0
    out, err = capsys.readouterr()
    assert [row["id"] for row in json.loads(out)] == ["item-id"]
    assert f"skipped 1 item(s); missing fields: {field}\n" in err
    assert all(value not in out + err for value in ("PRIVATE", "SECRET_VALUE", TWO))


def test_all_incomplete_rows_report_count_and_fixed_labels(metadata_approval, monkeypatch, capsys):
    payload = json.dumps([{}, {"value": "SECRET"}, None, [], {"vault": "PRIVATE"}]).encode()
    done = subprocess.CompletedProcess([], 0, payload)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)
    assert secret_run.main(ARGS) == 0
    out, err = capsys.readouterr()
    assert json.loads(out) == []
    assert "skipped 5 item(s); missing fields: category, id, title, vault.id, vault.name\n" in err
    assert "SECRET" not in out + err and "PRIVATE" not in out + err


@pytest.mark.parametrize("scope", [{"id": "x", "name": "y"}, {"id": "x"}, {"name": "y"}])
@pytest.mark.parametrize("title", ["", ITEM["title"]])
def test_wrong_vault_aborts_all_output(metadata_approval, monkeypatch, capsys, scope, title):
    malformed = ITEM | {"title": title, "vault": scope}
    payload = json.dumps([ITEM, {}, malformed]).encode()
    done = subprocess.CompletedProcess([], 0, payload)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)
    assert secret_run.main(ARGS) == 1
    out, err = capsys.readouterr()
    assert out == "" and "outside the requested vault" in err
    assert "skipped" not in err
