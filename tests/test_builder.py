import pytest

import agent_kit.builder as builder_module
from agent_kit.builder import (
    BuilderPaths,
    check_model_reachable,
    create_agent,
    create_class,
    delete_agent,
    duplicate_agent,
    is_builder_generated,
    read_sample_input,
    reload_registries,
    seed_core_sample_inputs,
    update_agent,
    write_sample_input,
)
from agent_kit.errors import (
    AgentNotFoundError,
    ClassNotFoundError,
    CoreAgentConfirmationRequiredError,
    DuplicateAgentError,
    DuplicateClassError,
    OutputModelNotEditableError,
)
from agent_kit.model_codegen import FieldSpec
from tests.conftest import stat_yaml
from agent_kit.registry import get_registry


@pytest.fixture
def paths(tmp_path, monkeypatch):
    p = BuilderPaths(data_dir=tmp_path / "agent_kit_data")
    monkeypatch.setattr(builder_module, "DEFAULT_PATHS", p)
    yield p


@pytest.fixture(autouse=True)
def _reload_after_each_test(isolated_registries, paths):
    # isolated_registries already gave us a clean built-in-only registry state;
    # nothing else needed here since each test explicitly calls create/update/etc.
    yield


def _simple_fields():
    return [FieldSpec(name="greeting", type="string")]


def test_create_agent_happy_path(paths):
    definition = create_agent(
        "greeter_bot", system_prompt="You are nice.", output_fields=_simple_fields(),
    )
    assert definition.name == "greeter_bot"
    assert get_registry().get("greeter_bot").system_prompt == "You are nice."
    assert is_builder_generated(definition, paths)


def test_create_agent_duplicate_name_raises(paths):
    create_agent("dup_agent", system_prompt="sp", output_fields=_simple_fields())
    with pytest.raises(DuplicateAgentError):
        create_agent("dup_agent", system_prompt="sp2", output_fields=_simple_fields())


def test_create_agent_invalid_field_spec_rolls_back_cleanly(paths):
    with pytest.raises(Exception):
        create_agent("bad_agent", system_prompt="sp", output_fields=[])  # EmptyOutputModelError
    with pytest.raises(AgentNotFoundError):
        get_registry().get("bad_agent")
    assert not (paths.agents_dir / "bad_agent.yaml").exists()
    assert not (paths.generated_models_dir / "bad_agent.py").exists()


def test_update_agent_changes_prompt(paths):
    create_agent("editable", system_prompt="original", output_fields=_simple_fields())
    update_agent("editable", system_prompt="updated")
    assert get_registry().get("editable").system_prompt == "updated"


def test_update_agent_swallowed_error_regression(paths):
    """The core regression this task exists to prevent: DefinitionLoader.load_directory()
    silently drops a bad file (logs+continues) as long as something else loads OK.
    A save must never rely on that path for user-facing validation — an invalid
    edit must raise here, not silently vanish while everything else keeps working."""
    create_agent("stable_agent", system_prompt="sp", output_fields=_simple_fields())

    with pytest.raises(ClassNotFoundError):
        update_agent("stable_agent", card={"main_class": "totally_not_a_real_class"})

    # The edit must be rejected, not silently dropped — agent still has its old state.
    assert get_registry().get("stable_agent").system_prompt == "sp"
    assert get_registry().get("stable_agent").card is None


def test_update_agent_output_fields_regenerates_and_reflects_new_schema(paths):
    """The module-cache regression test: editing a builder-generated agent's
    output fields and reloading must yield a genuinely different class with the
    new fields, not a stale cached one."""
    definition = create_agent("schema_agent", system_prompt="sp", output_fields=_simple_fields())
    old_class = definition.output_model
    assert set(old_class.model_fields.keys()) == {"greeting"}

    new_fields = [FieldSpec(name="greeting", type="string"), FieldSpec(name="count", type="integer")]
    updated = update_agent("schema_agent", output_fields=new_fields)
    new_class = updated.output_model

    assert set(new_class.model_fields.keys()) == {"greeting", "count"}
    assert new_class is not old_class


def test_update_agent_hand_written_output_model_rejected(paths):
    """hello's output_model (agent_kit.agents.models.hello.HelloOutput) is hand-written,
    not builder-generated — editing its output fields must be refused."""
    with pytest.raises(OutputModelNotEditableError):
        update_agent("hello", output_fields=_simple_fields())


def test_update_agent_hello_prompt_still_editable(paths):
    updated = update_agent("hello", system_prompt="A new greeting style.")
    assert updated.system_prompt == "A new greeting style."
    # output model must be untouched/still the original hand-written class
    assert updated.output_model.__module__ == "agent_kit.agents.models.hello"


def test_update_agent_unknown_name_raises(paths):
    with pytest.raises(AgentNotFoundError):
        update_agent("does_not_exist", system_prompt="x")


def test_delete_agent_removes_builder_created_agent(paths):
    create_agent("to_delete", system_prompt="sp", output_fields=_simple_fields())
    delete_agent("to_delete")
    with pytest.raises(AgentNotFoundError):
        get_registry().get("to_delete")


def test_delete_core_agent_requires_confirm_core(paths):
    with pytest.raises(CoreAgentConfirmationRequiredError):
        delete_agent("hello")
    # hello must still be present
    get_registry().get("hello")


def test_delete_core_agent_succeeds_with_confirm_core(paths):
    delete_agent("hello", confirm_core=True)
    with pytest.raises(AgentNotFoundError):
        get_registry().get("hello")


def test_delete_never_edited_core_agent_actually_removes_it(paths):
    """Regression: unlinking a never-existing override file is a no-op — deletion
    of a pristine built-in only works because of the tombstone mechanism."""
    assert not (paths.agents_dir / "news.yaml").exists()  # never edited
    delete_agent("news", confirm_core=True)
    with pytest.raises(AgentNotFoundError):
        get_registry().get("news")
    # And it stays gone across another reload (not just until the next _initialise()).
    reload_registries(paths)
    with pytest.raises(AgentNotFoundError):
        get_registry().get("news")


def test_recreating_a_deleted_agent_undoes_the_tombstone(paths):
    create_agent("temp_agent", system_prompt="sp", output_fields=_simple_fields())
    delete_agent("temp_agent")
    create_agent("temp_agent", system_prompt="sp2", output_fields=_simple_fields())
    assert get_registry().get("temp_agent").system_prompt == "sp2"


def test_duplicate_agent_shares_hand_written_model_without_file_copy(paths):
    duplicate_agent("news", "news_variant")
    original = get_registry().get("news")
    clone = get_registry().get("news_variant")
    assert clone.output_model is original.output_model
    assert clone.system_prompt == original.system_prompt


def test_duplicate_agent_copies_generated_model_with_renamed_class(paths):
    create_agent("gen_agent", system_prompt="sp", output_fields=_simple_fields())
    duplicate_agent("gen_agent", "gen_agent_clone")
    original = get_registry().get("gen_agent")
    clone = get_registry().get("gen_agent_clone")
    assert clone.output_model is not original.output_model
    assert set(clone.output_model.model_fields.keys()) == set(original.output_model.model_fields.keys())


def test_duplicate_agent_to_existing_name_raises(paths):
    create_agent("dup_src", system_prompt="sp", output_fields=_simple_fields())
    with pytest.raises(DuplicateAgentError):
        duplicate_agent("dup_src", "hello")


def test_create_class_happy_path_yaml(paths):
    definition = create_class(
        "name: investigator_v2\ntitle: Investigator V2\nstats:\n" + stat_yaml("skepticism", 60)
    )
    assert definition.name == "investigator_v2"
    assert definition.stat_values == {"skepticism": 60}
    assert definition.stats["skepticism"].prompt_effect  # effects survived the round trip


def test_create_class_happy_path_json(paths):
    definition = create_class(
        '{"name": "explorer", "title": "Explorer", "stats": {"curiosity": '
        '{"value": 70, "prompt_effect": [{"label": "low", "text": "t"}], '
        '"runtime_effect": {"temperature": {"at_0": 0, "at_100": 0.1}}}}}'
    )
    assert definition.name == "explorer"
    assert definition.stat_values == {"curiosity": 70}


def test_create_class_duplicate_raises(paths):
    with pytest.raises(DuplicateClassError):
        create_class("name: greeter\ntitle: Greeter Again\nstats:\n" + stat_yaml("warmth", 50))


def test_create_class_legacy_flat_stat_form_rejected(paths):
    from agent_kit.errors import InvalidStatEffectError

    with pytest.raises(InvalidStatEffectError):
        create_class("name: legacy_class\ntitle: Legacy\nstats:\n  warmth: 50\n")


def test_create_class_bad_yaml_syntax_raises(paths):
    from agent_kit.errors import YAMLSyntaxError

    with pytest.raises(YAMLSyntaxError):
        create_class("name: [unterminated\ntitle: Bad\n")


def test_create_class_missing_required_field_raises(paths):
    from agent_kit.errors import MissingFieldError

    with pytest.raises(MissingFieldError):
        create_class("name: incomplete_class\n")  # missing title/stats


def test_check_model_reachable_never_raises_and_works_offline(paths, monkeypatch):
    import httpx as httpx_module

    def _boom(*args, **kwargs):
        raise httpx_module.ConnectError("no route to host")

    monkeypatch.setattr(builder_module.httpx, "get", _boom)
    result = check_model_reachable("qwen2.5:14b")
    assert result["available"] is False
    assert "message" in result


def test_sample_input_round_trip(paths):
    from agent_kit.builder import delete_sample_input, read_sample_input, write_sample_input

    assert read_sample_input("some_agent", paths) is None
    write_sample_input("some_agent", {"name": "World"}, paths)
    assert read_sample_input("some_agent", paths) == {"name": "World"}
    delete_sample_input("some_agent", paths)
    assert read_sample_input("some_agent", paths) is None


def test_seed_core_sample_inputs_fills_in_hello_and_news(paths):
    assert read_sample_input("hello", paths) is None
    assert read_sample_input("news", paths) is None

    seed_core_sample_inputs(paths)

    assert read_sample_input("hello", paths) == {"name": "Alice"}
    assert read_sample_input("news", paths) == {"keywords": ["AI", "climate"]}


def test_seed_core_sample_inputs_never_overwrites_an_existing_one(paths):
    """A user editing hello/news's sample input via the wizard must stick —
    the seed only fills a gap, it never resets what's already there."""
    write_sample_input("hello", {"name": "someone the user chose"}, paths)

    seed_core_sample_inputs(paths)

    assert read_sample_input("hello", paths) == {"name": "someone the user chose"}
    # news still gets seeded — the guard is per-agent, not all-or-nothing.
    assert read_sample_input("news", paths) == {"keywords": ["AI", "climate"]}


def test_seed_core_sample_inputs_is_idempotent(paths):
    seed_core_sample_inputs(paths)
    seed_core_sample_inputs(paths)
    assert read_sample_input("hello", paths) == {"name": "Alice"}


def test_seed_core_sample_inputs_ignores_unknown_core_agent_names(paths, monkeypatch):
    """A future core agent not yet in the seed map is a no-op, not an error."""
    monkeypatch.setattr(builder_module, "CORE_AGENT_NAMES", frozenset({"hello", "news", "future_agent"}))
    seed_core_sample_inputs(paths)  # must not raise
    assert read_sample_input("future_agent", paths) is None
