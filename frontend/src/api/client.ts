/**
 * Typed client for the playground API.
 *
 * One thin `request` helper plus one function per endpoint. Request and
 * response types all come from `types.ts`, i.e. from the backend's OpenAPI
 * document, so a Pydantic change that this client hasn't caught up with is a
 * compile error rather than a runtime surprise.
 */
import type {
  AgentBuilderDetail,
  AgentSummary,
  CardDetail,
  CardSummary,
  ClassSummary,
  CreateAgentRequest,
  CreateClassRequest,
  GradeRequest,
  GradeResponse,
  ModelCheckResponse,
  PlaygroundSettings,
  RespecProcessResult,
  RespecQueueEntry,
  RunResponse,
  SettingsUpdate,
  SuggestionSummary,
  UpdateAgentRequest,
} from "./types";

const API_BASE_STORAGE_KEY = "agent-kit.apiBase";

/** Same-origin by default: the Vite dev server proxies /api to FastAPI. */
export const DEFAULT_API_BASE = "/api/v1";

export function getApiBase(): string {
  const stored = localStorage.getItem(API_BASE_STORAGE_KEY);
  return (stored || DEFAULT_API_BASE).replace(/\/$/, "");
}

export function setApiBase(base: string): void {
  const trimmed = base.trim().replace(/\/$/, "");
  if (!trimmed || trimmed === DEFAULT_API_BASE) {
    localStorage.removeItem(API_BASE_STORAGE_KEY);
  } else {
    localStorage.setItem(API_BASE_STORAGE_KEY, trimmed);
  }
}

/** One FastAPI validation-error entry, as it appears inside a 422 body. */
interface ValidationDetail {
  loc?: (string | number)[];
  msg?: string;
}

/**
 * An HTTP error carrying FastAPI's `detail`, already flattened to a string.
 *
 * `detail` is a plain string for the handlers that raise `HTTPException`, and
 * an array of per-field objects for Pydantic's own 422s. Both are normalised
 * here so screens never have to branch on the shape.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(`HTTP ${status} — ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: ValidationDetail) => {
        const loc = d?.loc ? `${d.loc.join(".")}: ` : "";
        return d?.msg ? `${loc}${d.msg}` : JSON.stringify(d);
      })
      .join("\n");
  }
  if (detail === undefined) return "Request failed";
  return JSON.stringify(detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${getApiBase()}${path}`, {
      ...init,
      headers:
        init?.body === undefined
          ? init?.headers
          : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (e) {
    // A transport failure is not an HTTP status — surface it as a 0 so callers
    // can tell "server unreachable" apart from "server said no".
    throw new ApiError(0, e instanceof Error ? e.message : "network request failed");
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // 204s and empty error bodies are both fine; body stays null.
  }

  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    throw new ApiError(response.status, formatDetail(detail));
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

const put = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });

const seg = encodeURIComponent;

// --- agents & running ---

export const listAgents = () => request<AgentSummary[]>("/agents");

export const runAgent = (name: string, input: Record<string, unknown>) =>
  post<RunResponse>(`/agents/${seg(name)}/run`, { input });

export const getSampleInput = (name: string) =>
  request<Record<string, unknown> | null>(`/agents/${seg(name)}/sample-input`);

// --- roster ---

export const listCards = () => request<CardSummary[]>("/cards");

export const getCard = (name: string) => request<CardDetail>(`/agents/${seg(name)}/card`);

export const gradeAgent = (name: string, body: GradeRequest) =>
  post<GradeResponse>(`/agents/${seg(name)}/grade`, body);

// --- builder ---

export const listTools = () => request<string[]>("/tools");

export const listClasses = () => request<ClassSummary[]>("/classes");

export const getAgentBuilderDetail = (name: string) =>
  request<AgentBuilderDetail>(`/agents/${seg(name)}/builder`);

export const createAgent = (body: CreateAgentRequest) =>
  post<AgentBuilderDetail>("/builder/agents", body);

export const updateAgent = (name: string, body: UpdateAgentRequest) =>
  put<AgentBuilderDetail>(`/builder/agents/${seg(name)}`, body);

export const duplicateAgent = (name: string, newName: string) =>
  post<AgentBuilderDetail>(`/builder/agents/${seg(name)}/duplicate`, { new_name: newName });

/**
 * `confirm` is mandatory server-side; `confirmCore` is the second gate the
 * backend requires for the built-in `hello` / `news` agents (409 otherwise).
 */
export const deleteAgent = (name: string, confirmCore = false) =>
  request<{ status: string; name: string }>(
    `/builder/agents/${seg(name)}?confirm=true&confirm_core=${confirmCore}`,
    { method: "DELETE" },
  );

export const createClass = (content: CreateClassRequest["content"]) =>
  post<ClassSummary>("/builder/classes", { content });

export const checkModel = (model: string) =>
  request<ModelCheckResponse>(`/builder/model-check?model=${seg(model)}`);

// --- game master ---

export const getRespecQueue = () => request<RespecQueueEntry[]>("/gm/queue");

export const processRespecQueue = () => post<RespecProcessResult>("/gm/queue/process");

export const listSuggestions = (status = "pending") =>
  request<SuggestionSummary[]>(`/gm/suggestions?status=${seg(status)}`);

export const approveSuggestion = (id: number) =>
  post<SuggestionSummary>(`/gm/suggestions/${id}/approve`);

export const rejectSuggestion = (id: number) =>
  post<SuggestionSummary>(`/gm/suggestions/${id}/reject`);

// --- settings ---

export const getSettings = () => request<PlaygroundSettings>("/settings");

export const updateSettings = (patch: SettingsUpdate) =>
  put<PlaygroundSettings>("/settings", patch);
