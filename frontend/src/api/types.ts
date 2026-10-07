/**
 * Named aliases over the generated OpenAPI schema.
 *
 * `schema.d.ts` is produced by `npm run gen:types` from the FastAPI service's
 * own OpenAPI document — never edit it, and never hand-write a shape that
 * belongs to the backend. Re-run the generator after any change to the Pydantic
 * models and the compiler will point at everything that needs updating.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type AgentSummary = S["AgentSummary"];
export type RunRequest = S["RunRequest"];
export type RunResponse = S["RunResponse"];

export type CardSummary = S["CardSummary"];
export type CardDetail = S["CardDetail"];
export type GradeRequest = S["GradeRequest"];
export type GradeResponse = S["GradeResponse"];

export type ClassSummary = S["ClassSummary"];
export type CardSpec = S["CardSpec"];
// FieldSpec is recursive (nested_fields) and used on both the request side
// (CreateAgentRequest/UpdateAgentRequest) and the response side
// (AgentBuilderDetail's field_spec — refinement Phase 2, Task 10), which
// openapi-typescript renders as two structurally-identical schemas rather
// than one. FieldSpec stays the request-building shape everything else
// already uses; FieldSpecFromServer is only for reading the response back.
export type FieldSpec = S["FieldSpec-Input"];
export type FieldSpecFromServer = S["FieldSpec-Output"];
export type AgentBuilderDetail = S["AgentBuilderDetail"];
export type CreateAgentRequest = S["CreateAgentRequest"];
export type UpdateAgentRequest = S["UpdateAgentRequest"];
export type DuplicateAgentRequest = S["DuplicateAgentRequest"];
export type CreateClassRequest = S["CreateClassRequest"];
export type ModelCheckResponse = S["ModelCheckResponse"];

export type RespecQueueEntry = S["RespecQueueEntry"];
export type RespecProcessResult = S["RespecProcessResult"];
export type SuggestionSummary = S["SuggestionSummary"];

export type PlaygroundSettings = S["PlaygroundSettings"];
export type SettingsUpdate = S["SettingsUpdate"];

export type ModelProviderSummary = S["ModelProviderSummary"];
export type CreateModelRequest = S["CreateModelRequest"];
export type ModelKind = ModelProviderSummary["kind"];

/** The backend's own field-type vocabulary, not a parallel frontend list. */
export type FieldType = FieldSpec["type"];

/** Grading actions accepted by `POST /agents/{name}/grade`.
 *
 * `GradeRequest.action` is a plain `str` in the Pydantic model (the valid set
 * lives in `xp_rules.py`, which OpenAPI cannot see), so this is the one place a
 * literal union is written by hand. `UnknownGradeActionError` → 422 remains the
 * server-side authority; this only keeps the UI's own buttons honest. */
export type GradeAction =
  | "thumbs_up"
  | "thumbs_down"
  | "more_like_this"
  | "less_like_this"
  | "implicit_view";
