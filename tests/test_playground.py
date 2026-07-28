import pytest
from fastapi.testclient import TestClient

from agent_kit.playground.app import app
from agent_kit.registry import get_registry


@pytest.fixture
def client():
    return TestClient(app)


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
