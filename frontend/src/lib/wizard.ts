/**
 * The Builder wizard's editing model, and its translation to/from the API.
 *
 * The wizard edits a local draft rather than the API shapes directly, because
 * one draft maps to several request fields (`model` + `customModel` collapse to
 * one string; the card fields collapse to one `CardSpec`) and because drafts can
 * be saved to localStorage in states the backend would reject.
 */
import type { AgentBuilderDetail, CardSpec, CreateAgentRequest, FieldSpec, FieldType } from "../api/types";

export interface OutputFieldDraft {
  /** Stable local key for React and for per-row error mapping. */
  id: string;
  name: string;
  type: FieldType;
  required: boolean;
  isList: boolean;
  /** Populated only when `type === "nested"`; the backend allows one level. */
  nested: OutputFieldDraft[];
}

export interface WizardDraft {
  name: string;
  description: string;
  systemPrompt: string;
  /** Either a known option or the literal "custom", in which case customModel wins. */
  model: string;
  customModel: string;
  temperature: number;
  outputFields: OutputFieldDraft[];
  tools: string[];
  feeds: string[];
  mainClass: string;
  subClass: string;
  cardTitle: string;
  portrait: string;
  backstory: string;
  sampleInput: string;
  isCore: boolean;
  /**
   * True once the user edits the output model.
   *
   * Matters because `update_agent` treats `output_fields=None` as "leave
   * unchanged". The builder detail endpoint returns only a stringified
   * annotation per field, not the original FieldSpec list, so a reconstruction
   * is lossy for nested fields. Leaving this false means we omit
   * `output_fields` from the update entirely and the stored model is untouched.
   */
  outputFieldsTouched: boolean;
}

export const CUSTOM_MODEL = "custom";

let fieldCounter = 0;
export const nextFieldId = () => `f${fieldCounter++}`;

export function blankOutputField(): OutputFieldDraft {
  return { id: nextFieldId(), name: "", type: "string", required: true, isList: false, nested: [] };
}

export function blankDraft(defaultModel: string): WizardDraft {
  return {
    name: "",
    description: "",
    systemPrompt: "",
    model: defaultModel,
    customModel: "",
    temperature: 0.7,
    outputFields: [blankOutputField()],
    tools: [],
    feeds: [],
    mainClass: "",
    subClass: "",
    cardTitle: "",
    portrait: "",
    backstory: "",
    sampleInput: "",
    isCore: false,
    outputFieldsTouched: true, // a new agent must send its output model
  };
}

/**
 * Best-effort reconstruction of a field draft from `str(field.annotation)`.
 *
 * The builder detail endpoint exposes output fields only as stringified Python
 * annotations, so this recovers optionality, list-ness and the scalar type.
 * A non-scalar inner type (a generated nested model) is reported as "nested"
 * with no sub-fields, which is why `outputFieldsTouched` exists.
 */
export function parseAnnotation(annotation: string): Omit<OutputFieldDraft, "id" | "name"> {
  let text = annotation.trim();
  const classMatch = text.match(/^<class '(.+)'>$/);
  if (classMatch) text = classMatch[1];

  let required = true;
  const optional = text.match(/^(.*?)\s*\|\s*None$/);
  if (optional) {
    required = false;
    text = optional[1].trim();
  }

  let isList = false;
  const list = text.match(/^list\[(.*)\]$/);
  if (list) {
    isList = true;
    text = list[1].trim();
  }

  const scalar = text.split(".").pop() ?? text;
  const type: FieldType =
    scalar === "str"
      ? "string"
      : scalar === "int"
        ? "integer"
        : scalar === "float"
          ? "number"
          : scalar === "bool"
            ? "boolean"
            : "nested";

  return { type, required, isList, nested: [] };
}

export function draftFromDetail(detail: AgentBuilderDetail, knownModels: string[]): WizardDraft {
  const card = (detail.card ?? {}) as Record<string, unknown>;
  const known = knownModels.includes(detail.model);
  return {
    name: detail.name,
    description: detail.description,
    systemPrompt: detail.system_prompt,
    model: known ? detail.model : CUSTOM_MODEL,
    customModel: known ? "" : detail.model,
    temperature: detail.temperature,
    outputFields: Object.entries(detail.output_fields_summary).map(([name, annotation]) => ({
      id: nextFieldId(),
      name,
      ...parseAnnotation(annotation),
    })),
    tools: [...detail.tools],
    feeds: [...detail.feeds],
    mainClass: typeof card.main_class === "string" ? card.main_class : "",
    subClass: typeof card.sub_class === "string" ? card.sub_class : "",
    cardTitle: typeof card.title === "string" ? card.title : "",
    portrait: typeof card.portrait === "string" ? card.portrait : "",
    backstory: typeof card.backstory === "string" ? card.backstory : "",
    sampleInput: detail.sample_input ? JSON.stringify(detail.sample_input, null, 2) : "",
    isCore: detail.is_core,
    outputFieldsTouched: false,
  };
}

export function resolvedModel(draft: WizardDraft): string {
  return draft.model === CUSTOM_MODEL ? draft.customModel.trim() : draft.model;
}

export function toFieldSpecs(fields: OutputFieldDraft[]): FieldSpec[] {
  return fields
    .filter((f) => f.name.trim())
    .map((f) => ({
      name: f.name.trim(),
      type: f.type,
      required: f.required,
      is_list: f.isList,
      description: "",
      nested_fields: f.type === "nested" ? toFieldSpecs(f.nested) : null,
    }));
}

/** A CardSpec, or null when no main class is chosen (agents may be card-less). */
export function toCardSpec(draft: WizardDraft): CardSpec | null {
  if (!draft.mainClass) return null;
  return {
    main_class: draft.mainClass,
    sub_class: draft.subClass || null,
    title: draft.cardTitle.trim() || null,
    backstory: draft.backstory,
    portrait: draft.portrait,
    base_stats: null,
    unlock_table: null,
    level: 1,
    xp: 0,
  };
}

export function parseSampleInput(text: string): Record<string, unknown> | null {
  if (!text.trim()) return null;
  return JSON.parse(text) as Record<string, unknown>;
}

export function toCreateRequest(draft: WizardDraft): CreateAgentRequest {
  return {
    name: draft.name.trim(),
    system_prompt: draft.systemPrompt,
    output_fields: toFieldSpecs(draft.outputFields),
    description: draft.description,
    model: resolvedModel(draft),
    temperature: draft.temperature,
    tools: draft.tools,
    feeds: draft.feeds,
    card: toCardSpec(draft),
    sample_input: parseSampleInput(draft.sampleInput),
  };
}

export interface WizardErrors {
  name?: string;
  systemPrompt?: string;
  model?: string;
  fields?: string;
  sampleInput?: string;
  fieldRows?: Record<string, string>;
}

/**
 * Client-side validation.
 *
 * Deliberately a subset of the server's rules — the backend stays the authority
 * (it validates the generated model, writes to a temp file and loads it before
 * committing). This exists to catch the obvious mistakes without a round trip;
 * anything it misses still comes back as a 422 and is shown to the user.
 */
export function validateDraft(
  draft: WizardDraft,
  existingNames: string[],
  originalName: string | null,
  asDraft: boolean,
): WizardErrors {
  const errors: WizardErrors = {};

  if (!draft.name.trim()) errors.name = "Name is required.";
  else if (!/^[a-z][a-z0-9_]*$/.test(draft.name))
    errors.name = "Use lowercase letters, numbers and underscores, starting with a letter.";
  else if (existingNames.some((n) => n === draft.name && n !== originalName))
    errors.name = "An agent with this name already exists.";

  if (!draft.systemPrompt.trim()) errors.systemPrompt = "System prompt is required.";

  if (draft.model === CUSTOM_MODEL) {
    if (!draft.customModel.trim()) errors.model = "Enter a model name, or pick one from the list.";
    else if (!/^[a-z0-9.:_-]+$/i.test(draft.customModel))
      errors.model = "Use letters, numbers, and : . _ - only.";
  }

  if (draft.sampleInput.trim()) {
    try {
      const parsed: unknown = JSON.parse(draft.sampleInput);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
        errors.sampleInput = "Sample input must be a JSON object.";
    } catch (e) {
      errors.sampleInput = `Not valid JSON: ${e instanceof Error ? e.message : String(e)}`;
    }
  }

  // A draft is allowed to be incomplete; only a registered agent needs a
  // valid output model, since that is what gets code-generated.
  if (!asDraft) {
    const rowErrors = collectFieldErrors(draft.outputFields);
    if (draft.outputFields.filter((f) => f.name.trim()).length === 0)
      errors.fields = "Add at least one output field.";
    if (Object.keys(rowErrors).length) errors.fieldRows = rowErrors;
  }

  return errors;
}

function collectFieldErrors(
  fields: OutputFieldDraft[],
  into: Record<string, string> = {},
): Record<string, string> {
  const named = fields.filter((f) => f.name.trim());
  const seen = new Set<string>();
  for (const f of fields) {
    const name = f.name.trim();
    if (!name) {
      if (fields.length > 1 || named.length > 0) into[f.id] = "Name required.";
      continue;
    }
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) into[f.id] = "Not a valid field name.";
    else if (name.startsWith("model_") || name.startsWith("_"))
      into[f.id] = "Reserved name — cannot start with `_` or `model_`.";
    else if (seen.has(name)) into[f.id] = "Duplicate field name.";
    seen.add(name);

    if (f.type === "nested") {
      if (f.nested.filter((n) => n.name.trim()).length === 0)
        into[f.id] = "A nested field needs at least one sub-field.";
      else collectFieldErrors(f.nested, into);
    }
  }
  return into;
}
