import importlib
import sys

import pytest

from agent_kit.errors import (
    DuplicateFieldNameError,
    EmptyOutputModelError,
    InvalidFieldSpecError,
    NestingDepthExceededError,
    ReservedFieldNameError,
)
from agent_kit.model_codegen import FieldSpec, generate_model_source, output_class_name, to_pascal_case


def _import_generated(tmp_path, module_name: str, source: str):
    """Write generated source to a real file and import it via the real import
    machinery — NOT exec() with a plain dict, which spuriously fails on
    pydantic's forward-ref resolution (it looks up `cls.__module__`'s globals
    in sys.modules, not an arbitrary namespace dict passed to exec).
    """
    package_dir = tmp_path / "codegen_pkg"
    package_dir.mkdir(exist_ok=True)
    (package_dir / "__init__.py").touch(exist_ok=True)
    (package_dir / f"{module_name}.py").write_text(source)

    sys.path.insert(0, str(tmp_path))
    try:
        full_name = f"codegen_pkg.{module_name}"
        # Different tests reuse the "codegen_pkg" name across different tmp_path
        # dirs — pop the parent package too, or a stale cached "codegen_pkg"
        # (pointing at a previous test's tmp_path) shadows this one.
        for cached_name in [n for n in sys.modules if n == "codegen_pkg" or n.startswith("codegen_pkg.")]:
            del sys.modules[cached_name]
        importlib.invalidate_caches()
        return importlib.import_module(full_name)
    finally:
        sys.path.remove(str(tmp_path))


def test_generates_valid_python_that_compiles():
    fields = [FieldSpec(name="greeting", type="string")]
    source = generate_model_source("hello", fields)
    compile(source, "<generated>", "exec")  # raises SyntaxError if malformed


def test_generated_class_has_expected_fields(tmp_path):
    fields = [
        FieldSpec(name="title", type="string"),
        FieldSpec(name="count", type="integer", required=False),
    ]
    source = generate_model_source("simple_agent", fields)
    mod = _import_generated(tmp_path, "simple_agent", source)
    Output = getattr(mod, "SimpleAgentOutput")

    assert set(Output.model_fields.keys()) == {"title", "count"}
    assert Output.model_fields["title"].is_required()
    assert not Output.model_fields["count"].is_required()

    instance = Output(title="hi")
    assert instance.title == "hi"
    assert instance.count is None


def test_reproduces_news_output_shape_field_for_field(tmp_path):
    fields = [
        FieldSpec(
            name="items", type="nested", is_list=True,
            nested_fields=[
                FieldSpec(name="title", type="string"),
                FieldSpec(name="source", type="string"),
                FieldSpec(name="url", type="string"),
                FieldSpec(name="relevance_note", type="string"),
            ],
        ),
    ]
    source = generate_model_source("weather_bot", fields)
    mod = _import_generated(tmp_path, "weather_bot", source)
    Output = getattr(mod, "WeatherBotOutput")
    Item = getattr(mod, "WeatherBotOutputItems")

    assert set(Output.model_fields.keys()) == {"items"}
    assert set(Item.model_fields.keys()) == {"title", "source", "url", "relevance_note"}

    instance = Output(items=[{"title": "t", "source": "s", "url": "u", "relevance_note": "r"}])
    assert isinstance(instance.items[0], Item)
    assert instance.items[0].title == "t"


def test_optional_list_field_defaults_to_none(tmp_path):
    fields = [FieldSpec(name="tags", type="string", is_list=True, required=False)]
    source = generate_model_source("tagger", fields)
    mod = _import_generated(tmp_path, "tagger", source)
    Output = getattr(mod, "TaggerOutput")
    instance = Output()
    assert instance.tags is None
    instance2 = Output(tags=["a", "b"])
    assert instance2.tags == ["a", "b"]


@pytest.mark.parametrize(
    "name,expected",
    [("hello", "Hello"), ("weather_bot", "WeatherBot"), ("news-agent", "NewsAgent"), ("a b c", "ABC")],
)
def test_to_pascal_case(name, expected):
    assert to_pascal_case(name) == expected


def test_output_class_name():
    assert output_class_name("hello") == "HelloOutput"


def test_empty_field_list_raises():
    with pytest.raises(EmptyOutputModelError):
        generate_model_source("x", [])


def test_duplicate_field_names_raise():
    with pytest.raises(DuplicateFieldNameError):
        generate_model_source("x", [FieldSpec(name="a", type="string"), FieldSpec(name="a", type="integer")])


def test_reserved_field_name_raises():
    with pytest.raises(ReservedFieldNameError):
        generate_model_source("x", [FieldSpec(name="model_config", type="string")])


def test_invalid_identifier_raises():
    with pytest.raises(InvalidFieldSpecError):
        generate_model_source("x", [FieldSpec(name="bad-name", type="string")])


def test_nested_without_nested_fields_raises():
    with pytest.raises(InvalidFieldSpecError):
        generate_model_source("x", [FieldSpec(name="a", type="nested")])


def test_non_nested_with_nested_fields_raises():
    with pytest.raises(InvalidFieldSpecError):
        generate_model_source(
            "x", [FieldSpec(name="a", type="string", nested_fields=[FieldSpec(name="b", type="string")])]
        )


def test_depth_two_nesting_raises():
    with pytest.raises(NestingDepthExceededError):
        generate_model_source(
            "x",
            [
                FieldSpec(
                    name="a", type="nested",
                    nested_fields=[
                        FieldSpec(name="b", type="nested", nested_fields=[FieldSpec(name="c", type="string")])
                    ],
                )
            ],
        )
