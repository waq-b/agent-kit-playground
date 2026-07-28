"""Playground — a minimal FastAPI app for interactively listing and running agents."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

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
    yield


app = FastAPI(title="agent-kit playground", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/api/v1/agents", response_model=list[AgentSummary])
def list_agents() -> list[AgentSummary]:
    return [AgentSummary(**d) for d in get_registry().list()]


@app.post("/api/v1/agents/{agent_name}/run", response_model=RunResponse)
def run_agent_endpoint(agent_name: str, request: RunRequest) -> RunResponse:
    try:
        definition = get_registry().get(agent_name)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail=f"agent '{agent_name}' not found")

    runner = Runner()
    try:
        result = runner.execute(definition, request.input)
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

    get_card_store().ensure_seeded(agent_name, definition.card)
    try:
        result = get_card_store().record_xp_event(agent_name, request.action, request.tool_used)
    except UnknownGradeActionError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return GradeResponse(**result.model_dump())


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
    sample_input: dict[str, Any] | None


class CreateAgentRequest(BaseModel):
    name: str
    system_prompt: str
    output_fields: list[FieldSpec]
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


@app.post("/api/v1/gm/queue/process", response_model=RespecProcessResult)
def gm_queue_process() -> RespecProcessResult:
    """Retry GM synthesis for every debuffed agent — the "as soon as the GM is
    available" action. Explicit rather than a background thread, so it stays
    observable and keeps agent-kit single-threaded."""
    from agent_kit.gm import synthesize_traits
    from agent_kit.stat_effects import band_signature, resolve_effects

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
        if synthesis.suggested_system_prompt:
            store.record_suggestion(
                entry.agent_name, definition.system_prompt, synthesis.suggested_system_prompt,
                "; ".join(synthesis.conflicts) or "the GM recommended a system prompt revision",
            )
        resynthesized.append(entry.agent_name)

    return RespecProcessResult(
        processed=len(queued), resynthesized=resynthesized, still_pending=still_pending
    )


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


_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>agent-kit playground</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; background: #ffffff; }
  h1 { font-size: 1.4rem; }
  select, textarea, button { font-family: inherit; font-size: 1rem; }
  textarea { width: 100%; box-sizing: border-box; min-height: 6rem; }
  #agent-list { margin-bottom: 1.5rem; }
  .agent-entry { padding: 0.4rem 0; border-bottom: 1px solid #eee; }
  .agent-entry b { color: #222; }
  form { display: flex; flex-direction: column; gap: 0.6rem; max-width: 500px; }
  #error { color: #b00020; white-space: pre-wrap; }
  #output pre { background: #f5f5f5; padding: 0.75rem; overflow-x: auto; border-radius: 4px; }
  details summary { cursor: pointer; margin-top: 0.5rem; }
  nav a { font-size: 0.9rem; }
  .grading { margin-top: 0.75rem; display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
  .grading button { cursor: pointer; }
  #grade-status { color: #2a6f2a; margin-top: 0.4rem; min-height: 1.2rem; }
</style>
</head>
<body>
<h1>agent-kit playground</h1>
<nav><a href="/cards">View character roster →</a> · <a href="/builder">Build/edit agents →</a></nav>

<div id="agent-list">Loading agents…</div>

<form id="run-form">
  <label for="agent-select">Agent</label>
  <select id="agent-select" name="agent"></select>

  <label for="input-text">Input (JSON object)</label>
  <textarea id="input-text" name="input">{}</textarea>

  <button type="submit">Run</button>
</form>

<div id="error"></div>
<div id="output"></div>

<script>
let agents = [];

async function loadAgents() {
  const res = await fetch('/api/v1/agents');
  agents = await res.json();
  const listEl = document.getElementById('agent-list');
  const selectEl = document.getElementById('agent-select');
  selectEl.innerHTML = '';

  if (agents.length === 0) {
    listEl.textContent = 'No agents available.';
    return;
  }

  listEl.innerHTML = agents.map(
    a => `<div class="agent-entry"><b>${a.name}</b> — ${a.description}</div>`
  ).join('');

  for (const a of agents) {
    const opt = document.createElement('option');
    opt.value = a.name;
    opt.textContent = a.name;
    selectEl.appendChild(opt);
  }

  const preselect = new URLSearchParams(window.location.search).get('agent');
  if (preselect && agents.some(a => a.name === preselect)) {
    selectEl.value = preselect;
    try {
      const sampleRes = await fetch(`/api/v1/agents/${encodeURIComponent(preselect)}/sample-input`);
      const sample = await sampleRes.json();
      if (sample) {
        document.getElementById('input-text').value = JSON.stringify(sample, null, 2);
      }
    } catch (e) { /* no sample input available — fine, leave the default {} */ }
  }
}

function formatDetail(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(d => (d && d.msg) ? d.msg : JSON.stringify(d)).join('; ');
  }
  return JSON.stringify(detail);
}

let lastRun = null;

function sendGrade(action) {
  if (!lastRun) return;
  const statusEl = document.getElementById('grade-status');
  fetch(`/api/v1/agents/${encodeURIComponent(lastRun.agentName)}/grade`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, tool_used: lastRun.toolUsed }),
  })
    .then(async (res) => {
      const result = await res.json();
      if (!res.ok) {
        statusEl.textContent = formatDetail(result.detail) || 'Could not record feedback.';
        return;
      }
      statusEl.textContent = result.leveled_up
        ? `+${result.xp_delta} XP — level up! Now level ${result.new_level}.`
        : `+${result.xp_delta} XP (total ${result.new_xp}, level ${result.new_level}).`;
    })
    .catch(() => { statusEl.textContent = 'Could not record feedback.'; });
}

function sendImplicitView() {
  if (!lastRun || lastRun.implicitViewSent) return;
  lastRun.implicitViewSent = true;
  sendGrade('implicit_view');
}

document.getElementById('run-form').addEventListener('submit', async (evt) => {
  evt.preventDefault();
  const errorEl = document.getElementById('error');
  const outputEl = document.getElementById('output');
  errorEl.textContent = '';
  outputEl.innerHTML = '';

  const agentName = document.getElementById('agent-select').value;
  const inputText = document.getElementById('input-text').value;

  let inputObj;
  try {
    inputObj = JSON.parse(inputText);
  } catch (e) {
    errorEl.textContent = 'Input is not valid JSON: ' + e.message;
    return;
  }

  try {
    const res = await fetch(`/api/v1/agents/${encodeURIComponent(agentName)}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input: inputObj }),
    });
    const data = await res.json();

    if (!res.ok) {
      errorEl.textContent = (data && data.detail) ? formatDetail(data.detail) : `Request failed (${res.status})`;
      return;
    }

    lastRun = {
      agentName,
      toolUsed: (data.tools_used && data.tools_used[0]) || null,
      implicitViewSent: false,
    };

    outputEl.innerHTML = `
      <h3>Output</h3>
      <pre>${JSON.stringify(data.output, null, 2)}</pre>
      <details id="raw-prompt-details"><summary>Raw prompt</summary><pre>${data.raw_prompt}</pre></details>
      <details id="raw-response-details"><summary>Raw response</summary><pre>${data.raw_response}</pre></details>
      <div class="grading">
        <span>Rate this result:</span>
        <button type="button" onclick="sendGrade('thumbs_up')">👍</button>
        <button type="button" onclick="sendGrade('thumbs_down')">👎</button>
        <button type="button" onclick="sendGrade('more_like_this')">More like this</button>
        <button type="button" onclick="sendGrade('less_like_this')">Less like this</button>
      </div>
      <div id="grade-status"></div>
    `;
    document.getElementById('raw-prompt-details').addEventListener('toggle', sendImplicitView);
    document.getElementById('raw-response-details').addEventListener('toggle', sendImplicitView);
  } catch (e) {
    errorEl.textContent = 'Request failed: ' + e.message;
  }
});

loadAgents();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX_HTML


_CARDS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>agent-kit playground — roster</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 1000px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; background: #ffffff; }
  h1 { font-size: 1.4rem; }
  nav a { font-size: 0.9rem; }
  #roster { display: flex; flex-wrap: wrap; gap: 1rem; margin-top: 1rem; }
  .card { border: 1px solid #ccc; border-radius: 8px; padding: 1rem; width: 260px; }
  .card .portrait { font-size: 2.5rem; }
  .card h2 { font-size: 1.1rem; margin: 0.3rem 0 0; }
  .card .meta { color: #666; font-size: 0.85rem; margin-bottom: 0.5rem; }
  .card .xp-bar { background: #eee; border-radius: 4px; height: 8px; overflow: hidden; margin-bottom: 0.6rem; }
  .card .xp-bar-fill { background: #2a6f2a; height: 100%; }
  .card .stat-group h3 { font-size: 0.8rem; text-transform: uppercase; color: #888; margin: 0.5rem 0 0.2rem; }
  .card .stat-row { display: flex; justify-content: space-between; font-size: 0.85rem; }
  .respec-badge { background: #fff4e0; color: #8a5a00; border: 1px solid #f0d9a8; border-radius: 4px; font-size: 0.75rem; padding: 0.15rem 0.4rem; margin-bottom: 0.5rem; display: inline-block; }
</style>
</head>
<body>
<h1>agent-kit playground — roster</h1>
<nav><a href="/">← Run agents</a> · <a href="/builder">Build/edit agents →</a></nav>

<div id="roster">Loading cards…</div>

<script>
function statRows(stats) {
  return Object.entries(stats).map(
    ([name, value]) => `<div class="stat-row"><span>${name}</span><span>${value}</span></div>`
  ).join('');
}

async function loadCards() {
  const res = await fetch('/api/v1/cards');
  const cards = await res.json();
  const rosterEl = document.getElementById('roster');

  if (cards.length === 0) {
    rosterEl.textContent = 'No character cards available.';
    return;
  }

  rosterEl.innerHTML = cards.map(c => {
    const xpIntoLevel = c.xp % 50;
    const xpPercent = Math.max(0, Math.min(100, (xpIntoLevel / 50) * 100));
    const classLine = c.sub_class ? `${c.main_class} / ${c.sub_class}` : c.main_class;
    return `
      <div class="card">
        <div class="portrait">${c.portrait || '🤖'}</div>
        <h2>${c.title}</h2>
        <div class="meta">${c.name} · ${classLine} · Level ${c.level}</div>
        ${c.awaiting_respec ? '<div class="respec-badge">⚠️ Awaiting respec</div>' : ''}
        <div class="xp-bar"><div class="xp-bar-fill" style="width:${xpPercent}%"></div></div>
        <div class="stat-group">
          <h3>Base stats</h3>
          ${statRows(c.base_stats)}
        </div>
        <div class="stat-group">
          <h3>Class stats</h3>
          ${statRows(c.class_stats)}
        </div>
      </div>
    `;
  }).join('');
}

loadCards();
</script>
</body>
</html>
"""


@app.get("/cards", response_class=HTMLResponse)
def cards_page() -> str:
    return _CARDS_HTML


_BUILDER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>agent-kit playground — builder</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; background: #ffffff; }
  h1 { font-size: 1.4rem; }
  h2 { font-size: 1.1rem; margin-top: 1.5rem; }
  nav a { font-size: 0.9rem; }
  input[type=text], input:not([type]), textarea, select { width: 100%; box-sizing: border-box; font-family: inherit; font-size: 1rem; padding: 0.3rem; }
  textarea { min-height: 4rem; }
  label { display: block; margin-top: 0.6rem; font-size: 0.9rem; }
  fieldset { margin-top: 1rem; }
  .agent-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0; border-bottom: 1px solid #eee; }
  .agent-row .name { flex: 1; }
  .agent-row button { cursor: pointer; }
  .field-row { display: flex; gap: 0.4rem; align-items: center; margin-bottom: 0.4rem; flex-wrap: wrap; }
  .field-row input[type=text], .field-row select { width: auto; flex: 1; min-width: 6rem; }
  .field-row .nested-editor { width: 100%; padding-left: 1.5rem; border-left: 2px solid #eee; margin-top: 0.3rem; }
  #builder-error { color: #b00020; white-space: pre-wrap; margin-top: 0.6rem; }
  #builder-success { color: #2a6f2a; margin-top: 0.6rem; }
  #model-check-banner { font-size: 0.85rem; color: #666; margin-top: 0.2rem; }
  .core-badge { font-size: 0.75rem; background: #eee; border-radius: 3px; padding: 0.1rem 0.4rem; margin-left: 0.4rem; }
  .readonly-note { color: #888; font-size: 0.85rem; font-style: italic; }
  .code-editor { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 0.85rem; min-height: 8rem; tab-size: 2; background: #f8f8f8; }
  .field-error { color: #b00020; font-size: 0.85rem; white-space: pre-wrap; margin-top: 0.3rem; }
  .suggestion { border: 1px solid #e0e0e0; border-radius: 6px; padding: 0.6rem; margin-bottom: 0.6rem; }
  .suggestion pre { background: #f5f5f5; padding: 0.5rem; overflow-x: auto; white-space: pre-wrap; font-size: 0.8rem; }
  .diff-old pre { border-left: 3px solid #d9a0a0; }
  .diff-new pre { border-left: 3px solid #a0d9a8; }
  #respec-status { color: #2a6f2a; font-size: 0.9rem; min-height: 1.2rem; }
</style>
</head>
<body>
<h1>agent-kit playground — builder</h1>
<nav><a href="/">← Run agents</a> · <a href="/cards">Roster →</a></nav>

<h2>Existing agents</h2>
<div id="agent-list">Loading…</div>

<h2>Respec queue <button type="button" onclick="processRespecQueue()">Process queue</button></h2>
<div id="respec-queue">Loading…</div>
<div id="respec-status"></div>

<h2>GM suggestions</h2>
<div id="gm-suggestions">Loading…</div>

<h2 id="form-heading">Create a new agent</h2>
<form id="builder-form">
  <label>Name
    <input id="f-name" required>
  </label>
  <label>Description
    <input id="f-description">
  </label>
  <label>System prompt
    <textarea id="f-system-prompt" required></textarea>
  </label>
  <label>Model
    <input id="f-model" value="qwen2.5:14b">
  </label>
  <div id="model-check-banner"></div>
  <label>Temperature
    <input id="f-temperature" type="number" step="0.1" min="0" max="2" value="0.7">
  </label>

  <fieldset id="output-fields-fieldset">
    <legend>Output fields</legend>
    <div id="field-rows"></div>
    <button type="button" onclick="addFieldRow()">+ Add field</button>
  </fieldset>

  <fieldset>
    <legend>Class (optional)</legend>
    <label>Main class
      <select id="f-main-class"><option value="">(none)</option></select>
    </label>
    <label>Sub class
      <select id="f-sub-class"><option value="">(none)</option></select>
    </label>
    <button type="button" onclick="toggleNewClassForm()">+ Create new class</button>
    <div id="new-class-form" style="display:none; margin-top: 0.5rem;">
      <label>Class definition (YAML or JSON)
        <textarea id="nc-content" class="code-editor" spellcheck="false">name: explorer
title: "Explorer"
description: "A curious wanderer who follows leads wherever they go."
stats:
  curiosity:
    value: 70
    # Bands are ordered low -> high and split 0-100 evenly.
    # Labels are cosmetic; any number of bands is allowed.
    prompt_effect:
      - label: "incurious"
        text: "You answer exactly what was asked and never volunteer more."
      - label: "curious"
        text: "You follow the most promising thread beyond the literal question."
      - label: "insatiable"
        text: "You chase every interesting lead and surface what you found along the way."
    # Deltas layered on top of the base-stat values, interpolated by stat value.
    runtime_effect:
      temperature: {at_0: -0.1, at_100: 0.2}
</textarea>
      </label>
      <div id="new-class-error" class="field-error"></div>
      <button type="button" onclick="submitNewClass()">Create class</button>
    </div>
  </fieldset>

  <label>Sample input (JSON, optional — pre-fills the Run screen)
    <textarea id="f-sample-input">{}</textarea>
  </label>

  <button type="submit" id="submit-btn">Create agent</button>
  <button type="button" id="cancel-edit-btn" style="display:none" onclick="startCreate()">Cancel edit</button>
</form>

<div id="builder-error"></div>
<div id="builder-success"></div>

<script>
let editingAgent = null;
let outputEditable = true;

function fieldRowHtml(field) {
  field = field || { name: '', type: 'string', required: true, is_list: false };
  return `
    <div class="field-row">
      <input type="text" class="fld-name" placeholder="field name" value="${field.name}">
      <select class="fld-type" onchange="onFieldTypeChange(this)">
        <option value="string" ${field.type === 'string' ? 'selected' : ''}>string</option>
        <option value="integer" ${field.type === 'integer' ? 'selected' : ''}>integer</option>
        <option value="number" ${field.type === 'number' ? 'selected' : ''}>number</option>
        <option value="boolean" ${field.type === 'boolean' ? 'selected' : ''}>boolean</option>
        <option value="nested" ${field.type === 'nested' ? 'selected' : ''}>nested object</option>
      </select>
      <label><input type="checkbox" class="fld-list" ${field.is_list ? 'checked' : ''}> list</label>
      <label><input type="checkbox" class="fld-required" ${field.required ? 'checked' : ''}> required</label>
      <button type="button" onclick="this.closest('.field-row').remove()">Remove</button>
      <div class="nested-editor" style="display:${field.type === 'nested' ? 'block' : 'none'}">
        <div class="nested-field-rows"></div>
        <button type="button" onclick="addFieldRow(null, this.closest('.field-row'))">+ Add nested field</button>
      </div>
    </div>
  `;
}

function addFieldRow(field, parentRow) {
  const container = parentRow
    ? parentRow.querySelector('.nested-editor > .nested-field-rows')
    : document.getElementById('field-rows');
  container.insertAdjacentHTML('beforeend', fieldRowHtml(field));
}

function onFieldTypeChange(selectEl) {
  const row = selectEl.closest('.field-row');
  const nestedEditor = row.querySelector('.nested-editor');
  nestedEditor.style.display = selectEl.value === 'nested' ? 'block' : 'none';
}

function collectFieldSpecs(container) {
  const rows = container.querySelectorAll(':scope > .field-row');
  const specs = [];
  for (const row of rows) {
    const name = row.querySelector('.fld-name').value.trim();
    if (!name) continue;
    const type = row.querySelector('.fld-type').value;
    const spec = {
      name,
      type,
      is_list: row.querySelector('.fld-list').checked,
      required: row.querySelector('.fld-required').checked,
    };
    if (type === 'nested') {
      spec.nested_fields = collectFieldSpecs(row.querySelector('.nested-editor > .nested-field-rows'));
    }
    specs.push(spec);
  }
  return specs;
}

async function loadClasses() {
  const res = await fetch('/api/v1/classes');
  const classes = await res.json();
  for (const selId of ['f-main-class', 'f-sub-class']) {
    const sel = document.getElementById(selId);
    sel.innerHTML = '<option value="">(none)</option>' +
      classes.map(c => `<option value="${c.name}">${c.title}</option>`).join('');
  }
}

function toggleNewClassForm() {
  const el = document.getElementById('new-class-form');
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function submitNewClass() {
  const errorEl = document.getElementById('new-class-error');
  errorEl.textContent = '';
  const content = document.getElementById('nc-content').value;

  const res = await fetch('/api/v1/builder/classes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  const data = await res.json();
  if (!res.ok) {
    errorEl.textContent = formatDetail(data.detail);
    return;
  }
  await loadClasses();
  document.getElementById('f-main-class').value = data.name;
  toggleNewClassForm();
}

function formatDetail(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(d => (d && d.msg) ? d.msg : JSON.stringify(d)).join('; ');
  }
  return JSON.stringify(detail);
}

async function loadAgentList() {
  const res = await fetch('/api/v1/agents');
  const agents = await res.json();
  const el = document.getElementById('agent-list');
  if (agents.length === 0) {
    el.textContent = 'No agents yet.';
    return;
  }
  el.innerHTML = agents.map(a => `
    <div class="agent-row">
      <span class="name">${a.name}</span>
      <button type="button" onclick="startEdit('${a.name}')">Edit</button>
      <button type="button" onclick="duplicateAgent('${a.name}')">Duplicate</button>
      <button type="button" onclick="deleteAgentPrompt('${a.name}')">Delete</button>
    </div>
  `).join('');
}

async function loadRespecQueue() {
  const res = await fetch('/api/v1/gm/queue');
  const queue = await res.json();
  const el = document.getElementById('respec-queue');
  el.innerHTML = queue.length === 0
    ? '<span class="readonly-note">No agents awaiting respec.</span>'
    : queue.map(q => `
        <div class="agent-row">
          <span class="name">⚠️ ${q.agent_name}</span>
          <span class="readonly-note">waiting since ${(q.pending_since || '').slice(0, 19)}</span>
        </div>`).join('');
}

async function processRespecQueue() {
  const statusEl = document.getElementById('respec-status');
  statusEl.textContent = 'Asking the GM to respec queued agents…';
  try {
    const res = await fetch('/api/v1/gm/queue/process', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      statusEl.textContent = formatDetail(data.detail);
      return;
    }
    statusEl.textContent =
      `Processed ${data.processed}: ${data.resynthesized.length} respecced` +
      (data.still_pending.length ? `, ${data.still_pending.length} still waiting (GM unavailable)` : '');
    await loadRespecQueue();
    await loadSuggestions();
  } catch (e) {
    statusEl.textContent = 'Could not reach the GM queue: ' + e.message;
  }
}

async function loadSuggestions() {
  const res = await fetch('/api/v1/gm/suggestions');
  const suggestions = await res.json();
  const el = document.getElementById('gm-suggestions');
  el.innerHTML = suggestions.length === 0
    ? '<span class="readonly-note">No pending GM suggestions.</span>'
    : suggestions.map(s => `
        <div class="suggestion">
          <div><b>${s.agent_name}</b> — ${s.rationale}</div>
          <details>
            <summary>Proposed system prompt</summary>
            <div class="diff-old"><b>current:</b><pre>${s.current_system_prompt}</pre></div>
            <div class="diff-new"><b>suggested:</b><pre>${s.suggested_system_prompt}</pre></div>
          </details>
          <button type="button" onclick="resolveSuggestion(${s.id}, 'approve')">Approve</button>
          <button type="button" onclick="resolveSuggestion(${s.id}, 'reject')">Reject</button>
        </div>`).join('');
}

async function resolveSuggestion(id, action) {
  const res = await fetch(`/api/v1/gm/suggestions/${id}/${action}`, { method: 'POST' });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById('builder-error').textContent = formatDetail(data.detail);
    return;
  }
  await loadSuggestions();
  await loadAgentList();
  document.getElementById('builder-success').textContent =
    action === 'approve'
      ? `Applied the GM's suggested prompt to "${data.agent_name}".`
      : `Rejected the suggestion for "${data.agent_name}".`;
}

function startCreate() {
  editingAgent = null;
  outputEditable = true;
  document.getElementById('form-heading').textContent = 'Create a new agent';
  document.getElementById('submit-btn').textContent = 'Create agent';
  document.getElementById('cancel-edit-btn').style.display = 'none';
  document.getElementById('f-name').disabled = false;
  document.getElementById('f-name').value = '';
  document.getElementById('f-description').value = '';
  document.getElementById('f-system-prompt').value = '';
  document.getElementById('f-model').value = 'qwen2.5:14b';
  document.getElementById('f-temperature').value = '0.7';
  document.getElementById('f-main-class').value = '';
  document.getElementById('f-sub-class').value = '';
  document.getElementById('f-sample-input').value = '{}';
  document.getElementById('field-rows').innerHTML = '';
  document.getElementById('output-fields-fieldset').style.display = 'block';
  addFieldRow();
  document.getElementById('builder-error').textContent = '';
  document.getElementById('builder-success').textContent = '';
}

async function startEdit(name) {
  const res = await fetch(`/api/v1/agents/${encodeURIComponent(name)}/builder`);
  const data = await res.json();
  editingAgent = name;
  outputEditable = data.output_model_editable;

  document.getElementById('form-heading').innerHTML =
    `Editing "${name}"` + (data.is_core ? '<span class="core-badge">core demo agent</span>' : '');
  document.getElementById('submit-btn').textContent = 'Save changes';
  document.getElementById('cancel-edit-btn').style.display = 'inline-block';
  document.getElementById('f-name').disabled = true;
  document.getElementById('f-name').value = data.name;
  document.getElementById('f-description').value = data.description;
  document.getElementById('f-system-prompt').value = data.system_prompt;
  document.getElementById('f-model').value = data.model;
  document.getElementById('f-temperature').value = data.temperature;
  document.getElementById('f-sample-input').value = JSON.stringify(data.sample_input || {}, null, 2);

  const fieldsFieldset = document.getElementById('output-fields-fieldset');
  document.getElementById('field-rows').innerHTML = '';
  if (outputEditable) {
    fieldsFieldset.style.display = 'block';
    addFieldRow();
  } else {
    fieldsFieldset.style.display = 'block';
    const summary = Object.entries(data.output_fields_summary || {})
      .map(([k, v]) => `${k}: ${v}`).join(', ');
    document.getElementById('field-rows').innerHTML =
      `<p class="readonly-note">Hand-written output schema, not editable here: ${summary}</p>`;
  }

  if (data.card) {
    document.getElementById('f-main-class').value = data.card.main_class || '';
    document.getElementById('f-sub-class').value = data.card.sub_class || '';
  } else {
    document.getElementById('f-main-class').value = '';
    document.getElementById('f-sub-class').value = '';
  }

  document.getElementById('builder-error').textContent = '';
  document.getElementById('builder-success').textContent = '';
  window.scrollTo({ top: document.getElementById('form-heading').offsetTop, behavior: 'smooth' });
}

async function duplicateAgent(name) {
  const newName = prompt(`Duplicate "${name}" as:`, `${name}_copy`);
  if (!newName) return;
  const res = await fetch(`/api/v1/builder/agents/${encodeURIComponent(name)}/duplicate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_name: newName }),
  });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById('builder-error').textContent = formatDetail(data.detail);
    return;
  }
  await loadAgentList();
  document.getElementById('builder-success').textContent = `Duplicated as "${newName}".`;
}

async function deleteAgentPrompt(name) {
  const isCore = name === 'hello' || name === 'news';
  if (!confirm(`Delete agent "${name}"? This cannot be undone.`)) return;
  let url = `/api/v1/builder/agents/${encodeURIComponent(name)}?confirm=true`;
  if (isCore) {
    if (!confirm(`"${name}" is a core demo agent — delete it anyway?`)) return;
    url += '&confirm_core=true';
  }
  const res = await fetch(url, { method: 'DELETE' });
  const data = await res.json();
  if (!res.ok) {
    document.getElementById('builder-error').textContent = formatDetail(data.detail);
    return;
  }
  await loadAgentList();
  if (editingAgent === name) startCreate();
  document.getElementById('builder-success').textContent = `Deleted "${name}".`;
}

document.getElementById('f-model').addEventListener('blur', async () => {
  const model = document.getElementById('f-model').value.trim();
  if (!model) return;
  const banner = document.getElementById('model-check-banner');
  banner.textContent = 'Checking model availability…';
  try {
    const res = await fetch(`/api/v1/builder/model-check?model=${encodeURIComponent(model)}`);
    const data = await res.json();
    banner.textContent = data.message;
  } catch (e) {
    banner.textContent = '';
  }
});

document.getElementById('builder-form').addEventListener('submit', async (evt) => {
  evt.preventDefault();
  const errorEl = document.getElementById('builder-error');
  const successEl = document.getElementById('builder-success');
  errorEl.textContent = '';
  successEl.textContent = '';

  let sampleInput = null;
  const sampleText = document.getElementById('f-sample-input').value.trim();
  if (sampleText && sampleText !== '{}') {
    try {
      sampleInput = JSON.parse(sampleText);
    } catch (e) {
      errorEl.textContent = 'Sample input is not valid JSON: ' + e.message;
      return;
    }
  }

  // No tool picker here by design: an agent's Pydantic output model is its
  // full API contract, not a shared tool list. Omitting `tools` entirely
  // means create defaults to [] and update leaves whatever tools an agent
  // already had untouched (e.g. editing news's prompt won't drop fetch_rss_feed).
  const mainClass = document.getElementById('f-main-class').value;
  const card = mainClass
    ? { main_class: mainClass, sub_class: document.getElementById('f-sub-class').value || null }
    : null;

  const body = {
    description: document.getElementById('f-description').value,
    system_prompt: document.getElementById('f-system-prompt').value,
    model: document.getElementById('f-model').value,
    temperature: parseFloat(document.getElementById('f-temperature').value),
    card,
    sample_input: sampleInput,
  };

  if (outputEditable) {
    body.output_fields = collectFieldSpecs(document.getElementById('field-rows'));
  }

  let res;
  if (editingAgent) {
    res = await fetch(`/api/v1/builder/agents/${encodeURIComponent(editingAgent)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } else {
    body.name = document.getElementById('f-name').value;
    res = await fetch('/api/v1/builder/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  const data = await res.json();
  if (!res.ok) {
    errorEl.textContent = formatDetail(data.detail);
    return;
  }

  await loadAgentList();
  successEl.innerHTML = `Saved "${data.name}". <a href="/?agent=${encodeURIComponent(data.name)}">Run it now →</a>`;
  if (!editingAgent) {
    window.location.href = `/?agent=${encodeURIComponent(data.name)}`;
  }
});

(async function init() {
  await loadClasses();
  await loadAgentList();
  await loadRespecQueue();
  await loadSuggestions();
  startCreate();
})();
</script>
</body>
</html>
"""


@app.get("/builder", response_class=HTMLResponse)
def builder_page() -> str:
    return _BUILDER_HTML


if __name__ == "__main__":
    import uvicorn

    # Playground is local-only (Req 6.5): bind exclusively to 127.0.0.1, never 0.0.0.0.
    uvicorn.run(app, host="127.0.0.1", port=8000)
