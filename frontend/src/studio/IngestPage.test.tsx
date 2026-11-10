import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import IngestPage from "./IngestPage";

vi.mock("../adapters/videoDuration", () => ({ readVideoDuration: vi.fn().mockResolvedValue(300) }));

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
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(lecture), { status: 201, headers: { "Content-Type": "application/json" } })
    );
    const onComplete = vi.fn();
    render(<IngestPage onComplete={onComplete} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Vectors have magnitude and direction." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(lecture));
    expect(screen.queryByLabelText(/title|subject|grade|duration/i)).not.toBeInTheDocument();
    const [, init] = fetchMock.mock.calls[0];
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
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(lecture), { status: 201, headers: { "Content-Type": "application/json" } })
    );
    const view = render(<IngestPage onComplete={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Default Gemini key (saved for future lectures)"), { target: { value: "default-gemini-key" } });
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Lecture transcript." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect((fetchMock.mock.calls[0][1]?.headers as Record<string, string>)["X-Gemini-Key"]).toBe("default-gemini-key");
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
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(lecture), { status: 201, headers: { "Content-Type": "application/json" } })
    );
    render(<IngestPage onComplete={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Creator token"), { target: { value: "creator-token" } });
    fireEvent.click(screen.getByLabelText("Use a different Gemini key for this lecture only"));
    fireEvent.change(screen.getByLabelText("Gemini key for this lecture"), { target: { value: "one-lecture-key" } });
    fireEvent.change(screen.getByLabelText("Video URL"), { target: { value: "https://example.com/video.mp4" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Lecture transcript." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect((fetchMock.mock.calls[0][1]?.headers as Record<string, string>)["X-Gemini-Key"]).toBe("one-lecture-key");
    expect(window.localStorage.getItem("gl_creator_gemini_key")).toBe("saved-default-key");
  });
});
