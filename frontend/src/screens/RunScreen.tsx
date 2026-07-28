import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, getSampleInput, gradeAgent, runAgent } from "../api/client";
import type { AgentSummary, GradeAction, RunResponse } from "../api/types";
import { Corners } from "../components/Blueprint";
import { formatTiming, XP_PER_LEVEL, xpIntoLevel } from "../lib/format";

interface Props {
  agents: AgentSummary[] | null;
  loadError: string | null;
  onRetry: () => void;
  selected: string | null;
  onSelect: (name: string) => void;
  drafts: Record<string, string>;
  setDrafts: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  onGraded: () => void;
}

const EMPTY_DRAFT = "{\n  \n}";

export function RunScreen({
  agents,
  loadError,
  onRetry,
  selected,
  onSelect,
  drafts,
  setDrafts,
  onGraded,
}: Props) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timingMs, setTimingMs] = useState<number | null>(null);
  const [jsonHint, setJsonHint] = useState<string | null>(null);
  const [promptOpen, setPromptOpen] = useState(false);
  const [responseOpen, setResponseOpen] = useState(false);
  const [grading, setGrading] = useState(false);
  const [gradeAck, setGradeAck] = useState<string | null>(null);
  const [gradeError, setGradeError] = useState<string | null>(null);
  /** `implicit_view` is worth XP once per run, not once per disclosure toggle. */
  const implicitViewSent = useRef(false);

  const selectedAgent = agents?.find((a) => a.name === selected) ?? null;
  const draft = selected ? (drafts[selected] ?? "") : "";

  // Seed the input box from the agent's own sample input the first time it is
  // selected. The design hardcoded examples for hello/news; the real source is
  // whatever the builder saved alongside the agent.
  useEffect(() => {
    if (!selected || drafts[selected] !== undefined) return;
    let cancelled = false;
    setDrafts((d) => (d[selected] === undefined ? { ...d, [selected]: EMPTY_DRAFT } : d));
    void getSampleInput(selected)
      .then((sample) => {
        if (cancelled || !sample) return;
        setDrafts((d) => ({ ...d, [selected]: JSON.stringify(sample, null, 2) }));
      })
      .catch(() => {
        /* no sample input is a normal state — leave the empty object */
      });
    return () => {
      cancelled = true;
    };
  }, [selected, drafts, setDrafts]);

  // Reset per-run output whenever the selection changes.
  useEffect(() => {
    setResult(null);
    setError(null);
    setTimingMs(null);
    setJsonHint(null);
    setGradeAck(null);
    setGradeError(null);
    implicitViewSent.current = false;
  }, [selected]);

  const run = useCallback(async () => {
    if (!selected || running) return;
    let input: Record<string, unknown>;
    try {
      input = JSON.parse(draft || "");
    } catch (e) {
      setJsonHint(`Not valid JSON: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    setRunning(true);
    setError(null);
    setJsonHint(null);
    const started = performance.now();
    try {
      const data = await runAgent(selected, input);
      setResult(data);
      setTimingMs(Math.round(performance.now() - started));
      setGradeAck(null);
      setGradeError(null);
      implicitViewSent.current = false;
    } catch (e) {
      setResult(null);
      if (e instanceof ApiError && e.status === 0) {
        setTimingMs(null);
        setError(`Request failed: ${e.detail}\nIs the server running at ${location.origin}?`);
      } else if (e instanceof ApiError) {
        setTimingMs(Math.round(performance.now() - started));
        setError(`HTTP ${e.status} — ${e.detail}`);
      } else {
        setTimingMs(null);
        setError(String(e));
      }
    } finally {
      setRunning(false);
    }
  }, [selected, running, draft]);

  const grade = useCallback(
    async (action: GradeAction) => {
      if (!selected || grading) return;
      setGrading(true);
      setGradeAck(null);
      setGradeError(null);
      try {
        const data = await gradeAgent(selected, {
          action,
          tool_used: result?.tools_used?.[0] ?? null,
        });
        const sign = data.xp_delta >= 0 ? "+" : "";
        const inLevel = xpIntoLevel(data.new_xp);
        let ack = data.leveled_up
          ? `▲ Level up! Now LV ${data.new_level} · ${sign}${data.xp_delta} XP`
          : `${sign}${data.xp_delta} XP · ${inLevel}/${XP_PER_LEVEL} → LV ${data.new_level + 1}`;
        // Surfaced here so a respec triggered by this grade is visible where it
        // happened, rather than only as a badge on the Roster later.
        if (data.respec_processed) ack += " · traits re-synthesized";
        else if (data.respec_queued) ack += " · queued for respec";
        setGradeAck(ack);
        onGraded();
      } catch (e) {
        setGradeError(e instanceof ApiError ? `HTTP ${e.status} — ${e.detail}` : String(e));
      } finally {
        setGrading(false);
      }
    },
    [selected, grading, result, onGraded],
  );

  /** Reading the raw prompt/response counts as engagement worth a little XP. */
  const sendImplicitView = useCallback(() => {
    if (implicitViewSent.current || !result) return;
    implicitViewSent.current = true;
    void grade("implicit_view");
  }, [grade, result]);

  const formatInput = () => {
    try {
      const pretty = JSON.stringify(JSON.parse(draft || ""), null, 2);
      setJsonHint(null);
      if (selected) setDrafts((d) => ({ ...d, [selected]: pretty }));
    } catch (e) {
      setJsonHint(`Not valid JSON: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="ak-run-layout">
      <aside className="ak-sidebar">
        <div className="ak-kicker" style={{ padding: "0 2px" }}>
          Agents
        </div>
        {agents === null && (
          <div style={{ fontSize: 12.5, opacity: 0.5, padding: "4px 2px" }}>Loading agents…</div>
        )}
        {loadError && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 10,
              fontSize: 12.5,
              padding: "4px 2px",
            }}
          >
            <div style={{ color: "#a03d33", whiteSpace: "pre-wrap" }}>{loadError}</div>
            <button
              type="button"
              className="btn btn-secondary blueprint"
              onClick={onRetry}
              style={{ alignSelf: "flex-start" }}
            >
              <Corners />
              Retry
            </button>
          </div>
        )}
        {(agents ?? []).map((agent) => (
          <button
            key={agent.name}
            type="button"
            className="ak-agent-item blueprint"
            aria-pressed={agent.name === selected}
            onClick={() => onSelect(agent.name)}
          >
            <Corners />
            <span
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
              }}
            >
              <span className="ak-agent-name">{agent.name}</span>
              {agent.name === selected && (
                <span className="tag tag-accent" style={{ flex: "none" }}>
                  Active
                </span>
              )}
            </span>
            <span style={{ fontSize: 12, lineHeight: 1.45, opacity: 0.65 }}>
              {agent.description}
            </span>
          </button>
        ))}
      </aside>

      <main
        style={{
          overflowY: "auto",
          padding: "20px 24px 40px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          minWidth: 0,
        }}
      >
        <div className="ak-blurb">
          Built-in testing utility for exercising agents directly during development — not a
          consumer app. Real consumption happens through each agent's own API, from separate tools
          built independently.
        </div>

        {!selectedAgent && agents !== null && !loadError && (
          <div style={{ fontSize: 13, opacity: 0.5, paddingTop: 8 }}>Select an agent to run it.</div>
        )}

        {selectedAgent && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 860 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <h1 className="ak-screen-title">{selectedAgent.name}</h1>
              <p className="ak-screen-sub">{selectedAgent.description}</p>
            </div>

            <div className="field" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <label className="ak-kicker" htmlFor="agent-input">
                  Input · JSON object
                </label>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={formatInput}
                  style={{ fontSize: 12, padding: "2px 8px" }}
                >
                  Format
                </button>
              </div>
              <textarea
                id="agent-input"
                className="input ak-code-input"
                rows={8}
                spellCheck={false}
                value={draft}
                placeholder='{"name": "Alice"}'
                onChange={(e) =>
                  selected && setDrafts((d) => ({ ...d, [selected]: e.target.value }))
                }
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                    e.preventDefault();
                    void run();
                  }
                }}
              />
              {jsonHint && (
                <div className="ak-error-text ak-mono">{jsonHint}</div>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <button
                type="button"
                className="btn btn-primary blueprint"
                onClick={() => void run()}
                disabled={running}
              >
                <Corners />
                {running ? "Running…" : "Run"}
              </button>
              <span className="ak-mono" style={{ fontSize: 11.5, opacity: 0.45 }}>
                ⌘⏎ to run
              </span>
              {timingMs !== null && (
                <span
                  className="ak-mono"
                  style={{ fontSize: 11.5, opacity: 0.55, marginLeft: "auto" }}
                >
                  {formatTiming(timingMs)}
                </span>
              )}
            </div>

            {error && <div className="ak-error-box">{error}</div>}

            {result && (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div
                  className="blueprint"
                  style={{
                    position: "relative",
                    border: "1px solid var(--color-neutral-400)",
                    padding: "14px 16px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                >
                  <Corners />
                  <div className="ak-kicker">Output</div>
                  <pre className="ak-output-pre">{JSON.stringify(result.output, null, 2)}</pre>
                </div>

                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    borderTop: "1px solid var(--color-neutral-300)",
                  }}
                >
                  <button
                    type="button"
                    className="ak-disclosure"
                    onClick={() => {
                      setPromptOpen((v) => !v);
                      sendImplicitView();
                    }}
                  >
                    <span className="ak-chevron">{promptOpen ? "▾" : "▸"}</span>Raw prompt
                  </button>
                  {promptOpen && <pre className="ak-disclosure-body">{result.raw_prompt}</pre>}
                  <button
                    type="button"
                    className="ak-disclosure"
                    onClick={() => {
                      setResponseOpen((v) => !v);
                      sendImplicitView();
                    }}
                  >
                    <span className="ak-chevron">{responseOpen ? "▾" : "▸"}</span>Raw response
                  </button>
                  {responseOpen && <pre className="ak-disclosure-body">{result.raw_response}</pre>}
                </div>

                <div
                  style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
                >
                  <span className="ak-kicker" style={{ marginRight: 2 }}>
                    Grade
                  </span>
                  <button
                    type="button"
                    className="btn btn-secondary btn-icon blueprint"
                    aria-label="Thumbs up"
                    onClick={() => void grade("thumbs_up")}
                    disabled={grading}
                    style={{ width: 30, height: 30 }}
                  >
                    <Corners />
                    <ThumbsUpIcon />
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-icon blueprint"
                    aria-label="Thumbs down"
                    onClick={() => void grade("thumbs_down")}
                    disabled={grading}
                    style={{ width: 30, height: 30 }}
                  >
                    <Corners />
                    <ThumbsDownIcon />
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary blueprint"
                    onClick={() => void grade("more_like_this")}
                    disabled={grading}
                    style={{ fontSize: 12, padding: "4px 10px" }}
                  >
                    <Corners />
                    More like this
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary blueprint"
                    onClick={() => void grade("less_like_this")}
                    disabled={grading}
                    style={{ fontSize: 12, padding: "4px 10px" }}
                  >
                    <Corners />
                    Less like this
                  </button>
                  {gradeAck && <span className="ak-ok-text">{gradeAck}</span>}
                  {gradeError && <span className="ak-error-text ak-mono">{gradeError}</span>}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function ThumbsUpIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M7 10v12" />
      <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
    </svg>
  );
}

function ThumbsDownIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M17 14V2" />
      <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
    </svg>
  );
}
