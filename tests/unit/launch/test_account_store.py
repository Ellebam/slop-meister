"""A Claude start follows Orca's account switcher by the rule of Orca's own `claude` function."""

import pytest

from slopmeister import paths
from slopmeister.errors import SlopmeisterError
from slopmeister.launch import workspace
from slopmeister.launch.model import Launch, Stop

STORE = "CLAUDE_CONFIG_DIR"
POINTER = "ORCA_CLAUDE_PROFILE_POINTER"
INJECTED = "ORCA_CLAUDE_INJECTED_CONFIG_DIR"
USER = "ORCA_CLAUDE_USER_CONFIG_DIR"


@pytest.fixture
def homes(tmp_path, monkeypatch):
    """Two account homes, the operator's own store and a pointer file Orca would write."""
    for name in ("first", "second", "own"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv(POINTER, str(tmp_path / "selected-host"))
    return tmp_path


def _select(homes, text: str) -> None:
    (homes / "selected-host").write_text(text.format(root=homes))


@pytest.mark.parametrize(
    ("selection", "env", "expected"),
    [
        # A terminal on System default starts on the account selected now.
        ("{root}/first\n", {}, ("first", True)),
        # A dispatcher that runs on the first account starts workers on the second.
        ("{root}/second\n", {STORE: "{root}/first", INJECTED: "{root}/first"}, ("second", True)),
        # The operator's own store wins, also where Orca injected another one earlier.
        ("{root}/first\n", {STORE: "{root}/own"}, ("own", False)),
        ("{root}/first\n", {STORE: "{root}/own", INJECTED: "{root}/second"}, ("own", False)),
        # Orca recorded this store as the terminal's own, so the selection replaces it.
        ("{root}/first\n", {STORE: "{root}/own", USER: "{root}/own/"}, ("first", True)),
        # System default drops the account Orca injected and restores the terminal's own store.
        ("", {STORE: "{root}/first", INJECTED: "{root}/first"}, (None, False)),
        (
            "\n",
            {STORE: "{root}/first", INJECTED: "{root}/first", USER: "{root}/own"},
            ("own", False),
        ),
        # Orca removes the file when it manages no account.
        (None, {STORE: "{root}/first", INJECTED: "{root}/first"}, (None, False)),
        (None, {}, (None, False)),
    ],
)
def test_store_follows_orcas_rule(homes, monkeypatch, selection, env, expected):
    """Bug: a launch line bypasses Orca's function and starts Claude on another account."""
    if selection is not None:
        _select(homes, selection)
    for name, value in env.items():
        monkeypatch.setenv(name, value.format(root=homes))
    name, switched = expected
    assert paths.claude_store(homes) == (homes / name if name else None, switched)


def test_no_pointer_variable_keeps_the_old_rule(homes, monkeypatch):
    """Bug: a launch outside an Orca terminal changes, or a relative store loses its base."""
    monkeypatch.delenv(POINTER)
    assert paths.claude_store(homes) == (None, False)
    monkeypatch.setenv(STORE, "own")
    assert paths.claude_store(homes) == ((homes / "own").resolve(), False)
    monkeypatch.setenv(STORE, "")
    with pytest.raises(SlopmeisterError, match="CLAUDE_CONFIG_DIR is empty"):
        paths.claude_store(homes)


def test_pointer_below_the_home_folder_is_expanded(homes, monkeypatch):
    """Bug: Orca's `~/` pointer spelling reads as a missing file and selects System default."""
    monkeypatch.setenv("HOME", str(homes))
    monkeypatch.setenv(POINTER, "~/selected-host")
    _select(homes, "{root}/first\n")
    assert paths.claude_store(homes) == (homes / "first", True)


@pytest.mark.parametrize("selection", ["{root}/gone\n", "first\n", "{root}/selected-host\n"])
def test_unusable_selection_stops_and_names_it(homes, selection):
    """Bug: a selection without its folder falls back silently to another account."""
    _select(homes, selection)
    with pytest.raises(SlopmeisterError, match="not an existing directory.*in Orca") as stop:
        paths.claude_store(homes)
    assert selection.format(root=homes).strip("\n") in str(stop.value)


@pytest.mark.parametrize(
    ("control", "shown", "exists"),
    [("\x1b[2J", "\\x1b[2J", False), ("\x00", "\\x00", False), ("\x1b[2J", "\\x1b[2J", True)],
)
def test_a_selection_with_a_control_character_stops_and_is_shown_escaped(
    homes, control, shown, exists
):
    """Bug: a control sequence in a selected name reaches the terminal, also from a real folder."""
    if exists:
        (homes / f"first{control}").mkdir()
    _select(homes, "{root}/first" + control)
    with pytest.raises(SlopmeisterError, match="non-printable character") as stop:
        paths.claude_store(homes)
    assert control not in str(stop.value) and f"first{shown}" in str(stop.value)


def test_unreadable_pointer_stops(homes):
    """Bug: a pointer that cannot be read counts as System default."""
    (homes / "selected-host").mkdir()
    with pytest.raises(SlopmeisterError, match="cannot read Orca's Claude account selection"):
        paths.claude_store(homes)


def test_abandon_never_reads_the_selection(homes):
    """Bug: an unusable selection blocks the abandon of a worker, which starts no session."""
    _select(homes, "{root}/gone\n")
    launch = Launch("example-client", "example-client-one", "/repo")
    launch.claude_wt = homes
    with pytest.raises(Stop, match="not an existing directory"):
        workspace.claude_store(launch)
    launch.abandon = True
    workspace.claude_store(launch)
    assert launch.claude_root is None
