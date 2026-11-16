import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import IngestPage from "./IngestPage";

vi.mock("../adapters/videoDuration", () => ({ readVideoDuration: vi.fn().mockResolvedValue(300) }));

const preflightFixture = {
  windows: [{ start_s: 0, end_s: 30, words: 0, coverage: 0, verdict: "strong" as const }],
  speech_coverage: 0,
  longest_silent_stretch_s: 300,
  weak_windows: [],
  suitability: "unknown" as const,
  message: "No timestamped captions provided. Timed SRT/VTT captions give better placement.",
};

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

function mockApi(lecture: unknown, preflight = preflightFixture) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
    String(input).includes("/api/creator/ingest/preflight")
      ? jsonResponse(preflight)
      : jsonResponse(lecture, 201)
  );
}

describe("IngestPage", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("submits the video and transcript with automatically detected duration", async () => {
    const lecture = {
      id: "ingest_vectors",
      duration_seconds: 300, video_url: "https://example.com/video.mp4",
      timing_config: { min_trigger_gap: 15, tolerance: 2 }, transcript: [], interventions: [],
    };
    const fetchMock = mockApi(lecture);
    const onComplete = vi.fn();
    render(<IngestPage onComplete={onComplete} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Vectors have magnitude and direction." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));

    expect(await screen.findByTestId("review-list")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("continue-to-lecture"));
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(lecture));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/creator/ingest/preflight"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer creator-token" }),
      }),
    ));
    expect(screen.queryByLabelText(/title|subject|grade|duration/i)).not.toBeInTheDocument();
    const ingestCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/creator/ingest"));
    expect(ingestCall).toBeDefined();
    const [, init] = ingestCall!;
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer creator-token");
    expect(JSON.parse(String(init?.body))).toMatchObject({
      captions: "Vectors have magnitude and direction.", duration_seconds: 300,
    });
    expect(JSON.parse(String(init?.body))).not.toHaveProperty("title");
    expect(JSON.parse(String(init?.body))).not.toHaveProperty("subject");
    expect(JSON.parse(String(init?.body))).not.toHaveProperty("grade");
  });

  it("saves the default Gemini key for the next lecture", async () => {
    const lecture = {
      id: "ingest_saved_key",
      duration_seconds: 300, video_url: "https://example.com/video.mp4",
      timing_config: { min_trigger_gap: 15, tolerance: 2 }, transcript: [], interventions: [],
    };
    const fetchMock = mockApi(lecture);
    const view = render(<IngestPage onComplete={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Default Gemini key (saved for future lectures)"), { target: { value: "default-gemini-key" } });
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Lecture transcript." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const ingestCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/creator/ingest"));
    expect((ingestCall?.[1]?.headers as Record<string, string>)["X-Gemini-Key"]).toBe("default-gemini-key");
    expect(window.localStorage.getItem("gl_creator_gemini_key")).toBe("default-gemini-key");

    view.unmount();
    render(<IngestPage onComplete={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByLabelText("Default Gemini key (saved for future lectures)")).toHaveValue("default-gemini-key");
  });

  it("uses a lecture-only Gemini key without replacing the saved default", async () => {
    window.localStorage.setItem("gl_creator_gemini_key", "saved-default-key");
    const lecture = {
      id: "ingest_override_key",
      duration_seconds: 300, video_url: "https://example.com/video.mp4",
      timing_config: { min_trigger_gap: 15, tolerance: 2 }, transcript: [], interventions: [],
    };
    const fetchMock = mockApi(lecture);
    render(<IngestPage onComplete={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.click(screen.getByLabelText("Use a different Gemini key for this lecture only"));
    fireEvent.change(screen.getByLabelText("Gemini key for this lecture"), { target: { value: "one-lecture-key" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Lecture transcript." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const ingestCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/creator/ingest"));
    expect((ingestCall?.[1]?.headers as Record<string, string>)["X-Gemini-Key"]).toBe("one-lecture-key");
    expect(window.localStorage.getItem("gl_creator_gemini_key")).toBe("saved-default-key");
  });

  it("sends creator notes and chapter text with the ingest request", async () => {
    const lecture = {
      id: "ingest_context", duration_seconds: 300,
      video_url: "https://example.com/video.mp4", interventions: [],
      timing_config: { min_trigger_gap: 90, tolerance: 2 }, transcript: [],
    };
    const fetchMock = mockApi(lecture);
    const onComplete = vi.fn();
    render(<IngestPage onComplete={onComplete} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Transcript supports the concept." } });
    fireEvent.click(screen.getByTestId("toggle-context-panel"));
    fireEvent.change(screen.getByTestId("input-notes"), { target: { value: "Notes support the concept." } });
    fireEvent.change(screen.getByTestId("input-chapters"), { target: { value: "00:00 Introduction" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));

    expect(await screen.findByTestId("review-list")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("continue-to-lecture"));
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(lecture));
    const ingestCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/creator/ingest"));
    expect(JSON.parse(String(ingestCall?.[1]?.body))).toMatchObject({
      creator_context: { notes: "Notes support the concept.", chapters: "00:00 Introduction" },
    });
  });

  it("mounts the review list and applies one and bulk approvals after ingest", async () => {
    const flagged = {
      id: "cp_review", revision: 1, trigger_time: 120, concept: "A reviewed concept",
      difficulty: "Medium", type: "single_choice", question: "Which statement describes this concept?",
      options: [{ id: "a", text: "Supported behavior" }], correct_answer: "a",
      correct_feedback: "Correct", incorrect_feedback: "Try again", confidence: "medium",
      review_state: "needs_review", evidence: [{ source: "creator_context", quote: "verified creator quote" }],
    };
    const lecture = {
      id: "ingest_review", duration_seconds: 300,
      video_url: "https://example.com/video.mp4", interventions: [
        { ...flagged, id: "cp_auto", concept: "An automatic concept", confidence: "high", review_state: "auto" },
        flagged,
        { ...flagged, id: "cp_review2", concept: "Another reviewed concept" },
      ],
      timing_config: { min_trigger_gap: 90, tolerance: 2 }, transcript: [],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/creator/ingest/preflight")) return jsonResponse(preflightFixture);
      if (url.endsWith("/api/creator/ingest")) return jsonResponse(lecture, 201);
      if (url.endsWith("/checkpoints/cp_review/approve")) {
        return jsonResponse({ status: "approved", intervention: { ...flagged, review_state: "approved" } });
      }
      if (url.endsWith("/approve_flagged")) return jsonResponse({ approved_count: 1 });
      return jsonResponse({}, 404);
    });
    const onComplete = vi.fn();
    render(<IngestPage onComplete={onComplete} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Review evidence." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));

    expect(await screen.findByTestId("review-list")).toBeInTheDocument();
    expect(screen.getAllByText("[creator_context]")).toHaveLength(3);
    fireEvent.click(screen.getByTestId("btn-approve-cp_review"));
    expect(await screen.findByTestId("badge-state-cp_review")).toHaveTextContent("approved");
    expect(screen.getByTestId("badge-state-cp_review")).toHaveTextContent("approved");
    fireEvent.click(screen.getByTestId("btn-approve-all"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/approve_flagged"), expect.anything(),
    ));

    fireEvent.click(screen.getByTestId("continue-to-lecture"));
    await waitFor(() => expect(onComplete).toHaveBeenCalled());
    const completedLecture = onComplete.mock.calls[0][0];
    expect(completedLecture.interventions.find((item: { id: string }) => item.id === "cp_review").revision).toBe(1);
    expect(completedLecture.interventions.find((item: { id: string }) => item.id === "cp_review").review_state).toBe("approved");
  });

  it("does not block generation while preflight is still pending", async () => {
    const lecture = {
      id: "ingest_untimed", duration_seconds: 300,
      video_url: "https://example.com/video.mp4", interventions: [],
      timing_config: { min_trigger_gap: 90, tolerance: 2 }, transcript: [],
    };
    let releasePreflight!: () => void;
    const preflightPending = new Promise<void>((resolve) => { releasePreflight = resolve; });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/api/creator/ingest/preflight")) {
        await preflightPending;
        return jsonResponse(preflightFixture);
      }
      return jsonResponse(lecture, 201);
    });
    const onComplete = vi.fn();
    render(<IngestPage onComplete={onComplete} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Untimed transcript text." } });

    await screen.findByTestId("preflight-loading");
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));
    expect(await screen.findByTestId("review-list")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("continue-to-lecture"));
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(lecture));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/creator/ingest/preflight"),
      expect.objectContaining({ method: "POST" }),
    );

    releasePreflight();
  });

  it("shows the server hint for unknown untimed captions", async () => {
    const lecture = {
      id: "ingest_untimed", duration_seconds: 300,
      video_url: "https://example.com/video.mp4", interventions: [],
      timing_config: { min_trigger_gap: 90, tolerance: 2 }, transcript: [],
    };
    const fetchMock = mockApi(lecture);
    render(<IngestPage onComplete={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Untimed transcript text." } });

    expect(await screen.findByTestId("suitability-badge")).toHaveTextContent("unknown");
    expect(screen.getByTestId("preflight-message")).toHaveTextContent("Timed SRT/VTT captions give better placement");
    expect(screen.getByRole("button", { name: "Generate lecture" })).not.toBeDisabled();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/creator/ingest/preflight"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});
