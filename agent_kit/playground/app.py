"""Playground — a minimal FastAPI app for interactively listing and running agents."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError, model_validator

from agent_kit import builder
from agent_kit.card_definition import CardDefinition
from agent_kit.card_store import get_card_store
from agent_kit.class_registry import get_class_registry
from agent_kit.definition import AgentDefinition
from agent_kit.errors import (
    AgentKitError,
    AgentNotFoundError,
    ClassNotFoundError,
    CoreAgentConfirmationRequiredError,
    DuplicateAgentError,
    DuplicateClassError,
    GMSuggestionNotFoundError,
    UnknownGradeActionError,
)
from agent_kit.model_codegen import FieldSpec
from agent_kit.registry import get_registry
from agent_kit.runner import Runner
from agent_kit.settings import (
    ModelKind,
    ModelProviderEntry,
    PlaygroundSettings,
    apply_to_environment,
    load_settings,
    save_settings,
)
from agent_kit.tool_registry import get_tool_registry

@asynccontextmanager
async def _lifespan(app: FastAPI):
    # `import agent_kit` already ran _initialise(), which only loads the
    # built-in package agents dir. Layer in any builder-created/edited agents
    # from a *previous* process's data directory too, so they survive a
    # server restart — not just "no restart needed within this session"
    # (already true for any create/update/delete/duplicate call, which each
    # trigger their own reload). Using the ASGI lifespan hook rather than a
    # bare module-level call matters: a bare call fires the instant this
    # module is imported — including by the test suite, before any test's
    # monkeypatch of builder.DEFAULT_PATHS takes effect — and would litter a
    # real agent_kit_data/ directory into whatever the test runner's cwd is.
    # The lifespan hook only fires for a real ASGI server run (uvicorn); the
    # existing tests all use plain TestClient(app) without a `with` block,
    # which never triggers lifespan at all, so they're unaffected.
    builder.reload_registries()
    # Push any persisted settings into the environment before serving a single
    # request, so STUB_AI_PROVIDERS / the provider URL / the db path are already
    # what the user last saved. Same reasoning as the reload above: lifespan, not
    # import time, so the test suite's own environment is never clobbered.
    apply_to_environment(load_settings())
    # hello/news ship as plain YAML, never went through the Builder wizard, and
    # so never got a sample input — leaving the Run screen with nothing to
    # prefill for either. Idempotent: a no-op once seeded, or once a user has
    # edited either one's sample input themselves.
    builder.seed_core_sample_inputs()
    yield


app = FastAPI(title="agent-kit playground", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    """This service is an API only — the Playground UI (`frontend/`) is a
    separate React app, not served from here (see README: no StaticFiles
    mount, run it with `npm run dev` or `./dev.sh`). `/`, `/cards` and
    `/builder` used to serve a hand-rolled HTML/JS playground; removed once
    the React app fully replaced it, rather than kept as a second,
    unmaintained UI claiming to be the same tool."""
    return {
        "service": "agent-kit playground API",
        "docs": "/docs",
        "ui": "run the frontend separately — see README.md",
    }


class AgentSummary(BaseModel):
    name: str
    description: str


class RunRequest(BaseModel):
    input: dict[str, Any] = Field(
        ..., description="Agent input as a JSON object; passed to Runner as-is"
    )

    @model_validator(mode="after")
    def input_not_empty(self) -> "RunRequest":
        if not self.input:
            raise ValueError("input must not be an empty object")
        if len(json.dumps(self.input)) > 10_000:
            raise ValueError("input exceeds 10,000 character size limit")
        return self


class RunResponse(BaseModel):
    output: dict[str, Any]
    raw_prompt: str
    raw_response: str
    tools_used: list[str] = []


class CardSummary(BaseModel):
    name: str
    title: str
    main_class: str
    sub_class: str | None
    portrait: str
    level: int
    xp: int
    base_stats: dict[str, int]
    class_stats: dict[str, int]
    awaiting_respec: bool = False


class CardDetail(CardSummary):
    backstory: str
    unlock_table: list[dict[str, Any]]
    tool_proficiency: dict[str, dict[str, int]]


class GradeRequest(BaseModel):
    action: str
    tool_used: str | None = None


class GradeResponse(BaseModel):
    xp_delta: int
    new_xp: int
    new_level: int
    leveled_up: bool
    stat_deltas: dict[str, int]
    # v0.5 — surfaced so the Run screen can tell the user why the agent just
    # entered the respec queue, instead of it silently appearing on the Roster.
    events_since_respec: int = 0
    respec_queued: bool = False
    respec_processed: bool = False


@app.get("/api/v1/agents", response_model=list[AgentSummary])
def list_agents() -> list[AgentSummary]:
    return [AgentSummary(**d) for d in get_registry().list()]


@app.post("/api/v1/agents/{agent_name}/run", response_model=RunResponse)
def run_agent_endpoint(agent_name: str, request: RunRequest) -> RunResponse:
    try:
        definition = get_registry().get(agent_name)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"agent '{agent_name}' not found")

    # Agents with no input_model keep the pass-through behaviour they've always
    # had (Task 1's field is optional for exactly this reason). Agents with one
    # get real 422s with field-level detail here, before Runner ever sees a
    # malformed input — not a failure surfacing deep inside the agent.
    input_data = request.input
    if definition.input_model is not None:
        try:
            input_data = definition.input_model.model_validate(request.input).model_dump()
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors(include_url=False))

    runner = Runner()
    try:
        result = runner.execute(definition, input_data)
    except AgentKitError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return RunResponse(
        output=result.model_dump(),
        raw_prompt=runner.last_raw_prompt,
        raw_response=runner.last_raw_response,
        tools_used=runner.last_tools_used,
    )


def _get_agent_definition(agent_name: str) -> AgentDefinition:
    try:
        return get_registry().get(agent_name)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"agent '{agent_name}' not found")


def _card_summary(agent_name: str, card: CardDefinition) -> CardSummary:
    store = get_card_store()
    store.ensure_seeded(agent_name, card)
    state = store.get_state(agent_name)
    traits = store.get_traits(agent_name)
    return CardSummary(
        name=agent_name,
        title=card.title,
        main_class=card.main_class.name,
        sub_class=card.sub_class.name if card.sub_class else None,
        portrait=card.portrait,
        level=state.level,
        xp=state.xp,
        base_stats=state.base_stats,
        class_stats=state.class_stats,
        awaiting_respec=bool(traits and traits.is_stale),
    )


@app.get("/api/v1/cards", response_model=list[CardSummary])
def list_cards() -> list[CardSummary]:
    summaries = []
    for entry in get_registry().list():
        definition = get_registry().get(entry["name"])
        if definition.card is not None:
            summaries.append(_card_summary(entry["name"], definition.card))
    return summaries


@app.get("/api/v1/agents/{agent_name}/card", response_model=CardDetail)
def get_agent_card(agent_name: str) -> CardDetail:
    definition = _get_agent_definition(agent_name)
    if definition.card is None:
        raise HTTPException(status_code=404, detail=f"agent '{agent_name}' has no card")

    summary = _card_summary(agent_name, definition.card)
    state = get_card_store().get_state(agent_name)
    return CardDetail(
        **summary.model_dump(),
        backstory=definition.card.backstory,
        unlock_table=[
            {"level": u.level, "unlock": u.unlock, "description": u.description}
            for u in definition.card.unlock_table
        ],
        tool_proficiency={name: tp.model_dump() for name, tp in state.tool_proficiency.items()},
    )


@app.post("/api/v1/agents/{agent_name}/grade", response_model=GradeResponse)
def grade_agent(agent_name: str, request: GradeRequest) -> GradeResponse:
    definition = _get_agent_definition(agent_name)
    if definition.card is None:
        raise HTTPException(status_code=400, detail=f"agent '{agent_name}' has no card to grade")

    store = get_card_store()
    store.ensure_seeded(agent_name, definition.card)
    try:
        result = store.record_xp_event(agent_name, request.action, request.tool_used)
    except UnknownGradeActionError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Respec threshold: enough grading has accumulated since the last synthesis
    # that the cached trait paragraph no longer reflects how this agent is being
    # steered. Flag it for respec — and, if configured, do the respec right here
    # rather than waiting for someone to press Process Queue.
    settings = load_settings()
    events_since = store.count_events_since_synthesis(agent_name)
    respec_queued = False
    respec_processed = False
    if events_since >= settings.respec_threshold:
        traits = store.get_traits(agent_name)
        if traits is not None and not traits.is_stale:
            store.mark_traits_stale(agent_name)
            respec_queued = True
        if settings.auto_process_respec:
            processed = _process_respec_queue()
            respec_processed = agent_name in processed.resynthesized

    return GradeResponse(
        **result.model_dump(),
        events_since_respec=events_since,
        respec_queued=respec_queued,
        respec_processed=respec_processed,
    )


# --- Agent Builder (v0.3) ---


class ClassSummary(BaseModel):
    name: str
    title: str
    description: str
    stats: dict[str, int]


class CardSpec(BaseModel):
    main_class: str
    sub_class: str | None = None
    title: str | None = None
    backstory: str = ""
    portrait: str = ""
    base_stats: dict[str, int] | None = None
    unlock_table: list[dict[str, Any]] | None = None
    level: int = 1
    xp: int = 0


class AgentBuilderDetail(BaseModel):
    name: str
    description: str
    system_prompt: str
    model: str
    temperature: float
    tools: list[str]
    feeds: list[str]
    card: dict[str, Any] | None
    is_core: bool
    output_model_editable: bool
    output_fields_summary: dict[str, str]
    # None means "this agent has no input model at all" — distinct from an
    # editable-but-empty one (which can't actually exist; a generated model
    # always has at least one field). input_model_editable is True in that
    # no-model-yet case too: adding a first one is always allowed, there's
    # nothing hand-written to protect.
    input_model_editable: bool
    input_fields_summary: dict[str, str] | None
    # The original FieldSpec list, when known (refinement Phase 2, Task 10) —
    # None for a hand-written model, or a builder-generated one predating this
    # field (no sidecar was ever written for it). *_fields_summary above is
    # never removed: it's the fallback the wizard reconstructs from when this
    # is None, since it's derivable for every model, hand-written or not.
    output_field_spec: list[FieldSpec] | None
    input_field_spec: list[FieldSpec] | None
    sample_input: dict[str, Any] | None


class CreateAgentRequest(BaseModel):
    name: str
    system_prompt: str
    output_fields: list[FieldSpec]
    # Optional at the API layer — Task 1's "optional at load time" carries
    # through here. The wizard enforces "required for new agents" client-side;
    # a direct API caller can still omit it on purpose.
    input_fields: list[FieldSpec] | None = None
    description: str = ""
    model: str = "qwen2.5:14b"
    temperature: float = 0.7
    tools: list[str] = []
    feeds: list[str] = []
    card: CardSpec | None = None
    sample_input: dict[str, Any] | None = None


class UpdateAgentRequest(BaseModel):
    system_prompt: str | None = None
    output_fields: list[FieldSpec] | None = None
    # None = leave the input model exactly as it is (same "only send if
    # actually touched" contract output_fields already has).
    input_fields: list[FieldSpec] | None = None
    description: str | None = None
    model: str | None = None
    temperature: float | None = None
    tools: list[str] | None = None
    feeds: list[str] | None = None
    card: CardSpec | None = None
    sample_input: dict[str, Any] | None = None


class DuplicateAgentRequest(BaseModel):
    new_name: str


class CreateClassRequest(BaseModel):
    content: str  # raw YAML or JSON class definition, authored as code


class ModelCheckResponse(BaseModel):
    available: bool
    message: str


def _handle_builder_error(e: AgentKitError) -> HTTPException:
    if isinstance(e, (AgentNotFoundError, ClassNotFoundError, GMSuggestionNotFoundError)):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, CoreAgentConfirmationRequiredError):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, (DuplicateAgentError, DuplicateClassError)):
        return HTTPException(status_code=409, detail=str(e))
    return HTTPException(status_code=422, detail=str(e))


def _agent_builder_detail(definition: AgentDefinition) -> AgentBuilderDetail:
    return AgentBuilderDetail(
        name=definition.name,
        description=definition.description,
        system_prompt=definition.system_prompt,
        model=definition.model,
        temperature=definition.temperature,
        tools=list(definition.tools),
        feeds=list(definition.feeds),
        card=builder.card_definition_to_dict(definition.card),
        is_core=definition.name in builder.CORE_AGENT_NAMES,
        output_model_editable=builder.is_builder_generated(definition),
        output_fields_summary={
            field_name: str(field.annotation)
            for field_name, field in definition.output_model.model_fields.items()
        },
        input_model_editable=(
            True if definition.input_model is None else builder.is_input_builder_generated(definition)
        ),
        input_fields_summary=(
            {
                field_name: str(field.annotation)
                for field_name, field in definition.input_model.model_fields.items()
            }
            if definition.input_model is not None
            else None
        ),
        output_field_spec=builder.read_output_field_spec(definition.name),
        input_field_spec=builder.read_input_field_spec(definition.name),
        sample_input=builder.read_sample_input(definition.name),
    )


@app.get("/api/v1/tools", response_model=list[str])
def list_tools() -> list[str]:
    return get_tool_registry().list_names()


@app.get("/api/v1/classes", response_model=list[ClassSummary])
def list_classes() -> list[ClassSummary]:
    summaries = []
    for entry in get_class_registry().list():
        class_def = get_class_registry().get(entry["name"])
        summaries.append(
            ClassSummary(
                name=class_def.name, title=class_def.title,
                description=class_def.description, stats=class_def.stat_values,
            )
        )
    return summaries


@app.get("/api/v1/agents/{agent_name}/builder", response_model=AgentBuilderDetail)
def get_agent_builder_detail(agent_name: str) -> AgentBuilderDetail:
    definition = _get_agent_definition(agent_name)
    return _agent_builder_detail(definition)


@app.get("/api/v1/agents/{agent_name}/sample-input")
def get_sample_input(agent_name: str) -> dict[str, Any] | None:
    _get_agent_definition(agent_name)
    return builder.read_sample_input(agent_name)


@app.post("/api/v1/builder/agents", response_model=AgentBuilderDetail)
def create_agent_endpoint(request: CreateAgentRequest) -> AgentBuilderDetail:
    try:
        definition = builder.create_agent(
            request.name,
            system_prompt=request.system_prompt,
            output_fields=request.output_fields,
            input_fields=request.input_fields,
            description=request.description,
            model=request.model,
            temperature=request.temperature,
            tools=request.tools,
            feeds=request.feeds,
            card=request.card.model_dump(exclude_none=True) if request.card else None,
            sample_input=request.sample_input,
        )
    except AgentKitError as e:
        raise _handle_builder_error(e)
    return _agent_builder_detail(definition)


@app.put("/api/v1/builder/agents/{agent_name}", response_model=AgentBuilderDetail)
def update_agent_endpoint(agent_name: str, request: UpdateAgentRequest) -> AgentBuilderDetail:
    try:
        definition = builder.update_agent(
            agent_name,
            system_prompt=request.system_prompt,
            output_fields=request.output_fields,
            input_fields=request.input_fields,
            description=request.description,
            model=request.model,
            temperature=request.temperature,
            tools=request.tools,
            feeds=request.feeds,
            card=request.card.model_dump(exclude_none=True) if request.card else None,
            sample_input=request.sample_input,
        )
    except AgentKitError as e:
        raise _handle_builder_error(e)
    return _agent_builder_detail(definition)


@app.delete("/api/v1/builder/agents/{agent_name}")
def delete_agent_endpoint(agent_name: str, confirm: bool = False, confirm_core: bool = False) -> dict[str, str]:
    if not confirm:
        raise HTTPException(status_code=400, detail="deletion requires confirm=true")
    try:
        builder.delete_agent(agent_name, confirm_core=confirm_core)
    except AgentKitError as e:
        raise _handle_builder_error(e)
    return {"status": "deleted", "name": agent_name}


@app.post("/api/v1/builder/agents/{agent_name}/duplicate", response_model=AgentBuilderDetail)
def duplicate_agent_endpoint(agent_name: str, request: DuplicateAgentRequest) -> AgentBuilderDetail:
    try:
        definition = builder.duplicate_agent(agent_name, request.new_name)
    except AgentKitError as e:
        raise _handle_builder_error(e)
    return _agent_builder_detail(definition)


@app.post("/api/v1/builder/classes", response_model=ClassSummary)
def create_class_endpoint(request: CreateClassRequest) -> ClassSummary:
    try:
        class_def = builder.create_class(request.content)
    except AgentKitError as e:
        raise _handle_builder_error(e)
    return ClassSummary(
        name=class_def.name, title=class_def.title,
        description=class_def.description, stats=class_def.stat_values,
    )


@app.get("/api/v1/builder/model-check", response_model=ModelCheckResponse)
def model_check_endpoint(model: str) -> ModelCheckResponse:
    return ModelCheckResponse(**builder.check_model_reachable(model))


# --- GM respec queue and suggestions (v0.4) ---


class RespecQueueEntry(BaseModel):
    agent_name: str
    band_signature: str
    pending_since: str | None
    trait_paragraph: str


class RespecProcessResult(BaseModel):
    processed: int
    resynthesized: list[str]
    still_pending: list[str]


class SuggestionSummary(BaseModel):
    id: int
    agent_name: str
    current_system_prompt: str
    suggested_system_prompt: str
    rationale: str
    status: str
    created_at: str


@app.get("/api/v1/gm/queue", response_model=list[RespecQueueEntry])
def gm_queue() -> list[RespecQueueEntry]:
    return [
        RespecQueueEntry(
            agent_name=t.agent_name, band_signature=t.band_signature,
            pending_since=t.pending_since, trait_paragraph=t.trait_paragraph,
        )
        for t in get_card_store().list_stale_agents()
    ]


def _process_respec_queue() -> RespecProcessResult:
    """Retry GM synthesis for every debuffed agent.

    Shared by the explicit `POST /gm/queue/process` and by the auto-process
    setting. Still synchronous and in-request either way — the auto path just
    calls this at the end of a grade instead of waiting for a button — so
    agent-kit stays single-threaded and every respec remains observable in the
    response that triggered it.
    """
    from agent_kit.gm import synthesize_traits
    from agent_kit.stat_effects import band_signature, resolve_effects

    settings = load_settings()
    store = get_card_store()
    resynthesized: list[str] = []
    still_pending: list[str] = []
    queued = store.list_stale_agents()

    for entry in queued:
        try:
            definition = get_registry().get(entry.agent_name)
        except AgentNotFoundError:
            still_pending.append(entry.agent_name)
            continue
        if definition.card is None:
            still_pending.append(entry.agent_name)
            continue

        stat_defs = {
            **definition.card.main_class.stats,
            **(definition.card.sub_class.stats if definition.card.sub_class else {}),
        }
        state = store.get_state(entry.agent_name)
        resolved = resolve_effects(stat_defs, state.class_stats)

        try:
            synthesis = synthesize_traits(
                entry.agent_name, definition.system_prompt,
                resolved.selected_bands, definition.card.title,
            )
        except AgentKitError:
            still_pending.append(entry.agent_name)
            continue

        store.store_traits(
            entry.agent_name, band_signature(resolved.selected_bands), synthesis.trait_paragraph
        )
        if synthesis.suggested_system_prompt and settings.suggestions_enabled:
            store.record_suggestion(
                entry.agent_name, definition.system_prompt, synthesis.suggested_system_prompt,
                "; ".join(synthesis.conflicts) or "the GM recommended a system prompt revision",
            )
        resynthesized.append(entry.agent_name)

    return RespecProcessResult(
        processed=len(queued), resynthesized=resynthesized, still_pending=still_pending
    )


@app.post("/api/v1/gm/queue/process", response_model=RespecProcessResult)
def gm_queue_process() -> RespecProcessResult:
    return _process_respec_queue()


@app.get("/api/v1/gm/suggestions", response_model=list[SuggestionSummary])
def gm_suggestions(status: str | None = "pending") -> list[SuggestionSummary]:
    return [
        SuggestionSummary(**s.model_dump())
        for s in get_card_store().list_suggestions(None if status == "all" else status)
    ]


@app.post("/api/v1/gm/suggestions/{suggestion_id}/approve", response_model=SuggestionSummary)
def gm_approve_suggestion(suggestion_id: int) -> SuggestionSummary:
    """Apply a GM-suggested system prompt via the normal builder update path,
    so it inherits validate-then-commit and hot-reload like any other edit."""
    store = get_card_store()
    try:
        suggestion = store.get_suggestion(suggestion_id)
        builder.update_agent(suggestion.agent_name, system_prompt=suggestion.suggested_system_prompt)
        resolved = store.resolve_suggestion(suggestion_id, "approved")
    except AgentKitError as e:
        raise _handle_builder_error(e)
    return SuggestionSummary(**resolved.model_dump())


@app.post("/api/v1/gm/suggestions/{suggestion_id}/reject", response_model=SuggestionSummary)
def gm_reject_suggestion(suggestion_id: int) -> SuggestionSummary:
    try:
        resolved = get_card_store().resolve_suggestion(suggestion_id, "rejected")
    except AgentKitError as e:
        raise _handle_builder_error(e)
    return SuggestionSummary(**resolved.model_dump())


# --- Server settings (v0.5) ---


class SettingsUpdate(BaseModel):
    """Every field optional so the UI can PATCH-style one toggle at a time."""

    provider_url: str | None = None
    default_model: str | None = None
    gm_model: str | None = None
    stub_mode: bool | None = None
    respec_threshold: int | None = Field(default=None, ge=1, le=50)
    auto_process_respec: bool | None = None
    suggestions_enabled: bool | None = None
    ntfy_url: str | None = None
    db_path: str | None = None


# `models` carries plaintext API keys internally (see settings.py); excluded
# from both settings responses so a key never crosses the wire. The model
# registry has its own masked read path below (`ModelProviderSummary`).
_SETTINGS_RESPONSE_EXCLUDE = {"models"}


@app.get("/api/v1/settings", response_model=PlaygroundSettings, response_model_exclude=_SETTINGS_RESPONSE_EXCLUDE)
def get_settings() -> PlaygroundSettings:
    return load_settings()


@app.put("/api/v1/settings", response_model=PlaygroundSettings, response_model_exclude=_SETTINGS_RESPONSE_EXCLUDE)
def put_settings(request: SettingsUpdate) -> PlaygroundSettings:
    """Merge the patch over current settings, persist, and apply to the process.

    Process-global by nature: flipping stub mode changes behaviour for every
    caller of this server, not just this browser tab. That is acceptable for a
    playground that binds to localhost with no auth layer, and it is what makes
    the setting take effect without a restart.
    """
    current = load_settings()
    patch = request.model_dump(exclude_none=True)
    return save_settings(current.model_copy(update=patch))


# --- Model provider registry (v0.6) ---
#
# A model is either "local" (routes through the shared provider_url above,
# same as every model did before this existed) or "frontier" (its own base_url
# + api_key, entered once here). Registering isn't required to run against a
# local model — any string still works, exactly as before — but it is the only
# way to reach a frontier one: the Runner has no other source for that URL/key.


class ModelProviderSummary(BaseModel):
    """`ModelProviderEntry` without the api_key — what the browser is allowed to see."""

    model_id: str
    label: str
    kind: ModelKind
    base_url: str | None = None
    has_api_key: bool = False


class CreateModelRequest(BaseModel):
    model_id: str
    label: str = ""
    kind: ModelKind
    base_url: str | None = None
    api_key: str | None = None


def _model_summary(entry: ModelProviderEntry) -> ModelProviderSummary:
    return ModelProviderSummary(
        model_id=entry.model_id,
        label=entry.label or entry.model_id,
        kind=entry.kind,
        base_url=entry.base_url,
        has_api_key=bool(entry.api_key),
    )


@app.get("/api/v1/models", response_model=list[ModelProviderSummary])
def list_models() -> list[ModelProviderSummary]:
    return [_model_summary(m) for m in load_settings().models]


@app.post("/api/v1/models", response_model=ModelProviderSummary, status_code=201)
def create_model(request: CreateModelRequest) -> ModelProviderSummary:
    settings = load_settings()
    if any(m.model_id == request.model_id for m in settings.models):
        raise HTTPException(status_code=409, detail=f"model '{request.model_id}' is already registered")
    try:
        entry = ModelProviderEntry(**request.model_dump())
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    settings.models = [*settings.models, entry]
    save_settings(settings)
    return _model_summary(entry)


@app.delete("/api/v1/models/{model_id}")
def delete_model(model_id: str) -> dict[str, str]:
    settings = load_settings()
    if not any(m.model_id == model_id for m in settings.models):
        raise HTTPException(status_code=404, detail=f"model '{model_id}' is not registered")
    settings.models = [m for m in settings.models if m.model_id != model_id]
    save_settings(settings)
    return {"status": "deleted", "model_id": model_id}




if __name__ == "__main__":
    import uvicorn

    # Playground is local-only (Req 6.5): bind exclusively to 127.0.0.1, never 0.0.0.0.
    uvicorn.run(app, host="127.0.0.1", port=8000)
