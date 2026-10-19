import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

const mockLecture = {
  id: "math_sample_lecture",
  title: "Grade 9 Mathematics - Solving Linear Equations",
  subject: "Mathematics",
  grade: "Grade 9",
  duration_seconds: 300.0,
  video_url: "/media/math_sample_lecture.mp4",
  timing_config: { min_trigger_gap: 15.0, tolerance: 2.0 },
  transcript: [],
  interventions: [],
};

const mockLectureSummary = {
  id: "math_sample_lecture",
  title: "Grade 9 Mathematics - Solving Linear Equations",
  subject: "Mathematics",
  grade: "Grade 9",
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

  it("prefers the linear algebra lecture over the Grade 9 sample when both are available", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url: string | URL | Request) => {
      const urlStr = url.toString();
      if (urlStr.includes("/api/health")) {
        return { ok: true, json: async () => ({ status: "ok" }) } as Response;
      }
      if (urlStr.includes("/api/lectures/math_sample_lecture")) {
        return { ok: true, json: async () => mockLecture } as Response;
      }
      if (urlStr.includes("/api/lectures/linear_algebra_vectors")) {
        return { ok: true, json: async () => ({ ...mockLecture, id: "linear_algebra_vectors", title: "Grade 12 Mathematics - Introduction to Vectors and Linear Algebra", subject: "Linear Algebra", grade: "Grade 12" }) } as Response;
      }
      if (urlStr.includes("/api/lectures")) {
        return { ok: true, json: async () => [
          { id: "linear_algebra_vectors", title: "Grade 12 Mathematics - Introduction to Vectors and Linear Algebra", subject: "Linear Algebra", grade: "Grade 12", duration_seconds: 300.0, video_url: "/media/math_sample_lecture.mp4", intervention_count: 0 },
          { ...mockLectureSummary, id: "math_sample_lecture", title: "Grade 9 Mathematics - Solving Linear Equations" },
        ] } as Response;
      }
      if (urlStr.includes("/api/sessions")) {
        return { ok: true, json: async () => mockSession } as Response;
      }
      return { ok: false } as Response;
    });

    render(<App />);

    expect(await screen.findByRole("heading", { name: /Grade 12 Mathematics - Introduction to Vectors and Linear Algebra/i })).toBeInTheDocument();
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
    expect(await screen.findByText("Grade 9 Mathematics - Solving Linear Equations")).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByText("Interventions: 1")).toBeInTheDocument());
  });

  it("hides legacy lectures and shows an add-lecture form", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url: string | URL | Request, init?: RequestInit) => {
      const urlStr = url.toString();
      if (urlStr.includes("/api/health")) {
        return { ok: true, json: async () => ({ status: "ok" }) } as Response;
      }
      if (urlStr.includes("/api/lectures") && !urlStr.includes("/api/lectures/")) {
        if (init?.method === "POST") {
          return { ok: true, json: async () => ({
            id: "custom_lecture",
            title: "Custom Lecture",
            subject: "Linear Algebra",
            grade: "Grade 12",
            duration_seconds: 120,
            video_url: "/media/custom.mp4",
            timing_config: { min_trigger_gap: 15.0, tolerance: 2.0 },
            transcript: [{ start_time: 0, end_time: 120, text: "Welcome to custom lecture." }],
            interventions: [],
          }) } as Response;
        }
        return { ok: true, json: async () => [{
          id: "linear_algebra_vectors",
          title: "Grade 12 Mathematics - Introduction to Vectors and Linear Algebra",
          subject: "Linear Algebra",
          grade: "Grade 12",
          duration_seconds: 300,
          video_url: "/media/math_sample_lecture.mp4",
          intervention_count: 4,
          }, {
          id: "custom_lecture",
          title: "Custom Lecture",
          subject: "Linear Algebra",
          grade: "Grade 12",
          duration_seconds: 120,
          video_url: "/media/custom.mp4",
          intervention_count: 0,
        }] } as Response;
      }
      if (urlStr.includes("/api/lectures/linear_algebra_vectors")) {
        return { ok: true, json: async () => ({ ...mockLecture, id: "linear_algebra_vectors", title: "Grade 12 Mathematics - Introduction to Vectors and Linear Algebra", subject: "Linear Algebra", grade: "Grade 12" }) } as Response;
      }
      if (urlStr.includes("/api/lectures/custom_lecture")) {
        return { ok: true, json: async () => ({
          id: "custom_lecture",
          title: "Custom Lecture",
          subject: "Linear Algebra",
          grade: "Grade 12",
          duration_seconds: 120,
          video_url: "/media/custom.mp4",
          timing_config: { min_trigger_gap: 15.0, tolerance: 2.0 },
          transcript: [{ start_time: 0, end_time: 120, text: "Welcome to custom lecture." }],
          interventions: [],
        }) } as Response;
      }
      if (urlStr.includes("/api/sessions") && init?.method === "POST") {
        return { ok: true, json: async () => mockSession } as Response;
      }
      return { ok: false } as Response;
    });

    render(<App />);

    expect(await screen.findByRole("option", { name: /Grade 12 Mathematics - Introduction to Vectors and Linear Algebra/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Grade 9/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add Lecture/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Add Lecture/i }));
    fireEvent.change(screen.getByLabelText(/Lecture ID/i), { target: { value: "custom_lecture" } });
    fireEvent.change(screen.getByLabelText(/Lecture Title/i), { target: { value: "Custom Lecture" } });
    fireEvent.change(screen.getByLabelText(/Subject/i), { target: { value: "Linear Algebra" } });
    fireEvent.change(screen.getByLabelText(/Grade/i), { target: { value: "Grade 12" } });
    fireEvent.change(screen.getByLabelText(/Duration/i), { target: { value: "120" } });
    fireEvent.change(screen.getByLabelText(/Video URL/i), { target: { value: "/media/custom.mp4" } });
    fireEvent.change(screen.getByLabelText(/Transcript/i), { target: { value: JSON.stringify([{ start_time: 0, end_time: 30, text: "Welcome to custom lecture." }]) } });
    fireEvent.click(screen.getByRole("button", { name: /Create Lecture/i }));

    expect(await screen.findByText("Custom Lecture")).toBeInTheDocument();
  });
});
