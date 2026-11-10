import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Player from "./Player";
import type { Lecture, SessionState } from "./types";

const lecture: Lecture = {
  id: "tab-test",
  duration_seconds: 300, video_url: "https://example.com/video.mp4",
  timing_config: { min_trigger_gap: 15, tolerance: 2 }, transcript: [], interventions: [],
};
const session: SessionState = {
  session_id: "session-1", lecture_id: lecture.id, version: 1,
  active_intervention_id: null, interventions: [],
};

describe("Player tab return recall", () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it("requests and displays a recall card after returning from a long absence", async () => {
    let now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      card: { id: "recall_1", type: "flash_recall", question: "What is the key idea?" }, reason: null,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const { container } = render(<Player lecture={lecture} sessionState={session} onSessionStateChange={vi.fn()} mediaBaseUrl="" />);
    const pauseSpy = vi.spyOn(container.querySelector("video")!, "pause");
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    fireEvent(document, new Event("visibilitychange"));
    now += 61_000;
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    fireEvent(document, new Event("visibilitychange"));

    expect(await screen.findByTestId("tab-return-recall")).toHaveTextContent("What is the key idea?");
    expect(screen.getByRole("button", { name: "Dismiss recall card" })).toBeInTheDocument();
    expect(pauseSpy).not.toHaveBeenCalled();
  });
});
