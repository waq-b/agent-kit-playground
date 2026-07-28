# agent-kit

A minimal, reusable Python library and developer web UI for running AI-agent-powered
applications on local infrastructure.

- **`agent_kit/`** — the library: YAML agent definitions, a Pydantic-AI runner, a
  character/stat layer, and a Game Master that synthesizes agent traits from graded feedback.
- **`agent_kit/playground/`** — a FastAPI service exposing all of that over `/api/v1`.
- **`frontend/`** — the Playground UI: a React + TypeScript app whose types are generated
  from the service's own OpenAPI schema.

## Quick start

```bash
./dev.sh
```

That starts both processes with per-process labelled output and stops both on Ctrl-C:

- `[api]` → FastAPI on <http://127.0.0.1:8000>
- `[web]` → Vite dev server on <http://localhost:5173>

On Windows:

```powershell
.\dev.ps1
```

Open <http://localhost:5173>. The dev server proxies `/api` to the backend, so the app is
same-origin and CORS never comes into it.

Override the backend address with `AGENT_KIT_HOST` / `AGENT_KIT_PORT`; the Vite proxy follows
automatically.

### First-time setup

`dev.sh` refuses to start — with instructions — if either half isn't installed yet.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cd frontend && npm install
```

## Running the two processes manually

Backend only:

```bash
.venv/bin/python -m uvicorn agent_kit.playground.app:app --host 127.0.0.1 --port 8000 --reload
```

Frontend only (expects a backend on port 8000):

```bash
cd frontend && npm run dev
```

Point the frontend at a backend somewhere else:

```bash
cd frontend && AGENT_KIT_API=http://127.0.0.1:9000 npm run dev
```

Production build of the frontend (static files in `frontend/dist/`):

```bash
cd frontend && npm run build
```

> The FastAPI service does not serve `frontend/dist/` — it has no `StaticFiles` mount, and
> adding one would be a backend change. Serve the build with any static file server, or keep
> using the dev server.

## Frontend types are generated, not hand-written

`frontend/src/api/schema.d.ts` is generated from the backend's OpenAPI document. Never edit it,
and never hand-write a type that belongs to a Pydantic model.

```bash
cd frontend && npm run gen:types
```

That runs `scripts/dump_openapi.py` (offline — it imports the app, no server needed) to write
`frontend/openapi.json`, then `openapi-typescript` to produce `schema.d.ts`. Both are committed
so the contract the types came from is visible in review.

`frontend/src/api/types.ts` gives those generated shapes readable aliases; that file, and the
client in `frontend/src/api/client.ts`, are the only places the app touches the API.

Re-run `npm run gen:types` after any change to the Pydantic models — `npm run typecheck` will
then point at everything that needs updating.

## Tests

```bash
.venv/bin/python -m pytest
```

Frontend typecheck:

```bash
cd frontend && npm run typecheck
```

## Configuration

Settings are editable at runtime from the Playground's **Settings** screen and persist to
`agent_kit_data/settings.json`. They are also readable and writable over the API:

```
GET  /api/v1/settings
PUT  /api/v1/settings
```

Each maps to the environment variable the library already read, so nothing changes for code
using agent-kit as a plain library:

| Setting | Environment variable | Effect |
| --- | --- | --- |
| `stub_mode` | `STUB_AI_PROVIDERS` | Return registered fixtures; make no model calls |
| `provider_url` | `AGENT_KIT_PROVIDER_URL` | OpenAI-compatible endpoint for agents and the GM |
| `gm_model` | `AGENT_KIT_GM_MODEL` | Model the Game Master uses for trait synthesis |
| `ntfy_url` | `NTFY_URL` | Notification endpoint; unset disables notifications |
| `db_path` | `AGENT_KIT_DB_PATH` | SQLite file backing the card store |
| `default_model` | — | Default model pre-selected in the Builder wizard |
| `respec_threshold` | — | Grade events since last synthesis before a respec is queued |
| `auto_process_respec` | — | Run the respec immediately instead of waiting for *Process Queue* |
| `suggestions_enabled` | — | Whether the GM may propose system-prompt revisions |

**Precedence.** Before `settings.json` exists, the environment seeds the defaults — so
`STUB_AI_PROVIDERS=1 ./dev.sh` still does what you expect. Once the file exists it is the source
of truth and is applied to the environment at startup, otherwise a value saved in the UI would
be silently ignored after a restart. Delete the file to go back to environment-only behaviour.

Settings apply to the whole server process, not per browser tab. The playground binds to
localhost and has no auth layer; this is a development tool, not a multi-tenant service.

The Settings screen's **Base URL** field is the one exception — it is which server the browser
talks to, so it lives in `localStorage`, not on any server.

Other environment variables, not exposed in the UI:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENT_KIT_DATA_DIR` | `agent_kit_data` | Where builder-created agents, classes and settings live |
| `AGENT_KIT_GM_RETRIES` | `4` | GM structured-output retry budget |
| `AGENT_KIT_GM_PROVIDER` | `ollama` | GM provider name |
| `AGENT_KIT_GM_API_KEY` | — | API key when the GM provider needs one |

## Playground screens

- **Run** — pick an agent, send it a JSON input, read the structured output plus the raw prompt
  and response, and grade the result. Grading is what feeds the character layer.
- **Roster** — each agent's character card: level, XP, base and class stats, unlock table, tool
  proficiency, and a per-agent API reference. Expand a card to see all of it.
- **Builder** — create, edit, duplicate and delete agents through a wizard: identity, system
  prompt, model settings, output model, tools and feeds, class assignment and character card,
  and a sample input that pre-fills the Run screen. Also hosts the respec queue and GM
  suggestion approval.
- **Class Builder** — author a class as YAML or JSON, with a schema reference alongside. Reached
  from *+ Create new class* in the wizard.
- **Settings** — everything in the table above.

### Drafts are local

*Save as draft* in the Builder keeps work in `localStorage` and never contacts the API — the
backend has no draft concept, an agent either exists in the registry or it does not. A draft
becomes a real agent only through *Save & Register*.

### Editing an existing agent's output model

The builder API exposes an agent's output fields only as stringified Python type annotations, so
the wizard reconstructs the rows from those. Optionality, list-ness and scalar types survive;
the sub-fields of a nested model cannot be recovered.

The wizard therefore leaves the stored model completely alone unless you edit a row. Touch one
and the whole output model is regenerated from what's on screen — so fill in any nested
sub-fields before saving.
