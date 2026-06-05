import type { PendingConfirm } from "../../models/terminal.model";

interface Props {
  pending: PendingConfirm[];
  onOpenTerminal: () => void;
}

/**
 * Floating notification shown in the bottom-right of the chat area when there
 * are pending terminal confirms AND the terminal drawer is closed. Click to
 * open the drawer (where ConfirmBanner shows the full prompt + actions).
 */
export default function ConfirmToast({ pending, onOpenTerminal }: Props) {
  if (pending.length === 0) return null;
  const first = pending[0];
  const more = pending.length - 1;

  return (
    <div
      role="alert"
      aria-live="polite"
      onClick={onOpenTerminal}
      className="absolute right-4 bottom-4 z-20 max-w-sm cursor-pointer rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-900 shadow-lg hover:shadow-xl transition-shadow"
      style={{ animation: "shore-toast-in 200ms ease-out" }}
    >
      <div className="flex items-start gap-2">
        <span className="text-amber-600 font-bold text-sm leading-none mt-0.5">⚠</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold">
            Shore wants to run a command
            {more > 0 && <span className="text-amber-600 font-normal"> (+{more} more)</span>}
          </div>
          <code className="block mt-1 text-xs bg-amber-100/60 border border-amber-200 px-2 py-1 rounded truncate">
            {first.command}
          </code>
          <div className="text-xs text-amber-700 mt-2 underline">
            Open terminal to review →
          </div>
        </div>
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
