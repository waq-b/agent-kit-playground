import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  approveSuggestion,
  createAgent,
  deleteAgent,
  duplicateAgent,
  getAgentBuilderDetail,
  getRespecQueue,
  getSettings,
  listClasses,
  listSuggestions,
  listTools,
  processRespecQueue,
  rejectSuggestion,
  updateAgent,
} from "../api/client";
import type {
  AgentBuilderDetail,
  AgentSummary,
  ClassSummary,
  RespecQueueEntry,
  SuggestionSummary,
  UpdateAgentRequest,
} from "../api/types";
import { Corners } from "../components/Blueprint";
import { deleteDraft, listDrafts, saveDraft } from "../lib/drafts";
import { commonPrefixLength, titleize } from "../lib/format";
import {
  BASE_MODEL_OPTIONS,
  blankDraft,
  draftFromDetail,
  parseSampleInput,
  resolvedModel,
  toCardSpec,
  toCreateRequest,
  toFieldSpecs,
  type WizardDraft,
} from "../lib/wizard";
import { AgentWizard } from "./AgentWizard";
import { ClassBuilder } from "./ClassBuilder";

type Mode = "list" | "wizard" | "classBuilder";

interface Props {
  agents: AgentSummary[];
  dataVersion: number;
  onAgentsChanged: () => void;
  onRunAgent: (name: string, sampleInput?: string) => void;
}

/** A row in the Builder list: either a registered agent or a local draft. */
interface ListRow {
  name: string;
  description: string;
  isCore: boolean;
  isDraft: boolean;
  metaLine: string;
}

interface SavedBanner {
  name: string;
  registered: boolean;
  sampleInput: string;
}

export function BuilderScreen({ agents, dataVersion, onAgentsChanged, onRunAgent }: Props) {
  const [mode, setMode] = useState<Mode>("list");
  const [details, setDetails] = useState<Record<string, AgentBuilderDetail>>({});
  const [drafts, setDrafts] = useState<WizardDraft[]>(() => listDrafts());
  const [classes, setClasses] = useState<ClassSummary[]>([]);
  const [tools, setTools] = useState<string[]>([]);
  const [defaultModel, setDefaultModel] = useState(BASE_MODEL_OPTIONS[0]);

  const [wizardDraft, setWizardDraft] = useState<WizardDraft | null>(null);
  const [wizardIsNew, setWizardIsNew] = useState(true);
  const [originalName, setOriginalName] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedBanner, setSavedBanner] = useState<SavedBanner | null>(null);

  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [coreDeleteConfirm, setCoreDeleteConfirm] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);

  const [queue, setQueue] = useState<RespecQueueEntry[]>([]);
  const [suggestions, setSuggestions] = useState<SuggestionSummary[]>([]);
  const [processing, setProcessing] = useState(false);
  const [queueAck, setQueueAck] = useState<string | null>(null);

  // Per-agent builder detail powers the meta line and seeds the edit wizard.
  const loadDetails = useCallback(async () => {
    const loaded = await Promise.all(
      agents.map((a) =>
        getAgentBuilderDetail(a.name)
          .then((d) => [a.name, d] as const)
          .catch(() => null),
      ),
    );
    setDetails(
      Object.fromEntries(loaded.filter((x): x is [string, AgentBuilderDetail] => x !== null)),
    );
  }, [agents]);

  const loadGm = useCallback(async () => {
    try {
      const [q, s] = await Promise.all([getRespecQueue(), listSuggestions()]);
      setQueue(q);
      setSuggestions(s);
    } catch {
      setQueue([]);
      setSuggestions([]);
    }
  }, []);

  useEffect(() => {
    void loadDetails();
    void loadGm();
  }, [loadDetails, loadGm, dataVersion]);

  useEffect(() => {
    void listClasses().then(setClasses).catch(() => setClasses([]));
    void listTools().then(setTools).catch(() => setTools([]));
    void getSettings()
      .then((s) => setDefaultModel(s.default_model))
      .catch(() => {});
  }, []);

  const rows: ListRow[] = [
    ...agents.map((a) => {
      const d = details[a.name];
      const cardClass = (d?.card as Record<string, unknown> | null)?.main_class;
      return {
        name: a.name,
        description: a.description,
        isCore: d?.is_core ?? false,
        isDraft: false,
        metaLine: d
          ? [d.model, `T${d.temperature}`, typeof cardClass === "string" ? titleize(cardClass) : null]
              .filter(Boolean)
              .join(" · ")
          : "…",
      };
    }),
    ...drafts
      // A draft whose name now exists as a real agent has been superseded.
      .filter((d) => !agents.some((a) => a.name === d.name))
      .map((d) => ({
        name: d.name,
        description: d.description,
        isCore: false,
        isDraft: true,
        metaLine: `${resolvedModel(d) || "no model"} · T${d.temperature} · local draft`,
      })),
  ];

  const openNewAgent = () => {
    setWizardDraft(blankDraft(defaultModel));
    setWizardIsNew(true);
    setOriginalName(null);
    setSubmitError(null);
    setSavedBanner(null);
    setMode("wizard");
  };

  const openEdit = async (row: ListRow) => {
    setSubmitError(null);
    setSavedBanner(null);
    if (row.isDraft) {
      const draft = drafts.find((d) => d.name === row.name);
      if (!draft) return;
      setWizardDraft(draft);
      setWizardIsNew(true); // a draft has never been registered, so the name is still free
      setOriginalName(row.name);
      setMode("wizard");
      return;
    }
    try {
      const detail = details[row.name] ?? (await getAgentBuilderDetail(row.name));
      setWizardDraft(draftFromDetail(detail, [defaultModel, ...BASE_MODEL_OPTIONS]));
      setWizardIsNew(false);
      setOriginalName(row.name);
      setMode("wizard");
    } catch (e) {
      setListError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const saveRegister = async () => {
    if (!wizardDraft) return;
    setSaving(true);
    setSubmitError(null);
    try {
      let sampleInput: Record<string, unknown> | null;
      try {
        sampleInput = parseSampleInput(wizardDraft.sampleInput);
      } catch (e) {
        setSubmitError(`Sample input is not valid JSON: ${e instanceof Error ? e.message : e}`);
        return;
      }

      if (wizardIsNew) {
        await createAgent(toCreateRequest(wizardDraft));
      } else {
        const patch: UpdateAgentRequest = {
          system_prompt: wizardDraft.systemPrompt,
          description: wizardDraft.description,
          model: resolvedModel(wizardDraft),
          temperature: wizardDraft.temperature,
          tools: wizardDraft.tools,
          feeds: wizardDraft.feeds,
          card: toCardSpec(wizardDraft),
          sample_input: sampleInput,
          // Omitted unless edited: the backend reads null as "leave the stored
          // output model alone", which avoids regenerating it from a lossy
          // reconstruction of its type annotations.
          output_fields: wizardDraft.outputFieldsTouched
            ? toFieldSpecs(wizardDraft.outputFields)
            : null,
        };
        await updateAgent(wizardDraft.name, patch);
      }

      // Registering supersedes any local draft under the same name.
      deleteDraft(wizardDraft.name);
      if (originalName && originalName !== wizardDraft.name) deleteDraft(originalName);
      setDrafts(listDrafts());

      setSavedBanner({
        name: wizardDraft.name,
        registered: true,
        sampleInput: wizardDraft.sampleInput,
      });
      setMode("list");
      onAgentsChanged();
    } catch (e) {
      setSubmitError(e instanceof ApiError ? `HTTP ${e.status} — ${e.detail}` : String(e));
    } finally {
      setSaving(false);
    }
  };

  const saveAsDraft = () => {
    if (!wizardDraft) return;
    saveDraft(wizardDraft, originalName);
    setDrafts(listDrafts());
    setSavedBanner({ name: wizardDraft.name, registered: false, sampleInput: "" });
    setMode("list");
  };

  const removeAgent = async (row: ListRow, confirmCore: boolean) => {
    if (row.isDraft) {
      deleteDraft(row.name);
      setDrafts(listDrafts());
      setDeleteConfirm(null);
      return;
    }
    try {
      await deleteAgent(row.name, confirmCore);
      setDeleteConfirm(null);
      setCoreDeleteConfirm(null);
      onAgentsChanged();
    } catch (e) {
      // 409 is the backend's core-agent gate: it wants a second, explicit
      // confirmation before removing something that ships with agent-kit.
      if (e instanceof ApiError && e.status === 409) {
        setDeleteConfirm(null);
        setCoreDeleteConfirm(row.name);
      } else {
        setListError(e instanceof ApiError ? e.detail : String(e));
        setDeleteConfirm(null);
      }
    }
  };

  const duplicate = async (row: ListRow) => {
    const taken = new Set(rows.map((r) => r.name));
    let candidate = `${row.name}_copy`;
    for (let i = 2; taken.has(candidate); i += 1) candidate = `${row.name}_copy${i}`;
    try {
      await duplicateAgent(row.name, candidate);
      onAgentsChanged();
    } catch (e) {
      setListError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  const runQueue = async () => {
    setProcessing(true);
    setQueueAck(null);
    try {
      const result = await processRespecQueue();
      setQueueAck(
        result.resynthesized.length
          ? `Respec complete — ${result.resynthesized.join(", ")} traits refreshed.`
          : `Processed ${result.processed}; ${result.still_pending.length} still pending (the GM may be unavailable).`,
      );
      await loadGm();
    } catch (e) {
      setQueueAck(e instanceof ApiError ? `Failed — ${e.detail}` : String(e));
    } finally {
      setProcessing(false);
    }
  };

  const resolveSuggestion = async (id: number, approve: boolean) => {
    try {
      if (approve) {
        await approveSuggestion(id);
        // Approval applies the prompt through the normal builder update path,
        // so the agent's stored definition changed.
        onAgentsChanged();
      } else {
        await rejectSuggestion(id);
      }
      await loadGm();
    } catch (e) {
      setListError(e instanceof ApiError ? e.detail : String(e));
    }
  };

  if (mode === "classBuilder") {
    return (
      <div className="ak-screen">
        <ClassBuilder
          onSaved={(created) => {
            setClasses((cs) => [...cs.filter((c) => c.name !== created.name), created]);
            setWizardDraft((d) => (d && !d.mainClass ? { ...d, mainClass: created.name } : d));
            setMode("wizard");
          }}
          onCancel={() => setMode("wizard")}
        />
      </div>
    );
  }

  if (mode === "wizard" && wizardDraft) {
    return (
      <div className="ak-screen">
        <AgentWizard
          draft={wizardDraft}
          setDraft={(update) => setWizardDraft((d) => (d ? update(d) : d))}
          isNew={wizardIsNew}
          originalName={originalName}
          existingNames={rows.map((r) => r.name)}
          classes={classes}
          tools={tools}
          defaultModel={defaultModel}
          submitError={submitError}
          saving={saving}
          onSaveRegister={() => void saveRegister()}
          onSaveDraft={saveAsDraft}
          onCancel={() => setMode("list")}
          onOpenClassBuilder={() => setMode("classBuilder")}
        />
      </div>
    );
  }

  return (
    <div className="ak-screen">
      <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 920 }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 16,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <h1 className="ak-screen-title">Builder</h1>
            <p className="ak-screen-sub">
              Create, edit and register agents — output schema and class assignment, no YAML by
              hand.
            </p>
          </div>
          <button
            type="button"
            className="btn btn-primary blueprint"
            style={{ flex: "none" }}
            onClick={openNewAgent}
          >
            <Corners />+ New Agent
          </button>
        </div>

        {listError && <div className="ak-error-box">{listError}</div>}

        {savedBanner && (
          <div className="ak-saved-banner blueprint">
            <Corners />
            <span style={{ fontSize: 13 }}>
              {savedBanner.registered
                ? `${savedBanner.name} registered.`
                : `${savedBanner.name} saved as a draft — it lives in this browser until you register it.`}
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}>
              {savedBanner.registered && (
                <button
                  type="button"
                  className="btn btn-primary blueprint"
                  onClick={() => onRunAgent(savedBanner.name, savedBanner.sampleInput || undefined)}
                >
                  <Corners />
                  Run this agent
                </button>
              )}
              <button
                type="button"
                className="btn btn-ghost"
                style={{ fontSize: 12 }}
                onClick={() => setSavedBanner(null)}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {rows.map((row) => (
            <div key={row.name} className="ak-panel blueprint">
              <Corners />
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 14,
                }}
              >
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}
                >
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
                  >
                    <span
                      style={{
                        fontFamily: "var(--font-heading)",
                        fontWeight: 600,
                        fontSize: 17,
                        letterSpacing: "0.03em",
                        textTransform: "uppercase",
                      }}
                    >
                      {row.name}
                    </span>
                    {row.isCore && <span className="tag tag-outline">Core Demo Agent</span>}
                    {row.isDraft && <span className="tag tag-neutral">Draft</span>}
                  </div>
                  <span style={{ fontSize: 12.5, opacity: 0.65 }}>{row.description}</span>
                  <span className="ak-mono" style={{ fontSize: 11, opacity: 0.5 }}>
                    {row.metaLine}
                  </span>
                </div>

                {coreDeleteConfirm === row.name ? (
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}
                  >
                    <span style={{ fontSize: 12, color: "#a03d33", maxWidth: 260 }}>
                      {row.name} ships with agent-kit. Delete it anyway?
                    </span>
                    <button
                      type="button"
                      className="btn btn-secondary blueprint"
                      style={{
                        fontSize: 12,
                        padding: "4px 10px",
                        borderColor: "#a03d33",
                        color: "#a03d33",
                      }}
                      onClick={() => void removeAgent(row, true)}
                    >
                      <Corners />
                      Delete anyway
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      style={{ fontSize: 12 }}
                      onClick={() => setCoreDeleteConfirm(null)}
                    >
                      Cancel
                    </button>
                  </div>
                ) : deleteConfirm === row.name ? (
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8, flex: "none" }}
                  >
                    <span style={{ fontSize: 12, color: "#a03d33" }}>Delete {row.name}?</span>
                    <button
                      type="button"
                      className="btn btn-secondary blueprint"
                      style={{
                        fontSize: 12,
                        padding: "4px 10px",
                        borderColor: "#a03d33",
                        color: "#a03d33",
                      }}
                      onClick={() => void removeAgent(row, false)}
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
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 6, flex: "none" }}
                  >
                    {!row.isDraft && (
                      <button
                        type="button"
                        className="btn btn-secondary blueprint"
                        style={{ fontSize: 12, padding: "4px 10px" }}
                        onClick={() => onRunAgent(row.name)}
                      >
                        <Corners />
                        Run
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-secondary blueprint"
                      style={{ fontSize: 12, padding: "4px 10px" }}
                      onClick={() => void openEdit(row)}
                    >
                      <Corners />
                      Edit
                    </button>
                    {!row.isDraft && (
                      <button
                        type="button"
                        className="btn btn-ghost"
                        style={{ fontSize: 12 }}
                        onClick={() => void duplicate(row)}
                      >
                        Duplicate
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-ghost"
                      style={{ fontSize: 12, color: "#a03d33" }}
                      onClick={() => setDeleteConfirm(row.name)}
                    >
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* Respec queue */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 10,
            borderTop: "1px solid var(--color-neutral-300)",
            paddingTop: 20,
          }}
        >
          <div className="ak-kicker">Respec Queue</div>
          <div className="ak-panel blueprint" style={{ gap: 12 }}>
            <Corners />
            {queue.length === 0 && (
              <span style={{ fontSize: 12.5, opacity: 0.55 }}>
                Nothing pending — all agents' traits are in sync with recent grading.
              </span>
            )}
            {queue.map((entry) => (
              <div
                key={entry.agent_name}
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}
                >
                  <span className="ak-mono" style={{ fontSize: 13, fontWeight: 600 }}>
                    {entry.agent_name}
                  </span>
                  <span style={{ fontSize: 12, opacity: 0.6 }}>
                    Stat bands changed to <span className="ak-mono">{entry.band_signature}</span>
                    {entry.pending_since
                      ? ` — pending since ${new Date(entry.pending_since).toLocaleString()}`
                      : ""}
                  </span>
                </div>
                <span className="ak-respec-badge" style={{ flex: "none" }}>
                  Queued
                </span>
              </div>
            ))}
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <button
                type="button"
                className="btn btn-primary blueprint"
                onClick={() => void runQueue()}
                disabled={processing || queue.length === 0}
              >
                <Corners />
                {processing ? "Processing…" : "Process Queue"}
              </button>
              {queueAck && <span className="ak-ok-text">{queueAck}</span>}
            </div>
          </div>
        </div>

        {/* GM suggestions */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="ak-kicker">GM Suggestions</div>
          {suggestions.length === 0 && (
            <div className="ak-panel blueprint">
              <Corners />
              <span style={{ fontSize: 12.5, opacity: 0.55 }}>
                No pending prompt suggestions.
              </span>
            </div>
          )}
          {suggestions.map((s) => {
            const shared = commonPrefixLength(s.current_system_prompt, s.suggested_system_prompt);
            return (
              <div key={s.id} className="ak-panel blueprint" style={{ padding: "16px 18px", gap: 12 }}>
                <Corners />
                <div
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    justifyContent: "space-between",
                    gap: 12,
                  }}
                >
                  <span className="ak-mono" style={{ fontSize: 14, fontWeight: 600 }}>
                    {s.agent_name}
                  </span>
                  <span style={{ fontSize: 11, opacity: 0.5 }}>system prompt suggestion</span>
                </div>
                <p style={{ margin: 0, fontSize: 12.5, opacity: 0.65, lineHeight: 1.5 }}>
                  {s.rationale}
                </p>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <div className="ak-kicker-xs">Current</div>
                    <pre className="ak-snippet" style={{ opacity: 0.8 }}>
                      {s.current_system_prompt}
                    </pre>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <div className="ak-kicker-xs">Suggested</div>
                    <pre className="ak-snippet">
                      {s.suggested_system_prompt.slice(0, shared)}
                      <mark
                        style={{
                          background: "var(--color-accent-100)",
                          color: "var(--color-accent-800)",
                          padding: "1px 2px",
                        }}
                      >
                        {s.suggested_system_prompt.slice(shared)}
                      </mark>
                    </pre>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-secondary blueprint"
                    style={{ fontSize: 12, padding: "4px 10px" }}
                    onClick={() => void resolveSuggestion(s.id, true)}
                  >
                    <Corners />
                    Approve
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    style={{ fontSize: 12 }}
                    onClick={() => void resolveSuggestion(s.id, false)}
                  >
                    Reject
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
