/**
 * Local drafts for the Builder's "Save as draft".
 *
 * The backend has no draft concept — an agent either exists as YAML in the
 * registry or it does not. So a draft is exactly what its name says: work in
 * progress held in this browser, never sent to the API. It becomes a real agent
 * only via "Save & Register", which goes through the normal create/update path.
 */
import type { WizardDraft } from "./wizard";

const STORAGE_KEY = "agent-kit.builderDrafts";

type DraftMap = Record<string, WizardDraft>;

function read(): DraftMap {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as DraftMap) : {};
  } catch {
    // A corrupt blob shouldn't wedge the Builder — start over with none.
    return {};
  }
}

function write(map: DraftMap): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // Quota or private-browsing failures are non-fatal; the draft just won't persist.
  }
}

export function listDrafts(): WizardDraft[] {
  return Object.values(read());
}

export function getDraft(name: string): WizardDraft | null {
  return read()[name] ?? null;
}

export function saveDraft(draft: WizardDraft, previousName: string | null): void {
  const map = read();
  if (previousName && previousName !== draft.name) delete map[previousName];
  map[draft.name] = draft;
  write(map);
}

export function deleteDraft(name: string): void {
  const map = read();
  delete map[name];
  write(map);
}
