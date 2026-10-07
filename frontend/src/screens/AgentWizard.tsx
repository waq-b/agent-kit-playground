import { useState } from "react";

import { checkModel } from "../api/client";
import type { ClassSummary, FieldType, ModelCheckResponse, ModelProviderSummary } from "../api/types";
import { Corners } from "../components/Blueprint";
import { ModelSelect } from "../components/ModelSelect";
import { buildModelOptions } from "../lib/models";
import {
  CUSTOM_MODEL,
  blankOutputField,
  resolvedModel,
  validateDraft,
  type OutputFieldDraft,
  type WizardDraft,
  type WizardErrors,
} from "../lib/wizard";

interface Props {
  draft: WizardDraft;
  setDraft: (update: (d: WizardDraft) => WizardDraft) => void;
  isNew: boolean;
  originalName: string | null;
  existingNames: string[];
  classes: ClassSummary[];
  tools: string[];
  models: ModelProviderSummary[];
  defaultModel: string;
  submitError: string | null;
  saving: boolean;
  onSaveRegister: () => void;
  onSaveDraft: () => void;
  onCancel: () => void;
  onOpenClassBuilder: () => void;
}

const FIELD_TYPES: FieldType[] = ["string", "integer", "number", "boolean", "nested"];

export function AgentWizard({
  draft,
  setDraft,
  isNew,
  originalName,
  existingNames,
  classes,
  tools,
  models,
  defaultModel,
  submitError,
  saving,
  onSaveRegister,
  onSaveDraft,
  onCancel,
  onOpenClassBuilder,
}: Props) {
  const [errors, setErrors] = useState<WizardErrors>({});
  const [modelCheck, setModelCheck] = useState<ModelCheckResponse | null>(null);
  const [checking, setChecking] = useState(false);

  const patch = (p: Partial<WizardDraft>) => setDraft((d) => ({ ...d, ...p }));

  const patchFields = (update: (fields: OutputFieldDraft[]) => OutputFieldDraft[]) =>
    setDraft((d) => ({ ...d, outputFields: update(d.outputFields), outputFieldsTouched: true }));

  const patchInputFields = (update: (fields: OutputFieldDraft[]) => OutputFieldDraft[]) =>
    setDraft((d) => ({ ...d, inputFields: update(d.inputFields), inputFieldsTouched: true }));

  const modelOptions = [
    ...buildModelOptions(models, [defaultModel, draft.model === CUSTOM_MODEL ? null : draft.model]),
    { value: CUSTOM_MODEL, label: "Custom…", kind: "local" as const },
  ];

  const attemptSave = (asDraft: boolean) => {
    const found = validateDraft(draft, existingNames, originalName, asDraft, isNew);
    setErrors(found);
    if (Object.keys(found).length) return;
    if (asDraft) onSaveDraft();
    else onSaveRegister();
  };

  const runModelCheck = async () => {
    const model = resolvedModel(draft);
    if (!model) return;
    setChecking(true);
    setModelCheck(null);
    try {
      setModelCheck(await checkModel(model));
    } catch {
      setModelCheck({ available: false, message: "Could not reach the API to check." });
    } finally {
      setChecking(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 22, maxWidth: 720 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h1 className="ak-screen-title ak-sm">
            {isNew ? "New agent" : `Edit ${originalName}`}
          </h1>
          {draft.isCore && <span className="tag tag-outline">Core Demo Agent</span>}
        </div>
        {draft.isCore && (
          <p style={{ margin: 0, fontSize: 12.5, opacity: 0.6 }}>
            This ships with agent-kit. Edits here are written to your local data directory —
            consider Duplicate if you want to keep the original untouched.
          </p>
        )}
      </div>

      {/* Identity */}
      <section style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="ak-kicker">Identity</div>
        <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label htmlFor="w-name">Name</label>
          <input
            id="w-name"
            className="input ak-mono"
            value={draft.name}
            disabled={!isNew}
            onChange={(e) => patch({ name: e.target.value })}
            placeholder="e.g. weather_briefing"
          />
          {!isNew && (
            <span style={{ fontSize: 11.5, opacity: 0.55 }}>
              Renaming isn't supported by the builder API — use Duplicate to create a copy under a
              new name.
            </span>
          )}
          {errors.name && <span className="ak-error-text">{errors.name}</span>}
        </div>
        <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label htmlFor="w-desc">Description</label>
          <input
            id="w-desc"
            className="input"
            value={draft.description}
            onChange={(e) => patch({ description: e.target.value })}
            placeholder="One line — shown in the agent list"
          />
        </div>
      </section>

      {/* System prompt */}
      <section style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="ak-kicker">System prompt</div>
        <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <textarea
            className="input ak-code-input"
            rows={6}
            value={draft.systemPrompt}
            onChange={(e) => patch({ systemPrompt: e.target.value })}
            placeholder="You are a..."
          />
          {errors.systemPrompt && <span className="ak-error-text">{errors.systemPrompt}</span>}
        </div>
      </section>

      {/* Model settings */}
      <section style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="ak-kicker">Model settings</div>
        <div className="ak-two-col">
          <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label htmlFor="w-model">Model</label>
            <ModelSelect
              id="w-model"
              options={modelOptions}
              value={draft.model}
              onChange={(v) => {
                patch({ model: v });
                setModelCheck(null);
              }}
            />
            {draft.model === CUSTOM_MODEL && (
              <input
                className="input ak-mono"
                style={{ marginTop: 4 }}
                value={draft.customModel}
                onChange={(e) => patch({ customModel: e.target.value })}
                placeholder="e.g. mixtral:8x7b"
              />
            )}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
              <button
                type="button"
                className="btn btn-ghost"
                style={{ fontSize: 11.5, padding: "2px 6px" }}
                onClick={() => void runModelCheck()}
                disabled={checking}
              >
                {checking ? "Checking…" : "Check availability"}
              </button>
              {modelCheck && (
                <span
                  className="ak-mono"
                  style={{
                    fontSize: 11.5,
                    color: modelCheck.available ? "var(--color-accent-700)" : "#a03d33",
                  }}
                >
                  {modelCheck.message}
                </span>
              )}
            </div>
            {errors.model && <span className="ak-error-text">{errors.model}</span>}
          </div>
          <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label htmlFor="w-temp">Temperature — {draft.temperature.toFixed(1)}</label>
            <input
              id="w-temp"
              type="range"
              min={0}
              max={2}
              step={0.1}
              className="ak-range"
              value={draft.temperature}
              onChange={(e) => patch({ temperature: parseFloat(e.target.value) })}
            />
          </div>
        </div>
      </section>

      {/* Input model — required for a new agent (there's no fallback), optional
          for an existing one that never got one. Same field-row editor as
          Output model below, second independent instance. */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <div className="ak-kicker">Input model</div>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ fontSize: 12 }}
            onClick={() => patchInputFields((f) => [...f, blankOutputField()])}
          >
            + Add field
          </button>
        </div>
        {!draft.hasInputModel && (
          <div style={{ fontSize: 11.5, opacity: 0.6 }}>
            {isNew
              ? "This becomes the real contract POST /run validates the input against — not just a hint."
              : "This agent has no input model yet — POST /run currently accepts any JSON object " +
                "unvalidated. Add fields below to give it a real contract, or leave it as-is."}
          </div>
        )}
        {!isNew && draft.hasInputModel && !draft.inputFieldsTouched && (
          <div style={{ fontSize: 11.5, opacity: 0.6 }}>
            {draft.inputSpecIsReal
              ? "Loaded from the original field definitions, including any nested sub-fields."
              : "Reconstructed from the stored model's type annotations — nested sub-field " +
                "structure may not be fully recovered."}{" "}
            Leave it alone and the saved input model is kept exactly as-is; edit any row and the
            whole model is regenerated from what you see here.
          </div>
        )}
        {errors.inputFields && <span className="ak-error-text">{errors.inputFields}</span>}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <FieldHeader />
          {draft.inputFields.map((field) => (
            <FieldRow
              key={field.id}
              field={field}
              error={errors.inputFieldRows?.[field.id]}
              fieldErrors={errors.inputFieldRows}
              onChange={(p) =>
                patchInputFields((fields) =>
                  fields.map((f) => (f.id === field.id ? { ...f, ...p } : f)),
                )
              }
              onRemove={() => patchInputFields((fields) => fields.filter((f) => f.id !== field.id))}
              onNestedChange={(nested) =>
                patchInputFields((fields) =>
                  fields.map((f) => (f.id === field.id ? { ...f, nested } : f)),
                )
              }
            />
          ))}
        </div>
      </section>

      {/* Output model */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
          <div className="ak-kicker">Output model</div>
          <button
            type="button"
            className="btn btn-ghost"
            style={{ fontSize: 12 }}
            onClick={() => patchFields((f) => [...f, blankOutputField()])}
          >
            + Add field
          </button>
        </div>
        {!isNew && !draft.outputFieldsTouched && (
          <div style={{ fontSize: 11.5, opacity: 0.6 }}>
            {draft.outputSpecIsReal
              ? "Loaded from the original field definitions, including any nested sub-fields."
              : "Reconstructed from the stored model's type annotations — nested sub-field " +
                "structure may not be fully recovered."}{" "}
            Leave it alone and the saved output model is kept exactly as-is; edit any row and the
            whole model is regenerated from what you see here.
          </div>
        )}
        {errors.fields && <span className="ak-error-text">{errors.fields}</span>}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <FieldHeader />
          {draft.outputFields.map((field) => (
            <FieldRow
              key={field.id}
              field={field}
              error={errors.fieldRows?.[field.id]}
              fieldErrors={errors.fieldRows}
              onChange={(p) =>
                patchFields((fields) =>
                  fields.map((f) => (f.id === field.id ? { ...f, ...p } : f)),
                )
              }
              onRemove={() => patchFields((fields) => fields.filter((f) => f.id !== field.id))}
              onNestedChange={(nested) =>
                patchFields((fields) =>
                  fields.map((f) => (f.id === field.id ? { ...f, nested } : f)),
                )
              }
            />
          ))}
        </div>
      </section>

      {/* Tools & feeds — not in the imported design; the API supports both and
          an agent like `news` cannot be rebuilt without them. */}
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="ak-kicker">Tools &amp; feeds</div>
        {tools.length === 0 && (
          <span style={{ fontSize: 12, opacity: 0.55 }}>No tools registered on the server.</span>
        )}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
          {tools.map((tool) => (
            <label key={tool} className="ak-checkbox-row">
              <input
                type="checkbox"
                checked={draft.tools.includes(tool)}
                onChange={(e) =>
                  patch({
                    tools: e.target.checked
                      ? [...draft.tools, tool]
                      : draft.tools.filter((t) => t !== tool),
                  })
                }
              />
              <span className="ak-mono">{tool}</span>
            </label>
          ))}
        </div>
        <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <label htmlFor="w-feeds">Feed URLs — one per line</label>
          <textarea
            id="w-feeds"
            className="input ak-code-input"
            rows={3}
            value={draft.feeds.join("\n")}
            onChange={(e) =>
              patch({ feeds: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })
            }
            placeholder="https://feeds.bbci.co.uk/news/rss.xml"
          />
        </div>
      </section>

      {/* Class assignment + character card */}
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="ak-kicker">Class assignment</div>
        <div className="ak-two-col">
          <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label htmlFor="w-main-class">Main class</label>
            <select
              id="w-main-class"
              className="input"
              value={draft.mainClass}
              onChange={(e) => patch({ mainClass: e.target.value })}
            >
              <option value="">None</option>
              {classes.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.title}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label htmlFor="w-sub-class">
              Sub class{" "}
              <span style={{ opacity: 0.5, textTransform: "none", letterSpacing: 0 }}>
                (optional)
              </span>
            </label>
            <select
              id="w-sub-class"
              className="input"
              value={draft.subClass}
              disabled={!draft.mainClass}
              onChange={(e) => patch({ subClass: e.target.value })}
            >
              <option value="">None</option>
              {classes
                .filter((c) => c.name !== draft.mainClass)
                .map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.title}
                  </option>
                ))}
            </select>
          </div>
        </div>
        <button
          type="button"
          className="btn btn-ghost"
          style={{ alignSelf: "flex-start", fontSize: 12.5 }}
          onClick={onOpenClassBuilder}
        >
          + Create new class
        </button>

        {/* Card fields only matter once a class makes this agent a character. */}
        {draft.mainClass && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 4 }}>
            <div className="ak-two-col">
              <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label htmlFor="w-card-title">Character title</label>
                <input
                  id="w-card-title"
                  className="input"
                  value={draft.cardTitle}
                  onChange={(e) => patch({ cardTitle: e.target.value })}
                  placeholder="Defaults to the class title"
                />
              </div>
              <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label htmlFor="w-portrait">Portrait</label>
                <input
                  id="w-portrait"
                  className="input"
                  value={draft.portrait}
                  onChange={(e) => patch({ portrait: e.target.value })}
                  placeholder="🤖"
                />
              </div>
            </div>
            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label htmlFor="w-backstory">Backstory</label>
              <textarea
                id="w-backstory"
                className="input"
                rows={2}
                value={draft.backstory}
                onChange={(e) => patch({ backstory: e.target.value })}
                placeholder="A line of flavour, shown on the Roster card."
              />
            </div>
            <span style={{ fontSize: 11.5, opacity: 0.55 }}>
              Starting stats and the unlock table come from the class definition. Live stats are
              owned by the card store and change through grading, so they aren't edited here.
            </span>
          </div>
        )}
      </section>

      {/* Sample input */}
      <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div className="ak-kicker">
          Sample input{" "}
          <span style={{ opacity: 0.6, textTransform: "none", letterSpacing: 0 }}>
            (optional — pre-fills the Run screen)
          </span>
        </div>
        <textarea
          className="input ak-code-input"
          rows={3}
          value={draft.sampleInput}
          onChange={(e) => patch({ sampleInput: e.target.value })}
          placeholder='{"name": "Alice"}'
        />
        {errors.sampleInput && <span className="ak-error-text">{errors.sampleInput}</span>}
      </section>

      {submitError && <div className="ak-error-box">{submitError}</div>}

      <div className="ak-actions-row" style={{ marginTop: 4 }}>
        <button
          type="button"
          className="btn btn-primary blueprint"
          onClick={() => attemptSave(false)}
          disabled={saving}
        >
          <Corners />
          {saving ? "Saving…" : "Save & Register"}
        </button>
        <button
          type="button"
          className="btn btn-secondary blueprint"
          onClick={() => attemptSave(true)}
          disabled={saving}
        >
          <Corners />
          Save as draft
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function FieldHeader() {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 120px 70px 90px 28px",
        gap: 8,
        fontSize: 10.5,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        opacity: 0.5,
        padding: "0 2px",
      }}
    >
      <span>Field name</span>
      <span>Type</span>
      <span>List</span>
      <span>Required</span>
      <span />
    </div>
  );
}

interface FieldRowProps {
  field: OutputFieldDraft;
  error?: string;
  fieldErrors?: Record<string, string>;
  onChange: (patch: Partial<OutputFieldDraft>) => void;
  onRemove: () => void;
  onNestedChange: (nested: OutputFieldDraft[]) => void;
  /** Sub-fields cannot themselves nest — the backend allows one level. */
  depth?: number;
}

function FieldRow({
  field,
  error,
  fieldErrors,
  onChange,
  onRemove,
  onNestedChange,
  depth = 0,
}: FieldRowProps) {
  const availableTypes = depth === 0 ? FIELD_TYPES : FIELD_TYPES.filter((t) => t !== "nested");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 120px 70px 90px 28px",
          gap: 8,
          alignItems: "center",
        }}
      >
        <input
          className="input ak-mono"
          style={{ fontSize: 13 }}
          value={field.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="field_name"
          aria-label="Field name"
        />
        <select
          className="input"
          style={{ fontSize: 13 }}
          value={field.type}
          aria-label="Field type"
          onChange={(e) => {
            const type = e.target.value as FieldType;
            onChange({
              type,
              // Entering "nested" needs a sub-field to be valid; leaving it
              // should not keep orphaned sub-fields around.
              nested: type === "nested" ? (field.nested.length ? field.nested : [blankOutputField()]) : [],
            });
          }}
        >
          {availableTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <label className="ak-checkbox-row" style={{ justifySelf: "start" }}>
          <input
            type="checkbox"
            checked={field.isList}
            aria-label="Is a list"
            onChange={(e) => onChange({ isList: e.target.checked })}
          />
        </label>
        <label className="ak-checkbox-row">
          <input
            type="checkbox"
            checked={field.required}
            onChange={(e) => onChange({ required: e.target.checked })}
          />
          Required
        </label>
        <button type="button" className="ak-field-remove" aria-label="Remove field" onClick={onRemove}>
          ✕
        </button>
      </div>
      {error && (
        <span className="ak-error-text" style={{ fontSize: 11.5, paddingLeft: 2 }}>
          {error}
        </span>
      )}

      {field.type === "nested" && (
        <div
          style={{
            marginLeft: 14,
            paddingLeft: 12,
            borderLeft: "2px solid var(--color-neutral-300)",
            display: "flex",
            flexDirection: "column",
            gap: 8,
            marginTop: 4,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              justifyContent: "space-between",
            }}
          >
            <span className="ak-kicker-xs">Sub-fields of {field.name || "this field"}</span>
            <button
              type="button"
              className="btn btn-ghost"
              style={{ fontSize: 11.5 }}
              onClick={() => onNestedChange([...field.nested, blankOutputField()])}
            >
              + Add sub-field
            </button>
          </div>
          {field.nested.map((sub) => (
            <FieldRow
              key={sub.id}
              field={sub}
              depth={depth + 1}
              error={fieldErrors?.[sub.id]}
              fieldErrors={fieldErrors}
              onChange={(p) =>
                onNestedChange(field.nested.map((n) => (n.id === sub.id ? { ...n, ...p } : n)))
              }
              onRemove={() => onNestedChange(field.nested.filter((n) => n.id !== sub.id))}
              onNestedChange={() => {
                /* one level of nesting only */
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
