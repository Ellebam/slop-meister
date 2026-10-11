"""Plot policy validation cannot infer permissions or provenance."""

from copy import deepcopy

import pytest

from slopmeister.plots import validate
from tests.unit.plots.cases import PATH, VALID, change


@pytest.mark.parametrize(
    "actions", ["jira-assigned", ["*"], ["../other"], [1], ["jira-assigned", "jira-assigned"]]
)
def test_service_actions_cannot_enable_wildcards_duplicates_or_paths(actions):
    with pytest.raises(ValueError, match="service_actions"):
        validate(change("target.service_actions", actions), PATH)


@pytest.mark.parametrize("actions", [[], ["jira-assigned"]])
def test_service_actions_require_an_explicit_unique_declaration(actions):
    result = validate(change("target.service_actions", actions), PATH)
    assert result["target"]["service_actions"] == actions


@pytest.mark.parametrize(
    "key",
    ["plot", "plot.base", "target.tasks", "target.repository.commit", "slots"],
)
def test_missing_required_field_never_infers_policy(key):
    with pytest.raises(ValueError, match=key.replace(".", r"\.")) as error:
        validate(change(key, None, remove=True), PATH)
    assert str(PATH) in str(error.value)


@pytest.mark.parametrize("key", ["plot", "target", "target.repository", "slots", "slots.ports"])
@pytest.mark.parametrize("bad", [None, True, 1, "text", [], [{"commit": "allow"}]])
def test_wrong_table_shape_cannot_bypass_required_checks(key, bad):
    with pytest.raises(ValueError, match=key.replace(".", r"\.")):
        validate(change(key, bad), PATH)


@pytest.mark.parametrize("key", ["", "plot", "target", "target.repository", "slots"])
def test_unknown_keys_are_rejected_at_every_depth(key):
    data = deepcopy(VALID)
    parent = data
    for part in key.split(".") if key else []:
        parent = parent[part]
    parent["typo"] = True
    with pytest.raises(ValueError, match="typo"):
        validate(data, PATH)


@pytest.mark.parametrize(
    "key,values",
    [
        ("plot.base", ["", "../code", "Code", "code\n", "cоde", False, [], 1]),
        ("target.tasks", ["githb", "GitHub", "github ", "github\n", "", True, [], 1]),
        ("target.repository.commit", ["yes", "ALLOW", "allow\n", "", True, [], 1]),
    ],
)
def test_invalid_scalar_cannot_select_a_policy_or_inject_output(key, values):
    for value in values:
        with pytest.raises(ValueError, match=key.replace(".", r"\.")):
            validate(change(key, value), PATH)


@pytest.mark.parametrize("seed", [None, False, True])
@pytest.mark.parametrize("base", ["code", "inject", "freeform"])
@pytest.mark.parametrize("permission", ["allow", "deny"])
@pytest.mark.parametrize("tasks", ["github", "vault", "manual"])
def test_provenance_cannot_choose_template_permission_or_tasks(seed, base, permission, tasks):
    """Bug: freeform workers could not use a repository worktree."""
    data = deepcopy(VALID)
    data["plot"]["base"] = base
    if seed is not None:
        data["plot"]["seed"] = seed
    data["target"].update(tasks=tasks, repository={"commit": permission})
    assert validate(data, PATH) == data


def test_repository_default_path_is_explicit_and_safe():
    """Bug: a repo-capable area plot could not declare its local default worktree source."""
    data = change("target.repository.default", "~/projects/example-notes")
    assert validate(data, PATH) == data
    for bad in ("", "example-notes", "../dev", "~/../dev", "/tmp/../dev", "~/dev\nother", True):
        with pytest.raises(ValueError, match="target.repository.default"):
            validate(change("target.repository.default", bad), PATH)


@pytest.mark.parametrize("seed", [None, 0, 1, "true", [], {}])
def test_seed_history_is_a_boolean_not_a_runtime_selector(seed):
    with pytest.raises(ValueError, match="plot.seed"):
        validate(change("plot.seed", seed), PATH)


@pytest.mark.parametrize("delivery", ["inject", "seed", "committed"])
def test_retired_delivery_field_cannot_restore_an_old_path(delivery):
    with pytest.raises(ValueError, match="target.repository.delivery"):
        validate(change("target.repository.delivery", delivery), PATH)


@pytest.mark.parametrize("seed", [False, True])
def test_directory_provenance_does_not_create_repository_permission(seed):
    data = {
        "plot": {"base": "freeform", "seed": seed},
        "target": {"tasks": "vault"},
    }
    assert validate(data, PATH) == data


def test_template_and_directory_lane_do_not_gain_repository_permission():
    assert validate({"plot": {"base": "code", "open-points": ["target"]}}, PATH)
    data = {"plot": {"base": "freeform"}, "target": {"tasks": "vault"}}
    assert validate(data, PATH)
    for key, value in [("commit", "allow"), ("slots", {"none": True})]:
        bad = deepcopy(data)
        bad[key] = value
        with pytest.raises(ValueError, match=key):
            validate(bad, PATH)
    data["plot"]["open-points"] = ["target"]
    with pytest.raises(ValueError, match="open-points"):
        validate(data, PATH)


@pytest.mark.parametrize(
    "points", [[], "target", [1], [""], ["target", "target"], ["a b"], ["Target"], ["a\n"]]
)
def test_invalid_open_points_cannot_hide_incomplete_composition(points):
    with pytest.raises(ValueError, match="open-points"):
        validate({"plot": {"base": "code", "open-points": points}}, PATH)


@pytest.mark.parametrize("permission", ["allow", "deny"])
def test_shipping_is_explicit_and_independent_of_commit(permission):
    data = change("target.repository.shipping", permission)
    assert validate(data, PATH)["target"]["repository"]["shipping"] == permission
    data["target"]["repository"]["commit"] = "deny"
    assert validate(data, PATH)["target"]["repository"]["shipping"] == permission
    assert "shipping" not in validate(deepcopy(VALID), PATH)["target"]["repository"]


@pytest.mark.parametrize("value", [True, None, "", "ALLOW", "allow\n", []])
def test_invalid_shipping_permission_never_grants_remote_authority(value):
    with pytest.raises(ValueError, match="target.repository.shipping"):
        validate(change("target.repository.shipping", value), PATH)


def test_retired_colour_field_is_refused():
    """Bug: a declaration kept a tab colour nothing reads, and the schema drifted silently."""
    with pytest.raises(ValueError, match="colour"):
        validate(change("target.colour", "#E85D75"), PATH)


@pytest.mark.parametrize("permission", ["local", "tailnet"])
def test_bloom_publication_is_explicit_and_independent_of_git(permission):
    data = change("target.bloom", permission)
    data["target"]["repository"]["commit"] = "deny"
    assert validate(data, PATH)["target"]["bloom"] == permission
    assert "bloom" not in validate(deepcopy(VALID), PATH)["target"]


@pytest.mark.parametrize("permission", [True, None, "allow", "TAILNET", "tailnet\n", []])
def test_invalid_bloom_policy_never_enables_publication(permission):
    with pytest.raises(ValueError, match="target.bloom"):
        validate(change("target.bloom", permission), PATH)
