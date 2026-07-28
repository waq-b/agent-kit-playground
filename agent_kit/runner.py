"""Runner — executes an AgentDefinition, either live (via Pydantic AI + Ollama) or stubbed."""

from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any, Callable

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import AgentRunError, ModelAPIError
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from agent_kit.card_store import get_card_store
from agent_kit.definition import AgentDefinition
from agent_kit.errors import (
    AgentConnectionError,
    AgentKitError,
    FeedFetchError,
    TemperatureRangeError,
    TypeMismatchError,
)
from agent_kit.stat_mapping import compute_runtime_params
from agent_kit.stub_store import get_stub_store
from agent_kit.tool_registry import get_tool_registry

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434/v1"


def _tolerate_feed_failures(fn: Callable) -> Callable:
    """Wrap a tool callable so a `FeedFetchError` during an agentic run is logged
    and swallowed (returning an empty list) rather than aborting the whole run —
    per Design's fetch_rss_feed docstring: "the caller ... catches FeedFetchError,
    logs a warning, and continues with remaining feeds" (Req 9.5)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except FeedFetchError as e:
            logger.warning("tool '%s' call failed, continuing: %s", fn.__name__, e)
            return []

    return wrapper


def _part_text(part: Any) -> str:
    content = getattr(part, "content", None)
    if isinstance(content, str):
        return content
    args = getattr(part, "args", None)
    if args is not None:
        return json.dumps(args, default=str)
    return str(part)


class Runner:
    """Executes agents. Also exposes the raw prompt/response of the most recent
    `execute()` call as `last_raw_prompt` / `last_raw_response`, since the method's
    return type is the validated Output_Model itself (per spec) and has no room
    to carry them."""

    def __init__(self) -> None:
        self.last_raw_prompt: str = ""
        self.last_raw_response: str = ""
        self.last_tools_used: list[str] = []

    def execute(self, definition: AgentDefinition, input_data: dict[str, Any]) -> BaseModel:
        if not (0.0 <= definition.temperature <= 2.0):
            raise TemperatureRangeError(
                f"temperature {definition.temperature} for agent '{definition.name}' "
                "is outside the allowed range [0.0, 2.0]"
            )

        if os.environ.get("STUB_AI_PROVIDERS") == "1":
            return self._execute_stub(definition, input_data)
        return self._execute_live(definition, input_data)

    def _execute_stub(self, definition: AgentDefinition, input_data: dict[str, Any]) -> BaseModel:
        fixture = get_stub_store().get(definition.name)
        if not isinstance(fixture, definition.output_model):
            raise TypeMismatchError(
                f"fixture registered for agent '{definition.name}' has type "
                f"{type(fixture).__name__}, expected {definition.output_model.__name__}"
            )
        try:
            validated = definition.output_model.model_validate(fixture.model_dump())
        except Exception as e:
            raise AgentKitError(
                f"stub fixture for agent '{definition.name}' failed validation "
                f"against {definition.output_model.__name__}: {e}"
            ) from e

        self.last_raw_prompt = f"[stub mode] input: {input_data}"
        self.last_raw_response = f"[stub mode] fixture: {validated.model_dump()}"
        self.last_tools_used = []
        return validated

    def _ensure_feeds_reachable(self, definition: AgentDefinition) -> None:
        """Fail fast if every feed URL declared on this definition is unreachable (Req 9.6).

        Individual feed failures during the agentic run itself are tolerated by
        `_tolerate_feed_failures`; this pre-check exists only to catch the
        all-feeds-dead case deterministically, without depending on whether/how
        the LLM chooses to call the fetch tool.
        """
        from agent_kit.tools.rss import fetch_rss_feed

        any_reachable = False
        for feed_url in definition.feeds:
            try:
                fetch_rss_feed(feed_url)
                any_reachable = True
            except FeedFetchError as e:
                logger.warning(
                    "feed '%s' unreachable for agent '%s': %s", feed_url, definition.name, e
                )
        if not any_reachable:
            raise AgentKitError(
                f"no feed data was available for agent '{definition.name}': "
                f"all {len(definition.feeds)} configured feed(s) were unreachable"
            )

    def _execute_live(self, definition: AgentDefinition, input_data: dict[str, Any]) -> BaseModel:
        if definition.feeds:
            self._ensure_feeds_reachable(definition)

        tools = [_tolerate_feed_failures(get_tool_registry().get(name)) for name in definition.tools]

        model_settings = {"temperature": definition.temperature}
        retries = tool_timeout = max_concurrency = None

        if definition.card is not None:
            store = get_card_store()
            store.ensure_seeded(definition.name, definition.card)
            state = store.get_state(definition.name)
            tool_tiers = {name: tp.tier for name, tp in state.tool_proficiency.items()}
            params = compute_runtime_params(definition.temperature, state.base_stats, tool_tiers)
            model_settings["temperature"] = params.temperature
            retries, tool_timeout, max_concurrency = params.retries, params.tool_timeout, params.max_concurrency

        model = OpenAIChatModel(
            definition.model,
            provider=OpenAIProvider(base_url=OLLAMA_BASE_URL, api_key="ollama"),
        )
        agent = Agent(
            model=model,
            output_type=definition.output_model,
            system_prompt=definition.system_prompt,
            tools=tools,
            model_settings=model_settings,
            retries=retries,
            tool_timeout=tool_timeout,
            max_concurrency=max_concurrency,
        )

        # Feed URLs are declared in YAML (Req 9.2), not the system prompt, so they're
        # supplied at call time via the prompt payload instead.
        prompt_payload: Any = {"input": input_data, "feeds": definition.feeds} if definition.feeds else input_data
        prompt = str(prompt_payload)
        try:
            result = agent.run_sync(prompt)
        except ModelAPIError as e:
            raise AgentConnectionError(
                f"could not reach model provider at {OLLAMA_BASE_URL} for agent "
                f"'{definition.name}': {e}"
            ) from e
        except AgentRunError as e:
            raise AgentKitError(
                f"agent '{definition.name}' response failed to validate against "
                f"{definition.output_model.__name__}: {e}"
            ) from e

        messages = result.all_messages()
        self.last_raw_prompt = (
            "\n".join(_part_text(p) for p in messages[0].parts) if messages else prompt
        )
        self.last_raw_response = "\n".join(_part_text(p) for p in result.response.parts)
        self.last_tools_used = [
            part.tool_name
            for msg in messages
            for part in getattr(msg, "parts", [])
            if isinstance(part, ToolCallPart)
        ]

        return result.output
