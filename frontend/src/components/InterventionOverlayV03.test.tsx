import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import InterventionOverlay from "./InterventionOverlay";
import type {
  ActiveInterventionPayload,
  EvaluationResult,
  OpenEndedSubmissionResponse,
} from "../types";

const mockOpenEndedIntervention: ActiveInterventionPayload = {
  id: "q_open_1",
  trigger_time: 45.0,
  concept: "Geometric Proofs",
  difficulty: "Hard",
  type: "open_ended",
  question: "Explain why alternate interior angles are equal when two parallel lines are cut by a transversal.",
  options: [],
  policy: "skippable",
  resumption_policy: "immediate_optimistic",
  rubric: {
    key_concepts: ["transversal", "parallel lines", "rotation 180 degrees"],
    misconceptions: [
      {
        tag: "assume_perpendicular",
        description: "Assumes transversal is perpendicular",
        remediation: "Transversal can be at any non-zero angle",
      },
    ],
    reference_answer: "Rotating 180 degrees around the midpoint of the transversal maps the alternate interior angles directly onto each other.",
    passing_score: 0.6,
  },
  session_state: {
    session_id: "sess_v03",
    lecture_id: "geometry_proofs",
    version: 1,
    active_intervention_id: "q_open_1",
    interventions: [{ id: "q_open_1", trigger_time: 45.0, state: "ACTIVE" }],
  },
};

describe("InterventionOverlay V0.3 Enhancements", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders open-ended reasoning textarea and handles immediate optimistic submission", async () => {
    const handleOpenEndedSubmit = vi.fn().mockResolvedValue({
      submission_id: "sub_123",
      status: "pending",
      resumption_policy: "immediate_optimistic",
      formative_feedback: "Your reasoning was captured and submitted for background evaluation.",
      misconceptions_detected: [],
    } as OpenEndedSubmissionResponse);

    const handleComplete = vi.fn();

    const { getByText, getByPlaceholderText, getByRole } = render(
      <InterventionOverlay
        intervention={mockOpenEndedIntervention}
        onSubmit={vi.fn()}
        onSubmitOpenEnded={handleOpenEndedSubmit}
        onFeedbackComplete={handleComplete}
      />
    );

    expect(
      getByText("Explain why alternate interior angles are equal when two parallel lines are cut by a transversal.")
    ).toBeDefined();

    const textarea = getByPlaceholderText(
      "Explain your mathematical or conceptual reasoning step-by-step..."
    );
    const submitBtn = getByRole("button", { name: "Submit for Evaluation" }) as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);

    // Type explanation
    fireEvent.change(textarea, {
      target: { value: "A 180 degree rotation around the midpoint of the transversal segment maps alternate angles directly." },
    });
    expect(submitBtn.disabled).toBe(false);

    // Submit
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(handleOpenEndedSubmit).toHaveBeenCalledWith(
        "A 180 degree rotation around the midpoint of the transversal segment maps alternate angles directly."
      );
    });

    expect(
      getByText("Your reasoning was captured and submitted for background evaluation.")
    ).toBeDefined();
  });

  it("renders Skip Checkpoint button for skippable interventions and calls onSkip", async () => {
    const handleSkip = vi.fn().mockResolvedValue(undefined);
    const handleComplete = vi.fn();

    const { getByText, getByRole } = render(
      <InterventionOverlay
        intervention={mockOpenEndedIntervention}
        onSubmit={vi.fn()}
        onSkip={handleSkip}
        onFeedbackComplete={handleComplete}
      />
    );

    const skipBtn = getByRole("button", { name: "Skip Checkpoint" });
    expect(skipBtn).toBeDefined();

    fireEvent.click(skipBtn);

    await waitFor(() => {
      expect(handleSkip).toHaveBeenCalledTimes(1);
      expect(handleComplete).toHaveBeenCalledTimes(1);
    });
  });

  it("does not render Skip Checkpoint button when intervention policy is required", () => {
    const requiredIntervention: ActiveInterventionPayload = {
      ...mockOpenEndedIntervention,
      policy: "required",
    };

    const { queryByRole, getByText } = render(
      <InterventionOverlay
        intervention={requiredIntervention}
        onSubmit={vi.fn()}
        onFeedbackComplete={vi.fn()}
      />
    );

    expect(queryByRole("button", { name: "Skip Checkpoint" })).toBeNull();
    expect(getByText("Required")).toBeDefined();
  });

  it("offers self-assessment fallback when evaluation response times out", async () => {
    vi.useFakeTimers();

    const handleOpenEndedSubmit = vi.fn().mockResolvedValue({
      submission_id: "sub_slow",
      status: "evaluating",
      resumption_policy: "wait_for_result",
      misconceptions_detected: [],
    } as OpenEndedSubmissionResponse);

    const handleSelfAssess = vi.fn().mockResolvedValue(undefined);
    const handleComplete = vi.fn();

    const { getByPlaceholderText, getByRole, getByText } = render(
      <InterventionOverlay
        intervention={{ ...mockOpenEndedIntervention, resumption_policy: "wait_for_result" }}
        onSubmit={vi.fn()}
        onSubmitOpenEnded={handleOpenEndedSubmit}
        onSelfAssess={handleSelfAssess}
        onFeedbackComplete={handleComplete}
      />
    );

    const textarea = getByPlaceholderText(
      "Explain your mathematical or conceptual reasoning step-by-step..."
    );
    fireEvent.change(textarea, { target: { value: "Parallel lines and transversal rotation." } });

    const submitBtn = getByRole("button", { name: "Submit for Evaluation" });
    fireEvent.click(submitBtn);

    // Resolve submission promise microtask
    await Promise.resolve();

    // Fast forward past foreground evaluation timeout asynchronously
    await vi.advanceTimersByTimeAsync(5500);

    expect(getByText("Self-Assessment: Reference Rubric")).toBeDefined();
    expect(getByText("transversal")).toBeDefined();
    expect(getByText("rotation 180 degrees")).toBeDefined();

    const coveredBtn = getByRole("button", { name: "✓ Covered Key Concepts" });
    fireEvent.click(coveredBtn);

    await Promise.resolve();
    expect(handleSelfAssess).toHaveBeenCalledWith("sub_slow", true);

    vi.useRealTimers();
  });
});
