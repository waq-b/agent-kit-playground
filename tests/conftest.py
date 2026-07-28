import os

import pytest

import agent_kit
from agent_kit.class_registry import get_class_registry
from agent_kit.registry import get_registry
from agent_kit.stub_store import get_stub_store
from agent_kit.tool_registry import get_tool_registry


@pytest.fixture(scope="session", autouse=True)
def _stub_ai_providers():
    os.environ["STUB_AI_PROVIDERS"] = "1"
    yield


@pytest.fixture
def isolated_registries():
    get_registry().clear()
    get_stub_store().clear()
    get_tool_registry().clear()
    get_class_registry().clear()
    agent_kit._initialise()
    yield
