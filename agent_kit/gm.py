"""gm — the Game Master: turns selected stat fragments into one coherent trait paragraph.

This is the only place in agent-kit where a model is asked to interpret
character data, and it is deliberately a *separate* role from the agent being
described: the GM never sees the agent's task input, never produces the
agent's output, and cannot change any runtime parameter. Which fragments apply
is decided by `stat_effects` in plain code before the GM is called at all —
the GM only smooths the wording so that N fragments from M stats read as one
character rather than a list of bullet points.

Provider is configurable: a local model by default (zero config, works
offline), any paid provider opt-in via an API key. Every failure path raises
GMUnavailableError so callers can fall back to the last good paragraph.
"""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel
from pydantic_ai import Agent

from agent_kit.errors import GMUnavailableError
from agent_kit.runner import OLLAMA_BASE_URL
from agent_kit.stat_effects import PromptBand

logger = logging.getLogger(__name__)

_DEFAULT_GM_MODEL = "qwen2.5:14b"
_DEFAULT_GM_PROVIDER = "ollama"

#: pydantic-ai defaults to a single output-validation retry, which a small
#: local model routinely burns getting a three-field structured response right.
#: Verified against a real local qwen2.5:14b: the GM failed outright at the
#: default and succeeds reliably with a few attempts. Overridable for users on
#: a stronger paid model who would rather fail fast.
_GM_OUTPUT_RETRIES = int(os.environ.get("AGENT_KIT_GM_RETRIES", "4"))

_GM_SYSTEM_PROMPT = """\
You are the Game Master for a roster of AI agents. Each agent has character
stats, and each stat has contributed one behavioural fragment describing how
this agent currently acts.

Your job is to rewrite those fragments as a single cohesive paragraph written
in the second person ("You ..."), as if describing one consistent character.

Rules:
- Preserve the behavioural meaning of every fragment. Do not drop, soften, or
  invent traits.
- Resolve overlaps into natural prose rather than repeating similar points.
- Do not restate the agent's task; the paragraph describes disposition only.
- If a fragment directly contradicts the agent's own system prompt, still write
  the paragraph, but record the clash in `conflicts`.
- Only set `suggested_system_prompt` if you genuinely recommend a change to the
  agent's system prompt; otherwise leave it null. It is a suggestion for a human
  to approve, never applied automatically.
"""


class GMSynthesis(BaseModel):
    trait_paragraph: str
    conflicts: list[str] = []
    suggested_system_prompt: str | None = None


def gm_configuration() -> dict[str, str | None]:
    """Resolve GM provider settings from the environment at call time.

    Read fresh on every call (not cached at import) so tests and running
    servers can change providers without a restart — the same convention
    STUB_AI_PROVIDERS and NTFY_URL already follow.
    """
    return {
        "model": os.environ.get("AGENT_KIT_GM_MODEL", _DEFAULT_GM_MODEL),
        "provider": os.environ.get("AGENT_KIT_GM_PROVIDER", _DEFAULT_GM_PROVIDER),
        "api_key": os.environ.get("AGENT_KIT_GM_API_KEY"),
    }


def _build_gm_agent() -> Agent:
    config = gm_configuration()
    provider_name = str(config["provider"])
    model_name = str(config["model"])
    api_key = config["api_key"]

    try:
        if provider_name in ("ollama", "local"):
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider

            model = OpenAIChatModel(
                model_name,
                provider=OpenAIProvider(base_url=OLLAMA_BASE_URL, api_key=api_key or "ollama"),
            )
        elif provider_name == "anthropic":
            if not api_key:
                raise GMUnavailableError(
                    "AGENT_KIT_GM_PROVIDER=anthropic requires AGENT_KIT_GM_API_KEY"
                )
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            model = AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key))
        elif provider_name == "openai":
            if not api_key:
                raise GMUnavailableError(
                    "AGENT_KIT_GM_PROVIDER=openai requires AGENT_KIT_GM_API_KEY"
                )
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider

            model = OpenAIChatModel(model_name, provider=OpenAIProvider(api_key=api_key))
        else:
            raise GMUnavailableError(
                f"unsupported GM provider '{provider_name}'; "
                "expected one of: ollama, local, anthropic, openai"
            )
    except GMUnavailableError:
        raise
    except Exception as e:
        raise GMUnavailableError(f"could not construct GM model '{model_name}': {e}") from e

    return Agent(
        model=model,
        output_type=GMSynthesis,
        system_prompt=_GM_SYSTEM_PROMPT,
        retries=_GM_OUTPUT_RETRIES,
    )


def _format_fragments(selected_bands: dict[str, PromptBand]) -> str:
    return "\n".join(
        f"- {name} (currently '{selected_bands[name].label}'): {selected_bands[name].text}"
        for name in sorted(selected_bands)
    )


def synthesize_traits(
    agent_name: str,
    system_prompt: str,
    selected_bands: dict[str, PromptBand],
    card_title: str = "",
) -> GMSynthesis:
    """Ask the GM to weave the selected fragments into one trait paragraph.

    Raises GMUnavailableError on any failure — the caller is responsible for
    falling back to a previously cached paragraph (and flagging the agent as
    needing a respec) rather than failing the agent's run.
    """
    if os.environ.get("STUB_AI_PROVIDERS") == "1":
        raise GMUnavailableError(
            "GM synthesis is disabled in stub mode; callers must use the deterministic fallback"
        )

    if not selected_bands:
        return GMSynthesis(trait_paragraph="")

    gm_agent = _build_gm_agent()
    prompt = (
        f"Agent name: {agent_name}\n"
        f"Character: {card_title or '(untitled)'}\n\n"
        f"The agent's own system prompt:\n{system_prompt}\n\n"
        f"Current behavioural fragments, one per stat:\n{_format_fragments(selected_bands)}"
    )

    try:
        result = gm_agent.run_sync(prompt)
    except Exception as e:
        raise GMUnavailableError(f"GM synthesis failed for agent '{agent_name}': {e}") from e

    return result.output
