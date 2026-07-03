/**
 * Desktop half of the computer-use loop: execute one action through Tauri,
 * wait for the UI to settle, capture a fresh frame, and return one result.
 */
import { isTauri } from "@Shore/utils/tauri.util";
import {
  captureFrameDataUrl,
  isScreenSharing,
} from "./screen-capture.service";

export interface CuaStepMessage {
  request_id: string;
  action: { func: string } & Record<string, unknown>;
  display_hint: string;
}

const CAPTURE_MAX_SIZE = 1280;
const DEFAULT_SETTLE_MS = 800;

function screenSize() {
  return { width: window.screen.width, height: window.screen.height };
}

export async function announceCuaReady(
  sendReady: (screen: { width: number; height: number }) => void,
): Promise<void> {
  if (!isTauri() || !isScreenSharing()) return;
  sendReady(screenSize());
}

export async function executeCuaStep(
  message: CuaStepMessage,
  sendResult: (payload: object) => void,
  settleMs = DEFAULT_SETTLE_MS,
): Promise<void> {
  const reply = (extra: object) =>
    sendResult({ request_id: message.request_id, ...extra });

  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("input_execute", { action: message.action });
    if (settleMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, settleMs));
    }
    const screenshot = await captureFrameDataUrl(CAPTURE_MAX_SIZE);
    reply({ screenshot, screen: screenSize() });
  } catch (cause) {
    reply({
      error: cause instanceof Error ? cause.message : String(cause),
      screen: screenSize(),
    });
  }
}
