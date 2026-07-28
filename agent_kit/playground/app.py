"""Playground — a minimal FastAPI app for interactively listing and running agents."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

from agent_kit.card_definition import CardDefinition
from agent_kit.card_store import get_card_store
from agent_kit.definition import AgentDefinition
from agent_kit.errors import AgentKitError, AgentNotFoundError, UnknownGradeActionError
from agent_kit.registry import get_registry
from agent_kit.runner import Runner

app = FastAPI(title="agent-kit playground")

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
<nav><a href="/cards">View character roster →</a></nav>

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
</style>
</head>
<body>
<h1>agent-kit playground — roster</h1>
<nav><a href="/">← Run agents</a></nav>

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


if __name__ == "__main__":
    import uvicorn

    # Playground is local-only (Req 6.5): bind exclusively to 127.0.0.1, never 0.0.0.0.
    uvicorn.run(app, host="127.0.0.1", port=8000)
