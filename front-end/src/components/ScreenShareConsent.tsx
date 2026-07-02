import type { PendingConsent } from "../hooks/useScreenShare";

interface Props {
  pending: PendingConsent | null;
  onApprove: () => void;
  onDeny: () => void;
}

/**
 * Floating consent prompt shown when the LLM calls capture_screen /
 * analyze_screen and no screen share is active yet. Clicking "Share" is the
 * user gesture getDisplayMedia() requires — it cannot be triggered silently
 * by the agent-initiated screen_capture_request that caused this to appear.
 */
export default function ScreenShareConsent({ pending, onApprove, onDeny }: Props) {
  if (!pending) return null;
  return (
    <div
      role="alertdialog"
      aria-live="assertive"
      className="absolute right-4 bottom-4 z-20 max-w-sm rounded-lg border border-sky-300 bg-sky-50 p-3 text-sky-900 shadow-lg"
      style={{ animation: "shore-toast-in 200ms ease-out" }}
    >
      <div className="text-sm font-semibold">Shore wants to see your screen</div>
      <div className="text-xs text-sky-700 mt-1">
        To answer this, Shore needs a screenshot. Click Share, then choose what
        to share in the browser prompt that follows.
      </div>
      <div className="flex gap-2 mt-2">
        <button
          onClick={onApprove}
          className="px-3 py-1 rounded bg-sky-500 hover:bg-sky-600 text-white text-sm"
        >
          Share
        </button>
        <button
          onClick={onDeny}
          className="px-3 py-1 rounded bg-gray-300 hover:bg-gray-400 text-sm"
        >
          Decline
        </button>
      </div>
      <style>{`
        @keyframes shore-toast-in {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
