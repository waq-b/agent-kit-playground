import { useState } from "react";

import { ApiError, createClass } from "../api/client";
import type { ClassSummary } from "../api/types";
import { Corners } from "../components/Blueprint";

interface Props {
  onSaved: (created: ClassSummary) => void;
  onCancel: () => void;
}

/**
 * Starter document.
 *
 * Matches `class_loader`'s v0.4 shape: every stat carries a value, prompt_effect
 * bands and a runtime_effect curve. A stat without all of those is not a stat —
 * it's a name with no behaviour behind it — and the loader rejects it.
 */
const TEMPLATE = `archivist:
  title: "Archivist"
  description: "A meticulous cataloguer who never loses a thread."
  stats:
    recall:
      value: 60
      prompt_effect:
        - label: low
          text: "Treats each request as if starting fresh, rarely citing prior context."
        - label: high
          text: "Confidently references specific past details and cross-checks against them."
      runtime_effect:
        retries: {at_0: 0.0, at_100: 2.0}
    precision:
      value: 55
      prompt_effect:
        - label: low
          text: "Accepts loose paraphrasing without pushback."
        - label: high
          text: "Insists on exact terminology and rejects ambiguous phrasing."
      runtime_effect:
        temperature: {at_0: 0.0, at_100: -0.2}
`;

const SCHEMA_REFERENCE = `<class_key>:
  title: string        # display name, e.g. "News Hound"
  description: string  # flavor line
  stats:
    <stat_key>:
      value: int       # 0–100 starting value
      prompt_effect:   # bands, ordered low → high
        - label: string
          text: string # behavior in this band
      runtime_effect:  # knob → curve across the 0–100 range
        <param>: {at_0: float, at_100: float}
                       # param is a runtime knob, e.g.
                       # temperature, retries, tool_timeout

A stat is only real once value, prompt_effect
and runtime_effect are all filled in — a name
and a description alone don't define behavior.

YAML or JSON are both accepted.`;

export function ClassBuilder({ onSaved, onCancel }: Props) {
  const [source, setSource] = useState(TEMPLATE);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      onSaved(await createClass(source));
    } catch (e) {
      // The server parses and validates the document — surfacing its message
      // verbatim is more useful than a second, weaker client-side parser.
      setError(e instanceof ApiError ? `HTTP ${e.status} — ${e.detail}` : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 1240 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <h1 className="ak-screen-title ak-sm">Class Builder</h1>
        <p className="ak-screen-sub">
          Classes are authored directly as structured data — a stat isn't just a name, it's a
          definition of how it changes the agent's prompt and runtime behavior.
        </p>
      </div>

      <div className="ak-note">
        Universal base stats — Accuracy, Insight, Speed, Reliability — are fixed and not edited
        here. This page is only for a class's bespoke stats.
      </div>

      {error && <div className="ak-error-box">{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 18, alignItems: "start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <label className="ak-kicker" htmlFor="class-source">
            class.yaml
          </label>
          <textarea
            id="class-source"
            className="ak-code-editor"
            spellCheck={false}
            value={source}
            onChange={(e) => setSource(e.target.value)}
          />
        </div>
        <div
          className="blueprint"
          style={{
            position: "relative",
            border: "1px solid var(--color-neutral-400)",
            padding: "16px 18px",
            display: "flex",
            flexDirection: "column",
            gap: 10,
            alignSelf: "start",
          }}
        >
          <Corners />
          <div className="ak-kicker">Schema reference</div>
          <pre
            className="ak-mono"
            style={{
              margin: 0,
              fontSize: 11.5,
              lineHeight: 1.65,
              whiteSpace: "pre-wrap",
              opacity: 0.8,
            }}
          >
            {SCHEMA_REFERENCE}
          </pre>
        </div>
      </div>

      <div className="ak-actions-row" style={{ marginTop: 4 }}>
        <button
          type="button"
          className="btn btn-primary blueprint"
          onClick={() => void save()}
          disabled={saving}
        >
          <Corners />
          {saving ? "Saving…" : "Save class"}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
