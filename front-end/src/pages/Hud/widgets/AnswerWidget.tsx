import { useEffect, useState } from "react";

import type { HudAnswer } from "@Shore/services/hud-bridge.service";
import type { HudActionRequest } from "@Shore/services/hud-actions";
import HudPopover from "../HudPopover";

export default function AnswerWidget({
  answer,
  active,
  expanded,
  hasPending,
  onToggle,
  sendAction,
  measureRef,
}: {
  answer: HudAnswer | null;
  active: boolean;
  expanded: boolean;
  hasPending: boolean;
  onToggle: () => void;
  sendAction: (action: HudActionRequest) => string;
  measureRef: (element: HTMLElement | null) => void;
}) {
  const [feedback, setFeedback] = useState("");
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    return () => window.speechSynthesis?.cancel();
  }, [answer?.messageId]);

  if (!answer) return null;

  const copyAnswer = async () => {
    try {
      await navigator.clipboard.writeText(answer.text);
      setFeedback("Copied.");
    } catch {
      setFeedback("Could not copy the answer.");
    }
  };

  const toggleSpeech = () => {
    if (!("speechSynthesis" in window)) return;
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }
    const utterance = new SpeechSynthesisUtterance(answer.text);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => {
      setSpeaking(false);
      setFeedback("Read aloud failed.");
    };
    window.speechSynthesis.speak(utterance);
    setSpeaking(true);
  };

  return (
    <>
      <button
        ref={measureRef}
        type="button"
        className="hud-widget hud-bl"
        data-hud-widget="answer"
        aria-expanded={expanded}
        onClick={() => {
          if (active) onToggle();
        }}
      >
        Answer: {answer.text}
      </button>
      {active && expanded && (
        <HudPopover
          title="Latest answer"
          className="hud-answer-popover"
          onClose={onToggle}
        >
          <div className="hud-answer-content">{answer.text}</div>
          <div className="hud-popover-actions">
            <button type="button" onClick={() => void copyAnswer()}>
              Copy
            </button>
            {"speechSynthesis" in window && (
              <button type="button" onClick={toggleSpeech}>
                {speaking ? "Stop speaking" : "Read aloud"}
              </button>
            )}
            <button
              type="button"
              disabled={hasPending}
              onClick={() => sendAction({
                action: "focus_main",
                payload: {
                  destination: "chat",
                  messageId: answer.messageId,
                },
              })}
            >
              Open in chat
            </button>
          </div>
          <div className="hud-inline-feedback" aria-live="polite">
            {feedback}
          </div>
        </HudPopover>
      )}
    </>
  );
}
