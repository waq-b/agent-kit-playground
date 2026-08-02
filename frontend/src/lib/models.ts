/** Shared shape for anywhere a model picker appears — Settings, the wizard. */
import type { ModelKind, ModelProviderSummary } from "../api/types";

export interface ModelOption {
  value: string;
  label: string;
  kind: ModelKind;
  baseUrl?: string | null;
}

/**
 * Registry entries, plus any ids the caller needs to guarantee are present
 * even if unregistered (e.g. the value already saved in a settings field, or
 * an existing agent's `model:` string) — same defensive-union pattern this
 * screen already used before a real registry existed. Ids appear once each;
 * a registered entry's label/kind win over a bare id passed via `ensurePresent`.
 */
export function buildModelOptions(
  models: ModelProviderSummary[],
  ensurePresent: (string | undefined | null)[] = [],
): ModelOption[] {
  const byId = new Map<string, ModelOption>();
  for (const m of models) {
    byId.set(m.model_id, { value: m.model_id, label: m.label || m.model_id, kind: m.kind, baseUrl: m.base_url });
  }
  for (const id of ensurePresent) {
    if (id && !byId.has(id)) byId.set(id, { value: id, label: id, kind: "local", baseUrl: null });
  }
  return Array.from(byId.values());
}
