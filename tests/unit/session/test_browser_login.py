"""Credential input stays bound to the page and never reaches native keyboard focus."""

import json
import subprocess

import pytest

from slopmeister.session import browser_login as browser
from slopmeister.session import browser_runtime as runtime
from slopmeister.session import browser_state as state

SECRET = "dummy-private-value"


@pytest.mark.parametrize("value", ["", "op://example/item/otp", "otpauth://seed", "ABCDEF"])
def test_unresolved_or_seed_otp_is_refused(monkeypatch, value):
    monkeypatch.setenv("BROWSER_LOGIN_OTP", value)
    with pytest.raises(ValueError, match="BROWSER_(CREDENTIAL|OTP)"):
        browser.fields([["#field", "BROWSER_LOGIN_OTP"]])


def test_generated_otp_keeps_leading_zeroes(monkeypatch):
    monkeypatch.setenv("BROWSER_LOGIN_OTP", "001234")
    assert browser.fields([["#otp", "BROWSER_LOGIN_OTP"]]) == [["#otp", "001234"]]


def test_unrelated_environment_is_refused():
    with pytest.raises(ValueError, match="FIELD_REFUSED"):
        browser.fields([["#password", "OP_SERVICE_ACCOUNT_TOKEN"]])


def test_values_use_private_stdin_not_child_environment_or_arguments(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", SECRET)
    monkeypatch.setenv("NODE_OPTIONS", SECRET)
    monkeypatch.setenv("OP_SERVICE_ACCOUNT_TOKEN", SECRET)

    def execute(argv, **options):
        assert SECRET not in json.dumps(argv) + json.dumps(options["env"])
        assert json.loads(options["input"])["value"] == SECRET
        return subprocess.CompletedProcess(argv, 0, '{"result":"BROWSER_LOGIN_SUBMITTED"}')

    monkeypatch.setattr(state.subprocess, "run", execute)
    assert state.execute(tmp_path, ["installed-node", "input.cjs"], {"value": SECRET}) == {
        "result": "BROWSER_LOGIN_SUBMITTED"
    }


def test_entry_preserves_explicit_preflight_refusal(tmp_path, monkeypatch, capsys):
    refusal = {
        "result": "BROWSER_BLOCKED",
        "phase": "preflight",
        "reason": "SUBMIT_UNAVAILABLE",
        "credential_input": False,
        "submission_attempted": False,
    }
    state.save(tmp_path, {"worktree": str(tmp_path)})
    monkeypatch.setattr(runtime, "owned", lambda _: tmp_path)
    monkeypatch.setattr(runtime, "request", lambda *_: refusal)
    monkeypatch.setenv("BROWSER_LOGIN_USERNAME", SECRET)
    code = browser.main(
        [
            "fill",
            str(tmp_path),
            "--step",
            json.dumps(
                {
                    "url": "https://example.com/",
                    "fields": [["#username", "BROWSER_LOGIN_USERNAME"]],
                    "submit": "#continue",
                }
            ),
        ]
    )
    output = capsys.readouterr()
    assert code == 1 and json.loads(output.out) == refusal
    assert SECRET not in output.out + output.err


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        '{"url": "https://example.com/", "fields": []}',
        '{"url": "http://example.com/", "fields": [], "submit": "#go"}',
        '{"url": "https://example.com/", "fields": "x", "submit": "#go"}',
        '{"url": "https://example.com/", "fields": [["#a"]], "submit": "#go"}',
        '{"url": "https://example.com/", "fields": [["#a", "OTHER"]], "submit": "#go"}',
        '{"url": "https://example.com/", "fields": [], "submit": "#go"}',
        '{"url": "https://example.com/", "fields": [["#a", "BROWSER_LOGIN_OTP"]], "submit": ""}',
        '{"url": "https://example.com/", "frame": "http://id.example/in", '
        '"fields": [["#a", "BROWSER_LOGIN_PASSWORD"]], "submit": "#go"}',
        '{"url": "https://example.com/", "frame": ["https://id.example/in"], '
        '"fields": [["#a", "BROWSER_LOGIN_PASSWORD"]], "submit": "#go"}',
        '{"url": "https://example.com/", "frames": "https://id.example/in", '
        '"fields": [["#a", "BROWSER_LOGIN_PASSWORD"]], "submit": "#go"}',
    ],
)
def test_malformed_steps_are_refused_before_any_value_is_read(monkeypatch, raw):
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", SECRET)
    with pytest.raises(ValueError, match="BROWSER_(STEP|URL|FIELD)"):
        browser.step(raw)


def test_a_login_of_more_steps_than_allowed_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", SECRET)
    monkeypatch.setattr(runtime, "request", lambda *_: pytest.fail("credential input started"))
    state.save(tmp_path, {"worktree": str(tmp_path)})
    valid = json.dumps(
        {
            "url": "https://example.com/",
            "fields": [["#p", "BROWSER_LOGIN_PASSWORD"]],
            "submit": "#go",
        }
    )
    args = browser.arguments(["fill", str(tmp_path), *["--step", valid] * browser.MAX_STEPS])
    args.step.append(valid)
    with pytest.raises(ValueError, match="STEP_REFUSED"):
        browser.fill(tmp_path, args)


def test_each_step_carries_its_own_destination_and_stored_fields_hold_no_value(
    tmp_path, monkeypatch
):
    state.save(tmp_path, {"worktree": str(tmp_path)})
    monkeypatch.setenv("BROWSER_LOGIN_USERNAME", "dummy-user")
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", SECRET)
    sent = {}
    monkeypatch.setattr(runtime, "request", lambda _, payload: sent.update(payload) or {})
    raw = [
        {
            "url": "https://id.example/name",
            "fields": [["#u", "BROWSER_LOGIN_USERNAME"]],
            "submit": "#n",
        },
        {
            "url": "https://id.example/pass",
            "fields": [["#p", "BROWSER_LOGIN_PASSWORD"]],
            "submit": "#s",
        },
    ]
    args = browser.arguments(
        ["fill", str(tmp_path), *[a for r in raw for a in ("--step", json.dumps(r))]]
    )
    browser.fill(tmp_path, args)
    assert [s["path"] for s in sent["steps"]] == ["/name", "/pass"]
    assert sent["steps"][1]["fields"][0]["types"] == ["password"]
    stored = (tmp_path / "owner.json").read_text()
    assert SECRET not in stored and json.loads(stored)["credential_fields"] == ["#p"]


@pytest.mark.parametrize(
    ("code", "shares"),
    [("001234", ["0", "0", "1", "2", "3", "4"]), ("00123456", ["0012", "3456"])],
    ids=["six-boxes", "two-boxes-of-four"],
)
def test_a_split_code_gives_each_box_its_share_and_guards_every_box(
    tmp_path, monkeypatch, code, shares
):
    state.save(tmp_path, {"worktree": str(tmp_path)})
    monkeypatch.setenv("BROWSER_LOGIN_OTP", code)
    sent = {}
    monkeypatch.setattr(runtime, "request", lambda _, payload: sent.update(payload) or {})
    boxes = [f"#d{i}" for i in range(len(shares))]
    raw = {
        "url": "https://id.example/mfa",
        "fields": [[boxes, "BROWSER_LOGIN_OTP"]],
        "submit": "#v",
    }
    browser.fill(tmp_path, browser.arguments(["fill", str(tmp_path), "--step", json.dumps(raw)]))
    fields = sent["steps"][0]["fields"]
    assert [(f["selector"], f["value"]) for f in fields] == list(zip(boxes, shares, strict=True))
    stored = (tmp_path / "owner.json").read_text()
    assert code not in stored and json.loads(stored)["credential_fields"] == boxes


@pytest.mark.parametrize(
    ("group", "variable", "code"),
    [
        (["#a", "#b"], "BROWSER_LOGIN_PASSWORD", "001234"),
        ([f"#d{i}" for i in range(5)], "BROWSER_LOGIN_OTP", "001234"),
        (["#a", "#" + "b" * browser.GROUP_SELECTOR_LIMIT], "BROWSER_LOGIN_OTP", "001234"),
        (["#a", ""], "BROWSER_LOGIN_OTP", "001234"),
        (["#a", 1], "BROWSER_LOGIN_OTP", "001234"),
        (["#a", "#b", "#c", "#d"], "BROWSER_LOGIN_OTP", "001234"),
    ],
    ids=["not-a-code", "five-boxes", "long-selector", "empty", "not-text", "uneven-share"],
)
def test_a_code_group_that_cannot_hold_the_code_is_refused(monkeypatch, group, variable, code):
    monkeypatch.setenv(variable, code)
    raw = json.dumps(
        {"url": "https://id.example/mfa", "fields": [[group, variable]], "submit": "#v"}
    )
    with pytest.raises(ValueError, match="BROWSER_FIELD_REFUSED"):
        browser.step(raw)


@pytest.mark.parametrize(("count", "accepted"), [(3, True), (5, False), (8, True), (9, False)])
def test_check_accepts_only_box_counts_a_supported_code_divides(count, accepted):
    raw = {"url": "https://id.example/mfa", "submit": "#v"}
    raw["fields"] = [[[f"#d{i}" for i in range(count)], "BROWSER_LOGIN_OTP"]]
    if accepted:
        assert len(browser.step(json.dumps(raw), resolved=False)["fields"]) == count
    else:
        with pytest.raises(ValueError, match="BROWSER_FIELD_REFUSED"):
            browser.step(json.dumps(raw), resolved=False)


def test_a_named_frame_adds_its_own_destination_and_a_step_without_one_is_unchanged(monkeypatch):
    monkeypatch.setenv("BROWSER_LOGIN_PASSWORD", SECRET)
    top = {"url": "https://example.com/login", "fields": [["#p", "BROWSER_LOGIN_PASSWORD"]]}
    plain = browser.step(json.dumps({**top, "submit": "#s"}))
    framed = browser.step(json.dumps({**top, "frame": "https://id.example/in?x=1", "submit": "#s"}))
    assert set(plain) == {"origin", "path", "fields", "submit"}
    assert framed == {**plain, "frame": {"origin": "https://id.example", "path": "/in"}}


STEP = {
    "url": "https://example.com/login",
    "fields": [["#p", "BROWSER_LOGIN_PASSWORD"]],
    "submit": "#s",
}


def test_check_runs_before_approval_with_no_secret_and_only_the_page_in_front_of_it(
    tmp_path, monkeypatch, capsys
):
    state.save(tmp_path, {"worktree": str(tmp_path)})
    monkeypatch.delenv("BROWSER_LOGIN_PASSWORD", raising=False)
    monkeypatch.setattr(runtime, "owned", lambda _: tmp_path)
    sent = {}
    monkeypatch.setattr(
        runtime,
        "request",
        lambda _, payload: sent.update(payload) or {"result": "BROWSER_FILL_READY"},
    )
    later = {**STEP, "url": "https://example.com/code"}
    code = browser.main(
        ["check", str(tmp_path), "--step", json.dumps(STEP), "--step", json.dumps(later)]
    )
    assert code == 0 and json.loads(capsys.readouterr().out)["result"] == "BROWSER_FILL_READY"
    assert sent["action"] == "check" and [s["path"] for s in sent["steps"]] == ["/login"]
    assert sent["steps"][0]["fields"] == [{"selector": "#p", "value": "", "types": ["password"]}]
    assert "credential_fields" not in json.loads((tmp_path / "owner.json").read_text())


def test_check_refuses_a_step_fill_would_refuse(tmp_path, monkeypatch):
    state.save(tmp_path, {"worktree": str(tmp_path)})
    monkeypatch.setattr(runtime, "request", lambda *_: pytest.fail("the page was checked"))
    bad = {**STEP, "fields": [["#p", "OP_SERVICE_ACCOUNT_TOKEN"]]}
    args = browser.arguments(["check", str(tmp_path), "--step", json.dumps(bad)])
    with pytest.raises(ValueError, match="FIELD_REFUSED"):
        browser.check(tmp_path, args)


def test_a_refused_check_exits_nonzero(tmp_path, monkeypatch, capsys):
    state.save(tmp_path, {"worktree": str(tmp_path)})
    monkeypatch.setattr(runtime, "owned", lambda _: tmp_path)
    refusal = {"result": "BROWSER_BLOCKED", "reason": "WRONG_DESTINATION"}
    monkeypatch.setattr(runtime, "request", lambda *_: refusal)
    code = browser.main(["check", str(tmp_path), "--step", json.dumps(STEP)])
    assert code == 1 and json.loads(capsys.readouterr().out) == refusal


@pytest.mark.parametrize("flag", [[], ["--private-display"]])
def test_start_passes_the_profile_and_the_private_display_choice_to_the_runtime(
    monkeypatch, capsys, flag
):
    # Without it, the route that BROWSER_NO_MONITOR names would refuse again with the same result.
    seen = []
    monkeypatch.setattr(runtime, "start", lambda *args: seen.append(args) or {})
    assert browser.main(["start", "--profile", "plot", *flag, "https://example.com/"]) == 0
    assert seen == [("https://example.com/", "plot", bool(flag))]


def test_start_without_a_profile_is_refused(capsys):
    with pytest.raises(SystemExit):
        browser.main(["start", "https://example.com/"])
