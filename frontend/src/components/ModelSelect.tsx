import { useState } from "react";

import type { ModelOption } from "../lib/models";
import { Corners } from "./Blueprint";

interface Props {
  id?: string;
  options: ModelOption[];
  value: string;
  onChange: (value: string) => void;
}

/**
 * A model dropdown that gates frontier picks behind a confirmation.
 *
 * Picking a local model applies immediately, same as any other select. Picking
 * a frontier one does not — the underlying value stays put, a banner explains
 * what's about to happen and where, and only Confirm actually calls `onChange`.
 * Cancel (or picking something else first) discards it with no side effect.
 *
 * Used everywhere a model is chosen — Settings' two model fields and the
 * Builder wizard's — so this confirmation is the same regardless of which
 * screen it started from.
 */
export function ModelSelect({ id, options, value, onChange }: Props) {
  const [pending, setPending] = useState<ModelOption | null>(null);

  const handleSelect = (next: string) => {
    const option = options.find((o) => o.value === next);
    if (option?.kind === "frontier") {
      setPending(option);
      return;
    }
    setPending(null);
    onChange(next);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <select id={id} className="input" value={value} onChange={(e) => handleSelect(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
            {o.kind === "frontier" ? " (frontier)" : ""}
          </option>
        ))}
      </select>
      {pending && (
        <div
          className="blueprint"
          style={{
            position: "relative",
            border: "1px solid #c9a227",
            background: "#fbf3d9",
            padding: "10px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <Corners />
          <span style={{ fontSize: 12.5, color: "#6b5220", lineHeight: 1.5 }}>
            <strong>{pending.label}</strong> is a frontier model — running it sends data to{" "}
            <span className="ak-mono">{pending.baseUrl}</span>, outside your local machine. Use it?
          </span>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="btn btn-secondary blueprint"
              style={{ fontSize: 12, padding: "4px 10px" }}
              onClick={() => {
                onChange(pending.value);
                setPending(null);
              }}
            >
              <Corners />
              Confirm
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              style={{ fontSize: 12 }}
              onClick={() => setPending(null)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
