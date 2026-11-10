/**
 * VideoPlayerAdapter - Decoupled player interface for embeddable B2B integrations.
 *
 * In a B2B context, the client hosts and controls their own video player
 * (e.g., HTML5 video, Video.js, JWPlayer, YouTube IFrame, Vimeo, or a custom Canvas player).
 * game-loop attaches to any player implementing this contract to observe playback
 * and orchestrate interventions without owning or proxying the media stream.
 */

export interface VideoPlayerAdapter {
  play(): Promise<void>;
  pause(): void;
  getCurrentTime(): number;
  seekTo(seconds: number): void;
  getDuration(): number;
  onTimeUpdate(callback: (currentTime: number) => void): () => void;
  onSeeking(callback: (targetTime: number) => void): () => void;
  onSeeked?(callback: () => void): () => void;
  onEnded?(callback: () => void): () => void;
  destroy(): void;
}

export type VideoSource =
  | { kind: "youtube" | "vimeo"; embedUrl: string }
  | { kind: "direct"; url: string; isHls: boolean };

export function getVideoSource(rawUrl: string): VideoSource {
  const url = new URL(rawUrl, window.location.href);
  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  if (host === "youtu.be" || host === "youtube.com" || host === "m.youtube.com") {
    const id = host === "youtu.be" ? url.pathname.split("/").filter(Boolean)[0] :
      url.pathname.includes("/embed/") ? url.pathname.split("/embed/")[1]?.split("/")[0] :
      url.searchParams.get("v");
    if (id) return { kind: "youtube", embedUrl: `https://www.youtube.com/embed/${encodeURIComponent(id)}?enablejsapi=1&origin=${encodeURIComponent(window.location.origin)}` };
  }
  if (host === "vimeo.com" || host === "player.vimeo.com") {
    const id = url.pathname.split("/").filter(Boolean).find((part) => /^\d+$/.test(part));
    if (id) {
      const privacyHash = url.searchParams.get("h");
      const hashQuery = privacyHash ? `&h=${encodeURIComponent(privacyHash)}` : "";
      return { kind: "vimeo", embedUrl: `https://player.vimeo.com/video/${id}?api=1&player_id=game-loop${hashQuery}` };
    }
  }
  return { kind: "direct", url: rawUrl, isHls: url.pathname.toLowerCase().endsWith(".m3u8") };
}

class IFrameVideoAdapter implements VideoPlayerAdapter {
  private time = 0;
  private duration = 0;
  private timeListeners = new Set<(time: number) => void>();
  private seekingListeners = new Set<(time: number) => void>();
  private endedListeners = new Set<() => void>();
  private pollId: number;
  private readonly origin: string;
  private readonly onMessage = (event: MessageEvent) => {
    if (event.source !== this.frame.contentWindow || event.origin !== this.origin) return;
    let data: Record<string, any>;
    try { data = typeof event.data === "string" ? JSON.parse(event.data) : event.data; } catch { return; }
    if (this.provider === "youtube") {
      const info = data?.infoDelivery?.info;
      if (typeof info?.currentTime === "number") {
        this.time = info.currentTime;
        for (const listener of this.timeListeners) listener(this.time);
      }
      if (typeof info?.duration === "number") this.duration = info.duration;
      if (data?.event === "onReady") {
        this.send({ event: "command", func: "addEventListener", args: ["onStateChange"], id: 1 });
      }
      if (data?.infoDelivery?.playerState === 0 || info?.playerState === 0) {
        for (const listener of this.endedListeners) listener();
      }
    } else if (data?.event === "ready" && this.provider === "vimeo") {
      this.send({ method: "addEventListener", value: "timeupdate" });
      this.send({ method: "addEventListener", value: "seeking" });
      this.send({ method: "addEventListener", value: "ended" });
      this.send({ method: "getDuration" });
    } else if (this.provider === "vimeo" && data?.method === "getDuration" && typeof data?.value === "number") {
      this.duration = data.value;
    } else if (data?.event === "timeupdate" && typeof data?.data?.seconds === "number") {
      this.time = data.data.seconds;
      this.duration = Number(data.data.duration) || this.duration;
      for (const listener of this.timeListeners) listener(this.time);
    } else if (data?.event === "seeking") {
      this.time = Number(data.data?.seconds) || this.time;
      for (const listener of this.seekingListeners) listener(this.time);
    } else if (data?.event === "ended") {
      for (const listener of this.endedListeners) listener();
    }
  };

  constructor(private frame: HTMLIFrameElement, private provider: "youtube" | "vimeo") {
    this.origin = provider === "youtube" ? "https://www.youtube.com" : "https://player.vimeo.com";
    window.addEventListener("message", this.onMessage);
    this.pollId = window.setInterval(() => {
      if (provider === "vimeo") this.send({ method: "getCurrentTime" });
      else {
        this.send({ event: "listening", id: 1 });
        this.send({ event: "command", func: "getCurrentTime", args: [], id: 1 });
      }
    }, 500);
    if (provider === "vimeo") {
      this.send({ method: "addEventListener", value: "timeupdate" });
      this.send({ method: "addEventListener", value: "seeking" });
      this.send({ method: "addEventListener", value: "ended" });
    } else {
      this.send({ event: "listening", id: 1 });
      this.send({ event: "command", func: "addEventListener", args: ["onStateChange"], id: 1 });
    }
  }

  private send(message: object): void { this.frame.contentWindow?.postMessage(JSON.stringify(message), this.origin); }
  async play(): Promise<void> { this.send(this.provider === "vimeo" ? { method: "play" } : { event: "command", func: "playVideo", args: [], id: 1 }); }
  pause(): void { this.send(this.provider === "vimeo" ? { method: "pause" } : { event: "command", func: "pauseVideo", args: [], id: 1 }); }
  getCurrentTime(): number { return this.time; }
  seekTo(seconds: number): void {
    this.time = seconds;
    for (const listener of this.seekingListeners) listener(seconds);
    this.send(this.provider === "vimeo" ? { method: "setCurrentTime", value: seconds } : { event: "command", func: "seekTo", args: [seconds, true], id: 1 });
  }
  getDuration(): number { return this.duration; }
  onTimeUpdate(callback: (time: number) => void): () => void { this.timeListeners.add(callback); return () => this.timeListeners.delete(callback); }
  onSeeking(callback: (time: number) => void): () => void { this.seekingListeners.add(callback); return () => this.seekingListeners.delete(callback); }
  onEnded(callback: () => void): () => void { this.endedListeners.add(callback); return () => this.endedListeners.delete(callback); }
  destroy(): void { window.clearInterval(this.pollId); window.removeEventListener("message", this.onMessage); this.timeListeners.clear(); this.seekingListeners.clear(); this.endedListeners.clear(); }
}

export class YouTubePlayerAdapter extends IFrameVideoAdapter {
  constructor(frame: HTMLIFrameElement) { super(frame, "youtube"); }
}

export class VimeoPlayerAdapter extends IFrameVideoAdapter {
  constructor(frame: HTMLIFrameElement) { super(frame, "vimeo"); }
}

/**
 * Standard HTML5 <video> element adapter.
 */
export class HTML5VideoAdapter implements VideoPlayerAdapter {
  private element: HTMLVideoElement | null = null;
  private timeUpdateListeners: Set<(currentTime: number) => void> = new Set();
  private seekingListeners: Set<(targetTime: number) => void> = new Set();
  private seekedListeners: Set<() => void> = new Set();
  private endedListeners: Set<() => void> = new Set();

  constructor(videoElement?: HTMLVideoElement | null) {
    if (videoElement) {
      this.attach(videoElement);
    }
  }

  public attach(videoElement: HTMLVideoElement): void {
    this.detach();
    this.element = videoElement;

    this.element.addEventListener("timeupdate", this.handleTimeUpdate);
    this.element.addEventListener("seeking", this.handleSeeking);
    this.element.addEventListener("seeked", this.handleSeeked);
    this.element.addEventListener("ended", this.handleEnded);
  }

  public detach(): void {
    if (!this.element) return;
    this.element.removeEventListener("timeupdate", this.handleTimeUpdate);
    this.element.removeEventListener("seeking", this.handleSeeking);
    this.element.removeEventListener("seeked", this.handleSeeked);
    this.element.removeEventListener("ended", this.handleEnded);
    this.element = null;
  }

  private handleTimeUpdate = (): void => {
    if (!this.element) return;
    const time = this.element.currentTime;
    for (const listener of this.timeUpdateListeners) {
      listener(time);
    }
  };

  private handleSeeking = (): void => {
    if (!this.element) return;
    const time = this.element.currentTime;
    for (const listener of this.seekingListeners) {
      listener(time);
    }
  };

  private handleSeeked = (): void => {
    for (const listener of this.seekedListeners) {
      listener();
    }
  };

  private handleEnded = (): void => {
    for (const listener of this.endedListeners) {
      listener();
    }
  };

  public async play(): Promise<void> {
    if (this.element) {
      await this.element.play();
    }
  }

  public pause(): void {
    if (this.element) {
      this.element.pause();
    }
  }

  public getCurrentTime(): number {
    return this.element ? this.element.currentTime : 0;
  }

  public seekTo(seconds: number): void {
    if (this.element) {
      this.element.currentTime = seconds;
    }
  }

  public getDuration(): number {
    return this.element ? this.element.duration || 0 : 0;
  }

  public onTimeUpdate(callback: (currentTime: number) => void): () => void {
    this.timeUpdateListeners.add(callback);
    return () => {
      this.timeUpdateListeners.delete(callback);
    };
  }

  public onSeeking(callback: (targetTime: number) => void): () => void {
    this.seekingListeners.add(callback);
    return () => {
      this.seekingListeners.delete(callback);
    };
  }

  public onSeeked(callback: () => void): () => void {
    this.seekedListeners.add(callback);
    return () => {
      this.seekedListeners.delete(callback);
    };
  }

  public onEnded(callback: () => void): () => void {
    this.endedListeners.add(callback);
    return () => {
      this.endedListeners.delete(callback);
    };
  }

  public destroy(): void {
    this.detach();
    this.timeUpdateListeners.clear();
    this.seekingListeners.clear();
    this.seekedListeners.clear();
    this.endedListeners.clear();
  }
}
