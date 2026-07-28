import { useEffect, useState } from "react";

import {
  ApiError,
  DEFAULT_API_BASE,
  getApiBase,
  getSettings,
  listAgents,
  listCards,
  setApiBase,
  updateSettings,
} from "../api/client";
import type { PlaygroundSettings } from "../api/types";
import { Corners } from "../components/Blueprint";
import { BASE_MODEL_OPTIONS } from "../lib/wizard";

export function SettingsScreen() {
  const [settings, setSettings] = useState<PlaygroundSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [apiBase, setApiBaseInput] = useState(getApiBase());
  const [saving, setSaving] = useState(false);
  const [ack, setAck] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    void getSettings()
      .then(setSettings)
      .catch((e: unknown) =>
        setLoadError(e instanceof ApiError ? e.detail : String(e)),
      );
  }, []);

  const patch = (p: Partial<PlaygroundSettings>) => {
    setSettings((s) => (s ? { ...s, ...p } : s));
    setAck(null);
  };

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setAck(null);
    setSaveError(null);
    // The API base is the browser's own setting — which server to talk to —
    // so it is stored locally rather than sent to that server.
    setApiBase(apiBase);
    try {
      setSettings(await updateSettings(settings));
      setAck("Saved — applied to the running server.");
    } catch (e) {
      setSaveError(e instanceof ApiError ? `HTTP ${e.status} — ${e.detail}` : String(e));
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    setApiBaseInput(DEFAULT_API_BASE);
    setSettings({
      provider_url: "http://localhost:11434/v1",
      default_model: "qwen2.5:14b",
      gm_model: "qwen2.5:14b",
      stub_mode: false,
      respec_threshold: 12,
      auto_process_respec: false,
      suggestions_enabled: true,
      ntfy_url: "",
      db_path: "agent_kit.db",
    });
    setAck("Reset to defaults — press Save settings to apply.");
    setTestResult(null);
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    setApiBase(apiBase);
    try {
      const [agents, cards] = await Promise.all([listAgents(), listCards()]);
      setTestResult({
        ok: true,
        text: `Connected — ${agents.length} agents, ${cards.length} cards`,
      });
    } catch (e) {
      setTestResult({
        ok: false,
        text: e instanceof ApiError ? `No response — ${e.detail}` : String(e),
      });
    } finally {
      setTesting(false);
    }
  };

  if (loadError) {
    return (
      <div className="ak-screen">
        <div className="ak-error-box" style={{ maxWidth: 720 }}>
          Could not load settings: {loadError}
        </div>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="ak-screen">
        <div style={{ fontSize: 12.5, opacity: 0.5 }}>Loading settings…</div>
      </div>
    );
  }

  const modelOptions = Array.from(
    new Set([settings.default_model, settings.gm_model, ...BASE_MODEL_OPTIONS]),
  );

  return (
    <div className="ak-screen">
      <div style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 720 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <h1 className="ak-screen-title">Settings</h1>
          <p className="ak-screen-sub">
            API connections, model providers and Game Master behavior. Local-only — the playground
            binds to 127.0.0.1 and has no auth layer.
          </p>
        </div>

        <section style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="ak-kicker">Playground API</div>
          <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <label htmlFor="s-api-base">Base URL</label>
            <input
              id="s-api-base"
              className="input ak-mono"
              value={apiBase}
              onChange={(e) => setApiBaseInput(e.target.value)}
            />
            <span style={{ fontSize: 11.5, opacity: 0.55 }}>
              Stored in this browser, not on the server — it's which server this page talks to. The
              default <span className="ak-mono">{DEFAULT_API_BASE}</span> goes through the dev
              server's proxy.
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              type="button"
              className="btn btn-secondary blueprint"
              style={{ fontSize: 12.5 }}
              onClick={() => void testConnection()}
              disabled={testing}
            >
              <Corners />
              {testing ? "Testing…" : "Test connection"}
            </button>
            {testResult && (
              <span
                className="ak-mono"
                style={{
                  fontSize: 12,
                  color: testResult.ok ? "var(--color-accent-700)" : "#a03d33",
                }}
              >
                {testResult.text}
              </span>
            )}
          </div>
        </section>

        <section style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="ak-kicker">Model provider</div>
          <div className="ak-two-col">
            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label htmlFor="s-provider">Provider base URL</label>
              <input
                id="s-provider"
                className="input ak-mono"
                value={settings.provider_url}
                onChange={(e) => patch({ provider_url: e.target.value })}
              />
            </div>
            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label htmlFor="s-default-model">Default agent model</label>
              <select
                id="s-default-model"
                className="input"
                value={settings.default_model}
                onChange={(e) => patch({ default_model: e.target.value })}
              >
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <label className="ak-checkbox-row">
            <input
              type="checkbox"
              checked={settings.stub_mode}
              onChange={(e) => patch({ stub_mode: e.target.checked })}
            />
            <span>
              Stub mode (<span className="ak-mono">STUB_AI_PROVIDERS=1</span>) — return fixtures,
              make no model calls
            </span>
          </label>
          <span style={{ fontSize: 11.5, opacity: 0.55, marginTop: -6 }}>
            Applies to the whole server process, not just this browser tab.
          </span>
        </section>

        <section style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="ak-kicker">Game Master</div>
          <div className="ak-two-col">
            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label htmlFor="s-gm-model">GM model</label>
              <select
                id="s-gm-model"
                className="input"
                value={settings.gm_model}
                onChange={(e) => patch({ gm_model: e.target.value })}
              >
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label htmlFor="s-threshold">
                Respec threshold — {settings.respec_threshold} grade events
              </label>
              <input
                id="s-threshold"
                type="range"
                min={1}
                max={50}
                step={1}
                className="ak-range"
                value={settings.respec_threshold}
                onChange={(e) => patch({ respec_threshold: parseInt(e.target.value, 10) })}
              />
            </div>
          </div>
          <label className="ak-checkbox-row">
            <input
              type="checkbox"
              checked={settings.auto_process_respec}
              onChange={(e) => patch({ auto_process_respec: e.target.checked })}
            />
            Process the respec queue automatically when the threshold is reached
          </label>
          <label className="ak-checkbox-row">
            <input
              type="checkbox"
              checked={settings.suggestions_enabled}
              onChange={(e) => patch({ suggestions_enabled: e.target.checked })}
            />
            Let the GM propose system-prompt suggestions (always requires approval)
          </label>
        </section>

        <section style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="ak-kicker">Notifications &amp; storage</div>
          <div className="ak-two-col">
            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label htmlFor="s-ntfy">NTFY_URL</label>
              <input
                id="s-ntfy"
                className="input ak-mono"
                value={settings.ntfy_url}
                onChange={(e) => patch({ ntfy_url: e.target.value })}
                placeholder="https://ntfy.example.com/agent-kit"
              />
            </div>
            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <label htmlFor="s-db">AGENT_KIT_DB_PATH</label>
              <input
                id="s-db"
                className="input ak-mono"
                value={settings.db_path}
                onChange={(e) => patch({ db_path: e.target.value })}
              />
            </div>
          </div>
          <span style={{ fontSize: 11.5, opacity: 0.55, marginTop: -6 }}>
            Changing the database path reconnects the card store to a different file — existing
            character progress stays in the old one.
          </span>
        </section>

        {saveError && <div className="ak-error-box">{saveError}</div>}

        <div className="ak-actions-row">
          <button
            type="button"
            className="btn btn-primary blueprint"
            onClick={() => void save()}
            disabled={saving}
          >
            <Corners />
            {saving ? "Saving…" : "Save settings"}
          </button>
          <button type="button" className="btn btn-ghost" onClick={reset}>
            Reset to defaults
          </button>
          {ack && <span className="ak-ok-text">{ack}</span>}
        </div>
      </div>
    </div>
  );
}
