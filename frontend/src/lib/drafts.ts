/**
 * Local drafts for the Builder's "Save as draft".
 *
 * The backend has no draft concept — an agent either exists as YAML in the
 * registry or it does not. So a draft is exactly what its name says: work in
 * progress held in this browser, never sent to the API. It becomes a real agent
 * only via "Save & Register", which goes through the normal create/update path.
 */
import { blankOutputField, type WizardDraft } from "./wizard";

const STORAGE_KEY = "agent-kit.builderDrafts";

type DraftMap = Record<string, WizardDraft>;

/**
 * Backfills fields a draft saved before they existed won't have.
 *
 * `read()` trusts `JSON.parse` with a type assertion, not real validation —
 * a draft saved in an earlier browser session is whatever shape it was saved
 * as. When `inputFields`/`inputFieldsTouched`/`hasInputModel` were added, an
 * older saved draft would deserialize with them `undefined` and crash the
 * wizard on `draft.inputFields.map(...)`. Same defaults `draftFromDetail`
 * uses for "no input model yet". `outputSpecIsReal`/`inputSpecIsReal`
 * (Task 10) get the safer of the two possible defaults — `false`, i.e. "show
 * the reconstructed-from-annotations caveat" — since an older draft's rows
 * really did come from that lossy path, not the lossless one.
 */
function normalize(draft: WizardDraft): WizardDraft {
  return {
    ...draft,
    inputFields: draft.inputFields ?? [blankOutputField()],
    inputFieldsTouched: draft.inputFieldsTouched ?? false,
    hasInputModel: draft.hasInputModel ?? false,
    outputSpecIsReal: draft.outputSpecIsReal ?? false,
    inputSpecIsReal: draft.inputSpecIsReal ?? false,
  };
}

function read(): DraftMap {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as DraftMap;
    return Object.fromEntries(Object.entries(parsed).map(([name, draft]) => [name, normalize(draft)]));
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
