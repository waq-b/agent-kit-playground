from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from agent_kit.playground.app import app
from agent_kit.registry import get_registry
from agent_kit.stub_store import get_stub_store


@pytest.fixture
def client():
    return TestClient(app)


def test_root_returns_a_minimal_api_pointer_not_legacy_html(client):
    """Refinement Phase 2 Task 7: the legacy HTML playground that used to live
    at "/" is gone — the React app (frontend/) is the only UI now. "/" is a
    plain API service pointer, not an attempt to serve or redirect to a UI
    whose actual location the backend can't reliably know."""
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["docs"] == "/docs"


def test_legacy_cards_and_builder_html_routes_are_gone(client):
    assert client.get("/cards").status_code == 404
    assert client.get("/builder").status_code == 404


class _TypedIn(BaseModel):
    name: str = Field(min_length=1, max_length=5)
    count: int = 1


class _TypedOut(BaseModel):
    echo: str


def _register_typed_agent() -> None:
    from agent_kit.definition import AgentDefinition

    get_registry().register(
        AgentDefinition(
            name="typed_agent", description="d", system_prompt="sp", model="m",
            temperature=0.7, tools=[], output_model=_TypedOut, source_path=Path("x.yaml"),
            input_model=_TypedIn,
        )
    )


def _register_untyped_agent() -> None:
    """A genuinely input-model-less agent — hello/news both declare a real
    input_model as of refinement Phase 1 Task 5, so they're no longer good
    fixtures for exercising the pass-through path itself."""
    from agent_kit.definition import AgentDefinition

    get_registry().register(
        AgentDefinition(
            name="untyped_agent", description="d", system_prompt="sp", model="m",
            temperature=0.7, tools=[], output_model=_TypedOut, source_path=Path("x.yaml"),
        )
    )


def test_list_agents_returns_registered_agents(client, isolated_registries):
    r = client.get("/api/v1/agents")
    assert r.status_code == 200
    names = {a["name"] for a in r.json()}
    assert {"hello", "news"} <= names


def test_list_agents_returns_empty_array_when_registry_cleared(client):
    get_registry().clear()
    r = client.get("/api/v1/agents")
    assert r.status_code == 200
    assert r.json() == []


def test_run_unknown_agent_returns_404(client, isolated_registries):
    r = client.post("/api/v1/agents/does-not-exist/run", json={"input": {"x": 1}})
    assert r.status_code == 404
    assert "does-not-exist" in r.json()["detail"]


def test_run_empty_input_returns_422(client, isolated_registries):
    r = client.post("/api/v1/agents/hello/run", json={"input": {}})
    assert r.status_code == 422


def test_run_missing_input_field_returns_422(client, isolated_registries):
    r = client.post("/api/v1/agents/hello/run", json={})
    assert r.status_code == 422


def test_run_oversized_input_returns_422(client, isolated_registries):
    big_input = {"name": "x" * 20000}
    r = client.post("/api/v1/agents/hello/run", json={"input": big_input})
    assert r.status_code == 422


def test_successful_run_returns_output_and_raw_fields(client, isolated_registries):
    r = client.post("/api/v1/agents/hello/run", json={"input": {"name": "World"}})
    assert r.status_code == 200
    data = r.json()
    assert data["output"] == {"greeting": "Hello, World!"}
    assert "raw_prompt" in data
    assert "raw_response" in data
    assert data["tools_used"] == []  # stub mode, no real tool calls


def test_agent_without_input_model_still_passes_input_through_unvalidated(client, isolated_registries):
    """Task 2's whole "agents with no input_model keep the current
    pass-through behaviour" guarantee, on an agent that genuinely has none."""
    _register_untyped_agent()
    get_stub_store().register("untyped_agent", _TypedOut(echo="ok"))
    r = client.post(
        "/api/v1/agents/untyped_agent/run", json={"input": {"anything": "goes", "here": 1}}
    )
    assert r.status_code == 200


def test_hello_now_validates_against_its_real_input_model(client, isolated_registries):
    """Refinement Phase 1 Task 5: hello declares a real input_model
    (HelloInput) instead of accepting anything shaped like an object."""
    r = client.post("/api/v1/agents/hello/run", json={"input": {"not_name": "World"}})
    assert r.status_code == 422
    assert any(err["loc"] == ["name"] for err in r.json()["detail"])


def test_news_now_validates_against_its_real_input_model(client, isolated_registries):
    r = client.post("/api/v1/agents/news/run", json={"input": {"not_keywords": ["AI"]}})
    assert r.status_code == 422
    assert any(err["loc"] == ["keywords"] for err in r.json()["detail"])


def test_run_with_input_model_rejects_input_failing_validation(client, isolated_registries):
    _register_typed_agent()
    r = client.post("/api/v1/agents/typed_agent/run", json={"input": {"name": "too-long-a-name"}})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list)
    assert any(err["loc"] == ["name"] for err in detail)


def test_run_with_input_model_rejects_missing_required_field(client, isolated_registries):
    _register_typed_agent()
    r = client.post("/api/v1/agents/typed_agent/run", json={"input": {"count": 2}})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(err["loc"] == ["name"] and err["type"] == "missing" for err in detail)


def test_run_with_input_model_rejects_wrong_type(client, isolated_registries):
    _register_typed_agent()
    r = client.post("/api/v1/agents/typed_agent/run", json={"input": {"name": "ok", "count": "not-an-int"}})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(err["loc"] == ["count"] for err in detail)


def test_run_with_input_model_accepts_valid_input_and_reaches_the_runner(client, isolated_registries):
    """Proves validated input actually reaches Runner.execute — not just that
    the 422 branch is skipped. Applies defaults too: `count` is omitted here
    and the fixture's own value proves the validated (not raw) dict was used."""
    _register_typed_agent()
    get_stub_store().register("typed_agent", _TypedOut(echo="ok"))

    r = client.post("/api/v1/agents/typed_agent/run", json={"input": {"name": "ok"}})

    assert r.status_code == 200
    assert r.json()["output"] == {"echo": "ok"}
    assert "'count': 1" in r.json()["raw_prompt"]
