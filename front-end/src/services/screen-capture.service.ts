/**
 * Client-side screen capture via getDisplayMedia. The backend host has no
 * guaranteed display of its own, so screenshots for analyze_screen /
 * capture_screen, analyze_screen, and computer-use tasks are captured here
 * and relayed to the backend over the chat WebSocket.
 *
 * A single shared MediaStream is reused across callers (on-demand tool
 * captures and computer-use steps) so the user isn't re-prompted by the
 * browser's share picker on every request within a session.
 *
 * Inside the Tauri desktop app, WKWebView (macOS) does not implement
 * getDisplayMedia, so capture goes through the native `capture_screen_png`
 * Tauri command instead (primary monitor via CoreGraphics; macOS prompts for
 * Screen Recording permission on first use). The public API is identical —
 * only there is no native "share ended" event, so `onScreenShareEnded`
 * listeners never fire in Tauri.
 */

import { invoke } from "@tauri-apps/api/core";

const isTauri = "__TAURI_INTERNALS__" in window;

let activeStream: MediaStream | null = null;
let activeVideo: HTMLVideoElement | null = null;
let tauriActive = false;
const endedListeners = new Set<() => void>();

export function isScreenSharing(): boolean {
  if (isTauri) return tauriActive;
  return (
    !!activeStream &&
    activeStream.getVideoTracks().some((t) => t.readyState === "live")
  );
}

/** Subscribe to the user stopping the share from the browser's native UI. */
export function onScreenShareEnded(cb: () => void): () => void {
  endedListeners.add(cb);
  return () => endedListeners.delete(cb);
}

export function stopScreenStream(): void {
  tauriActive = false;
  activeStream?.getTracks().forEach((t) => t.stop());
  activeStream = null;
  activeVideo = null;
}

async function ensureScreenStream(): Promise<MediaStream> {
  if (isScreenSharing() && activeStream) return activeStream;

  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new Error("Screen capture is not supported in this browser.");
  }

  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: true,
    audio: false,
  });

  const track = stream.getVideoTracks()[0];
  track.addEventListener("ended", () => {
    stopScreenStream();
    endedListeners.forEach((cb) => cb());
  });

  const video = document.createElement("video");
  video.srcObject = stream;
  video.muted = true;
  video.playsInline = true;
  await video.play();
  if (video.readyState < 2) {
    await new Promise<void>((resolve) => {
      video.onloadeddata = () => resolve();
    });
  }

  activeStream = stream;
  activeVideo = video;
  return stream;
}

function grabCanvas(maxSize: number): HTMLCanvasElement {
  if (!activeVideo) throw new Error("No active screen share to capture.");
  const vw = activeVideo.videoWidth || 1280;
  const vh = activeVideo.videoHeight || 720;
  const scale = Math.min(1, maxSize / Math.max(vw, vh));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(vw * scale));
  canvas.height = Math.max(1, Math.round(vh * scale));
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable.");
  ctx.drawImage(activeVideo, 0, 0, canvas.width, canvas.height);
  return canvas;
}

/** Native full-resolution PNG capture of the primary monitor (Tauri only). */
async function invokeTauriCapture(): Promise<string> {
  try {
    return await invoke<string>("capture_screen_png");
  } catch (e) {
    throw new Error(
      typeof e === "string"
        ? e
        : e instanceof Error
          ? e.message
          : "Native screen capture failed.",
    );
  }
}

/** Draw a native capture onto a canvas, longest edge capped at maxSize. */
async function grabTauriCanvas(maxSize: number): Promise<HTMLCanvasElement> {
  const dataUrl = await invokeTauriCapture();
  const img = new Image();
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () =>
      reject(new Error("Failed to decode native screen capture."));
    img.src = dataUrl;
  });
  const iw = img.naturalWidth || 1280;
  const ih = img.naturalHeight || 720;
  const scale = Math.min(1, maxSize / Math.max(iw, ih));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(iw * scale));
  canvas.height = Math.max(1, Math.round(ih * scale));
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable.");
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas;
}

/** Full-resolution (capped to maxSize longest edge) JPEG frame, as a data: URL. */
export async function captureFrameDataUrl(
  maxSize = 1280,
  quality = 0.85,
): Promise<string> {
  if (isTauri) {
    const canvas = await grabTauriCanvas(maxSize);
    tauriActive = true;
    return canvas.toDataURL("image/jpeg", quality);
  }
  await ensureScreenStream();
  return grabCanvas(maxSize).toDataURL("image/jpeg", quality);
}

/** Explicitly request screen-share permission before enabling Screen access. */
export async function requestScreenShare(): Promise<void> {
  if (isTauri) {
    // One test capture triggers the macOS Screen Recording (TCC) prompt and
    // validates that native capture works before Screen access is announced.
    await invokeTauriCapture();
    tauriActive = true;
    return;
  }
  await ensureScreenStream();
}
