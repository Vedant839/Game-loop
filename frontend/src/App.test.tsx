import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

const mockLecture = {
  id: "math_sample_lecture",
  duration_seconds: 300.0,
  video_url: "/media/math_sample_lecture.mp4",
  timing_config: { min_trigger_gap: 15.0, tolerance: 2.0 },
  transcript: [],
  interventions: [],
};

const mockLectureSummary = {
  id: "math_sample_lecture",
  duration_seconds: 300.0,
  video_url: "/media/math_sample_lecture.mp4",
  intervention_count: 0,
};

const mockSession = {
  session_id: "sess_123",
  lecture_id: "math_sample_lecture",
  version: 1,
  active_intervention_id: null,
  interventions: [],
};

const generatedIntervention = {
  id: "gen_int_1",
  trigger_time: 45.0,
  concept: "Balancing Equations",
  difficulty: "Medium",
  type: "single_choice",
  question: "A friend says you can add 3 to one side only. What should you test first?",
  options: [
    { id: "opt_a", text: "Whether both sides stay equal after the same operation." },
    { id: "opt_b", text: "Whether the numbers look smaller." },
    { id: "opt_c", text: "Whether the variable moves to the left." },
    { id: "opt_d", text: "Whether the equation has a plus sign." },
  ],
  correct_answer: "opt_a",
  correct_feedback: "Correct. Equality is preserved by doing the same thing to both sides.",
  incorrect_feedback: "Not quite. Focus on preserving equality on both sides.",
};

const generatedLecture = {
  ...mockLecture,
  interventions: [generatedIntervention],
};

const generatedSession = {
  ...mockSession,
  session_id: "sess_generated",
  interventions: [{ id: "gen_int_1", trigger_time: 45.0, state: "PENDING" }],
};

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("starts with the sample lecture when several videos are available", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url: string | URL | Request) => {
      const urlStr = url.toString();
      if (urlStr.includes("/api/health")) {
        return { ok: true, json: async () => ({ status: "ok" }) } as Response;
      }
      if (urlStr.includes("/api/lectures/math_sample_lecture")) {
        return { ok: true, json: async () => mockLecture } as Response;
      }
      if (urlStr.includes("/api/lectures/python_tutorial_for_beginners_pip_comments_types_basic_operations_pylenza_1")) {
        return { ok: true, json: async () => ({ ...mockLecture, id: "python_tutorial_for_beginners_pip_comments_types_basic_operations_pylenza_1" }) } as Response;
      }
      if (urlStr.includes("/api/lectures")) {
        return { ok: true, json: async () => [
          { id: "python_tutorial_for_beginners_pip_comments_types_basic_operations_pylenza_1", duration_seconds: 872.65, video_url: "/media/python_tutorial.mp4", intervention_count: 0 },
          { ...mockLectureSummary, id: "math_sample_lecture" },
        ] } as Response;
      }
      if (urlStr.includes("/api/sessions")) {
        return { ok: true, json: async () => mockSession } as Response;
      }
      return { ok: false } as Response;
    });

    render(<App />);

    const options = await screen.findAllByRole("option");
    expect(options[0]).toHaveValue("math_sample_lecture");
  });

  it("shows connected backend and loads lecture player on startup", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url: string | URL | Request) => {
      const urlStr = url.toString();
      if (urlStr.includes("/api/health")) {
        return { ok: true, json: async () => ({ status: "ok" }) } as Response;
      }
      if (urlStr.includes("/api/lectures/math_sample_lecture")) {
        return { ok: true, json: async () => mockLecture } as Response;
      }
      if (urlStr.includes("/api/lectures")) {
        return { ok: true, json: async () => [mockLectureSummary] } as Response;
      }
      if (urlStr.includes("/api/sessions")) {
        return { ok: true, json: async () => mockSession } as Response;
      }
      return { ok: false } as Response;
    });

    render(<App />);

    expect(await screen.findByText("Backend connected")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Lecture" })).toBeInTheDocument();
    expect(await screen.findByText("Length: 5m 0s")).toBeInTheDocument();
  });

  it("shows an unavailable state when the health request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network unavailable"));

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("network unavailable");
  });

  it("shows generated interventions as player checkpoints", async () => {
    let sessionRequestCount = 0;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (url: string | URL | Request, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes("/api/health")) {
        return { ok: true, json: async () => ({ status: "ok" }) } as Response;
      }
      if (urlStr.endsWith("/generate_interventions")) {
        return { ok: true, json: async () => generatedLecture } as Response;
      }
      if (urlStr.includes("/api/lectures/math_sample_lecture")) {
        return { ok: true, json: async () => mockLecture } as Response;
      }
      if (urlStr.includes("/api/lectures")) {
        return { ok: true, json: async () => [mockLectureSummary] } as Response;
      }
      if (urlStr.includes("/api/sessions") && init?.method === "POST") {
        sessionRequestCount += 1;
        return {
          ok: true,
          json: async () => (sessionRequestCount === 1 ? mockSession : generatedSession),
        } as Response;
      }
      return { ok: false } as Response;
    });

    render(<App />);

    const generateButton = await screen.findByRole("button", { name: /Generate Interventions/i });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);

    expect(await screen.findByText("Intervention checkpoints")).toBeInTheDocument();
    expect(await screen.findByText("Balancing Equations")).toBeInTheDocument();
    expect(await screen.findByText("PENDING")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Interactions: 1")).toBeInTheDocument());
  });

  it("keeps ingestion focused on video and content rather than school metadata", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url: string | URL | Request, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes("/api/health")) return { ok: true, json: async () => ({ status: "ok" }) } as Response;
      if (urlStr.includes("/api/lectures/math_sample_lecture")) return { ok: true, json: async () => mockLecture } as Response;
      if (urlStr.includes("/api/lectures")) return { ok: true, json: async () => [mockLectureSummary] } as Response;
      if (urlStr.includes("/api/sessions") && init?.method === "POST") return { ok: true, json: async () => mockSession } as Response;
      return { ok: false } as Response;
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Add video" }));
    expect(await screen.findByRole("heading", { name: "Create a lecture" })).toBeInTheDocument();
    expect(screen.getByLabelText("Video URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Checkpoint intensity")).toBeInTheDocument();
    expect(screen.queryByLabelText(/title|subject|grade|duration/i)).not.toBeInTheDocument();
  });
});
