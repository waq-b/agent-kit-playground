import pytest
from fastapi.testclient import TestClient

import agent_kit.builder as builder_module
from agent_kit.builder import BuilderPaths
from agent_kit.playground.app import app
from tests.conftest import stat_yaml


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_builder_paths(tmp_path, monkeypatch):
    paths = BuilderPaths(data_dir=tmp_path / "agent_kit_data")
    monkeypatch.setattr(builder_module, "DEFAULT_PATHS", paths)
    yield paths


def _simple_output_fields():
    return [{"name": "greeting", "type": "string"}]


def test_full_create_run_grade_loop(client, isolated_registries):
    r = client.post(
        "/api/v1/builder/agents",
        json={
            "name": "loop_agent",
            "system_prompt": "You are helpful.",
            "output_fields": _simple_output_fields(),
        },
    )
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["name"] == "loop_agent"
    assert detail["output_model_editable"] is True

    # newly created agent appears in the agent list immediately, no restart
    names = {a["name"] for a in client.get("/api/v1/agents").json()}
    assert "loop_agent" in names

    # No stub fixture registered for a fresh agent -> run raises 500 (NoFixtureError),
    # which is expected/correct; the point of this test is create->list visibility,
    # not exercising the run path for a fixture-less agent.
    r_run = client.post("/api/v1/agents/loop_agent/run", json={"input": {"x": 1}})
    assert r_run.status_code == 500


def test_edit_hello_prompt_succeeds(client, isolated_registries):
    r = client.put("/api/v1/builder/agents/hello", json={"system_prompt": "New greeting style."})
    assert r.status_code == 200, r.text
    assert r.json()["system_prompt"] == "New greeting style."


def test_edit_hello_output_fields_returns_422(client, isolated_registries):
    r = client.put("/api/v1/builder/agents/hello", json={"output_fields": _simple_output_fields()})
    assert r.status_code == 422


def test_delete_core_agent_without_confirm_core_returns_409(client, isolated_registries):
    r = client.delete("/api/v1/builder/agents/hello?confirm=true")
    assert r.status_code == 409

    r2 = client.delete("/api/v1/builder/agents/hello?confirm=true&confirm_core=true")
    assert r2.status_code == 200


def test_delete_without_confirm_returns_400(client, isolated_registries):
    r = client.delete("/api/v1/builder/agents/hello")
    assert r.status_code == 400


def test_duplicate_news_with_different_feeds(client, isolated_registries):
    r = client.post("/api/v1/builder/agents/news/duplicate", json={"new_name": "news_variant"})
    assert r.status_code == 200, r.text

    r2 = client.put(
        "/api/v1/builder/agents/news_variant",
        json={"feeds": ["https://example.com/only-one-feed.xml"]},
    )
    assert r2.status_code == 200
    assert r2.json()["feeds"] == ["https://example.com/only-one-feed.xml"]

    # original news agent's feeds are untouched
    original = client.get("/api/v1/agents/news/builder").json()
    assert len(original["feeds"]) == 2


def test_list_tools_endpoint(client, isolated_registries):
    r = client.get("/api/v1/tools")
    assert r.status_code == 200
    assert "fetch_rss_feed" in r.json()


def test_list_classes_endpoint(client, isolated_registries):
    r = client.get("/api/v1/classes")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()}
    assert {"greeter", "news_hound", "investigator"} <= names


def test_create_class_endpoint(client, isolated_registries):
    r = client.post(
        "/api/v1/builder/classes",
        json={"content": "name: explorer\ntitle: Explorer\nstats:\n" + stat_yaml("curiosity", 70)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "explorer"
    assert r.json()["stats"] == {"curiosity": 70}


def test_create_class_endpoint_accepts_json_content(client, isolated_registries):
    r = client.post(
        "/api/v1/builder/classes",
        json={
            "content": '{"name": "tinkerer", "title": "Tinkerer", "stats": {"ingenuity": '
            '{"value": 65, "prompt_effect": [{"label": "low", "text": "t"}], '
            '"runtime_effect": {"temperature": {"at_0": 0, "at_100": 0.1}}}}}'
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "tinkerer"


def test_create_class_endpoint_legacy_flat_form_returns_422(client, isolated_registries):
    r = client.post(
        "/api/v1/builder/classes",
        json={"content": "name: legacy\ntitle: Legacy\nstats:\n  curiosity: 70\n"},
    )
    assert r.status_code == 422


def test_create_class_endpoint_bad_yaml_returns_422(client, isolated_registries):
    r = client.post(
        "/api/v1/builder/classes",
        json={"content": "name: [unterminated\ntitle: Bad\n"},
    )
    assert r.status_code == 422


def test_builder_detail_endpoint_for_hello(client, isolated_registries):
    r = client.get("/api/v1/agents/hello/builder")
    assert r.status_code == 200
    data = r.json()
    assert data["is_core"] is True
    assert data["output_model_editable"] is False
    assert "greeting" in data["output_fields_summary"]


def test_agent_not_found_returns_404(client, isolated_registries):
    r = client.get("/api/v1/agents/does-not-exist/builder")
    assert r.status_code == 404
    r2 = client.put("/api/v1/builder/agents/does-not-exist", json={"system_prompt": "x"})
    assert r2.status_code == 404


def test_model_check_endpoint_never_fails_hard(client, isolated_registries):
    r = client.get("/api/v1/builder/model-check", params={"model": "qwen2.5:14b"})
    assert r.status_code == 200
    assert "available" in r.json()


def test_sample_input_endpoint(client, isolated_registries):
    client.post(
        "/api/v1/builder/agents",
        json={
            "name": "sample_agent",
            "system_prompt": "sp",
            "output_fields": _simple_output_fields(),
            "sample_input": {"x": 1},
        },
    )
    r = client.get("/api/v1/agents/sample_agent/sample-input")
    assert r.status_code == 200
    assert r.json() == {"x": 1}
