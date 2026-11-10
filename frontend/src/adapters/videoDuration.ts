import { getVideoSource, VimeoPlayerAdapter, YouTubePlayerAdapter } from "./PlayerAdapter";

const DURATION_TIMEOUT_MS = 30000;

function waitForDuration(readDuration: () => number, timeoutMs: number): Promise<number> {
  return new Promise((resolve, reject) => {
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      const duration = readDuration();
      if (Number.isFinite(duration) && duration > 0) {
        window.clearInterval(timer);
        resolve(duration);
      } else if (Date.now() - startedAt >= timeoutMs) {
        window.clearInterval(timer);
        reject(new Error("Could not read the video length. Check that the video is available and has a fixed duration."));
      }
    }, 200);
  });
}

async function readDirectDuration(url: string, isHls: boolean, timeoutMs: number): Promise<number> {
  const video = document.createElement("video");
  video.preload = "metadata";
  video.muted = true;
  video.style.cssText = "position:fixed;left:-10000px;top:0;width:1px;height:1px";
  document.body.appendChild(video);
  let destroyHls: (() => void) | null = null;
  let hlsDuration = 0;
  try {
    if (isHls && !video.canPlayType("application/vnd.apple.mpegurl")) {
      const { default: Hls } = await import("hls.js");
      if (!Hls.isSupported()) throw new Error("This browser cannot read the HLS video length.");
      const instance = new Hls();
      destroyHls = () => instance.destroy();
      instance.on(Hls.Events.LEVEL_LOADED, (_event, data) => {
        hlsDuration = Number(data?.details?.totalduration) || hlsDuration;
      });
      instance.attachMedia(video);
      instance.loadSource(url);
    } else {
      video.src = url;
      video.load();
    }
    return await waitForDuration(() => Number.isFinite(video.duration) ? video.duration : hlsDuration, timeoutMs);
  } finally {
    destroyHls?.();
    video.removeAttribute("src");
    video.load();
    video.remove();
  }
}

async function readProviderDuration(
  kind: "youtube" | "vimeo",
  embedUrl: string,
  timeoutMs: number
): Promise<number> {
  const frame = document.createElement("iframe");
  frame.src = embedUrl;
  frame.title = "Video duration probe";
  frame.style.cssText = "position:fixed;left:-10000px;top:0;width:1px;height:1px";
  document.body.appendChild(frame);
  const adapter = kind === "youtube" ? new YouTubePlayerAdapter(frame) : new VimeoPlayerAdapter(frame);
  try {
    return await waitForDuration(() => adapter.getDuration(), timeoutMs);
  } finally {
    adapter.destroy();
    frame.remove();
  }
}

export function readVideoDuration(rawUrl: string, timeoutMs = DURATION_TIMEOUT_MS): Promise<number> {
  const source = getVideoSource(rawUrl);
  if (source.kind === "direct") return readDirectDuration(source.url, source.isHls, timeoutMs);
  return readProviderDuration(source.kind, source.embedUrl, timeoutMs);
}
