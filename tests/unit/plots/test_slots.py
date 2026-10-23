"""Plot slot declarations reject collisions and unsafe shell-facing values."""

import pytest

from slopmeister.plots import slot_rows, validate
from tests.unit.plots.cases import PATH, VALID, change


@pytest.mark.parametrize("value", [False, 0, 1, "true", [], {}])
def test_none_means_boolean_true_only(value):
    with pytest.raises(ValueError, match="slots.none"):
        validate(change("slots", {"none": value}), PATH)


@pytest.mark.parametrize("key,value", [("max", 6), ("compose", "a.yml"), ("ports", {})])
def test_none_cannot_discard_any_sibling_even_an_empty_table(key, value):
    with pytest.raises(ValueError, match="slots.none"):
        validate(change("slots", {"none": True, key: value}), PATH)


@pytest.mark.parametrize("value", [0, 100, True, 1.0, "6", 10**30, [], None])
def test_max_is_a_bounded_integer_not_a_boolean_or_coercion(value):
    with pytest.raises(ValueError, match="slots.max"):
        validate(change("slots.max", value), PATH)


@pytest.mark.parametrize("maximum", [1, 99])
def test_max_boundaries_and_omitted_default(maximum):
    assert slot_rows(validate(change("slots.max", maximum), PATH))[-1] == f"slots\tmax\t{maximum}"
    assert slot_rows(validate(VALID, PATH))[-1] == "slots\tmax\t6"


@pytest.mark.parametrize("kind", ["ports"])
@pytest.mark.parametrize(
    "key",
    [
        "a",
        "_A",
        "A-B",
        "A\n",
        "SLOT",
        "SLOT_TARGET",
        "SLOT_NAME",
        "SLOT_PROJECT",
        "SLOT_DATA",
        "SLOT_COMPOSE",
    ],
)
def test_variable_cannot_override_allocation_or_inject_env(kind, key):
    with pytest.raises(ValueError, match="slots." + kind):
        validate(change("slots." + kind, {key: 45432}), PATH)


@pytest.mark.parametrize("kind", ["ports"])
@pytest.mark.parametrize("port", [1023, 65536, True, 1024.0, "45432", 10**30, {}, None])
def test_port_is_strictly_typed_and_bounded(kind, port):
    with pytest.raises(ValueError, match="slots." + kind):
        validate(change("slots." + kind, {"TEST": port}), PATH)


@pytest.mark.parametrize(
    "slots",
    [
        {},
        {"max": 2},
        {"ports": {}},
        {"compose": "a.yml"},
        {"ports": {"A": 65535}},
        {"ports": {"A": 45432, "B": 45432}},
        {"ports": {"A": 45432}, "fixed": {"B": 48000}},
    ],
)
def test_empty_overflowing_or_colliding_resource_set_cannot_allocate(slots):
    with pytest.raises(ValueError, match="slots"):
        validate(change("slots", slots), PATH)


@pytest.mark.parametrize("offset", [1, 2, -1, -2])
def test_parallel_slots_cannot_reserve_the_same_port_before_apps_start(offset):
    slots = {"max": 3, "ports": {"A": 45432, "B": 45432 + offset}}
    with pytest.raises(ValueError, match="collide") as error:
        validate(change("slots", slots), PATH)
    assert str(PATH) in str(error.value) and "slots.ports." in str(error.value)


@pytest.mark.parametrize(
    "slots",
    [
        {"max": 3, "ports": {"A": 45432, "B": 45435}},
        {"max": 1, "ports": {"A": 45432, "B": 45433}},
    ],
)
def test_disjoint_ranges_and_single_live_allocation_remain_valid(slots):
    assert validate(change("slots", slots), PATH)["slots"] == slots


@pytest.mark.parametrize(
    "path", ["", "/a", "../a", "x/../a", "a\n", "a\t", "a\x00", "a\x1b", True, [], 1]
)
def test_compose_cannot_escape_or_inject_a_row(path):
    with pytest.raises(ValueError, match="slots.compose"):
        validate(change("slots.compose", path), PATH)


def test_literal_compose_spaces_and_metacharacters_are_not_shell_code():
    data = validate(change("slots.compose", "docker/$(touch sentinel) stack.yml"), PATH)
    assert "compose\t-\tdocker/$(touch sentinel) stack.yml" in slot_rows(data)


@pytest.mark.parametrize(
    "slots",
    [
        {"ports": {"LOW": 1024, "HIGH": 65534}, "max": 1},
    ],
)
def test_valid_port_boundaries_are_not_overrestricted(slots):
    assert validate(change("slots", slots), PATH)


def test_setup_and_separate_tester_range_are_optional_and_reported():
    slots = {
        "max": 2,
        "testers": 1,
        "ports": {"WEB": 45100},
        "setup": ["python3", "prepare.py"],
        "setup_files": [".env.local", ".hooks/generated"],
    }
    data = validate(change("slots", slots), PATH)
    assert data["slots"] == slots
    assert "slots\ttesters\t1" in slot_rows(data)
    assert 'setup\t-\t["python3", "prepare.py"]' in slot_rows(data)


@pytest.mark.parametrize("testers", [-1, 100, True, "1"])
def test_tester_count_is_a_bounded_integer(testers):
    with pytest.raises(ValueError, match="slots.testers: expected an integer"):
        validate(change("slots.testers", testers), PATH)


def test_tester_range_participates_in_port_collisions_and_slot_limit():
    slots = {"max": 2, "testers": 1, "ports": {"A": 45100, "B": 45102}}
    with pytest.raises(ValueError, match="collide"):
        validate(change("slots", slots), PATH)
    slots = {"max": 99, "testers": 1, "ports": {"A": 45100}}
    with pytest.raises(ValueError, match="together exceed"):
        validate(change("slots", slots), PATH)


@pytest.mark.parametrize("command", ["prepare", [], [""], ["x\n"], [1]])
def test_setup_is_an_argument_array_without_control_characters(command):
    with pytest.raises(ValueError, match="slots.setup: expected a nonempty argument array"):
        validate(change("slots.setup", command), PATH)


@pytest.mark.parametrize("output", ["/tmp/out", "../out", ".git/config", ".slot.env", "x//y"])
def test_setup_output_paths_cannot_replace_metadata_or_escape(output):
    slots = {**VALID["slots"], "setup": ["prepare"], "setup_files": [output]}
    with pytest.raises(ValueError, match="relative output paths"):
        validate(change("slots", slots), PATH)


def test_setup_files_require_a_command_and_unique_names():
    with pytest.raises(ValueError, match="requires setup"):
        validate(change("slots.setup_files", [".env"]), PATH)
    slots = {**VALID["slots"], "setup": ["prepare"], "setup_files": [".env", ".env"]}
    with pytest.raises(ValueError, match="unique outputs"):
        validate(change("slots", slots), PATH)
