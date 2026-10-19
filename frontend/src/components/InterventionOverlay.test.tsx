import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import InterventionOverlay from "./InterventionOverlay";
import type { ActiveInterventionPayload, EvaluationResult } from "../types";

const mockSingleChoiceIntervention: ActiveInterventionPayload = {
  id: "int_1",
  trigger_time: 25.0,
  concept: "Degree of Linear Equations",
  difficulty: "Easy",
  type: "single_choice",
  question: "What is the degree of a linear equation in one variable?",
  options: [
    { id: "opt_a", text: "Degree 1" },
    { id: "opt_b", text: "Degree 2" },
  ],
  session_state: {
    session_id: "sess_1",
    lecture_id: "math_sample_lecture",
    version: 2,
    active_intervention_id: "int_1",
    interventions: [
      { id: "int_1", trigger_time: 25.0, state: "ACTIVE" },
    ],
  },
};

describe("InterventionOverlay", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders question and options with submit button disabled until option is selected", () => {
    const handleSubmit = vi.fn();
    const handleComplete = vi.fn();

    const { getByText, getByRole } = render(
      <InterventionOverlay
        intervention={mockSingleChoiceIntervention}
        onSubmit={handleSubmit}
        onFeedbackComplete={handleComplete}
      />
    );

    expect(getByText("What is the degree of a linear equation in one variable?")).toBeDefined();
    expect(getByText("Degree 1")).toBeDefined();
    expect(getByText("Degree 2")).toBeDefined();

    const submitBtn = getByRole("button", { name: "Submit Answer" }) as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);

    // Select option
    fireEvent.click(getByText("Degree 1"));
    expect(submitBtn.disabled).toBe(false);
  });

  it("submits selected answer and displays feedback result", async () => {
    const mockEvalResult: EvaluationResult = {
      is_correct: true,
      feedback: "Correct! A linear equation has degree 1.",
      submitted_answer: "opt_a",
      session_state: {
        session_id: "sess_1",
        lecture_id: "math_sample_lecture",
        version: 3,
        active_intervention_id: null,
        interventions: [
          { id: "int_1", trigger_time: 25.0, state: "COMPLETED" },
        ],
      },
    };

    const handleSubmit = vi.fn().mockResolvedValue(mockEvalResult);
    const handleComplete = vi.fn();

    const { getByText, getByRole, findByText } = render(
      <InterventionOverlay
        intervention={mockSingleChoiceIntervention}
        onSubmit={handleSubmit}
        onFeedbackComplete={handleComplete}
      />
    );

    fireEvent.click(getByText("Degree 1"));
    const submitBtn = getByRole("button", { name: "Submit Answer" });
    fireEvent.click(submitBtn);

    expect(await findByText("✓ Correct!")).toBeDefined();
    expect(await findByText("Correct! A linear equation has degree 1.")).toBeDefined();
  });

  it("handles predict_and_verify inquiry workflow: hypothesis lock then experiment submit", async () => {
    const mockInquiryIntervention: ActiveInterventionPayload = {
      id: "py_1",
      trigger_time: 65.0,
      concept: "List References",
      difficulty: "Medium",
      type: "predict_and_verify",
      question: "Predict what this code prints, then verify in sandbox.",
      options: [],
      hypothesis_prompt: "What will print(a) output?",
      hypothesis_options: [
        { id: "h_a", text: "[1, 2, 3] — a is unchanged" },
        { id: "h_b", text: "[1, 2, 3, 4] — a and b share reference" },
      ],
      sandbox_config: {
        environment: "python_wasm",
        initial_code: "a = [1, 2, 3]\nb = a\nb.append(4)\nprint(a)",
        test_cases: [
          { name: "Output includes 4", expected_output: "[1, 2, 3, 4]" },
        ],
        hints: ["b = a does not copy"],
      },
      session_state: {
        session_id: "sess_inq",
        lecture_id: "python_basics_lists",
        version: 2,
        active_intervention_id: "py_1",
        interventions: [{ id: "py_1", trigger_time: 65.0, state: "ACTIVE" }],
      },
      tier: 2,
    };

    const mockEvalResult: EvaluationResult = {
      is_correct: true,
      feedback: "Great job! Verified that b = a creates an alias.",
      submitted_answer: "h_b",
      session_state: {
        session_id: "sess_inq",
        lecture_id: "python_basics_lists",
        version: 3,
        active_intervention_id: null,
        interventions: [{ id: "py_1", trigger_time: 65.0, state: "COMPLETED" }],
      },
      tier: 2,
      mastery_delta: 0.15,
      suggested_next_tier: 3,
    };

    const handleSubmitExperiment = vi.fn().mockResolvedValue(mockEvalResult);
    const handleSubmit = vi.fn();
    const handleComplete = vi.fn();

    const { getByText, findByText, getByRole } = render(
      <InterventionOverlay
        intervention={mockInquiryIntervention}
        onSubmit={handleSubmit}
        onSubmitExperiment={handleSubmitExperiment}
        onFeedbackComplete={handleComplete}
      />
    );

    // 1. Observe & Hypothesize
    expect(getByText("Predict what this code prints, then verify in sandbox.")).toBeDefined();
    expect(getByText("What will print(a) output?")).toBeDefined();
    expect(getByText("[1, 2, 3, 4] — a and b share reference")).toBeDefined();

    // Select hypothesis
    fireEvent.click(getByText("[1, 2, 3, 4] — a and b share reference"));
    const lockBtn = getByText("Lock Hypothesis & Proceed to Experiment →");
    fireEvent.click(lockBtn);

    // 2. Experiment step
    expect(await findByText("Python Sandbox")).toBeDefined();
    expect(getByText("▶ Run Experiment")).toBeDefined();

    // Run experiment
    fireEvent.click(getByText("▶ Run Experiment"));
    expect(await findByText("Verification Checks:")).toBeDefined();

    // Submit conclusion
    const submitBtn = getByRole("button", { name: "Submit Conclusion & Verify" });
    fireEvent.click(submitBtn);

    expect(handleSubmitExperiment).toHaveBeenCalledTimes(1);
    expect(await findByText("✓ Verified & Correct!")).toBeDefined();
    expect(await findByText(/Great job! Verified that b = a creates an alias/)).toBeDefined();
  });
});

