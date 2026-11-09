import { describe, expect, it, vi } from "vitest";
import { getVideoSource, HTML5VideoAdapter, VimeoPlayerAdapter, YouTubePlayerAdapter } from "./PlayerAdapter";

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

describe("built-in media source adapters", () => {
  it("recognizes YouTube, Vimeo, direct MP4, and HLS sources", () => {
    expect(getVideoSource("https://youtu.be/abc123").kind).toBe("youtube");
    expect(getVideoSource("https://vimeo.com/123456").kind).toBe("vimeo");
    const privateVimeo = getVideoSource("https://vimeo.com/123456?h=privacy-token");
    expect(privateVimeo.kind).toBe("vimeo");
    if (privateVimeo.kind === "vimeo") expect(privateVimeo.embedUrl).toContain("h=privacy-token");
    expect(getVideoSource("https://cdn.example.com/lecture.mp4")).toMatchObject({ kind: "direct", isHls: false });
    expect(getVideoSource("https://cdn.example.com/lecture.m3u8")).toMatchObject({ kind: "direct", isHls: true });
  });

  it("sends secure provider commands and consumes time updates", () => {
    const youtube = document.createElement("iframe");
    const vimeo = document.createElement("iframe");
    const ytPost = vi.fn();
    const vmPost = vi.fn();
    Object.defineProperty(youtube, "contentWindow", { value: { postMessage: ytPost } });
    Object.defineProperty(vimeo, "contentWindow", { value: { postMessage: vmPost } });
    const yt = new YouTubePlayerAdapter(youtube);
    const vm = new VimeoPlayerAdapter(vimeo);
    const update = vi.fn();
    yt.onTimeUpdate(update);
    window.dispatchEvent(new MessageEvent("message", {
      origin: "https://www.youtube.com", source: youtube.contentWindow,
      data: JSON.stringify({ infoDelivery: { info: { currentTime: 12, duration: 100 } } }),
    }));
    void yt.play();
    void vm.play();
    expect(update).toHaveBeenCalledWith(12);
    expect(yt.getDuration()).toBe(100);
    expect(ytPost).toHaveBeenCalledWith(expect.stringContaining("playVideo"), "https://www.youtube.com");
    expect(vmPost).toHaveBeenCalledWith(expect.stringContaining('"method":"play"'), "https://player.vimeo.com");
    yt.destroy();
    vm.destroy();
  });
});
