/**
 * Client-side screen capture via getDisplayMedia. The backend host has no
 * guaranteed display of its own, so screenshots for analyze_screen /
 * capture_screen and the Screen Co-pilot watch loop are captured here and
 * relayed to the backend over the chat WebSocket.
 *
 * A single shared MediaStream is reused across callers (on-demand tool
 * captures and the co-pilot frame loop) so the user isn't re-prompted by the
 * browser's share picker on every request within a session.
 */

let activeStream: MediaStream | null = null;
let activeVideo: HTMLVideoElement | null = null;
const endedListeners = new Set<() => void>();

export function isScreenSharing(): boolean {
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

/** Full-resolution (capped to maxSize longest edge) JPEG frame, as a data: URL. */
export async function captureFrameDataUrl(
  maxSize = 1280,
  quality = 0.85,
): Promise<string> {
  await ensureScreenStream();
  return grabCanvas(maxSize).toDataURL("image/jpeg", quality);
}

/** Small JPEG frame for cheap change-detection diffing, as a data: URL. */
export async function captureThumbnailDataUrl(size = 64): Promise<string> {
  await ensureScreenStream();
  return grabCanvas(size).toDataURL("image/jpeg", 0.6);
}

/** Explicitly request screen-share permission (e.g. before starting Co-pilot). */
export async function requestScreenShare(): Promise<void> {
  await ensureScreenStream();
}
