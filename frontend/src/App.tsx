import { useCallback, useEffect, useState } from "react";

import { ApiError, getApiBase, listAgents } from "./api/client";
import type { AgentSummary } from "./api/types";
import { BuilderScreen } from "./screens/BuilderScreen";
import { ModelsScreen } from "./screens/ModelsScreen";
import { RosterScreen } from "./screens/RosterScreen";
import { RunScreen } from "./screens/RunScreen";
import { SettingsScreen } from "./screens/SettingsScreen";

export type View = "run" | "roster" | "builder" | "models" | "settings";

const TABS: { view: View; label: string }[] = [
  { view: "run", label: "Run" },
  { view: "roster", label: "Roster" },
  { view: "builder", label: "Builder" },
  { view: "models", label: "Models" },
  { view: "settings", label: "Settings" },
];

export function App() {
  const [view, setView] = useState<View>("run");
  const [agents, setAgents] = useState<AgentSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  /** Bumped whenever a mutation invalidates roster/queue data. */
  const [dataVersion, setDataVersion] = useState(0);

  const loadAgents = useCallback(async () => {
    setAgents(null);
    setLoadError(null);
    try {
      const loaded = await listAgents();
      setAgents(loaded);
      setSelected((current) =>
        current && loaded.some((a) => a.name === current) ? current : (loaded[0]?.name ?? null),
      );
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : String(e);
      setAgents([]);
      setLoadError(
        `Could not reach the API at ${getApiBase()}.\n${detail}\n\nIs the playground server running?`,
      );
    }
  }, []);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  const invalidate = useCallback(() => setDataVersion((v) => v + 1), []);

  /** Builder's "Run this agent" — switch tabs, select, and seed the input box. */
  const openInRun = useCallback((name: string, sampleInput?: string) => {
    setSelected(name);
    if (sampleInput) setDrafts((d) => ({ ...d, [name]: sampleInput }));
    setView("run");
  }, []);

  const agentCount = agents?.length ?? 0;

  return (
    <div className="ak-app">
      <header className="ak-header">
        <div style={{ display: "flex", alignItems: "center", gap: 28 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span className="ak-brand">Agent-Kit</span>
            <span className="ak-brand-sub">Playground</span>
          </div>
          <nav style={{ display: "flex", gap: 18 }}>
            {TABS.map((tab) => (
              <button
                key={tab.view}
                type="button"
                className="ak-tab"
                aria-current={view === tab.view ? "page" : undefined}
                onClick={() => setView(tab.view)}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
        <div className="ak-status">
          {agents !== null && !loadError && (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                color: "var(--color-accent-700)",
              }}
            >
              <span className="ak-status-dot" style={{ background: "var(--color-accent)" }} />
              {agentCount} agents
            </span>
          )}
          {loadError && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "#a03d33" }}>
              <span className="ak-status-dot" style={{ background: "#a03d33" }} />
              offline
            </span>
          )}
          <span style={{ opacity: 0.55 }}>{getApiBase()}</span>
        </div>
      </header>

      {view === "run" && (
        <RunScreen
          agents={agents}
          loadError={loadError}
          onRetry={loadAgents}
          selected={selected}
          onSelect={setSelected}
          drafts={drafts}
          setDrafts={setDrafts}
          onGraded={invalidate}
        />
      )}
      {view === "roster" && (
        <RosterScreen dataVersion={dataVersion} onConfigure={() => setView("settings")} />
      )}
      {view === "builder" && (
        <BuilderScreen
          agents={agents ?? []}
          dataVersion={dataVersion}
          onAgentsChanged={() => {
            void loadAgents();
            invalidate();
          }}
          onRunAgent={openInRun}
        />
      )}
      {view === "models" && <ModelsScreen />}
      {view === "settings" && <SettingsScreen onManageModels={() => setView("models")} />}
    </div>
  );
}
