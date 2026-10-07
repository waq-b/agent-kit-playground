import { describe, expect, it } from "vitest";

import { blankDraft, blankOutputField, validateDraft } from "./wizard";

/**
 * Refinement Phase 3, Task 11: wizard validation, including the input-model
 * editor from Task 3. This is the client-side gate before a create/update
 * request is even sent — a regression here means a bad agent save either
 * gets silently accepted (data quality) or a good one gets silently blocked
 * (false-positive friction), and neither shows up as an obvious crash.
 */
describe("validateDraft", () => {
  it("requires an output field for both new and existing agents", () => {
    const draft = { ...blankDraft("qwen2.5:14b"), outputFields: [blankOutputField()] };
    const errors = validateDraft(draft, [], null, /* asDraft */ false, /* isNew */ true);
    expect(errors.fields).toMatch(/output field/i);
  });

  it("requires an input field for a *new* agent", () => {
    const draft = { ...blankDraft("qwen2.5:14b"), name: "weather" };
    draft.outputFields = [{ ...blankOutputField(), name: "summary" }];
    draft.inputFields = [blankOutputField()]; // untouched, still blank
    const errors = validateDraft(draft, [], null, false, true);
    expect(errors.inputFields).toMatch(/input field/i);
  });

  it("does NOT require an input field when editing an existing agent that never had one", () => {
    const draft = { ...blankDraft("qwen2.5:14b"), name: "hello", isCore: true };
    draft.outputFields = [{ ...blankOutputField(), name: "greeting" }];
    draft.inputFields = [blankOutputField()]; // still blank — hasInputModel: false
    draft.hasInputModel = false;
    const errors = validateDraft(draft, ["hello"], "hello", false, /* isNew */ false);
    expect(errors.inputFields).toBeUndefined();
  });

  it("still catches a malformed input row on an existing agent, even though input itself is optional", () => {
    const draft = { ...blankDraft("qwen2.5:14b"), name: "hello" };
    draft.outputFields = [{ ...blankOutputField(), name: "greeting" }];
    draft.inputFields = [
      { ...blankOutputField(), name: "name" },
      { ...blankOutputField(), name: "name" }, // duplicate
    ];
    const errors = validateDraft(draft, ["hello"], "hello", false, false);
    expect(errors.inputFieldRows).toBeDefined();
    expect(Object.values(errors.inputFieldRows ?? {})).toContain("Duplicate field name.");
  });

  it("a Save-as-draft skips the output/input field requirements entirely", () => {
    const draft = blankDraft("qwen2.5:14b"); // name still blank too, but that's a separate error
    draft.name = "wip_agent";
    const errors = validateDraft(draft, [], null, /* asDraft */ true, true);
    expect(errors.fields).toBeUndefined();
    expect(errors.inputFields).toBeUndefined();
  });

  it("rejects a name that collides with an existing agent, unless it's the one being edited", () => {
    const draft = { ...blankDraft("qwen2.5:14b"), name: "news" };
    const errors = validateDraft(draft, ["hello", "news"], "hello", true, false);
    expect(errors.name).toMatch(/already exists/i);

    const okErrors = validateDraft(draft, ["hello", "news"], "news", true, false);
    expect(okErrors.name).toBeUndefined();
  });
});
