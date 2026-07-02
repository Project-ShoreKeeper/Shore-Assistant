import { useCallback, useEffect, useRef, useState } from "react";
import {
  chatWebsocketService,
  type ChatServerMessage,
} from "../services/chat-websocket.service";

export interface PendingConsent {
  requestId: string;
  kind: "thumbnail" | "full";
  maxSize: number;
}

interface CapturedFrame {
  dataUrl: string;
  label: string;
}

export interface UseScreenShareReturn {
  hasStream: boolean;
  pendingConsent: PendingConsent | null;
  acquireStream: () => Promise<boolean>;
  stopStream: () => void;
  approveConsent: () => Promise<void>;
  denyConsent: () => void;
}

/**
 * Owns one MediaStream (getDisplayMedia) plus a hidden <video>/<canvas> pair
 * used to grab the current frame on demand, in response to backend
 * screen_capture_request messages. See
 * docs/superpowers/specs/2026-07-02-client-side-screen-capture-design.md.
 */
export function useScreenShare(onStreamEnded: () => void): UseScreenShareReturn {
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [hasStream, setHasStream] = useState(false);
  const [pendingConsent, setPendingConsent] = useState<PendingConsent | null>(null);

  const getVideo = useCallback((): HTMLVideoElement => {
    if (!videoRef.current) {
      const v = document.createElement("video");
      v.muted = true;
      videoRef.current = v;
    }
    return videoRef.current;
  }, []);

  const getCanvas = useCallback((): HTMLCanvasElement => {
    if (!canvasRef.current) canvasRef.current = document.createElement("canvas");
    return canvasRef.current;
  }, []);

  const grabFrame = useCallback(
    (maxSize: number): CapturedFrame => {
      const video = getVideo();
      const canvas = getCanvas();
      const track = streamRef.current?.getVideoTracks()[0];
      const srcW = video.videoWidth || maxSize;
      const srcH = video.videoHeight || maxSize;
      const scale = Math.min(1, maxSize / Math.max(srcW, srcH));
      canvas.width = Math.max(1, Math.round(srcW * scale));
      canvas.height = Math.max(1, Math.round(srcH * scale));
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      return {
        dataUrl: canvas.toDataURL("image/jpeg", 0.85),
        label: track?.label || "",
      };
    },
    [getCanvas, getVideo],
  );

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setHasStream(false);
  }, []);

  const acquireStream = useCallback(async (): Promise<boolean> => {
    if (streamRef.current) return true;
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const track = stream.getVideoTracks()[0];
      track.onended = () => {
        stopStream();
        onStreamEnded();
      };
      streamRef.current = stream;
      const video = getVideo();
      video.srcObject = stream;
      await video.play();
      setHasStream(true);
      return true;
    } catch {
      return false;
    }
  }, [getVideo, onStreamEnded, stopStream]);

  const respond = useCallback((requestId: string, frame: CapturedFrame | null) => {
    chatWebsocketService.sendScreenCaptureResponse(
      requestId,
      frame ? frame.dataUrl : null,
      frame?.label,
    );
  }, []);

  useEffect(() => {
    const handler = (msg: ChatServerMessage) => {
      if (msg.type !== "screen_capture_request") return;
      if (streamRef.current) {
        respond(msg.request_id, grabFrame(msg.max_size));
        return;
      }
      setPendingConsent({ requestId: msg.request_id, kind: msg.kind, maxSize: msg.max_size });
    };
    chatWebsocketService.on("message", handler);
    return () => chatWebsocketService.off("message", handler);
  }, [grabFrame, respond]);

  const approveConsent = useCallback(async () => {
    const consent = pendingConsent;
    if (!consent) return;
    setPendingConsent(null);
    const ok = await acquireStream();
    respond(consent.requestId, ok ? grabFrame(consent.maxSize) : null);
  }, [pendingConsent, acquireStream, grabFrame, respond]);

  const denyConsent = useCallback(() => {
    if (!pendingConsent) return;
    respond(pendingConsent.requestId, null);
    setPendingConsent(null);
  }, [pendingConsent, respond]);

  return { hasStream, pendingConsent, acquireStream, stopStream, approveConsent, denyConsent };
}
