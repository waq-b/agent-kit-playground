# Changelog

Versions follow the milestones in the git history. The Python package and the
playground frontend share one version number from 0.5.0 onwards (before that
`pyproject.toml` said 0.4.0 and `frontend/package.json` said 0.5.0).

## 0.5.0

- React + TypeScript playground (Vite) replaces the original hand-written HTML
  pages. API types are generated from the backend's OpenAPI schema, and CI fails
  if the committed copies drift.
- Runtime Settings screen backed by `GET/PUT /api/v1/settings`: stub mode,
  provider URL, GM model, ntfy URL, database path, default model and respec
  threshold. Environment variables still work and seed the defaults.
- Model provider registry: register local and "frontier" models. Frontier entries
  carry their own base URL and API key; the key is never returned to the browser,
  and the UI asks for confirmation before selecting a frontier model.
- Optional `input_model` on agent definitions. Run input is validated against it,
  and the wizard and roster API reference read the real schema.
- GM controls: respec threshold, optional auto-processing of the respec queue, and
  a switch to turn prompt suggestions off.
- Frontend tests (Vitest and Testing Library), a frontend CI job, and
  `backend.sh` / `backend.ps1` to start the API on its own.
- New `webpage` demo agent with a `fetch_page_text` tool.
- Fixed: card store thread safety under concurrent requests; a Run screen prefill
  bug; `gen:openapi` no longer hardcodes a virtualenv path.

## 0.4.0 - Stat effects and the Game Master

- Class stats now carry authored effects: prompt bands (text appended to the
  agent's behaviour) and runtime curves (bounded deltas to temperature, retries,
  tool timeout and concurrency). Effects from a main class and a sub class stack.
  The old flat `stats: {name: 65}` class format is rejected with a clear error.
- `gm.py`: the Game Master turns the selected prompt fragments into one trait
  paragraph, cached by band signature. If the GM is unavailable the last good
  paragraph is reused and the agent is queued for a retry.
- The GM can propose a system-prompt change. It is stored as a suggestion and only
  applied when a person approves it.

## 0.3.0 - Agent builder

- Create, edit and delete agents from the playground. Output models are generated
  as Python code from field specs, written atomically, validated before commit,
  and hot-reloaded into the registry.
- Class builder with a YAML editor. Core demo agents need an extra confirmation
  to delete.

## 0.2.0 - Character layer

- Per-agent cards: level, XP, base stats, classes and an unlock table, persisted
  in SQLite.
- Deterministic rules turn grades (thumbs up/down, more/less like this) into XP,
  stat nudges and levels. Stats map to runtime parameters.
- Playground cards API and roster UI.

## 0.1.0 - Core library

- YAML agent definitions with specific error types, an agent registry, tool
  registry, and a Pydantic AI runner against any OpenAI-compatible endpoint
  (local Ollama by default).
- Stub mode (`STUB_AI_PROVIDERS=1`) returns registered fixtures with no model
  calls. Property-based tests with Hypothesis. GitHub Actions CI.
- `hello` and `news` (RSS) demo agents and a FastAPI playground.
