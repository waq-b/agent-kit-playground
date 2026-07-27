"""Property-based tests encoding Design's Correctness Properties P1-P10.

All run under STUB_AI_PROVIDERS=1 (enforced globally by conftest.py's session
fixture) and avoid real network calls and pytest fixtures that hypothesis
would flag as function-scoped (registries/stores are reset with plain
function calls inside each test body instead).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import agent_kit
import agent_kit.notify as notify_mod
from agent_kit.agents.models.hello import HelloOutput
from agent_kit.definition import AgentDefinition
from agent_kit.errors import DuplicateAgentError, TemperatureRangeError
from agent_kit.loader import DefinitionLoader
from agent_kit.registry import AgentRegistry, get_registry
from agent_kit.runner import Runner
from agent_kit.stub_store import get_stub_store
from agent_kit.tool_registry import get_tool_registry

OUTPUT_MODEL = "agent_kit.agents.models.hello.HelloOutput"


def _def_for(name: str, output_model=HelloOutput, temperature: float = 0.7, path: str = "x.yaml") -> AgentDefinition:
    return AgentDefinition(
        name=name, description="d", system_prompt="sp", model="m",
        temperature=temperature, tools=[], output_model=output_model, source_path=Path(path),
    )


def _reset_global_singletons() -> None:
    get_registry().clear()
    get_stub_store().clear()
    get_tool_registry().clear()
    agent_kit._initialise()


# P1 - Registry round-trip identity
@given(name=st.text(min_size=1, max_size=50))
@settings(max_examples=50, deadline=None)
def test_p1_registry_round_trip_identity(name):
    r = AgentRegistry()
    d = _def_for(name)
    r.register(d)
    assert r.get(name) == d


# P2 - Stub mode output type invariant
@given(greeting=st.text(min_size=1, max_size=200))
@settings(max_examples=30, deadline=None)
def test_p2_stub_mode_output_type_invariant(greeting):
    get_stub_store().clear()
    agent_name = "p2_agent"
    get_stub_store().register(agent_name, HelloOutput(greeting=greeting))
    d = _def_for(agent_name)
    result = Runner().execute(d, {"name": "x"})
    assert isinstance(result, HelloOutput)


# P3 - Zero-network invariant in stub mode
def test_p3_stub_mode_zero_network_invariant():
    get_stub_store().clear()
    agent_name = "p3_agent"
    get_stub_store().register(agent_name, HelloOutput(greeting="hi"))
    d = _def_for(agent_name)
    with patch("socket.socket.connect", side_effect=AssertionError("network used")):
        result = Runner().execute(d, {"name": "x"})
    assert result.greeting == "hi"


# P4 - Hello greeting non-empty for any valid name
@given(name=st.text(min_size=1, max_size=255))
@settings(max_examples=30, deadline=None)
def test_p4_hello_greeting_non_empty(name):
    _reset_global_singletons()
    result = agent_kit.run_agent("hello", {"name": name})
    assert result.greeting != ""


# P5 - News output schema completeness
def test_p5_news_item_schema_completeness():
    _reset_global_singletons()
    result = agent_kit.run_agent("news", {"keywords": ["AI"]})
    for item in result.items:
        assert len(item.title) > 0
        assert len(item.source) > 0
        assert len(item.url) > 0
        assert len(item.relevance_note) > 0


# P6 - Registry list completeness
@given(names=st.lists(st.text(min_size=1, max_size=30), min_size=1, max_size=10, unique=True))
@settings(max_examples=30, deadline=None)
def test_p6_registry_list_completeness(names):
    r = AgentRegistry()
    defs = [_def_for(n) for n in names]
    for d in defs:
        r.register(d)
    listing = r.list()
    assert len(listing) == len(names)
    for d in defs:
        assert {"name": d.name, "description": d.description} in listing


# P7 - Temperature range enforcement
@given(temp=st.floats(allow_nan=False).filter(lambda t: not (0.0 <= t <= 2.0)))
@settings(max_examples=30, deadline=None)
def test_p7_temperature_range_enforcement(temp):
    d = _def_for("p7_agent", temperature=temp)
    with pytest.raises(TemperatureRangeError):
        Runner().execute(d, {"name": "x"})


# P8 - Notification helper never raises
# ntfy_url excludes NUL bytes: real environment variables can never contain one
# (os.environ itself raises ValueError on assignment), so it's not a value
# notify() could ever actually receive from os.environ.get("NTFY_URL").
@given(
    message=st.text(max_size=10_000),
    ntfy_url=st.one_of(st.none(), st.text(max_size=200).filter(lambda s: "\x00" not in s)),
)
@settings(max_examples=50, deadline=None)
def test_p8_notify_never_raises(message, ntfy_url):
    original = os.environ.get("NTFY_URL")
    try:
        if ntfy_url is None:
            os.environ.pop("NTFY_URL", None)
        else:
            os.environ["NTFY_URL"] = ntfy_url
        with patch.object(notify_mod.httpx, "post", side_effect=RuntimeError("simulated failure")):
            try:
                notify_mod.notify(message)
            except Exception as e:
                pytest.fail(f"notify() raised {type(e).__name__}: {e}")
    finally:
        if original is None:
            os.environ.pop("NTFY_URL", None)
        else:
            os.environ["NTFY_URL"] = original


# P9 - Duplicate registration is rejected
@given(name=st.text(min_size=1, max_size=50))
@settings(max_examples=30, deadline=None)
def test_p9_duplicate_registration_rejected(name):
    r = AgentRegistry()
    r.register(_def_for(name, path="a.yaml"))
    with pytest.raises(DuplicateAgentError):
        r.register(_def_for(name, path="b.yaml"))


# P10 - Loader error isolation
@given(n=st.integers(min_value=1, max_value=8))
@settings(max_examples=15, deadline=None)
def test_p10_loader_error_isolation(tmp_path_factory, n):
    directory = tmp_path_factory.mktemp("p10")
    for i in range(n):
        (directory / f"good{i}.yaml").write_text(
            f"name: good{i}\nsystem_prompt: sp\noutput_model: {OUTPUT_MODEL}\n"
        )
    (directory / "bad.yaml").write_text("name: bad\n")

    defs = DefinitionLoader().load_directory(directory)
    assert len(defs) == n
