import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import IngestPage from "./IngestPage";

describe("IngestPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("submits video metadata and transcript to the creator ingest API", async () => {
    const lecture = {
      id: "ingest_vectors", title: "Vectors", subject: "Math", grade: "12",
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
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Vectors" } });
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "Math" } });
    fireEvent.change(screen.getByLabelText("Grade"), { target: { value: "12" } });
    fireEvent.change(screen.getByLabelText("Or paste transcript text"), { target: { value: "Vectors have magnitude and direction." } });
    fireEvent.click(screen.getByRole("button", { name: "Generate lecture" }));

    await waitFor(() => expect(onComplete).toHaveBeenCalledWith(lecture));
    const [, init] = fetchMock.mock.calls[0];
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer creator-token");
    expect(JSON.parse(String(init?.body)).captions).toBe("Vectors have magnitude and direction.");
  });
});
