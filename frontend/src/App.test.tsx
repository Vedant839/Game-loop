import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

  it("does not expose the removed transcript-direct generation action", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url: string | URL | Request, init?: RequestInit) => {
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
      if (urlStr.includes("/api/sessions") && init?.method === "POST") {
        return { ok: true, json: async () => mockSession } as Response;
      }
      return { ok: false } as Response;
    });

    render(<App />);

    await screen.findByRole("combobox", { name: "Select Lecture:" });
    expect(screen.queryByRole("button", { name: /Generate Interventions/i })).not.toBeInTheDocument();
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/generate_interventions"), expect.anything());
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
