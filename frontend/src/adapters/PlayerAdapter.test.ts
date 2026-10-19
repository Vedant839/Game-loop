import { describe, expect, it, vi } from "vitest";
import { HTML5VideoAdapter } from "./PlayerAdapter";

describe("HTML5VideoAdapter", () => {
  it("attaches event listeners to HTMLVideoElement and dispatches callbacks", () => {
    const video = document.createElement("video");
    const adapter = new HTML5VideoAdapter(video);

    const timeUpdateSpy = vi.fn();
    const seekingSpy = vi.fn();

    const unsubscribeTime = adapter.onTimeUpdate(timeUpdateSpy);
    const unsubscribeSeeking = adapter.onSeeking(seekingSpy);

    // Simulate currentTime change and event
    Object.defineProperty(video, "currentTime", { value: 42.5, writable: true });
    video.dispatchEvent(new Event("timeupdate"));
    expect(timeUpdateSpy).toHaveBeenCalledWith(42.5);

    // Simulate seeking event
    Object.defineProperty(video, "currentTime", { value: 60.0, writable: true });
    video.dispatchEvent(new Event("seeking"));
    expect(seekingSpy).toHaveBeenCalledWith(60.0);

    // Unsubscribe
    unsubscribeTime();
    video.dispatchEvent(new Event("timeupdate"));
    expect(timeUpdateSpy).toHaveBeenCalledTimes(1);

    // Clean up
    adapter.destroy();
  });

  it("controls play, pause, and seek", () => {
    const video = document.createElement("video");
    video.play = vi.fn().mockResolvedValue(undefined);
    video.pause = vi.fn();

    const adapter = new HTML5VideoAdapter(video);

    void adapter.play();
    expect(video.play).toHaveBeenCalled();

    adapter.pause();
    expect(video.pause).toHaveBeenCalled();

    adapter.seekTo(120);
    expect(video.currentTime).toBe(120);

    adapter.destroy();
  });
});
