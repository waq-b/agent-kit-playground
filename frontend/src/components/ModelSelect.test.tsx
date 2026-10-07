import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ModelOption } from "../lib/models";
import { ModelSelect } from "./ModelSelect";

const OPTIONS: ModelOption[] = [
  { value: "qwen2.5:14b", label: "qwen2.5:14b", kind: "local", baseUrl: null },
  { value: "gpt-4o", label: "GPT-4o", kind: "frontier", baseUrl: "https://api.openai.com/v1" },
];

/**
 * Refinement Phase 3, Task 11: the frontier confirm-gate. If this fails
 * open — a frontier pick applying immediately, no confirmation shown — a
 * user's data leaves their machine without them having agreed to it. This is
 * the single highest-consequence UI behaviour in the app, so it gets its own
 * test rather than relying on incidental coverage elsewhere.
 */
describe("ModelSelect", () => {
  it("applies a local pick immediately, with no confirmation banner", () => {
    const onChange = vi.fn();
    render(<ModelSelect options={OPTIONS} value="gpt-4o" onChange={onChange} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "qwen2.5:14b" } });

    expect(onChange).toHaveBeenCalledWith("qwen2.5:14b");
    expect(screen.queryByText(/frontier model/i)).not.toBeInTheDocument();
  });

  it("does NOT call onChange the instant a frontier model is picked", () => {
    const onChange = vi.fn();
    render(<ModelSelect options={OPTIONS} value="qwen2.5:14b" onChange={onChange} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "gpt-4o" } });

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/frontier model/i)).toBeInTheDocument();
    expect(screen.getByText(/api\.openai\.com/)).toBeInTheDocument();
  });

  it("only calls onChange once the user explicitly clicks Confirm", () => {
    const onChange = vi.fn();
    render(<ModelSelect options={OPTIONS} value="qwen2.5:14b" onChange={onChange} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "gpt-4o" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));

    expect(onChange).toHaveBeenCalledWith("gpt-4o");
  });

  it("Cancel discards the pending pick with no call to onChange", () => {
    const onChange = vi.fn();
    render(<ModelSelect options={OPTIONS} value="qwen2.5:14b" onChange={onChange} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "gpt-4o" } });
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByText(/frontier model/i)).not.toBeInTheDocument();
  });
});
