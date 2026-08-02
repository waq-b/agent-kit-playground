import { useEffect, useState } from "react";

import { ApiError, createModel, deleteModel, getSettings, listModels, updateSettings } from "../api/client";
import type { ModelKind, ModelProviderSummary } from "../api/types";
import { Corners } from "../components/Blueprint";

const URL_PATTERN = /^https?:\/\/.+/i;
const MODEL_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9.:_\/-]*$/;

interface NewModelDraft {
  modelId: string;
  label: string;
  kind: ModelKind;
  baseUrl: string;
  apiKey: string;
}

function blankDraft(): NewModelDraft {
  return { modelId: "", label: "", kind: "local", baseUrl: "", apiKey: "" };
}

export function ModelsScreen() {
  const [models, setModels] = useState<ModelProviderSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  const [localUrl, setLocalUrl] = useState("");
  const [localUrlSaving, setLocalUrlSaving] = useState(false);
  const [localUrlAck, setLocalUrlAck] = useState<string | null>(null);

  const [draft, setDraft] = useState<NewModelDraft>(blankDraft());
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const loadModels = () => {
    setModels(null);
    setListError(null);
    listModels()
      .then(setModels)
      .catch((e: unknown) => {
        setModels([]);
        setListError(e instanceof ApiError ? e.detail : String(e));
      });
  };

  useEffect(() => {
    loadModels();
    void getSettings()
      .then((s) => setLocalUrl(s.provider_url))
      .catch(() => {});
  }, []);

  const saveLocalUrl = async () => {
    setLocalUrlSaving(true);
    setLocalUrlAck(null);
    try {
      const saved = await updateSettings({ provider_url: localUrl });
      setLocalUrl(saved.provider_url);
      setLocalUrlAck("Saved — every local model now uses this endpoint.");
    } catch (e) {
      setLocalUrlAck(e instanceof ApiError ? `Failed — ${e.detail}` : String(e));
    } finally {
      setLocalUrlSaving(false);
    }
  };

  const patch = (p: Partial<NewModelDraft>) => setDraft((d) => ({ ...d, ...p }));

  const validate = (d: NewModelDraft): Record<string, string> => {
    const errors: Record<string, string> = {};
    if (!d.modelId.trim()) errors.modelId = "Model ID is required.";
    else if (!MODEL_ID_PATTERN.test(d.modelId.trim()))
      errors.modelId = "Use letters, numbers, and . : _ - / only.";
    else if ((models ?? []).some((m) => m.model_id === d.modelId.trim()))
      errors.modelId = "This model ID is already registered.";
    if (d.kind === "frontier") {
      if (!d.baseUrl.trim()) errors.baseUrl = "Base URL is required for a frontier model.";
      else if (!URL_PATTERN.test(d.baseUrl.trim())) errors.baseUrl = "Enter a full http(s) URL.";
      if (!d.apiKey.trim()) errors.apiKey = "API key is required for a frontier model.";
    }
    return errors;
  };

  const addModel = async () => {
    const errors = validate(draft);
    setFieldErrors(errors);
    if (Object.keys(errors).length) return;

    setSaving(true);
    setSubmitError(null);
    try {
      await createModel({
        model_id: draft.modelId.trim(),
        label: draft.label.trim(),
        kind: draft.kind,
        base_url: draft.kind === "frontier" ? draft.baseUrl.trim() : null,
        api_key: draft.kind === "frontier" ? draft.apiKey.trim() : null,
      });
      setDraft(blankDraft());
      setFieldErrors({});
      loadModels();
    } catch (e) {
      setSubmitError(e instanceof ApiError ? `HTTP ${e.status} — ${e.detail}` : String(e));
    } finally {
      setSaving(false);
    }
  };

  const removeModel = async (modelId: string) => {
    try {
      await deleteModel(modelId);
      setDeleteConfirm(null);
      loadModels();
    } catch (e) {
      setListError(e instanceof ApiError ? e.detail : String(e));
      setDeleteConfirm(null);
    }
  };

  return (
    <div className="ak-screen">
      <div style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 760 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <h1 className="ak-screen-title">Model Providers</h1>
          <p className="ak-screen-sub">
            Register the models agents and the Game Master can run against. Registered models show
            up everywhere a model is picked — Settings, and the Builder wizard.
          </p>
        </div>

        {/* Local provider — the one shared endpoint every "local" model resolves to */}
        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="ak-kicker">Local provider</div>
          <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label htmlFor="m-local-url">Base URL</label>
            <input
              id="m-local-url"
              className="input ak-mono"
              value={localUrl}
              onChange={(e) => setLocalUrl(e.target.value)}
              placeholder="http://localhost:11434/v1"
            />
            <span style={{ fontSize: 11.5, opacity: 0.55 }}>
              Every model registered below as <strong>Local</strong> — and any unregistered model
              name, exactly as before this page existed — is sent here. There's one shared local
              endpoint, not one per model.
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              type="button"
              className="btn btn-secondary blueprint"
              onClick={() => void saveLocalUrl()}
              disabled={localUrlSaving}
              style={{ fontSize: 12.5 }}
            >
              <Corners />
              {localUrlSaving ? "Saving…" : "Save"}
            </button>
            {localUrlAck && <span className="ak-ok-text">{localUrlAck}</span>}
          </div>
        </section>

        {/* Registered models */}
        <section style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="ak-kicker">Registered models</div>
          {listError && <div className="ak-error-box">{listError}</div>}
          {models === null && <div style={{ fontSize: 12.5, opacity: 0.5 }}>Loading…</div>}
          {models !== null && models.length === 0 && !listError && (
            <div className="ak-panel blueprint">
              <Corners />
              <span style={{ fontSize: 12.5, opacity: 0.55 }}>
                No models registered yet — every agent still runs fine against an unregistered
                local model name. Register one below for it to appear in the dropdowns.
              </span>
            </div>
          )}
          {(models ?? []).map((m) => (
            <div key={m.model_id} className="ak-panel blueprint">
              <Corners />
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 14,
                }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span
                      style={{
                        fontFamily: "var(--font-heading)",
                        fontWeight: 600,
                        fontSize: 16,
                        letterSpacing: "0.03em",
                      }}
                    >
                      {m.label}
                    </span>
                    <span className={`tag ${m.kind === "frontier" ? "tag-accent" : "tag-neutral"}`}>
                      {m.kind === "frontier" ? "Frontier" : "Local"}
                    </span>
                  </div>
                  <span className="ak-mono" style={{ fontSize: 11.5, opacity: 0.6 }}>
                    {m.model_id}
                  </span>
                  {m.kind === "frontier" && (
                    <span className="ak-mono" style={{ fontSize: 11, opacity: 0.5 }}>
                      {m.base_url} · {m.has_api_key ? "API key set" : "no API key"}
                    </span>
                  )}
                </div>
                {deleteConfirm === m.model_id ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
                    <span style={{ fontSize: 12, color: "#a03d33" }}>Remove {m.model_id}?</span>
                    <button
                      type="button"
                      className="btn btn-secondary blueprint"
                      style={{
                        fontSize: 12,
                        padding: "4px 10px",
                        borderColor: "#a03d33",
                        color: "#a03d33",
                      }}
                      onClick={() => void removeModel(m.model_id)}
                    >
                      <Corners />
                      Confirm
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      style={{ fontSize: 12 }}
                      onClick={() => setDeleteConfirm(null)}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="btn btn-ghost"
                    style={{ fontSize: 12, color: "#a03d33", flex: "none" }}
                    onClick={() => setDeleteConfirm(m.model_id)}
                  >
                    Remove
                  </button>
                )}
              </div>
            </div>
          ))}
        </section>

        {/* Add a model */}
        <section
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 14,
            borderTop: "1px solid var(--color-neutral-300)",
            paddingTop: 20,
          }}
        >
          <div className="ak-kicker">Add a model</div>

          <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label>Provider</label>
            <div className="seg" style={{ alignSelf: "flex-start" }}>
              <label className="seg-opt">
                <input
                  type="radio"
                  name="model-kind"
                  checked={draft.kind === "local"}
                  onChange={() => patch({ kind: "local" })}
                />
                Local
              </label>
              <label className="seg-opt">
                <input
                  type="radio"
                  name="model-kind"
                  checked={draft.kind === "frontier"}
                  onChange={() => patch({ kind: "frontier" })}
                />
                Frontier
              </label>
            </div>
            <span style={{ fontSize: 11.5, opacity: 0.55 }}>
              {draft.kind === "local"
                ? "Uses the shared local provider URL above."
                : "Its own base URL and API key, defined below."}
            </span>
          </div>

          <div className="ak-two-col">
            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label htmlFor="m-id">Model ID</label>
              <input
                id="m-id"
                className="input ak-mono"
                value={draft.modelId}
                onChange={(e) => patch({ modelId: e.target.value })}
                placeholder="e.g. qwen2.5:14b or gpt-4o"
              />
              {fieldErrors.modelId && <span className="ak-error-text">{fieldErrors.modelId}</span>}
            </div>
            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label htmlFor="m-label">
                Label <span style={{ opacity: 0.5, textTransform: "none", letterSpacing: 0 }}>(optional)</span>
              </label>
              <input
                id="m-label"
                className="input"
                value={draft.label}
                onChange={(e) => patch({ label: e.target.value })}
                placeholder="Defaults to the model ID"
              />
            </div>
          </div>

          {draft.kind === "frontier" && (
            <div className="ak-two-col">
              <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label htmlFor="m-base-url">Base URL</label>
                <input
                  id="m-base-url"
                  className="input ak-mono"
                  value={draft.baseUrl}
                  onChange={(e) => patch({ baseUrl: e.target.value })}
                  placeholder="https://api.openai.com/v1"
                />
                {fieldErrors.baseUrl && <span className="ak-error-text">{fieldErrors.baseUrl}</span>}
              </div>
              <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label htmlFor="m-api-key">API key</label>
                <input
                  id="m-api-key"
                  className="input ak-mono"
                  type="password"
                  autoComplete="off"
                  value={draft.apiKey}
                  onChange={(e) => patch({ apiKey: e.target.value })}
                />
                {fieldErrors.apiKey && <span className="ak-error-text">{fieldErrors.apiKey}</span>}
                <span style={{ fontSize: 11, opacity: 0.5 }}>
                  Stored in plain text in <span className="ak-mono">agent_kit_data/settings.json</span>
                  {" "}on this machine — this is a local dev tool with no auth layer. Never sent back
                  to the browser once saved.
                </span>
              </div>
            </div>
          )}

          {submitError && <div className="ak-error-box">{submitError}</div>}

          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              type="button"
              className="btn btn-primary blueprint"
              onClick={() => void addModel()}
              disabled={saving}
              style={{ alignSelf: "flex-start" }}
            >
              <Corners />
              {saving ? "Adding…" : "+ Add model"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
