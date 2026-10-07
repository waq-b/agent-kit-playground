# Playground reference

Running, configuring and using the playground in detail. For an overview see the [README](../README.md).

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

## Running just the backend

```bash
./backend.sh
```

```powershell
.\backend.ps1
```

Same preflight checks as `dev.sh` (no frontend/Node required), same `AGENT_KIT_HOST` /
`AGENT_KIT_PORT` overrides. Useful for hitting the API directly, or pointing a frontend dev
server started separately at it. Manual equivalent:

```bash
.venv/bin/python -m uvicorn agent_kit.playground.app:app --host 127.0.0.1 --port 8000 --reload
```

## Running the two processes manually

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
STUB_AI_PROVIDERS=1 .venv/bin/python -m pytest
```

Frontend typecheck and tests:

```bash
cd frontend && npm run typecheck && npm test
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
| `provider_url` | `AGENT_KIT_PROVIDER_URL` | Shared OpenAI-compatible endpoint every *local* model resolves to |
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
- **Models** — the model provider registry: see below.
- **Settings** — everything in the table above.

## Model providers

Any model name has always worked as long as the local endpoint (`provider_url` above) actually
serves it — that hasn't changed. The **Models** screen adds a registry on top, for two things:

1. **Convenience** — a registered model shows up in every dropdown that picks a model (Settings'
   two model fields, the Builder wizard's), instead of you having to remember and retype it.
2. **Reaching a provider other than the shared local one at all.**

Each entry is one of:

- **Local** — just a model id (and an optional label). Always resolves to the shared
  `provider_url` above; registering one is pure convenience, never required.
- **Frontier** — a model id plus its own base URL and API key, entered inline. This is the only
  way to reach a provider other than the local one: the Runner and the Game Master have no other
  source for that URL/key. Any OpenAI-compatible endpoint works — real OpenAI, a hosted gateway,
  a self-hosted proxy with auth.

**Picking a frontier model anywhere asks for confirmation first** — the dropdown shows what it
resolves to (`<label> is a frontier model — running it sends data to <base_url>, outside your
local machine`) and only applies the selection on Confirm. This is a UI safeguard, not a backend
one: `POST /api/v1/models` itself doesn't require confirmation, so anything scripting the API
directly bypasses it.

**API keys** are stored in plain text in `agent_kit_data/settings.json`, the same as every other
setting — consistent with this being a localhost-only dev tool with no auth layer. They are
never sent back to the browser: every read (`GET /api/v1/models`, the create response, and
`GET`/`PUT /api/v1/settings`) reports `has_api_key: true/false` instead of the key itself.

```
GET    /api/v1/models
POST   /api/v1/models
DELETE /api/v1/models/{model_id}
```

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
