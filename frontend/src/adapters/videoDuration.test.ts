import { afterEach, describe, expect, it, vi } from "vitest";
import { readVideoDuration } from "./videoDuration";

describe("readVideoDuration", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads duration from direct video metadata and removes the probe element", async () => {
    vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(function (this: HTMLMediaElement) {
      Object.defineProperty(this, "duration", { configurable: true, value: 321 });
      queueMicrotask(() => this.dispatchEvent(new Event("loadedmetadata")));
    });

    await expect(readVideoDuration("https://media.example/video.mp4", 1000)).resolves.toBe(321);
    expect(document.querySelector("video")).toBeNull();
  });
});
