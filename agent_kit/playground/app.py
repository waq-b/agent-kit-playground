"""Playground — a minimal FastAPI app for interactively listing and running agents."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, model_validator

from agent_kit.errors import AgentKitError, AgentNotFoundError
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
    )


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
</style>
</head>
<body>
<h1>agent-kit playground</h1>

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

    outputEl.innerHTML = `
      <h3>Output</h3>
      <pre>${JSON.stringify(data.output, null, 2)}</pre>
      <details><summary>Raw prompt</summary><pre>${data.raw_prompt}</pre></details>
      <details><summary>Raw response</summary><pre>${data.raw_response}</pre></details>
    `;
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


if __name__ == "__main__":
    import uvicorn

    # Playground is local-only (Req 6.5): bind exclusively to 127.0.0.1, never 0.0.0.0.
    uvicorn.run(app, host="127.0.0.1", port=8000)
