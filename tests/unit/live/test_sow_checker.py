"""Deterministic coverage for the live sow message checker."""

import pytest

from tests.live.test_sow_smoke import opening_faults

FORK = "- Keep notes local on this computer, or sync across devices. I recommend local."
MESSAGE = f"""**Goal** Your notes are still there the next time you start the app.
**Plan** I save the notes to one file and load them at start.
**Your call**
{FORK}
**Risk** A crash while saving could lose the last note.

**Details**
- Read: notes.py, README.md
- Proof: `python notes.py` prints the saved note
- Left out: sync. Full plan in SMOKE-1-NOTES.md.
"""


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
        MESSAGE.replace("at start.", "at start. " + "word " * 98),
        MESSAGE + "word " * 277,
    ],
    ids=[
        "plain",
        "heading_label",
        "label_on_own_line",
        "sync_alone",
        "labelled_pick",
        "slash",
        "pick_with_negative_comparison",
        "summary_at_150_words",
        "message_at_350_words",
    ],
)
def test_the_plain_opening_is_accepted(reply):
    assert opening_faults(reply) == []


@pytest.mark.parametrize(
    ("reply", "fault"),
    [
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
        (MESSAGE.replace("at start.", "at start. " + "word " * 99), "summary exceeds"),
        (MESSAGE + "word " * 278, "message exceeds"),
        ("Where we stand: nothing is built yet.\n\n" + MESSAGE, "before Goal"),
        (MESSAGE.replace(" A crash while saving could lose the last note.", ""), "part is empty"),
    ],
    ids=[
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
        MESSAGE.replace("I recommend local.", "I recommend local. I recommend sync."),
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
        "two_recommendations",
        "excluded_option",
        "options_outside_your_call",
    ],
)
def test_a_decided_or_buried_fork_is_rejected(reply):
    """Escaping bug: a reply that decides first, or buries the decision, passes the paid smoke."""
    assert opening_faults(reply)
