"""PlaygroundSettings — runtime-configurable server settings, persisted to disk.

Everything here was previously an environment variable read at call time (or, in
the case of the provider URL, a module constant). The playground's Settings
screen needs to read and write these at runtime, so this module owns:

  * the canonical schema and defaults (`PlaygroundSettings`),
  * a JSON file under the same data directory the builder uses,
  * and `apply_to_environment()`, which pushes the values back into
    `os.environ` so the existing call-time `os.environ.get(...)` reads in
    runner/gm/notify/card_store keep working unchanged.

Environment variables stay the transport rather than being replaced, so anyone
running agent-kit as a library (no playground, no settings file) sees exactly
the v0.4 behaviour.

**Precedence**: on first use the settings file is seeded *from* the current
environment, so `STUB_AI_PROVIDERS=1 uvicorn ...` still does what you expect.
Once the file exists it is the source of truth and `apply_to_environment()`
overwrites the environment from it — otherwise a value saved in the UI would be
silently ignored on the next restart.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = "agent_kit_data"
_SETTINGS_FILENAME = "settings.json"

DEFAULT_PROVIDER_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:14b"
DEFAULT_DB_PATH = "agent_kit.db"

ModelKind = Literal["local", "frontier"]


class ModelProviderEntry(BaseModel):
    """One registered model: what to call it, and how to reach it.

    `kind="local"` entries carry no URL/key of their own — they always resolve
    to the shared `provider_url` above, so moving that one URL moves every
    local model with it (this mirrors how `provider_url` already worked before
    a registry existed: one shared endpoint for every locally-run model).
    `kind="frontier"` entries are self-contained: their own base_url and
    api_key, since a frontier provider (OpenAI, a hosted gateway, ...) has
    nothing to do with the local Ollama instance.
    """

    model_id: str = Field(min_length=1)
    label: str = ""
    kind: ModelKind
    base_url: str | None = None
    api_key: str | None = None

    @model_validator(mode="after")
    def _normalise(self) -> "ModelProviderEntry":
        if self.kind == "local":
            self.base_url = None
            self.api_key = None
        else:
            if not (self.base_url or "").strip():
                raise ValueError("a frontier model needs a base URL")
            if not (self.api_key or "").strip():
                raise ValueError("a frontier model needs an API key")
        return self


class PlaygroundSettings(BaseModel):
    """Server-side settings the playground UI can edit.

    The UI's "Base URL" field is deliberately absent: that is which server the
    browser talks to, which only the browser can know. It stays client-side.
    """

    provider_url: str = DEFAULT_PROVIDER_URL
    default_model: str = DEFAULT_MODEL
    gm_model: str = DEFAULT_MODEL
    stub_mode: bool = False
    respec_threshold: int = Field(default=12, ge=1, le=50)
    auto_process_respec: bool = False
    suggestions_enabled: bool = True
    ntfy_url: str = ""
    db_path: str = DEFAULT_DB_PATH
    # API keys live here in plaintext, same as every other setting — consistent
    # with this being a localhost-only dev tool with no auth layer (see README).
    # Never sent back to the browser: app.py masks it behind `has_api_key` on
    # every response that touches this list.
    models: list[ModelProviderEntry] = Field(default_factory=list)


def settings_path() -> Path:
    """Resolved per call, not cached, so tests can repoint AGENT_KIT_DATA_DIR."""
    root = os.environ.get("AGENT_KIT_DATA_DIR", _DEFAULT_DATA_DIR)
    return Path(root) / _SETTINGS_FILENAME


def settings_from_environment() -> PlaygroundSettings:
    """Seed values from the environment — used when no settings file exists yet."""
    return PlaygroundSettings(
        provider_url=os.environ.get("AGENT_KIT_PROVIDER_URL", DEFAULT_PROVIDER_URL),
        gm_model=os.environ.get("AGENT_KIT_GM_MODEL", DEFAULT_MODEL),
        stub_mode=os.environ.get("STUB_AI_PROVIDERS") == "1",
        ntfy_url=os.environ.get("NTFY_URL", ""),
        db_path=os.environ.get("AGENT_KIT_DB_PATH", DEFAULT_DB_PATH),
    )


def load_settings() -> PlaygroundSettings:
    """Read the settings file, falling back to environment-seeded defaults.

    A corrupt or unreadable file is logged and ignored rather than raised: the
    playground booting with default settings is strictly better than the whole
    server refusing to start over a malformed JSON blob.
    """
    path = settings_path()
    if not path.exists():
        return settings_from_environment()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("could not read settings from %s (%s); using defaults", path, e)
        return settings_from_environment()
    try:
        return PlaygroundSettings.model_validate(data)
    except Exception as e:
        logger.warning("settings in %s failed validation (%s); using defaults", path, e)
        return settings_from_environment()


def save_settings(settings: PlaygroundSettings) -> PlaygroundSettings:
    """Write settings to disk atomically, then push them into the environment."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings.model_dump(), indent=2) + "\n")
    os.replace(tmp, path)
    apply_to_environment(settings)
    return settings


def apply_to_environment(settings: PlaygroundSettings) -> None:
    """Push settings into `os.environ` for the call-time readers elsewhere.

    Also resets the CardStore singleton when `db_path` changes — that one is
    read once at construction, not per call, so it cannot pick up a new value
    on its own.
    """
    os.environ["AGENT_KIT_PROVIDER_URL"] = settings.provider_url
    os.environ["AGENT_KIT_GM_MODEL"] = settings.gm_model
    os.environ["STUB_AI_PROVIDERS"] = "1" if settings.stub_mode else "0"

    if settings.ntfy_url:
        os.environ["NTFY_URL"] = settings.ntfy_url
    else:
        # notify.py treats a missing NTFY_URL as "notifications off"; an empty
        # string would read as configured-but-broken, so unset it entirely.
        os.environ.pop("NTFY_URL", None)

    # Compare against the *effective* current path — an unset AGENT_KIT_DB_PATH
    # already means DEFAULT_DB_PATH, so comparing against None would tear down
    # and rebuild the store on the first save of any unrelated setting.
    effective_db_path = os.environ.get("AGENT_KIT_DB_PATH", DEFAULT_DB_PATH)
    os.environ["AGENT_KIT_DB_PATH"] = settings.db_path
    if effective_db_path != settings.db_path:
        from agent_kit.card_store import reset_card_store

        reset_card_store()


class ResolvedProvider(BaseModel):
    """Where to send a request for a given model id, and how to authenticate."""

    base_url: str
    api_key: str
    is_frontier: bool


def resolve_model_provider(model_id: str) -> ResolvedProvider:
    """Look up how to reach `model_id`.

    A model explicitly registered as frontier gets its own base_url + api_key.
    Everything else — a registered local model, or a model that was never
    registered at all (the v0.1–v0.4 default: any string works as long as the
    local Ollama instance has it) — resolves to the shared local provider_url
    with the fixed placeholder key Ollama ignores. Registration is required to
    reach a frontier provider at all (there is no other way for the Runner to
    learn its URL/key); it is purely a convenience for local models, never a
    requirement.
    """
    settings = load_settings()
    for entry in settings.models:
        if entry.model_id == model_id and entry.kind == "frontier":
            return ResolvedProvider(
                base_url=entry.base_url or "", api_key=entry.api_key or "", is_frontier=True
            )

    # Lazy import: runner.py imports load_settings from this module at module
    # level, so importing it back here at module level would be circular.
    from agent_kit.runner import provider_base_url

    return ResolvedProvider(base_url=provider_base_url(), api_key="ollama", is_frontier=False)
