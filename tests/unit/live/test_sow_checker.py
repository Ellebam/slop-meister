"""Deterministic coverage for the live sow smoke helpers."""

import pytest

from tests.live.test_sow_smoke import environment, opening_faults


def test_this_computer_only_is_a_local_option():
    reply = MESSAGE.replace(
        FORK,
        "- A, this computer only. Small and offline.\n"
        "- B, sync across devices. More setup.\nI recommend A.",
    )
    assert opening_faults(reply) == []


FORK = "- Keep notes local on this computer, or sync across devices. I recommend local."
MESSAGE = f"""**Goal** Your notes are still there the next time you start the app.
**Plan** I save the notes to one file and load them at start.
**Your call**
{FORK}
**Risk** A crash while saving could lose the last note.
**Proof:** Run the app twice and check the saved note remains.

**Details**
- Read: notes.py, README.md
- Proof: `python notes.py` prints the saved note
- Left out: sync. Full plan in SMOKE-1-NOTES.md.
"""


def test_environment_keeps_codex_home_but_drops_parent_tool_call_and_orca(monkeypatch):
    monkeypatch.setenv("SMOKE_KEEP", "ordinary")
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "fixture-terminal")
    monkeypatch.setenv("ORCA_AGENT_HOOK_TOKEN", "fixture-token")
    monkeypatch.setenv("ORCA_FUTURE_OPTION", "fixture-option")
    monkeypatch.setenv("CODEX_TOOL_CALL_ID", "parent-call")
    monkeypatch.setenv("CODEX_HOME", "/fixture/codex-home")

    child = environment()

    assert child["SMOKE_KEEP"] == "ordinary"
    assert child["CODEX_HOME"] == "/fixture/codex-home"
    assert "CODEX_TOOL_CALL_ID" not in child
    assert not any(key.startswith("ORCA_") for key in child)


@pytest.mark.parametrize(
    "reply",
    [
        MESSAGE,
        MESSAGE.replace("**Your call**", "### Your call"),
        MESSAGE.replace("**Goal** ", "Goal\n"),
        MESSAGE.replace("or sync across devices", "or sync, which adds accounts"),
        MESSAGE.replace(
            FORK, "- Option A, local file.\n- Option B, sync across devices.\n- I recommend A."
        ),
        MESSAGE.replace(
            "one file", "one file (e.g. a text file of 3.5 MB) by 10:30, and/or a backup"
        ),
        MESSAGE.replace("I recommend local.", "I recommend local. I do not recommend sync."),
        MESSAGE.replace(
            "I recommend local.",
            "I recommend local. Reply local to approve the recommended plan.",
        ),
        MESSAGE.replace("I recommend local.", "My recommendation is local."),
        MESSAGE.replace("I recommend local.", "This plan recommends local."),
        MESSAGE.replace("I recommend local.", "Local storage is recommended."),
        MESSAGE.replace(
            FORK, "- Local only: small, private, no accounts. Recommended.\n- Sync across devices."
        ),
        MESSAGE.replace(FORK, "- Local on this computer (recommended).\n- Sync across devices."),
        MESSAGE.replace(
            FORK, "- Option A (recommended), local file.\n- Option B, sync across devices."
        ),
        MESSAGE.replace("I recommend local.", "Local files are recommended."),
        MESSAGE.replace(FORK, "- **Local, recommended:** Offline.\n- **Sync:** Across devices."),
        MESSAGE.replace("at start.", "at start. " + "word " * 87),
        MESSAGE + "word " * 266,
    ],
    ids=[
        "plain",
        "heading_label",
        "label_on_own_line",
        "sync_alone",
        "labelled_pick",
        "slash",
        "pick_with_negative_comparison",
        "recommended_plan_is_not_another_pick",
        "noun_pick",
        "third_person_pick",
        "passive_pick",
        "standalone_recommended",
        "recommended_option_label",
        "recommended_letter_label",
        "plural_passive_pick",
        "bold_option_label",
        "summary_at_150_words",
        "message_at_350_words",
    ],
)
def test_the_plain_opening_is_accepted(reply):
    assert opening_faults(reply) == []


@pytest.mark.parametrize(
    ("reply", "fault"),
    [
        (
            MESSAGE.replace("**Proof:** Run the app twice and check the saved note remains.\n", ""),
            "Details is missing or out of order",
        ),
        (MESSAGE.replace("one file", "notes.json"), "a file path"),
        (MESSAGE.replace("one file", "src/store/notes"), "a file path"),
        (MESSAGE.replace("one file", "one file in ~/notes"), "a file path"),
        (MESSAGE.replace("at start", "at start, see line 3"), "a line reference"),
        (MESSAGE.replace("at start", "at start, see store:12"), "a line reference"),
        (MESSAGE.replace("at start", "at start, as in 5a77a679"), "a commit hash"),
        (MESSAGE.replace("one file", "one file with `json.dump`"), "code or a command"),
        (MESSAGE.replace("**Risk**", "```\npython notes.py\n```\n**Risk**"), "code or a command"),
        (MESSAGE.replace("I save", "In Step 4 I save"), "a step name"),
        (MESSAGE.replace("one file", "NOTES.PY"), "a file path"),
        (MESSAGE.replace("one file", "notes.csv"), "a file path"),
        (MESSAGE.replace("one file", "notes.sqlite3"), "a file path"),
        (MESSAGE.replace("one file", "one file, see https://example.invalid/notes"), "a link"),
        (MESSAGE.replace("at start.", "at start. " + "word " * 88), "summary exceeds"),
        (MESSAGE + "word " * 267, "message exceeds"),
        ("Where we stand: nothing is built yet.\n\n" + MESSAGE, "before Goal"),
        (MESSAGE.replace(" A crash while saving could lose the last note.", ""), "part is empty"),
    ],
    ids=[
        "proof_only_in_details",
        "file_name",
        "path",
        "home_path",
        "line_reference",
        "colon_line_reference",
        "commit_hash",
        "inline_code",
        "fenced_command",
        "capitalised_step_name",
        "capitalised_file_name",
        "any_file_ending",
        "long_file_ending",
        "link",
        "summary_over_budget",
        "message_over_budget",
        "prose_before_goal",
        "empty_part",
    ],
)
def test_an_unreadable_summary_is_rejected(reply, fault):
    """Escaping bug: a summary that passes the shape check and cannot be read."""
    assert [found for found in opening_faults(reply) if fault in found]


@pytest.mark.parametrize(
    "reply",
    [
        MESSAGE.replace("**Risk**", "**Details**").replace("\n**Details**\n", "\n**Risk** x\n", 1),
        MESSAGE.replace(f"**Your call**\n{FORK}\n", "") + f"**Your call**\n{FORK}\n",
        MESSAGE[: MESSAGE.index("**Details**")],
        MESSAGE.replace(", or sync across devices", ""),
        MESSAGE.replace(" I recommend local.", ""),
        MESSAGE.replace("I recommend local.", "No recommendation until you decide."),
        MESSAGE.replace("I recommend local.", "\n- I recommend waiting for your decision."),
        MESSAGE.replace("I recommend local.", "I do not recommend local."),
        MESSAGE.replace(FORK, "- Local only. Not recommended.\n- Sync across devices."),
        MESSAGE.replace(FORK, "- Local only. Recommended.\n- Sync across devices. Recommended."),
        MESSAGE.replace("I recommend local.", "I recommend local. I recommend sync."),
        MESSAGE.replace("I recommend local.", "I recommend local. My recommendation is sync."),
        MESSAGE.replace("I recommend local.", "I recommend local. The readme recommends sync."),
        MESSAGE.replace("I recommend local.", "I recommend local. Sync is recommended too."),
        MESSAGE.replace(
            FORK, "- Local on this computer (recommended).\n- Sync across devices (recommended)."
        ),
        MESSAGE.replace(
            FORK,
            "- Local on this computer (recommended).\n- Sync across devices.\n"
            "- Sync files are recommended too.",
        ),
        MESSAGE.replace(
            FORK,
            "- Choose local storage or sync across devices.\n"
            "- I recommend waiting for your decision.\n"
            "- Reply local or sync to approve the recommended plan.",
        ),
        MESSAGE.replace(FORK, "- Local on this computer. Sync is excluded. I recommend local."),
        MESSAGE.replace(FORK, "- Nothing, reply go.").replace(
            "- Left out: sync.", f"{FORK}\n- Left out: nothing."
        ),
    ],
    ids=[
        "parts_out_of_order",
        "decision_below_the_detail",
        "no_details",
        "one_option",
        "no_recommendation",
        "refused_recommendation",
        "recommends_waiting",
        "negated_recommendation",
        "negated_standalone_recommendation",
        "two_standalone_recommendations",
        "two_recommendations",
        "two_recommendations_noun",
        "two_recommendations_third_person",
        "two_recommendations_passive",
        "two_recommended_labels",
        "recommended_label_and_plural_passive",
        "waiting_with_adjective_line",
        "excluded_option",
        "options_outside_your_call",
    ],
)
def test_a_decided_or_buried_fork_is_rejected(reply):
    """Escaping bug: a reply that decides first, or buries the decision, passes the paid smoke."""
    assert opening_faults(reply)
