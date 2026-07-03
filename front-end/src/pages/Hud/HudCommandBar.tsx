import { useEffect, useRef, useState } from "react";

import type { HudStatePayload } from "@Shore/services/hud-bridge.service";
import type {
  HudActionRequest,
  HudActionResult,
} from "@Shore/services/hud-actions";

interface HudCommandBarProps {
  active: boolean;
  linked: boolean;
  capabilities: HudStatePayload["capabilities"];
  hasPending: boolean;
  lastResult: HudActionResult | null;
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  sendAction: (
    action: HudActionRequest,
    onResult?: (result: HudActionResult) => void,
  ) => string;
  onPromptSent: () => void;
  onCustomize: () => void;
}

export default function HudCommandBar({
  active,
  linked,
  capabilities,
  hasPending,
  lastResult,
  paletteOpen,
  setPaletteOpen,
  sendAction,
  onPromptSent,
  onCustomize,
}: HudCommandBarProps) {
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!active) return;
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [active]);

  if (!active) return null;

  const submitPrompt = () => {
    const text = draft.trim();
    if (!text || !linked || !capabilities.sendPrompt || hasPending) return;
    sendAction(
      {
        action: "send_prompt",
        payload: { text },
      },
      (result) => {
        if (!result.ok) return;
        setDraft("");
        onPromptSent();
      },
    );
  };

  const runAction = (action: HudActionRequest) => {
    if (hasPending) return;
    sendAction(action);
    setPaletteOpen(false);
  };

  return (
    <>
      <div className="hud-active-indicator" role="status">
        HUD active <span aria-hidden>·</span> Esc to close
      </div>
      <section className="hud-command-shell" aria-label="Shore HUD command">
        <div className="hud-command-row">
          <textarea
            ref={inputRef}
            className="hud-command-input"
            value={draft}
            rows={1}
            maxLength={2_000}
            placeholder={linked ? "Ask Shore…" : "Waiting for main app…"}
            disabled={!linked || !capabilities.sendPrompt}
            aria-label="Ask Shore"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.metaKey && event.key.toLowerCase() === "k") {
                event.preventDefault();
                setPaletteOpen(!paletteOpen);
                return;
              }
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submitPrompt();
              }
            }}
          />
          <button
            type="button"
            className="hud-command-menu-button"
            aria-label="Open command palette"
            aria-expanded={paletteOpen}
            onClick={() => setPaletteOpen(!paletteOpen)}
          >
            ⌘K
          </button>
          <button
            type="button"
            className="hud-command-send"
            disabled={
              !draft.trim()
              || !linked
              || !capabilities.sendPrompt
              || hasPending
            }
            onClick={submitPrompt}
          >
            Send
          </button>
        </div>

        {paletteOpen && (
          <div className="hud-command-palette" role="menu">
            <button
              type="button"
              role="menuitem"
              disabled={!capabilities.cancelGeneration || hasPending}
              onClick={() => runAction({ action: "cancel_generation" })}
            >
              Stop response
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={!capabilities.stopCopilot || hasPending}
              onClick={() => runAction({ action: "stop_copilot" })}
            >
              Pause Co-pilot
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={hasPending}
              onClick={() => runAction({
                action: "focus_main",
                payload: { destination: "settings" },
              })}
            >
              Open Co-pilot setup
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={!capabilities.retryConnection || hasPending}
              onClick={() => runAction({ action: "retry_connection" })}
            >
              Retry connection
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={hasPending}
              onClick={() => runAction({
                action: "focus_main",
                payload: { destination: "chat" },
              })}
            >
              Open chat
            </button>
            <button
              type="button"
              role="menuitem"
              disabled={hasPending}
              onClick={() => {
                setPaletteOpen(false);
                onCustomize();
              }}
            >
              Customize HUD
            </button>
          </div>
        )}

        <div
          className={`hud-action-feedback${
            lastResult && !lastResult.ok ? " hud-action-error" : ""
          }`}
          aria-live="polite"
        >
          {hasPending
            ? "Sending…"
            : lastResult?.message
              ?? (lastResult?.ok ? "Done" : "")}
        </div>
      </section>
    </>
  );
}
