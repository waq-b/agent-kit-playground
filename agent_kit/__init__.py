"""agent-kit public API — register agents, fixtures, and tools; run agents by name."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from agent_kit.errors import AgentKitError, LoadSummaryError
from agent_kit.loader import DefinitionLoader
from agent_kit.registry import get_registry
from agent_kit.runner import Runner
from agent_kit.stub_store import get_stub_store
from agent_kit.tool_registry import get_tool_registry

logger = logging.getLogger(__name__)

_BUILTIN_AGENTS_DIR = Path(__file__).parent / "agents"

__all__ = ["register_definition", "register_fixture", "register_tool", "run_agent"]


def register_definition(path: str | Path) -> None:
    resolved = Path(path)
    if not resolved.is_file():
        raise AgentKitError(f"agent definition file not found: {resolved}")
    definition = DefinitionLoader().load_file(resolved)
    get_registry().register(definition)


def register_fixture(agent_name: str, fixture: BaseModel) -> None:
    get_stub_store().register(agent_name, fixture)


def register_tool(name: str, fn: Callable) -> None:
    get_tool_registry().register(name, fn)


def run_agent(name: str, input_data: dict[str, Any]) -> BaseModel:
    _validate_builtin_input(name, input_data)
    definition = get_registry().get(name)
    return Runner().execute(definition, input_data)


def _validate_builtin_input(name: str, input_data: dict[str, Any]) -> None:
    """Validate input for agent-kit's own demo agents before invoking the Runner.

    Hello/News are the two demo agents proving the design end-to-end (Req 8, Req 9),
    so their input schemas are checked here explicitly. This is not a generic
    extension point — consuming-app agents are responsible for their own input
    validation (e.g. within a tool or downstream of `run_agent`).
    """
    if name == "hello":
        from agent_kit.agents.models.hello import HelloInput

        HelloInput.model_validate(input_data)
    elif name == "news":
        from agent_kit.agents.models.news import NewsInput

        NewsInput.model_validate(input_data)


def _initialise() -> None:
    """Load and register the built-in agents shipped with agent-kit."""
    if not _BUILTIN_AGENTS_DIR.is_dir():
        return
    try:
        definitions = DefinitionLoader().load_directory(_BUILTIN_AGENTS_DIR)
    except LoadSummaryError as e:
        logger.warning("failed to load any built-in agent definitions: %s", e)
        return
    for definition in definitions:
        get_registry().register(definition)

    from agent_kit.agents.models.hello import HelloOutput

    get_stub_store().register("hello", HelloOutput(greeting="Hello, World!"))

    from agent_kit.tools.rss import fetch_rss_feed

    get_tool_registry().register("fetch_rss_feed", fetch_rss_feed)

    from agent_kit.agents.models.news import NewsItem, NewsOutput

    get_stub_store().register(
        "news",
        NewsOutput(
            items=[
                NewsItem(
                    title="AI breakthrough announced by research lab",
                    source="BBC News",
                    url="https://www.bbc.co.uk/news/example-ai-breakthrough",
                    relevance_note="Directly matches keyword 'AI'",
                ),
                NewsItem(
                    title="Climate summit reaches new agreement",
                    source="The Guardian",
                    url="https://www.theguardian.com/uk/example-climate-summit",
                    relevance_note="Directly matches keyword 'climate'",
                ),
            ]
        ),
    )


_initialise()
