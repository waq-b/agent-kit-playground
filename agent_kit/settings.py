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

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = "agent_kit_data"
_SETTINGS_FILENAME = "settings.json"

DEFAULT_PROVIDER_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:14b"
DEFAULT_DB_PATH = "agent_kit.db"


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
