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
