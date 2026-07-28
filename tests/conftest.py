import os

import pytest

import agent_kit
from agent_kit.class_registry import get_class_registry
from agent_kit.registry import get_registry
from agent_kit.stat_effects import PromptBand, RuntimeCurve, StatDefinition
from agent_kit.stub_store import get_stub_store
from agent_kit.tool_registry import get_tool_registry


def make_stat(value: int, *, labels=("low", "high"), parameter="temperature") -> StatDefinition:
    """Build a minimal valid StatDefinition for tests.

    Since v0.4, every class stat must carry prompt_effect bands and a
    runtime_effect curve, so tests can no longer use the old bare-int form.
    """
    return StatDefinition(
        value=value,
        prompt_effect=tuple(PromptBand(label=label, text=f"{label} behaviour") for label in labels),
        runtime_effect={parameter: RuntimeCurve(at_0=0.0, at_100=0.1)},
    )


def stat_yaml(name: str, value: int, indent: str = "  ") -> str:
    """Render one stat in the v0.4 class YAML shape, for tests that write files."""
    return (
        f"{indent}{name}:\n"
        f"{indent}  value: {value}\n"
        f"{indent}  prompt_effect:\n"
        f"{indent}    - label: low\n"
        f"{indent}      text: low behaviour\n"
        f"{indent}    - label: high\n"
        f"{indent}      text: high behaviour\n"
        f"{indent}  runtime_effect:\n"
        f"{indent}    temperature: {{at_0: 0.0, at_100: 0.1}}\n"
    )


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
