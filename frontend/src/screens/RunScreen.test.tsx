import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentSummary, GradeResponse, RunResponse } from "../api/types";
import { RunScreen } from "./RunScreen";

const { getSampleInput, gradeAgent, runAgent } = vi.hoisted(() => ({
  getSampleInput: vi.fn(),
  gradeAgent: vi.fn(),
  runAgent: vi.fn(),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getSampleInput, gradeAgent, runAgent };
});

const AGENTS: AgentSummary[] = [{ name: "hello", description: "Greets a person by name" }];

const RUN_RESULT: RunResponse = {
  output: { greeting: "Hello, Alice!" },
  raw_prompt: "p",
  raw_response: "r",
  tools_used: [],
};

function renderRunScreen() {
  let drafts: Record<string, string> = { hello: '{"name": "Alice"}' };
  const setDrafts = vi.fn((update: React.SetStateAction<Record<string, string>>) => {
    drafts = typeof update === "function" ? update(drafts) : update;
  });
  const onGraded = vi.fn();
  const utils = render(
    <RunScreen
      agents={AGENTS}
      loadError={null}
      onRetry={vi.fn()}
      selected="hello"
      onSelect={vi.fn()}
      drafts={drafts}
      setDrafts={setDrafts}
      onGraded={onGraded}
    />,
  );
  return { ...utils, onGraded };
}

/**
 * Refinement Phase 3, Task 11: the grading flow. This is the only path that
 * feeds the entire character layer — XP, stat nudges, and (per Task 55's
 * `respec_queued`/`respec_processed` fields) respec triggers. A regression
 * here doesn't crash anything visible; a grade button that silently sends
 * the wrong action, or that fails to surface a respec trigger, would look
 * fine and just quietly corrupt an agent's character progress.
 */
describe("RunScreen grading", () => {
  beforeEach(() => {
    getSampleInput.mockReset().mockResolvedValue(null);
    gradeAgent.mockReset();
    runAgent.mockReset().mockResolvedValue(RUN_RESULT);
  });

  async function runThenGetGradeButtons() {
    renderRunScreen();
    fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
    await waitFor(() => expect(screen.getByText(/hello, alice/i)).toBeInTheDocument());
  }

  it("sends the exact grade action a button represents — thumbs up is thumbs_up, not any other action", async () => {
    gradeAgent.mockResolvedValue({
      xp_delta: 10, new_xp: 20, new_level: 1, leveled_up: false, stat_deltas: {},
      events_since_respec: 1, respec_queued: false, respec_processed: false,
    } satisfies GradeResponse);
    await runThenGetGradeButtons();

    fireEvent.click(screen.getByRole("button", { name: /thumbs up/i }));

    await waitFor(() => expect(gradeAgent).toHaveBeenCalledTimes(1));
    expect(gradeAgent).toHaveBeenCalledWith("hello", { action: "thumbs_up", tool_used: null });
  });

  it("surfaces the XP delta and resulting level from the response, not a generic 'done'", async () => {
    gradeAgent.mockResolvedValue({
      xp_delta: 10, new_xp: 20, new_level: 1, leveled_up: false, stat_deltas: {},
      events_since_respec: 1, respec_queued: false, respec_processed: false,
    } satisfies GradeResponse);
    await runThenGetGradeButtons();

    fireEvent.click(screen.getByRole("button", { name: /thumbs up/i }));

    await waitFor(() => expect(screen.getByText(/\+10 XP/)).toBeInTheDocument());
  });

  it("surfaces a respec trigger distinctly, so it isn't silently invisible until the Roster", async () => {
    gradeAgent.mockResolvedValue({
      xp_delta: -5, new_xp: 15, new_level: 1, leveled_up: false, stat_deltas: {},
      events_since_respec: 12, respec_queued: true, respec_processed: false,
    } satisfies GradeResponse);
    await runThenGetGradeButtons();

    fireEvent.click(screen.getByRole("button", { name: /thumbs down/i }));

    await waitFor(() => expect(screen.getByText(/queued for respec/i)).toBeInTheDocument());
  });

  it("calls onGraded (the roster/queue invalidation signal) after a successful grade", async () => {
    gradeAgent.mockResolvedValue({
      xp_delta: 6, new_xp: 26, new_level: 1, leveled_up: false, stat_deltas: {},
      events_since_respec: 2, respec_queued: false, respec_processed: false,
    } satisfies GradeResponse);
    const { onGraded } = await (async () => {
      const result = renderRunScreen();
      fireEvent.click(screen.getByRole("button", { name: /^run$/i }));
      await waitFor(() => expect(screen.getByText(/hello, alice/i)).toBeInTheDocument());
      return result;
    })();

    fireEvent.click(screen.getByRole("button", { name: /more like this/i }));

    await waitFor(() => expect(onGraded).toHaveBeenCalledTimes(1));
  });

  it("shows the server's error detail, not a silent failure, when grading fails", async () => {
    const { ApiError } = await vi.importActual<typeof import("../api/client")>("../api/client");
    gradeAgent.mockRejectedValue(new ApiError(422, "unknown grading action"));
    await runThenGetGradeButtons();

    fireEvent.click(screen.getByRole("button", { name: /thumbs up/i }));

    await waitFor(() => expect(screen.getByText(/unknown grading action/i)).toBeInTheDocument());
  });
});
