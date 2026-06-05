import React, { useEffect, useRef } from "react";
import { Box, Flex, IconButton, Text, Tooltip } from "@radix-ui/themes";
import type { ImageAttachment } from "../../services/chat-websocket.service";

export interface ChatComposerProps {
  // Text
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  isConnected: boolean;

  // Attachments
  attachments: ImageAttachment[];
  onRemoveAttachment: (id: string) => void;
  onPickFiles: (files: File[]) => void;
  onPasteImages: (e: React.ClipboardEvent) => void;

  // Mic
  isRecording: boolean;
  isVADLoaded: boolean;
  onToggleMic: () => void;

  // Stream control
  isAssistantThinking: boolean;
  onCancel: () => void;
}

const MIN_HEIGHT_PX = 24;
const MAX_HEIGHT_PX = 200;

// ── Icons ─────────────────────────────────────────────────────────────

function PaperclipIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M21 12L13 20C11.34 21.66 8.66 21.66 7 20C5.34 18.34 5.34 15.66 7 14L15 6C16.1 4.9 17.9 4.9 19 6C20.1 7.1 20.1 8.9 19 10L11.5 17.5C10.95 18.05 10.05 18.05 9.5 17.5C8.95 16.95 8.95 16.05 9.5 15.5L16 9"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" strokeWidth="1.6" fill="currentColor" fillOpacity="0.12" />
      <path d="M5 11C5 14.87 8.13 18 12 18C15.87 18 19 14.87 19 11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M12 18V22" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M3.4 20.6L21 12L3.4 3.4L3 10.5L15 12L3 13.5L3.4 20.6Z"
        fill="currentColor"
      />
    </svg>
  );
}

function StopIcon() {
  // Smaller, more rounded square — sits inside the button as a clear icon
  // rather than dominating it.
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <rect x="4" y="4" width="16" height="16" rx="3" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

// ── Component ─────────────────────────────────────────────────────────

export default function ChatComposer({
  value,
  onChange,
  onSend,
  isConnected,
  attachments,
  onRemoveAttachment,
  onPickFiles,
  onPasteImages,
  isRecording,
  isVADLoaded,
  onToggleMic,
  isAssistantThinking,
  onCancel,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Autosize textarea
  const resize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const next = Math.max(MIN_HEIGHT_PX, Math.min(MAX_HEIGHT_PX, el.scrollHeight));
    el.style.height = `${next}px`;
  };
  useEffect(resize, [value]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter or Cmd/Ctrl+Enter → send. Shift+Enter → newline (default).
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  const handleFilePick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length > 0) onPickFiles(files);
    // reset so the same file can be picked again later
    e.target.value = "";
  };

  const sendDisabled =
    !isConnected || (value.trim().length === 0 && attachments.length === 0);
  const placeholder = !isConnected
    ? "Backend disconnected"
    : isRecording
      ? "Listening…"
      : "Type a message…  (Shift+Enter for newline)";

  return (
    <Box px="3" pb="3" pt="2">
      <Box
        style={{
          borderRadius: 16,
          border: "1px solid var(--gray-5)",
          backgroundColor: "var(--gray-2)",
          opacity: isConnected ? 1 : 0.6,
          transition: "border-color 150ms ease, opacity 150ms ease",
        }}
      >
        {/* Attachment thumbnails (inside the box, above textarea) */}
        {attachments.length > 0 && (
          <Flex gap="2" px="3" pt="2" wrap="wrap">
            {attachments.map((att) => (
              <Box
                key={att.id}
                style={{
                  position: "relative",
                  width: 56,
                  height: 56,
                  borderRadius: 8,
                  overflow: "hidden",
                  background: "var(--gray-3)",
                  flexShrink: 0,
                }}
              >
                <img
                  src={att.dataUrl}
                  alt=""
                  style={{ width: "100%", height: "100%", objectFit: "cover" }}
                />
                <button
                  type="button"
                  onClick={() => onRemoveAttachment(att.id)}
                  aria-label="Remove attachment"
                  style={{
                    position: "absolute",
                    top: 2,
                    right: 2,
                    width: 16,
                    height: 16,
                    borderRadius: 8,
                    border: "none",
                    background: "rgba(0,0,0,0.65)",
                    color: "white",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: 0,
                  }}
                >
                  <CloseIcon />
                </button>
              </Box>
            ))}
          </Flex>
        )}

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={onPasteImages}
          placeholder={placeholder}
          disabled={!isConnected}
          rows={1}
          style={{
            width: "100%",
            resize: "none",
            border: "none",
            outline: "none",
            background: "transparent",
            color: "var(--gray-12)",
            font: "inherit",
            fontSize: 14,
            lineHeight: "1.5",
            padding: "10px 14px 4px",
            minHeight: MIN_HEIGHT_PX,
            maxHeight: MAX_HEIGHT_PX,
            overflowY: "auto",
          }}
        />

        {/* Control row */}
        <Flex align="center" gap="3" pl="4" pr="2" pb="2" pt="1">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            multiple
            onChange={handleFilePick}
            style={{ display: "none" }}
          />

          <Tooltip content="Attach images">
            <IconButton
              size="2"
              variant="ghost"
              color="gray"
              onClick={() => fileInputRef.current?.click()}
              disabled={!isConnected}
              aria-label="Attach images"
            >
              <PaperclipIcon />
            </IconButton>
          </Tooltip>

          <Tooltip
            content={
              !isVADLoaded
                ? "Loading VAD model…"
                : isRecording
                  ? "Stop recording"
                  : "Start recording"
            }
          >
            <IconButton
              size="2"
              variant={isRecording ? "solid" : "ghost"}
              color={isRecording ? "red" : "gray"}
              onClick={onToggleMic}
              disabled={!isVADLoaded}
              aria-label={isRecording ? "Stop recording" : "Start recording"}
              style={{
                position: "relative",
                boxShadow: isRecording
                  ? "0 0 0 3px var(--red-4)"
                  : "none",
                transition: "box-shadow 150ms ease",
              }}
            >
              <MicIcon />
            </IconButton>
          </Tooltip>

          {isRecording && (
            <Text size="1" color="red" weight="medium">
              Recording…
            </Text>
          )}

          <Box style={{ flex: 1 }} />

          {isAssistantThinking ? (
            <Tooltip content="Stop generating">
              <IconButton
                size="2"
                variant="solid"
                color="cyan"
                radius="full"
                onClick={onCancel}
                aria-label="Stop generating"
                style={{
                  boxShadow: "0 0 0 3px var(--cyan-a5)",
                  animation: "shore-stop-pulse 1.6s ease-in-out infinite",
                }}
              >
                <StopIcon />
              </IconButton>
            </Tooltip>
          ) : (
            <Tooltip content="Send (Enter)">
              <IconButton
                size="2"
                variant="solid"
                color="indigo"
                onClick={onSend}
                disabled={sendDisabled}
                aria-label="Send message"
              >
                <SendIcon />
              </IconButton>
            </Tooltip>
          )}
        </Flex>
      </Box>
      <style>{`
        @keyframes shore-stop-pulse {
          0%, 100% { box-shadow: 0 0 0 3px var(--cyan-a5); }
          50%      { box-shadow: 0 0 0 6px var(--cyan-a3); }
        }
      `}</style>
    </Box>
  );
}
